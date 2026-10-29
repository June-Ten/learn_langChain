import os
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from langchain_deepseek import ChatDeepSeek

load_dotenv()

llm = ChatDeepSeek(
    model=os.getenv("DEEPSEEK_MODEL", "deepseek-flash"),
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    api_base=os.getenv("DEEPSEEK_API_BASE", "https://api.deepseek.com"),
    temperature=0,
)

class WeatherAdvice(BaseModel):
    city: str = Field(description="城市名")
    temp_c: int = Field(description="气温，摄氏度整数")
    summary: str = Field(description="一句话天气描述")
    ok_outdoor: bool = Field(description="是否适合户外")

# DeepSeek 不支持 OpenAI 的 json_schema；flash 思考模式也不支持 tool_choice。
# 用 json_mode：提示词里必须出现 "json"，并说明字段结构。
structured_llm = llm.with_structured_output(WeatherAdvice, method="json_mode")

result: WeatherAdvice = structured_llm.invoke(
    "根据常识估计：今天北京适不适合户外跑步？"
    "请只返回 JSON，字段：city, temp_c, summary, ok_outdoor。"
)
print(result)
print(result.city, result.temp_c, result.ok_outdoor)
# 若要字典：result.model_dump()
