import os
from dotenv import load_dotenv
from langchain.messages import HumanMessage, ToolMessage
from langchain_core.tools import tool
from langchain_deepseek import ChatDeepSeek

load_dotenv()

llm = ChatDeepSeek(
    model=os.getenv("DEEPSEEK_MODEL", "deepseek-flash"),
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    api_base=os.getenv("DEEPSEEK_API_BASE", "https://api.deepseek.com"),
    temperature=0,
)


@tool
def get_weather(city: str) -> str:
    """查询城市当前天气。city 为中文城市名，例如北京。"""
    data = {"北京": "晴，18°C", "上海": "多云，22°C"}
    return data.get(city, f"{city}：暂无实测，按多云 20°C 估计")


# bind_tools 只把工具 schema 交给模型。模型返回 tool_calls，不会自己执行。
# 不要传 tool_choice：DeepSeek flash 思考模式不支持。
llm_with_tools = llm.bind_tools([get_weather])

question = "北京今天适不适合出门散步？先查天气再回答。"
ai = llm_with_tools.invoke([HumanMessage(content=question)])
print("tool_calls:", ai.tool_calls)

messages = [HumanMessage(content=question), ai]
for call in ai.tool_calls:
    if call["name"] != "get_weather":
        continue
    observation = get_weather.invoke(call["args"])
    messages.append(ToolMessage(content=observation, tool_call_id=call["id"]))

final = llm_with_tools.invoke(messages)
print(final.content)
