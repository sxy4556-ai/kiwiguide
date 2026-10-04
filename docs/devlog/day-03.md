# Day 3：Agent v1

- 日期：2026-10-04
- 用时：约 62 分钟（开始 12:29，结束 13:31；其中约 29 分钟在等本地模型跑演示问题）
- 状态：已完成

## 今日目标
用 LangGraph 搭出带自我纠错的 Agentic RAG 主流程（summarize → rewrite → retrieve → grade → generate）和基于 SQLite 的多轮会话记忆。

## 完成情况
- [x] 安装依赖：langgraph 1.2.12、langgraph-checkpoint-sqlite 3.1.1
- [x] `app/agent/state.py`：messages（add_messages 合并）、summary、question、search_queries、topic、retrieved、grade、retries、answer、citations；`new_turn()` 每轮重置中间结果
- [x] `app/agent/prompts.py`：全部提示词集中存放，中文说明；rewrite 和 grade 要求只输出 JSON
- [x] `app/agent/nodes.py`
  1. summarize：已完成的问答超过 6 轮时，把较早的消息压缩成摘要，保留最近两轮和当前问题
  2. rewrite：改写成 1–3 条英文检索词并判断主题；重试时带上上次的检索词和不足原因
  3. retrieve：每条检索词调用 Day 2 的混合检索，按名次交替合并、按父块去重，最多 6 个
  4. grade：LLM 输出 JSON 判断是否足够；不足且 retries < 2 时回到 rewrite
  5. generate：中文回答、术语附英文、[n] 引用，结尾附参考来源和免责声明
- [x] 结构化输出：pydantic 校验，失败时把错误告诉模型重试一次，仍失败走降级
- [x] `app/agent/graph.py`：StateGraph + SQLite checkpointer（`data/checkpoints.sqlite`），按 thread_id 保存会话
- [x] `tests/fakes.py`：新增可编排结果的 `FakeSearcher`（假 LLM 沿用 Day 2 的按顺序回复的 `FakeChatModel`）
- [x] 测试：正常路径引用对应、资料不足触发重试、重试上限 2 次、多轮上下文（含重启后恢复）

**验收**
- [x] 假模型测试全部通过
- [x] 用真实模型跑了 3 个问题（其中一个带追问），样例见下文

## 主要改动
- 新增：`app/agent/`（`state.py`、`prompts.py`、`nodes.py`、`graph.py`）
- 新增脚本：`scripts/ask.py`，命令行提问，`--thread` 指定会话、`--verbose` 打印检索词和评估结果
- 新增测试：`tests/test_agent.py`（10 个），`tests/fakes.py` 新增 `FakeSearcher`
- 依赖：`pyproject.toml`、`uv.lock`

## 关键实现说明
- **引用编号由代码重排**：generate 让模型按资料编号写 [n]，然后 `renumber_citations()` 按首次出现顺序把引用改成 1、2、3…，只把实际引用过的资料放进来源列表，越界编号（模型编出来的 [9]）直接删掉，也兼容 `[1, 3]` 这种写法。这样正文编号和来源列表一定一一对应，不依赖模型自觉。模型完全没标引用时，把全部资料列为来源。generate 没有要求输出 JSON：长篇中文放进 JSON 字符串容易出转义错误，小模型尤其明显，引用信息用正则就能可靠取出。
- **重试计数放在 grade 节点里**：grade 判断不足且 retries < 2 时，同时写入 `retry=True` 和 retries+1，条件边只看 `grade.retry`。路由函数因此是纯读取，"最多重试 2 次"的判断集中在一处。重试时 rewrite 会拿到上次的检索词和不足原因，避免原样重复检索。检索结果为空时 grade 不调用模型，直接判定不足；最终仍为空时 generate 也不调用模型，直接说明查不到。
- **降级策略**：rewrite 两次解析失败时用原问题检索、不按主题过滤，相当于退回朴素 RAG；grade 两次解析失败时视为足够，直接用现有资料作答，不再消耗重试；summarize 失败时本轮不压缩。主题不在四个之内时置为 null，不参与过滤，避免错误主题把正确页面全部滤掉。检索结果在状态里存成 dict 而不是 dataclass，因为状态要经 checkpointer 序列化保存。

## 测试结果
- `uv run ruff check .`：通过
- `uv run pytest -q`：62 个测试全部通过，0 失败，0 跳过（Day 2 的 52 个 + 今天新增 10 个）

**真实模型问答样例**（对话模型 qwen3:4b，原因见"问题与决策"）

| # | 问题 | 检索词 / 主题 | 回答摘要 | 引用 | 耗时 |
|---|---|---|---|---|---|
| 1 | 签证快到期了，新签证申请还没批下来，我还能合法留在新西兰吗？ | `student visa expiry date approaching`、`legal stay in new zealand with pending new visa application` / visa | 可以，移民局通常会发放临时签证（Interim Visa），等待期间可合法居留 | Check or change your student visa conditions | 545 秒 |
| 2a | 房东最多可以收多少押金？ | `maximum bond amount for landlords` / tenancy | 最多 4 周租金（bond） | Information for new tenants | 275 秒 |
| 2b | （同一会话追问）那涨租呢？多久能涨一次？ | `rent increase`、`rent increase frequency` / tenancy | 最多每 12 个月涨一次 | Rent increases and reductions | 429 秒 |
| 3 | Can my employer take money out of my wages without asking me? | `wage deductions without employee consent` / employment | 不能；只有法律要求、员工书面同意（written consent）或多付工资（overpayment）等例外情况才可扣款 | Deductions and premiums | 472 秒 |

- 三个问题都没有触发重试，引用编号均为 [1] 且与来源对应。
- 追问"那涨租呢？"被正确改写成 `rent increase`，说明多轮上下文起作用。
- v05（第 1 题）基线中标准页面 Interim Visa 排在第 10 位；这次回答提到了 Interim Visa，但引用的是学生签证条件页，不是标准页面。改写后的检索词仍没有出现 "interim"，能否改善要等 Day 6 跑全量评测再看。

## 问题与决策
- **主模型已下线**：`.env` 默认的 `LLM_MODEL=deepseek-v4-flash:cloud` 调用返回"已于 2026-09-25 下线"，本机另一个云模型 `glm-5.1:cloud` 也已下线。代码中的备用模型切换生效了（第一次试跑时自动改用了 qwen3:4b），但每次调用都会先失败一次。演示时直接设 `LLM_MODEL=qwen3:4b` 运行。是否换用其他云模型需要仓库所有者决定，今天没有修改默认配置。
- **本地模型很慢**：qwen3:4b 每题 4.5–9 分钟，一轮最少调用 2 次模型（rewrite、grade）再加 generate。qwen3 默认开启思考模式，输出很长，这应该是主要原因。Day 5 做接口和网页前需要解决：换可用的云模型，或者给本地模型关闭思考模式。
- **generate 不输出 JSON**：PLAN 写的是"提示词要求模型输出 JSON"，实际只对 rewrite、grade 要求 JSON；generate 输出普通文本，由代码解析引用，原因见"关键实现说明"。summarize 也输出纯文本，因为它只有一个字段。
- **新增 `scripts/ask.py`**：PLAN 中没有列出，但用真实模型跑验收问题需要一个入口，Day 5 的接口完成前也方便手动测试。
- **多条检索词的合并方式**：用按名次交替合并，没有再做一次 RRF。每条检索词的结果已经是 RRF 融合过的父块排名，交替合并能保证每个方面都至少有一个父块进入上下文，这正是拆成多条检索词的目的。

## 明日计划
Day 4：反问、并行与转介
- rewrite 后加 clarify 节点，信息不足时用 `interrupt()` 反问，回答后从断点继续
- 复合问题拆成最多 3 个子问题，用 `Send` 并行检索
- 无关问题拒答，移民和法律个案问题附转介说明
- 先确认可用的对话模型，否则演示会非常慢
