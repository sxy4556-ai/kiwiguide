# Day 5：API 与中文前端

- 日期：2026-10-06
- 用时：约 35 分钟（开始 12:37，结束 13:12）
- 状态：已完成

## 今日目标
把 Agent 包装成 HTTP 接口（普通问答、反问恢复、SSE 流式、来源列表、后台更新索引），并做一个不需要构建工具的中文网页界面。

## 完成情况
**接口**
- [x] 安装 `sse-starlette`
- [x] `app/api/schemas.py`：请求和响应模型；问题去掉首尾空白后不能为空，最长 2000 字；thread_id 只允许字母、数字、`_`、`-`
- [x] `POST /chat`：返回 thread_id、status（answered / needs_clarification）、answer、citations、clarification_question；不传 thread_id 时新建会话
- [x] `POST /chat/{thread_id}/resume`：从断点继续；会话没有待回答的反问时返回 409
- [x] `POST /chat/stream`：SSE，事件为 start、progress、token、answer、citations、done（反问时为 clarification，出错时为 error）
- [x] `GET /sources`：主题、标题、链接、抓取日期
- [x] `POST /ingest/refresh`：后台重新抓取并增量更新索引，立即返回 202 和任务状态；另加 `GET /ingest/refresh` 查询进度（见"问题与决策"）
- [x] 统一异常处理，错误信息为中文；请求日志记录耗时

**前端**
- [x] `app/web/index.html`：聊天区和输入框、四个主题的快捷问题、出处卡片（标题、链接、抓取日期）、反问提示和回答框、顶部免责声明、流式显示
- [x] 挂载到 `/`

**测试**
- [x] 用 httpx AsyncClient 和假模型组装的 Agent 覆盖每个接口的正常和异常情况
- [x] 首页可访问，且包含关键的中文元素

**验收**
- [x] 测试全部通过；`/docs` 可以访问（有测试覆盖）
- [x] 本地启动后在浏览器里完成了一次包含反问的完整问答，步骤见下文

## 主要改动
- `app/api/schemas.py`、`app/api/service.py`、`app/api/routes.py`：新增接口层
- `app/main.py`：`create_app(service_factory)`、错误处理、请求日志、首页路由；关闭时释放存储
- `app/web/index.html`：中文界面（原生 HTML、CSS、JS，支持深色模式）
- `app/ingest/refresh.py`：抓取流程从 `scripts/fetch_sources.py` 中提取为 `fetch_sources()`，脚本和后台更新共用
- `app/retrieval/store.py`：新增 `ParentStore.list_documents()`
- `app/retrieval/search.py`：检索锁改为公开属性 `storage_lock`，更新索引时也使用
- `app/config.py`、`.env.example`：新增 `SOURCES_FILE`
- 测试：新增 `tests/test_api.py`（14 个）、`tests/test_refresh.py`（1 个），`tests/test_index.py` 新增 1 个

## 关键实现说明
- **服务层与延迟创建**：路由只负责参数校验，并把同步的 Agent 调用放进线程池（`run_in_threadpool`、`iterate_in_threadpool`），不阻塞事件循环。实际逻辑在 ChatService 里，测试用假模型、假检索器和内存 checkpointer 组装同一个 ChatService，所以接口测试跑的是真实的图，不是替身。真实服务在第一次调用问答接口时才创建，因为创建时要调用 Ollama 探测向量维度；Ollama 没启动时问答接口返回中文的 503，`/health` 和首页仍可访问，用户能看到页面并知道原因。代价是第一个请求较慢（实测约 11 秒，主要是加载 BM25 模型和探测维度）。
- **流式输出**：用 LangGraph 的 `stream_mode=["updates", "messages"]`。updates 用来推送节点进度（"正在检索官方资料"等）；messages 能拿到模型逐字输出，但只转发 generate 节点的 `AIMessageChunk`，否则 rewrite 和 grade 的 JSON 也会出现在聊天框里（有测试覆盖）。generate 的原始输出里引用编号还没整理、也没附来源和免责声明，所以流结束后再发一个 answer 事件给出完整回答，前端整体替换已显示的文字。出错时响应头已经是 200，无法再改状态码，因此改为发送中文的 error 事件。
- **后台更新与检索互斥**：Qdrant 本地模式同一时间只允许一个客户端打开，服务运行时不能再跑建索引脚本，所以 `/ingest/refresh` 在服务进程内复用已打开的存储。抓取阶段（约 3 分钟）不持锁，问答照常；写索引时持有检索锁，检索会等写完。同一时间只允许一个任务，重复提交返回 409；任务失败只记录在状态里，不影响服务。
- **出处卡片按页面合并**：Day 4 记录的问题是同一页面的多个段落在来源列表中重复出现。前端把相同 URL 的引用合并成一张卡片，编号写在一起（如 `[1][2][3] Rent increases and reductions`），并隐藏正文末尾的文字版来源列表。接口返回的 answer 和 citations 保持不变，命令行和其他调用方不受影响。

## 测试结果
- `uv run ruff check .`：通过
- `uv run pytest -q`：89 个测试全部通过，0 失败，0 跳过（Day 4 结束时 73 个，今天新增 16 个）

**浏览器实测**（对话模型 gpt-oss:120b-cloud，本地 `uv run uvicorn app.main:app --port 8000`）

| 步骤 | 操作 | 结果 |
|---|---|---|
| 1 | 打开 `http://localhost:8000/`，`/health` 返回 ok，`/sources` 返回 50 个来源 | 页面显示免责声明和四个快捷问题按钮 |
| 2 | 输入"我住的地方要涨租了，我有什么权利？"并发送 | 约 5 秒内出现"需要补充信息"卡片："您是正式租客、合租房客还是寄宿者？" |
| 3 | 在卡片的回答框输入"我是正式租客，签了定期租约" | 调用 resume（6.4 秒），回答涨租的 12 个月间隔、市场租金评估、仲裁庭申请、严重困难时提前终止租约等，附免责声明；出处卡片 2 张：`[1][2][3] Rent increases and reductions`、`[4] Ending a fixed-term tenancy early` |
| 4 | 在同一会话点击"打工"快捷按钮 | 2 秒时显示"正在合并检索结果…"，7 秒时回答已逐字显示到最低工资部分，结束后显示 2 张出处卡片 |
| 5 | `curl -X POST /ingest/refresh` 两次 | 第一次 202 running，第二次 409；更新期间 `/chat` 正常回答（8.3 秒）；约 3 分钟后状态为 succeeded："抓取 50 个来源：成功 50，失败 0，跳过 0；索引：新增 0，更新 1，未变化 49，删除 0 个页面" |

浏览器控制台无报错，服务日志无异常。

## 问题与决策
- **新增 `GET /ingest/refresh`**：PLAN 只写了 POST 返回任务状态。更新要几分钟，没有查询接口就无法知道何时完成、是否失败，所以加了一个只读的状态接口。
- **新增配置项 `SOURCES_FILE`**：后台更新要读来源清单，按项目约定路径不写死在代码里。
- **抓取流程提取为函数**：后台更新和 `scripts/fetch_sources.py` 原本会各写一份抓取循环，提取为 `fetch_sources()` 后两边共用，脚本输出不变；Day 7 的 `refresh_sources.py` 也可以复用。
- **流式请求的耗时日志**：请求日志中间件在响应头发出时记录，流式请求只显示 2 毫秒。在流结束时另记一条"流式回答结束"的总耗时。
- **反问恢复不走流式**：前端提交反问的答案时调用普通的 resume 接口，等待期间显示进度文字（实测约 6 秒）。PLAN 没有要求恢复也流式输出，暂不增加。
- **服务运行时不能使用命令行脚本**：Qdrant 本地库被服务进程占用，`scripts/ask.py` 和 `scripts/build_index.py` 需要先停止服务再运行。已写进 `build_service()` 的文档字符串，Day 7 写 README 时一并说明。
## 明日计划
Day 6：评测与调优
- `scripts/run_eval.py --mode agent`：30 道题分别跑朴素 RAG 和 Agent
- 指标：hit@5、MRR，以及由 LLM 评判的忠实度和正确率
- 写 `docs/eval.md`，并调整 1–2 个参数做前后对比；顺带看 Day 4 记录的税码子问题检索不足
