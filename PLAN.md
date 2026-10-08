# KiwiGuide 开发计划

开发按天推进：每次完成下面"进度"中第一个未勾选的 Day，完成后勾选，并在 `docs/devlog/` 写当天日志。设计细节见 `docs/design.md`。

## 进度
- [x] Day 0：项目初始化（2026-10-02）
- [x] Day 1：工程骨架与数据采集
- [x] Day 2：分块、索引与检索基线
- [x] Day 3：Agent v1
- [x] Day 4：反问、并行与转介
- [x] Day 5：API 与中文前端
- [x] Day 6：评测与调优
- [x] Day 7：收尾发布
- [ ] Day 8：缓冲（可选）

---

## Day 0：项目初始化
- 项目骨架：git 仓库、uv 项目、`.gitignore` 和 `.gitattributes`、`.env.example`
- 文档：`PLAN.md`、`docs/design.md`、README、CHANGELOG、`day-00` 日志
- GitHub 远程仓库与首次 push

**验收**：首次 push 成功。

## Day 1：工程骨架与数据采集
**目标**：搭好可运行、可测试、能跑持续集成的 FastAPI 项目骨架；从新西兰政府官网采集四个主题的资料，清洗成带元数据的 Markdown。

**任务：工程骨架**
- 安装依赖
  - `uv add fastapi "uvicorn[standard]" pydantic-settings httpx trafilatura pyyaml`
  - `uv add --dev pytest pytest-asyncio ruff`
- `app/__init__.py`、`app/config.py`
  - 用 pydantic-settings 读取 `.env`，字段与 `.env.example` 一致
  - 提供带缓存的 `get_settings()`
- `app/logging_config.py`：统一日志格式（时间、级别、模块、消息），日志级别来自配置
- `app/main.py`
  - `create_app()` 应用工厂，模块级 `app = create_app()`
  - `GET /health` 返回服务状态、版本、Ollama 是否可达；不可达时返回 `degraded`，不要报 500
- `scripts/check_env.py`
  - 检查 Ollama 服务是否在运行、`LLM_MODEL` 和 `EMBED_MODEL` 是否已安装，并用中文输出结果
  - 缺少向量模型时执行 `ollama pull qwen3-embedding:0.6b`（约 640MB）
- `pyproject.toml`
  - ruff 配置：line-length 100，规则集 E、F、I、UP、B
  - pytest 配置：`pythonpath = ["."]`，`asyncio_mode = "auto"`
- `.github/workflows/ci.yml`
  - 在 push 和 pull_request 时触发，运行环境 ubuntu-latest
  - 用 astral-sh/setup-uv 安装依赖，然后运行 `uv run ruff check .` 和 `uv run pytest -q`
- 测试
  - `/health` 在 Ollama 可达和不可达两种情况下的行为（用 monkeypatch 模拟，不访问网络）
  - 配置的默认值，以及环境变量覆盖默认值

**任务：数据采集**
- 先查看各站点的 robots.txt 和版权页面，把结论写进 `docs/data-sources.md`：许可类型、是否允许抓取、引用要求。不允许抓取的站点直接排除
- 编写 `sources.yaml`
  - 四个主题：tenancy（租房）、employment（打工与劳动权益）、visa（学生签证）、tax（税务），共 30–50 个官方页面
  - 每条包含 url、topic、title（可选）、note（可选）
  - 每个 URL 都要先确认页面存在且内容相关，再写入
- 选题起点（按实际页面调整）
  - tenancy.govt.nz：押金、涨租、终止租约、健康住房标准、合租与寄宿、租赁仲裁庭
  - employment.govt.nz：最低工资、带薪年假与公共假日、雇佣协议、工资与扣款
  - immigration.govt.nz：学生签证的打工条件、签证条件与义务、毕业后工作签证
  - ird.govt.nz：申请 IRD 号码、税码、学生与兼职收入、KiwiSaver 基础
- `app/ingest/fetch.py`
  - 用 httpx 抓取，遵守 robots.txt
  - 同一域名请求间隔至少 1 秒
  - User-Agent 中带上项目的 GitHub 地址
  - 失败重试 2 次，并记录失败原因
- `app/ingest/clean.py`：用 trafilatura 提取正文并转成 Markdown，保留标题层级，去掉导航、页脚等噪音
- 输出到 `data/processed/<topic>/<slug>.json`，字段：url、title、topic、retrieved_at、content_hash（正文的 sha256）、markdown
- `scripts/fetch_sources.py`：命令行入口，用中文打印成功、失败、跳过的数量
- 测试（不访问网络）
  - 用 `tests/fixtures/` 中的离线 HTML 样例测试清洗：标题层级保留、噪音去除
  - slug 生成、content_hash 稳定
  - robots 判断（用假的 robots 内容）

**验收**
- `uv run ruff check .` 和 `uv run pytest -q` 全部通过
- 本地运行 `uv run uvicorn app.main:app` 后访问 `/health` 正常
- `uv run python scripts/check_env.py` 能如实报告 Ollama 和模型的状态
- 实际运行一次抓取，成功率 ≥90%，失败的页面在日志中列出原因；`data/` 没有被提交
- push 后 GitHub Actions 通过；无法确认 CI 状态时，在日志中如实写明

## Day 2：分块、索引与检索基线
**目标**：把清洗后的文档切成父子块，建立稠密加 BM25 的混合索引；实现混合检索和朴素 RAG 基线，建立评测集和检索指标。

**任务：分块与索引**
- 安装依赖：`uv add qdrant-client fastembed langchain-ollama`
- 确认向量模型已下载（`ollama list`）。如果 `qwen3-embedding:0.6b` 不可用，改用 `bge-m3`，并在日志中说明
- `app/ingest/chunk.py`：父子分块
  - 父块：按 Markdown 标题（#、##、###）切分；超过 2000 字符的按段落再切，少于 200 字符的与相邻块合并
  - 子块：在父块内按约 500 字符、重叠 80 字符切分，优先在句子边界断开
  - 每个块都带 parent_id、url、title、topic、heading_path（标题路径）、retrieved_at
- `app/retrieval/embeddings.py`
  - 封装稠密向量（OllamaEmbeddings）和稀疏向量（fastembed 的 `Qdrant/bm25`）
  - 向量维度在运行时探测，不要写死
- `app/retrieval/store.py`
  - Qdrant 本地模式，路径 `data/qdrant`；集合中包含命名的 dense 和 sparse 两种向量
  - 父块存入 SQLite（`data/parents.sqlite`）
- `app/ingest/index.py` 和 `scripts/build_index.py`
  - 按 content_hash 增量建索引：只重建内容有变化的页面，并删除已不存在页面的旧块
  - 用中文打印统计信息

**任务：检索与基线**
- `app/retrieval/search.py`
  - dense 和 sparse 各取 top 20 作为 prefetch，用 RRF 融合后取 top_k（默认 6）
  - 可按 topic 过滤
  - 命中的子块按 parent_id 去重，再取回对应的父块
- `app/llm.py`
  - 统一创建对话模型：ChatOllama，读取 `LLM_MODEL`
  - 调用失败时可以切换到 `FALLBACK_LLM_MODEL`
- `app/rag/naive.py`：朴素 RAG 基线。直接用原问题检索，拼接上下文，生成带编号引用的中文回答
- `eval/questions.yaml`：30 道题
  - 约三分之二中文、三分之一英文，覆盖四个主题，包含少量复合问题和信息不足的问题
  - 每题标注 gold_urls（应当命中的官方页面）和 key_points（答案要点）
  - 题目必须基于 `data/` 中实际抓到的内容编写；文件开头注明"标准答案待人工复核"
- `app/eval/metrics.py`：hit@k 和 MRR，纯代码计算
- `scripts/run_eval.py --mode naive --retrieval-only`：输出检索指标，结果保存到 `eval/results/`（结果文件提交）

**测试**（使用假向量模型、假 LLM 和临时目录）
- 分块规则：按标题切分、合并过短的块、子块重叠、元数据完整
- 父块回取；增量逻辑：content_hash 不变时跳过
- 指标计算（用手算的样例核对）、RRF 融合的排序、父块去重
- 朴素 RAG 的引用编号格式

**验收**
- 用真实数据建索引成功，在日志中记录块数和耗时
- 得到基线的 hit@5 和 MRR，写进当天日志
- 测试全部通过

## Day 3：Agent v1
**目标**：用 LangGraph 搭出带自我纠错的 Agentic RAG 主流程和多轮会话记忆。

**任务**
- 安装依赖：`uv add langgraph langgraph-checkpoint-sqlite`
- `app/agent/state.py`：图的状态，包括 messages、summary、question、search_queries、topic、retrieved、grade、retries、answer、citations 等
- `app/agent/prompts.py`：集中存放所有提示词。提示词用中文说明，要求模型输出 JSON
- `app/agent/nodes.py`，依次为：
  1. summarize：对话超过 6 轮时压缩历史
  2. rewrite：把问题改写成 1–3 条英文检索词，并判断所属主题
  3. retrieve：调用 Day 2 的混合检索
  4. grade：由 LLM 判断检索结果能否回答问题，输出 JSON；结果不足且 retries < 2 时，带上失败原因回到 rewrite
  5. generate：生成中文回答，官方术语附英文原名，用 [1][2] 编号引用，结尾附免责声明
- 结构化输出：用 pydantic 模型解析 JSON；解析失败时重试一次，仍失败就走降级逻辑
- `app/agent/graph.py`：组装 StateGraph，使用 SQLite checkpointer（`data/checkpoints.sqlite`），按 thread_id 保存多轮会话
- `tests/fakes.py`：可以预先编排输出的假 LLM 和假检索器
- 测试
  - 正常路径：引用编号与来源一一对应
  - 检索结果不足时触发重试，且最多重试 2 次
  - 多轮对话能保留上下文

**验收**：用假模型的测试全部通过；用真实模型跑 3 个问题，把问答样例写进日志。

## Day 4：反问、并行与转介
**目标**：让 Agent 会反问、会拆分复合问题，并且守住回答范围。

**任务**
- 反问
  - 在 rewrite 之后加一个 clarify 判断节点
  - 缺少关键信息时（例如签证类型；是正式租客、合租房客还是寄宿；是否在学期中），用 `interrupt()` 暂停并返回中文反问
  - 用户回答后从断点继续
- 并行：把复合问题拆成最多 3 个子问题，用 `Send` 并行检索，汇总后统一生成回答
- 范围与转介
  - 与新西兰留学生活无关的问题，礼貌拒答
  - 涉及个案法律或移民建议时，只提供官方的一般性信息，并建议联系对应的政府机构、社区法律中心（Community Law）或持牌移民顾问
- 测试
  - 反问时暂停，回答后能恢复
  - 复合问题拆成多个子问题，并且每个都被检索
  - 无关问题被拒答
  - 移民个案问题的回答中包含转介说明

**验收**：测试全部通过；用真实模型各演示一次反问和拆分，写进日志。

## Day 5：API 与中文前端
**目标**：把 Agent 包装成可用的 HTTP 接口，并做一个开箱即用的中文网页界面。

**任务：接口**
- 安装依赖：`uv add sse-starlette`
- `app/api/schemas.py`：请求和响应模型
- 接口
  - `POST /chat`
    - 输入：question，以及可选的 thread_id
    - 输出：thread_id、status（answered 或 needs_clarification）、answer、citations、clarification_question
  - `POST /chat/{thread_id}/resume`：提交反问的答案，从断点继续执行
  - `POST /chat/stream`：SSE 流式输出，先推送节点进度事件和回答文本，最后发送引用列表
  - `GET /sources`：已索引的来源列表，包含主题、标题、链接、抓取日期
  - `POST /ingest/refresh`：在后台重新抓取并增量更新索引，返回任务状态
- 统一异常处理，错误信息用中文；请求日志中记录耗时

**任务：前端**
- `app/web/index.html`：原生 HTML、CSS、JS，不引入构建工具，包含：
  - 聊天区和输入框
  - 主题快捷问题按钮：租房、打工、签证、税务
  - 出处卡片：标题、链接、抓取日期
  - 反问时的提示和回答框
  - 顶部免责声明
  - 流式显示回答
- FastAPI 把这个页面挂载到 `/`

**测试**
- 用 httpx AsyncClient 和假 Agent，覆盖每个接口的正常情况和异常情况
- 首页可访问，且包含关键的中文元素

**验收**
- 测试全部通过；`/docs` 可以访问
- 本地启动后，在浏览器里完成一次完整问答（其中包括一次反问），并在日志中写明操作步骤和结果

## Day 6：评测与调优
**目标**：用数据证明 Agent 比朴素 RAG 好在哪里，并完成一轮调优。

**任务**
- 运行 `scripts/run_eval.py --mode agent`，对 30 道题分别跑朴素 RAG 和 Agent
- 指标
  - hit@5、MRR：用代码计算
  - 忠实度：回答内容是否都能在引用中找到依据，由 LLM 评判，1–5 分
  - 正确率：是否覆盖了 key_points，由 LLM 评判，1–5 分
- 写 `docs/eval.md`：结果对比表、典型的成功和失败案例分析、改进方向
- 根据结果调整 1–2 个参数（例如子块大小、top_k），并记录调整前后的对比
- 如果云模型被限流，换用 `FALLBACK_LLM_MODEL`，并在报告中注明

**验收**：报告完成；Agent 至少有一项指标优于基线，否则在报告中如实写明原因。

## Day 7：收尾发布
**目标**：让别人照着 README 就能把项目跑起来。

**任务**
- `scripts/refresh_sources.py`：重新抓取所有来源，只更新内容有变化的页面（复用 Day 1 和 Day 2 的逻辑），并打印变化统计
- 中文 README，包含以下内容：
  - 项目介绍
  - 架构图（mermaid）
  - 快速开始：安装 uv、登录 Ollama、拉取模型、抓取数据、建索引、启动服务
  - 接口说明
  - 评测结果摘要
  - 数据来源与许可
  - 免责声明
- 在 CHANGELOG 中汇总 v1.0.0
- 按 README 从零走一遍。可以克隆到临时目录运行；做不到时，写明用了什么替代方式验证
- 打 `v1.0.0` 标签

**验收**：测试全部通过，README 中的步骤可以复现。

## Day 8：缓冲（可选）
- 先补完之前没完成、或没达到验收标准的任务
- 如果都已完成，可以从以下选做：
  - MCP 服务：通过 MCP 协议把问答能力提供给支持 MCP 的客户端
  - 重排序模型
  - Dockerfile
- 全部结束后，写项目总结日志
