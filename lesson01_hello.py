import os
from dotenv import load_dotenv
from langchain_deepseek import ChatDeepSeek
from langchain.messages import HumanMessage, SystemMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

load_dotenv()

llm = ChatDeepSeek(
    model=os.getenv("DEEPSEEK_MODEL", "deepseek-flash"),
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    api_base=os.getenv("DEEPSEEK_API_BASE", "https://api.deepseek.com"),
    temperature=0,
)

# 直接调用
resp = llm.invoke([
    SystemMessage(content="你是简洁的助手，用中文回答。"),
    HumanMessage(content="什么是向量数据库？一句话。"),
])
print(resp.content)

# LCEL 链
chain = (
    ChatPromptTemplate.from_messages([
        ("system", "用中文、两句话内回答。"),
        ("human", "{question}"),
    ])
    | llm
    | StrOutputParser()
)
print(chain.invoke({"question": "RAG 是什么？"}))