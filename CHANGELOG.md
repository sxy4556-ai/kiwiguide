# 更新记录

## 未发布

### Day 6（2026-10-07）
- `scripts/run_eval.py` 支持评测回答（`--mode naive|agent`），LLM 评判忠实度和正确率（1–5 分），支持并行和结果文件后缀
- 新增评测报告 `docs/eval.md`：Agent 的 hit@5 1.000（基线 0.967）、MRR 0.900（基线 0.894）、忠实度 4.77（基线 4.73），正确率 4.13 低于基线 4.53，报告中分析了原因
- Agent 每次放进上下文的父块数由 6 调为 8
- 收紧反问条件，30 题中的反问次数由 8 次降到 5 次
- 修复引用编号【[n]】显示为多余括号的问题
- 测试增至 95 个

### Day 5（2026-10-06）
- 新增接口：`POST /chat`、`POST /chat/{thread_id}/resume`、`POST /chat/stream`（SSE）、`GET /sources`、`POST /ingest/refresh` 和 `GET /ingest/refresh`
- 统一中文错误响应（422、409、503、500）和请求耗时日志；问答服务在首次调用时创建，Ollama 不可用时返回 503，不影响 `/health`
- 新增中文网页界面（`/`）：主题快捷问题、节点进度和流式回答、反问回答框、按页面合并的出处卡片、顶部免责声明
- 抓取流程提取为 `app/ingest/refresh.py`，命令行脚本和后台更新共用；新增配置项 `SOURCES_FILE`
- 新增依赖 `sse-starlette`
- 测试增至 89 个

### Day 4（2026-10-05）
- Agent 新增反问：缺少签证类型、学期/假期或居住方式等关键信息时暂停并反问，回答后从断点继续；每轮最多反问一次
- 复合问题拆成最多 3 个子问题，各自按主题过滤，用 `Send` 并行检索后按序合并
- 越界问题固定文字拒答；个案法律或移民问题附按主题选择机构的转介说明
- 混合检索支持多线程同时调用（修复并行检索时的 SQLite 跨线程错误）
- `scripts/ask.py` 支持反问和 `--resume`
- 测试增至 73 个

### 模型调整（2026-10-04）
- 对话模型默认改为 `gpt-oss:120b-cloud`：原来的 `deepseek-v4-flash:cloud` 已于 2026-09-25 下线，每次调用都会失败后退回本地模型。实测单题问答从约 9 分钟降到约 3 秒
- 备用模型改为不带思考的 `qwen3:4b-instruct-2507-q4_K_M`：原来的 `qwen3:4b` 是总是开启思考的版本，退回本地时每题约 320 秒，更换后约 19 秒
- 备用模型调用时请求关闭思考模式
- 引用解析兼容全角括号【n】和［n］，统一改写为 [n]
- 思考段的去除兼容只有结尾 `</think>` 的输出，避免推理草稿出现在回答里
- 测试增至 66 个

### Day 3（2026-10-04）
- 新增 LangGraph Agent：summarize（超过 6 轮压缩历史）、rewrite（英文检索词 + 主题判断）、retrieve、grade（资料不足时带原因重试，最多 2 次）、generate
- 结构化输出：JSON 经 pydantic 校验，失败重试一次后降级
- 引用编号由代码按出现顺序重排，删除越界编号，保证正文编号与来源列表一一对应
- 新增 SQLite checkpointer 多轮会话（`data/checkpoints.sqlite`，按 thread_id 区分）
- 新增命令行提问脚本 `scripts/ask.py`
- 新增假检索器；测试增至 62 个

### Day 2（2026-10-03）
- 新增父子分块（按标题切父块，约 500 字符、重叠 80 字符切子块）
- 新增 Qdrant 本地混合索引（qwen3-embedding 稠密向量 + BM25 稀疏向量）和 SQLite 父块库，按 content_hash 增量更新；`scripts/build_index.py`
- 新增混合检索：RRF 融合、主题过滤、父块去重回取
- 新增对话模型工厂（主模型失败时切换备用模型）和朴素 RAG 基线
- 新增 30 道评测题、hit@k 和 MRR 指标、`scripts/run_eval.py`；基线 hit@5 0.967、MRR 0.898
- 新增配置项 `SPARSE_MODEL`
- 测试增至 52 个

### Day 1（2026-10-02）
- 新增 FastAPI 应用骨架：配置读取、统一日志、`GET /health`（Ollama 不可达时返回 degraded）
- 新增环境检查脚本 `scripts/check_env.py`，缺少向量模型时自动下载
- 新增 GitHub Actions CI：运行 ruff 和 pytest
- 新增数据采集：`sources.yaml`（4 个主题共 50 个官方页面）、遵守 robots.txt 的抓取器、trafilatura 正文清洗、`scripts/fetch_sources.py`
- 新增 `docs/data-sources.md`：各站点的许可与抓取规则
- 26 个离线测试

### Day 0（2026-10-02）
- 初始化 git 仓库和 uv 项目（Python 3.12）
- 新增开发计划 `PLAN.md`、设计文档 `docs/design.md`、README 和开发日志
- 开发计划定为 7 天加 1 天缓冲
