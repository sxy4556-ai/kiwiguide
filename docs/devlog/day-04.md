# Day 4：反问、并行与转介

- 日期：2026-10-05
- 状态：已完成

## 今日目标
让 Agent 会反问、会把复合问题拆开并行检索，并守住回答范围：无关问题拒答，个案法律或移民问题只给一般性信息并转介。

## 完成情况
- [x] 反问：rewrite 之后新增 clarify 节点；缺少关键信息时用 `interrupt()` 暂停并返回中文反问，用户回答后从断点继续（补充信息拼进问题，再改写一次）
- [x] 并行：复合问题拆成最多 3 个子问题，每个子问题带自己的检索词和主题，用 `Send` 并行检索；新增 merge 节点按子问题序号交替合并
- [x] 范围与转介
  - 越界问题不检索、不再调用模型，固定文字礼貌拒答
  - 个案问题在回答后按主题附转介说明：签证 → 移民局（Immigration New Zealand）、持牌移民顾问或律师；租房 → Tenancy Services 或 Community Law；打工 → Employment New Zealand 或 Community Law；税务 → IRD 或注册税务代理
- [x] 测试：反问暂停与恢复、复合问题每个子问题都被检索、子问题上限、无关问题拒答、移民个案附转介、一般问题不附转介、跨线程检索

**验收**
- [x] 测试全部通过（73 个）
- [x] 用真实模型（gpt-oss:120b-cloud）演示了反问和拆分，另外演示了拒答和转介，样例见下文

## 主要改动
- `app/agent/state.py`：新增 sub_questions、scope、needs_referral、clarification_question、clarified、sub_results（`operator.add` 合并，用 `Overwrite([])` 清空）；去掉单一的 topic
- `app/agent/prompts.py`：rewrite 提示词改为输出子问题、范围、是否个案、反问；新增拒答文字、转介模板和各主题的机构
- `app/agent/nodes.py`：新增 clarify、merge 节点和 `referral_note()`；retrieve 改为处理单个子问题；generate 处理拒答、子问题提示和转介
- `app/agent/graph.py`：clarify 用 `Command` 路由；新增 `resume()` 和 `pending_clarification()`
- `app/retrieval/search.py`、`app/retrieval/store.py`：检索可在多个线程中同时调用
- `scripts/ask.py`：反问时打印反问并退出，`--resume` 在同一会话中回答
- `docs/design.md`：更新流程图和状态字段
- 测试：`tests/test_agent.py` 新增 6 个，`tests/test_search.py` 新增 1 个

## 关键实现说明
- **判断合并进 rewrite 的同一次调用**：PLAN 写的是在 rewrite 之后加一个 clarify 判断节点。实际做法是让 rewrite 一次输出子问题、范围、是否个案和反问，clarify 节点只读这些字段决定去向，不调用模型。这样每轮的模型调用次数和 Day 3 相同（rewrite、grade、generate），旧测试的调用顺序也不用改。取舍是 rewrite 的提示词变长、对小模型要求更高；解析失败时的降级逻辑不变（原问题检索、不反问、不拒答）。
- **反问用 `interrupt()` + `Command`**：clarify 节点调用 `interrupt(反问)` 后整张图暂停，状态存进 checkpointer；`resume()` 用 `Command(resume=回答)` 继续时节点从头重跑，`interrupt()` 这次直接返回用户的回答。节点把"原问题 + 补充信息"写回 question，并把反问和回答都记入 messages，然后用 `Command(goto="rewrite")` 重新改写。每轮最多反问一次（clarified 标记），grade 触发重试时也不反问，避免用户被反复追问。越界判断同样只在第一次改写后生效。
- **并行检索与合并**：clarify 返回 `Command(goto=[Send("retrieve", 子问题), ...])`，每个子问题各用自己的主题过滤，因为复合问题常常跨主题（例如"能打多少小时工、工资要交什么税"分别属于 visa 和 tax），共用一个主题会把一半资料滤掉。各 retrieve 往 sub_results 追加结果，merge 按子问题序号（而不是完成先后）交替合并、按父块去重，保证结果可复现、每个子问题至少有一个父块进入上下文。并行带来一个实际问题：LangGraph 在线程池里执行这些任务，SQLite 连接默认不允许跨线程使用。解决方式是父块库以 `check_same_thread=False` 打开，HybridSearcher 用一把锁串行访问 Qdrant 本地库和 SQLite，耗时的向量化（调用 Ollama）在锁外，仍然并行。

## 测试结果
- `uv run ruff check .`：通过
- `uv run pytest -q`：73 个测试全部通过，0 失败，0 跳过（Day 3 结束时 66 个，今天新增 7 个）

**真实模型演示**（对话模型 gpt-oss:120b-cloud）

| # | 场景 | 输入 | 结果 | 耗时 |
|---|---|---|---|---|
| 1a | 反问 | 我住的地方要涨租了，我有什么权利？ | 暂停并反问："请问您是正式租客、合租房客还是寄宿（boarder）？"，未检索 | 1.6 秒 |
| 1b | 恢复 | （`--resume`）我是寄宿的（boarder），住在寄宿屋里 | 子问题改写为 `boarder rent increase rights`；回答寄宿屋涨租需提前 28 天书面通知（正式租约是 60 天）、可向租赁仲裁庭（Tenancy Tribunal）申请等 | 6.4 秒 |
| 2 | 拆分 | 我是学生签证，学期中每周能打多少小时工？打工赚的钱要用什么税码？ | 拆成 2 个子问题，分别按 visa、tax 过滤检索；回答第 1 问每周 25 小时，第 2 问说明资料没有针对学生兼职的税码说明；引用 3 个页面，覆盖两个主题 | 12.1 秒 |
| 3 | 拒答 | 帮我写一个 Python 快速排序 | scope=off_topic，固定文字拒答，未检索 | 0.9 秒 |
| 4 | 转介 | 我是学生签证，上学期打工超过了允许的小时数，我会被遣返吗？该怎么办？ | 先反问"学期中还是假期"，回答"学期中"后作答；needs_referral=true，只介绍官方一般性规定，结尾附转介说明（移民局、持牌移民顾问或律师） | 2.7 秒 + 11.7 秒 |

## 问题与决策
- **真实运行发现的两个问题（已修复）**
  - 复合问题第一次运行时，并行检索报 SQLite 跨线程错误；假检索器的测试覆盖不到。修复见"关键实现说明"，并新增跨线程检索测试。
  - 越界问题第一次运行时，模型输出空的子问题列表，校验要求至少一个子问题，解析三次失败后降级成检索并硬答。改为越界时允许空列表、范围内仍至少一个，测试改用空列表的输出。
- **反问的触发条件**：最初提示词写"能先给出一般性回答的问题不要反问"，模型对"涨租有什么权利"直接作答，没有反问，但寄宿和正式租约的通知期不同（28 天和 60 天）。改为明确列出两类必须反问的关键信息，其他情况不反问。演示 4 中模型对"上学期"仍追问学期还是假期，属于偏保守的反问，暂不处理。
- **同一页面的多个父块在来源列表中重复出现**：例如演示 1b 的 5 个来源都是同一页面的不同段落。这是 Day 3 起就有的行为，编号和来源仍一一对应，但阅读体验差。今天不在范围内，Day 5 做出处卡片时再考虑按 URL 合并。
- **税码子问题检索不足**：演示 2 中税码子问题重试 2 次仍判定不足，回答如实说明了资料没有覆盖。属于检索质量问题，留到 Day 6 评测时一起看。
- **Windows 控制台编码**：`scripts/ask.py` 在默认 GBK 控制台打印含特殊空格（U+202F）的回答时报编码错误，演示时设置 `PYTHONIOENCODING=utf-8` 运行。Day 5 起回答经网页展示，不受影响，脚本暂不修改。

## 明日计划
Day 5：API 与中文前端
- `POST /chat`、`POST /chat/{thread_id}/resume`、`POST /chat/stream`（SSE）、`GET /sources`、`POST /ingest/refresh`
- 接口直接复用今天的 `ask()`、`resume()`、`pending_clarification()`
- 原生 HTML 中文界面：主题快捷问题、出处卡片、反问提示、流式显示
