# 星澜内部助手

把前面几课的模型调用、结构化输出和工具，放进一个能跑的企业内部助手里。每个模块只做最小实现：有接口、有数据、有权限，不展开复杂流程。

实现过程见 [TUTORIAL.md](TUTORIAL.md)。

## 运行

```powershell
.\.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
# 在 .env 填入 DEEPSEEK_API_KEY。查询员工、工单、制度不调用模型，可以不填。

docker compose --env-file .env -f docker/compose.yaml up -d
python -m uvicorn corp_assistant.main:app --reload --reload-dir corp_assistant
```

业务数据写入本机 MySQL。制度原文写入同一个 compose 里的 PostgreSQL（镜像 `pgvector/pgvector:pg17`，只监听 `127.0.0.1:5432`），库名默认都是 `langchain`。`corp_assistant/knowledge_docs/*.md` 只是种子，启动时切段并写入 `knowledge_chunks`。第一次会下载嵌入模型 `BAAI/bge-small-zh-v1.5`（约 90MB）。浏览器打开 http://127.0.0.1:8000 使用页面，http://127.0.0.1:8000/docs 是接口文档。

请求头：

- `X-API-Key: dev-key`
- `X-User-Id: E004`（赵敏，员工）。管理员是 `E001` 李明，财务主管是 `E005` 陈静。

命令行问一句（会调用模型）：

```powershell
python -m corp_assistant.demo 年假有几天？
```

不走模型的测试：

```powershell
python -m pytest
```

## 能做什么

- `POST /api/v1/chat`：LangChain agent。制度检索、查人、建工单、看进度、当前时间。
- `POST /api/v1/tickets/suggest`：用 json_mode 把一句话整理成工单草稿。
- 员工目录、部门、工单。员工看自己的，主管看本部门，管理员看全部。
- 制度文档存在 PostgreSQL + pgvector，按语义检索。管理员笔记仍在 MySQL。
- API Key、角色、每分钟限流、审计、健康检查、请求号、指标。

种子员工：E001 李明（管理员）、E002 王芳（人力主管）、E003 张伟（财务员工）、E004 赵敏（IT 员工）、E005 陈静（财务主管）。
