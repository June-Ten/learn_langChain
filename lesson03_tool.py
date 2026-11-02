import os
from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain.messages import HumanMessage, ToolMessage
from langchain.tools import tool
from langchain_deepseek import ChatDeepSeek

load_dotenv()

# flash 默认开着思考。思考模式不支持强制 tool_choice，
# 而且带工具的下一轮请求必须原样带回 reasoning_content。
# 这课关掉思考，走普通 function calling。
llm = ChatDeepSeek(
    model=os.getenv("DEEPSEEK_MODEL", "deepseek-flash"),
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    api_base=os.getenv("DEEPSEEK_API_BASE", "https://api.deepseek.com"),
    temperature=0,
    extra_body={"thinking": {"type": "disabled"}},
)


@tool
def get_weather(city: str) -> str:
    """查询城市当前气温，单位摄氏度。city 用中文城市名。"""
    temps = {"北京": 22, "上海": 26, "哈尔滨": -5}
    if city not in temps:
        return f"没有{city}的天气数据"
    return f"{city} {temps[city]} 摄氏度"


question = "北京现在多少度？只根据工具结果回答，不要编造。"

# 手动一轮：模型只返回 tool_calls，函数由我们执行，结果用 ToolMessage 交回去。
bound = llm.bind_tools([get_weather])
ai = bound.invoke([HumanMessage(content=question)])
print("tool_calls:", ai.tool_calls)

messages = [HumanMessage(content=question), ai]
for call in ai.tool_calls:
    observation = get_weather.invoke(call["args"])
    print("tool result:", observation)
    messages.append(ToolMessage(content=observation, tool_call_id=call["id"]))

final = bound.invoke(messages)
print(final.content)

# agent 自己循环：调用模型 → 执行工具 → 再调用模型，直到不再要工具。
agent = create_agent(
    llm,
    tools=[get_weather],
    system_prompt="用中文一句话回答。需要气温时必须调用工具。",
)
result = agent.invoke(
    {"messages": [HumanMessage(content="上海现在适不适合穿短袖？")]}
)
print(result["messages"][-1].content)
