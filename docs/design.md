# KiwiGuide 设计文档

## 1. 目标与范围
- **用户**：在新西兰学习和生活的国际学生，主要用中文提问。
- **主题**：
  - 租房（tenancy）
  - 打工与劳动权益（employment）
  - 学生签证条件（visa）
  - 税务（tax）
- **原则**：只依据政府官网内容回答，每条结论都给出处；信息不足时先反问。
- **不做**：
  - 个案法律、移民或税务建议。涉及时只给出官方的一般性信息，并建议联系对应机构或持牌顾问。新西兰对移民建议有执业许可要求。
  - 与主题无关的闲聊。

## 2. 总体架构

```mermaid
flowchart LR
    U[浏览器中文界面] -->|HTTP / SSE| API[FastAPI]
    API --> AG[LangGraph Agent]
    AG --> RET[混合检索]
    RET --> QD[(Qdrant 本地库<br/>dense + sparse)]
    RET --> PS[(父块存储 SQLite)]
    AG --> LLM[Ollama 对话模型]
    AG --> CP[(会话 SQLite)]
    ING[采集与索引脚本] --> QD
    ING --> PS
    SRC[sources.yaml<br/>政府官网] --> ING
```

## 3. 数据流水线
1. **来源清单**：`sources.yaml` 列出官方页面，字段为 url、topic、title、note。
2. **抓取**（`app/ingest/fetch.py`）
   - 用 httpx 抓取，遵守 robots.txt
   - 同一域名的请求间隔至少 1 秒，失败重试 2 次
3. **清洗**（`app/ingest/clean.py`）
   - 用 trafilatura 提取正文，转成 Markdown，保留标题层级
   - 输出到 `data/processed/<topic>/<slug>.json`，字段为 url、title、topic、retrieved_at、content_hash、markdown
4. **分块**（`app/ingest/chunk.py`）
   - 父块：按 #、##、### 标题切分；超过 2000 字符的按段落再切，少于 200 字符的与相邻块合并
   - 子块：在父块内按约 500 字符、重叠 80 字符切分，优先在句子边界断开
5. **索引**（`app/ingest/index.py`）
   - 子块同时写入稠密向量（qwen3-embedding:0.6b，维度在运行时探测）和稀疏向量（fastembed 的 BM25），存进 Qdrant 本地库 `data/qdrant`
   - 父块存进 `data/parents.sqlite`
   - 按 content_hash 增量更新
6. **数据不入库**：`data/` 已加入 gitignore，仓库只保存来源清单，需要时用脚本重新生成。

## 4. 检索
- **混合检索**：dense 和 sparse 各取 top 20 作为 prefetch，用 RRF 融合后取 top_k（默认 6）。
- **主题过滤**：Agent 判断出主题后，用 payload 中的 topic 过滤。
- **父块回取**：命中的子块按 parent_id 去重，再把对应的父块作为上下文，兼顾检索精度和上下文完整性。

## 5. Agent 设计（LangGraph）

```mermaid
flowchart TD
    S[summarize 对话摘要] --> R[rewrite 拆分子问题 + 英文检索词 + 范围/转介/反问判断]
    R --> C{clarify 决定去向}
    C -- 缺少关键信息 --> I[interrupt 反问用户] --> R
    C -- 越界 --> G
    C -->|每个子问题一个 Send，并行| RT[retrieve 混合检索]
    RT --> M[merge 交替合并、去重]
    M --> GR{grade 相关性评分}
    GR -- 不足且重试次数小于 2 --> R
    GR -- 足够 --> G[generate 生成中文回答 / 拒答 / 附转介]
```

- **一次调用完成判断**：拆分子问题、范围、是否个案、是否反问都由 rewrite 的同一次模型调用输出，clarify 只按结果路由，不再调用模型，每轮少一次模型调用。
- **反问**：只针对会让答案完全不同的关键信息（签证类型与学期/假期；正式租客、合租还是寄宿）。每轮最多反问一次，重试时不反问。
- **子问题**：最多 3 个，各自带主题过滤（复合问题可能跨主题），用 `Send` 并行检索，按子问题序号交替合并。
- **拒答与转介**：越界问题不检索、不调用模型，固定文字拒答；个案问题在回答后按主题附上对应机构的转介说明。两者都由代码附加，不依赖模型。

- **显式图**：流程由图控制，不依赖模型原生的工具调用，更换模型时更稳定。
- **结构化输出**：各节点要求模型输出 JSON，用 pydantic 校验；失败时重试一次，再失败就降级。
- **状态**：messages、summary、question、sub_questions（每个含 question、query、topic）、search_queries、scope、needs_referral、clarification_question、clarified、sub_results、retrieved、grade、retries、answer、citations。
- **回答格式**：
  - 中文作答；官方术语首次出现时附英文原名
  - 用 [1][2] 编号引用，并附出处列表（标题、链接、抓取日期）
  - 结尾附免责声明；需要时给出转介建议
- **会话记忆**：SQLite checkpointer，存在 `data/checkpoints.sqlite`，按 thread_id 区分会话。
- **模型**：对话模型用 `LLM_MODEL`（Ollama 云模型，默认 gpt-oss:120b-cloud），调用失败时切换到 `FALLBACK_LLM_MODEL`（本地 qwen3:4b-instruct-2507，不带思考的版本）。备用模型调用时还会请求关闭思考模式，防止换成带思考的模型后一次问答要几分钟。输出中的思考段（包括只有结尾 `</think>` 的情况）会在解析前去掉。

## 6. API 设计（FastAPI）

| 方法与路径 | 说明 |
|---|---|
| `GET /health` | 服务状态、版本、Ollama 是否可达 |
| `POST /chat` | 提问；返回 thread_id、status（answered 或 needs_clarification）、answer、citations、clarification_question |
| `POST /chat/{thread_id}/resume` | 回答反问，从断点继续 |
| `POST /chat/stream` | SSE 流式输出：节点进度事件、回答文本、引用列表 |
| `GET /sources` | 已索引的来源列表 |
| `POST /ingest/refresh` | 在后台重新抓取并增量更新索引（202；已有任务在运行时 409） |
| `GET /ingest/refresh` | 查看更新任务的状态和结果摘要 |
| `GET /` | 中文网页界面 |

- **分层**：`app/api/routes.py` 只做参数校验和线程池调度；`app/api/service.py` 的 ChatService 包装 Agent 的提问、恢复和流式输出，以及来源列表和后台任务。测试时用假模型组装同一个 ChatService。
- **延迟创建**：问答服务在第一次调用问答接口时才创建（需要 Ollama 探测向量维度），Ollama 不可用时问答接口返回 503，`/health` 和首页照常可用。
- **流式事件**：start（thread_id）→ progress（节点进度）→ token（generate 的原始输出）→ answer（整理编号、附来源和免责声明后的完整回答）→ citations → done；需要反问时以 clarification 代替 answer 和 citations，出错时发送 error。token 只用于边生成边显示，前端收到 answer 后整体替换。
- **索引更新与检索互斥**：Qdrant 本地库只允许一个进程打开，服务运行时由 `/ingest/refresh` 在同一进程内更新索引；写索引期间持有检索锁，抓取阶段不持锁，问答不受影响。
- **错误格式**：所有错误都返回 `{"detail": 中文说明}`，包括参数校验（422）、状态冲突（409）、服务不可用（503）和未处理异常（500）。

## 7. 配置
统一由 `app/config.py`（pydantic-settings）读取 `.env`，各字段见 `.env.example`。项目不需要任何 API 密钥。

## 8. 测试策略
- 测试不访问网络、不调用真实模型。网络请求用离线样例代替，模型用 `tests/fakes.py` 中的假模型。
- 每个测试的文档字符串都写明为什么必须保证这个行为。例如：回答必须带官方链接，因为用户需要自己核实；缺少签证类型时必须反问，因为不同签证的规定不同。
- CI（GitHub Actions）在每次 push 时运行 ruff 和 pytest。

## 9. 评测
- **题集**：`eval/questions.yaml`，共 30 题，中英文混合，覆盖四个主题；每题标注 gold_urls 和 key_points。
- **检索指标**：hit@k、MRR，用代码计算。
- **回答指标**：忠实度、要点覆盖率，由 LLM 评判，1–5 分。
- **对比对象**：朴素 RAG 基线与 Agent，结果写进 `docs/eval.md`。

## 10. 数据许可与合规
- 抓取前检查各站点的 robots.txt 和版权说明，结论记录在 `docs/data-sources.md`。
- 回答中引用原始链接；原始数据不提交、不再分发。
- 界面和每条回答都附免责声明。
