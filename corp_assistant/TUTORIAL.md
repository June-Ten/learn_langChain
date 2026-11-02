# 实现教程

这篇教程顺着一次真实请求，说明 `corp_assistant` 是怎么串起来的。建议边读边打开对应文件。运行方式在 [README.md](README.md)。

它做的事情可以收成一句：HTTP 请求先认出是谁，业务数据放在 MySQL，模型只通过工具读写这些数据。前面三课分别练了调用模型、结构化输出、手动执行工具。这里把三件事放进一个有接口、有身份、有落库的服务里。每一块都只做到能跑通。

## 文件各管一层

| 文件 | 这一层做什么 |
| --- | --- |
| `main.py` | 启动时建库、装文档、挂中间件和异常处理 |
| `api.py` | URL 到函数的映射，入参和出参用 Pydantic |
| `auth.py` | API Key、当前员工、每分钟限流 |
| `store.py` | MySQL 的表、种子数据和全部 SQL |
| `knowledge.py` | 把 Markdown 切成小段，按关键词打分 |
| `tools.py` | 给模型看的五个工具 |
| `assistant.py` | 组 Agent、跑对话、把一句话整理成工单草稿 |
| `context.py` | 用上下文变量把当前工号带进工具 |
| `schemas.py` | 请求体和响应体 |
| `demo.py` | 不经过 HTTP，直接叫 `chat()` |

依赖方向是单向的：`api` 调用 `assistant` 和 `store`，`assistant` 调用 `tools`，`tools` 再调用 `store` 和 `knowledge`。工具函数里不要去 import `api`，否则一启动就会循环导入。

## 一次对话实际走了哪些函数

以赵敏（`E004`）问「年假有几天？」为例。`POST /api/v1/chat` 的路径是：

```text
uvicorn
  -> main.access_log          生成请求号，记耗时
  -> auth.current_user        核对 Key，查出赵敏
  -> api.chat                 只做参数转发
  -> assistant.chat           写入用户这句话，取出最近 8 条
  -> create_agent(...).invoke 模型决定要不要调工具
  -> tools.search_knowledge   模型发出调用后，由框架执行
  -> knowledge.search         在制度和笔记里打分
  -> assistant.chat           把最终回答写回 messages，并记一条审计
```

模型自己不查数据库。它只能返回「请调用 `search_knowledge`，参数是年假」。真正打开文件、算分数的是 Python 函数。这和 `lesson03_tool.py` 里手写的循环是同一件事，只是循环交给了 `create_agent`。

## 启动时做了三件准备

`python -m uvicorn corp_assistant.main:app` 会导入 `main.py`。文件末尾的 `app = create_app()` 在导入时就执行。

`create_app()` 里按这个顺序准备：

1. `setup_logging()` 配置根日志。已经有 handler 时只改级别，避免测试里重复打印。
2. `store.init_db()` 执行 `CREATE TABLE IF NOT EXISTS`。表已经在就什么都不改。
3. `store.seed()` 数一下 `employees`。有记录就返回，所以重启不会把李明插进去两次。
4. `knowledge.load()` 读 `knowledge_docs/*.md`，放进内存列表 `_chunks`。
5. 创建 FastAPI，挂上 CORS、访问日志、两种异常处理，再 `include_router`。

数据库是本机 Docker 里的 MySQL，默认库名 `langchain`。连接参数来自 `MYSQL_HOST`、`MYSQL_PORT`、`MYSQL_USER`、`MYSQL_PASSWORD`、`MYSQL_DATABASE`。

`/health` 只表示进程活着。`/ready` 会执行 `SELECT 1`，库打不开就返回 503。这两个接口不经过 `current_user`。

## 配置每次现读

`config.get_settings()` 没有做缓存。每次调用都 `load_dotenv()`，再读环境变量。测试可以在请求前改 `MYSQL_DATABASE` 或 `CORP_RATE_LIMIT`，下一次读到的就是新值。

和模型有关的三个变量沿用前几课：`DEEPSEEK_API_KEY`、`DEEPSEEK_MODEL`、`DEEPSEEK_API_BASE`。助手自己的变量以 `CORP_` 开头。Key 默认是 `dev-key`，多个 Key 用逗号分开。

## 请求进业务之前

`/api/v1` 下的接口都写了 `user: dict = Depends(current_user)`。FastAPI 会先调用 `auth.current_user`，把它的返回值填进 `user`。

这个函数做四件事：

1. `X-API-Key` 必须在 `CORP_API_KEYS` 里，否则 401。日志只记「拒绝了」，不把 Key 打出来。
2. 用这个 Key 做限流。`CORP_RATE_LIMIT` 是每 60 秒的次数，`0` 表示关闭。时间用 `time.monotonic()`，改系统时钟不会把窗口算乱。计数存在进程内的字典里，重启就清空，多进程也不会共享。
3. `X-User-Id` 必须是 `employees` 表里的工号。这里没有密码，工号本身就是身份。示例项目用请求头代替登录。
4. 返回那一行员工，后面的接口拿 `user["role"]` 和 `user["department"]` 做判断。

业务代码想失败，就 `raise AppError(状态码, "说明")`。`main.py` 的异常处理把它收成 JSON：

```json
{"detail": "需要管理员权限", "request_id": "ab12cd34ef56"}
```

参数对不上 Pydantic 模型时，FastAPI 抛 `RequestValidationError`，统一返回 422，字段错误放在 `errors`。访问日志中间件无论成功失败都会加上 `X-Request-Id`。客户端如果自己带了这个头，就沿用它。

管理员接口在拿到 `user` 之后再调用 `require_admin(user)`。员工调 `GET /api/v1/audit` 或 `GET /api/v1/metrics` 会得到 403。笔记的新增、制度文件的重新加载也一样。

## 数据怎么落库

`store.get_conn()` 是每次操作新开一个 MySQL 连接的上下文管理器。成功就 `commit`，异常就 `rollback`，最后关闭。查询结果按列名收成字典，再交给 Pydantic。

六张表：

- `employees`：工号、部门、角色。角色只有 `employee`、`manager`、`admin`。
- `tickets`：工单。新建时状态固定是 `open`。
- `conversations` / `messages`：对话和其中的每一句。
- `audit_logs`：谁在什么时间做了写操作。
- `knowledge_notes`：管理员从接口写进去的补充说明。制度原文仍在 Markdown 文件里。

写操作成功后调用 `add_audit`。建工单记 `ticket.create`，改状态记 `ticket.update`，发笔记记 `note.create`，完成一轮对话记 `chat`。审计用的是另一个连接，所以工单已经提交、审计却写失败时，工单仍在。示例里接受这种缝隙。

SQL 的条件全部用 `?` 占位。用户输入进参数列表，不拼进 SQL 字符串。`LIKE` 的百分号是代码自己加的。

## 工单为什么有的人看不见

可见范围写在 `store.py`，接口层不再判断一次。

列表走 SQL：

- 员工：`t.requester_id = 自己`
- 主管：`e.department = 自己的部门`
- 管理员：不加这条条件

单条读取用 `can_view_ticket`。主管能看到的是「提单人所在部门等于自己部门」的工单，不是「自己名下员工」的工单。张伟（`E003`，财务部）提的单，陈静（`E005`，财务主管）能看，王芳（`E002`，人力主管）不能看。别人看不到时返回 404，不告诉他这张单存在。

改状态只允许主管和管理员。员工调用 `PATCH` 时，`update_ticket_status` 先看角色，直接 403，还没查这张单在不在。

`POST /api/v1/tickets` 和工具 `create_ticket` 最后都进 `store.create_ticket`。类别和优先级不在允许集合里就 400。HTTP 这边还会先被 `TicketIn` 挡成 422，因为请求体用了 `Literal`。工具没有这层 Pydantic，所以 `store` 里再查一次。

## 制度检索没有用向量

`knowledge.load()` 按文件读 Markdown，再用正则 `\n(?=## )` 在每个二级标题前切开。`leave.md` 会变成「标题段、年假、病假、事假」几段，每段记住来源文件名。这些段只活在内存里，重启要重新 `load()`。

查询时把中文和英文拆开：

- 英文和数字整词匹配，并转成小写。
- 不超过 4 个字的中文整段去对，所以「年假」能直接命中。
- 更长的中文切成二字片段。「年假有几天」会得到「年假、假有、有几、几天」，其中「年假」落在正文里。

分数是命中片段的字数之和。0 分丢掉，剩下按分数取前几条。管理员笔记在查询时从 MySQL 读出来，和文件段落放进同一个列表。笔记的 `source` 是 `note:3` 这种形式。

这里不用嵌入模型，是因为前几课只有对话模型，没有单独的向量接口。关键词够演示「先检索，再让模型根据检索结果回答」。

工具把命中结果拼成纯文本。一条都没有时，返回的句子要求模型承认不知道。系统提示里又说了一遍。两处都写，是因为模型有时不看工具结果里的那句交代。

## 工具怎么知道是谁在调用

`@tool` 装饰的函数签名里只有模型能填的参数，例如 `query`、`title`。HTTP 里的当前用户进不去这个签名。

`assistant.chat` 在调用 Agent 之前执行：

```python
token = current_user_id.set(user["id"])
```

`context.py` 里的 `ContextVar` 存在当前执行上下文中。`tools._requester()` 用 `current_user_id.get()` 取回工号，再建工单、查工单。`finally` 里 `reset(token)`，避免这个请求的工号留到下一个请求。

工具里的 `AppError` 被接住，变成普通字符串返回给模型。如果让异常直接抛出，这一轮 Agent 就断了，模型没有机会换个参数再试。HTTP 接口则相反：同样的错误要变成 4xx，所以 `store` 继续抛 `AppError`，由 `main.py` 接住。

五个工具和系统提示是成对的。提示里写了什么时候用哪一个：制度用 `search_knowledge`，查人用 `lookup_employee`，明确要提交才用 `create_ticket`，看进度用 `list_tickets`，问时间用 `current_time`。函数的 docstring 会变成工具 schema 的说明，模型靠它选工具、填参数。

## Agent 这一层对应第三课

第三课是手写的：

```python
llm_with_tools = llm.bind_tools([get_weather])
ai = llm_with_tools.invoke(...)
observation = get_weather.invoke(call["args"])
```

`create_agent` 把「模型决定调用、执行工具、把观察结果送回去、再问模型」这个循环包起来了。`assistant.chat` 每次请求新建一个 Agent，因为系统提示里写着当前用户的姓名、部门和角色。换一个人就要换提示。

有两个和 DeepSeek 有关的约束，和前两课相同：

- 不要传 `tool_choice`。`deepseek-flash` 的思考模式不支持强制选工具。`create_agent` 默认就是空，所以这里没有设置它。
- 结构化输出用 `method="json_mode"`，提示词里必须出现 `json`。DeepSeek 不支持 OpenAI 那套 `json_schema`。

`ToolLogMiddleware` 包在工具执行外面，只打一行日志，然后调用原来的 `handler`。同步和异步各写了一个，因为框架两条路径都可能走到。

`recursion_limit` 设成 12，是图里的步数上限。模型如果一直叫工具，会在这里停下来，而不是无限循环。

返回给接口的 `tools` 字段，是从结果消息的 `tool_calls` 里收集的。历史消息在送进模型之前被重构成了没有 `tool_calls` 的 `HumanMessage` 和 `AIMessage`，所以收上来的调用都属于这一轮。

`_as_text` 同时接受字符串和内容块列表。有的模型把正文放在 `content` 字符串里，有的放在 `[{"type": "text", "text": "..."}]` 里。

## 多轮对话存了什么

第一句没有 `conversation_id` 时，`create_conversation` 用问题的前 40 个字当标题。之后的请求带上返回的 id。

`require_conversation` 检查这轮对话属于当前用户。管理员可以读别人的会话。不属于自己时返回 404。

送进模型的历史只有最近 8 条，而且只有 `user` 和 `assistant` 的正文。工具的原始观察没有存进 `messages`。下一轮模型看到的是上一轮的最终回答，看不到当时检索到的原文。这样实现短，长对话也不会把工具原文越积越长。代价是模型不能引用上一轮检索的原句，除非那些内容已经写进了回答。

用户那句在调用模型之前就入库了。模型失败时，这句仍然在，接口返回 502。

## 工单草稿对应第二课

`POST /api/v1/tickets/suggest` 不创建工单。它调用 `suggest_ticket`：

```python
structured = get_llm().with_structured_output(TicketDraft, method="json_mode")
```

`TicketDraft` 的四个字段和 `Field(description=...)` 会告诉模型 JSON 长什么样。提示词里写了允许的类别和优先级，也写了「JSON」。返回后如果类别或优先级不在集合里，代码把它改成 `other` 或 `medium`，避免草稿因为一个越界词整个失败。

真正落库仍要再调 `POST /api/v1/tickets`，或者让对话里的模型调用 `create_ticket`。草稿和正式工单分开，是为了让结构化输出这一步可以单独看。

没有 `DEEPSEEK_API_KEY` 时，`get_llm()` 抛 503。员工目录、工单和制度搜索不经过这个函数，所以没有 Key 也能用。

## 测试覆盖的是不调用模型的部分

`corp_assistant/tests/test_api.py` 给每个测试一个临时库，并把限流设为 0。断言包括：

- 没有 Key 不能访问 `/api/v1/me`
- 财务员工的工单，本人和财务主管能看到，IT 员工和人力主管看不到
- 员工不能改状态，主管可以
- 员工不能读审计
- 搜索「年假」能命中「5 天」
- 只有管理员能写笔记，写完后关键词能搜到

对话和草稿依赖外网模型，没有放进这组测试。要看那两条链路，用 `python -m corp_assistant.demo 年假有几天？`，或者在 `/docs` 里调 `/api/v1/chat`。

## 和前三课的对应

| 课 | 在这个项目里的位置 |
| --- | --- |
| `lesson01_hello.py` 的 `ChatDeepSeek` | `assistant.get_llm` |
| `lesson02_structured.py` 的 `json_mode` | `assistant.suggest_ticket` |
| `lesson03_tool.py` 的 `bind_tools` 和手写循环 | `tools.py` 加 `create_agent` |

服务化之后多出来的部分是身份、权限、持久化和错误码。模型仍然只负责两件事：决定调用哪个工具，以及根据工具返回的文本组织回答。
