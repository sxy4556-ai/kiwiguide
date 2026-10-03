# Day 2：分块、索引与检索基线

- 日期：2026-10-03
- 用时：约 62 分钟（开始 13:03，结束 14:05）
- 状态：已完成

## 今日目标
把 Day 1 清洗好的 50 个页面切成父子块，建立 dense + BM25 的混合索引；实现混合检索和朴素 RAG 基线，编写 30 道评测题并算出基线的检索指标。

## 完成情况
**分块与索引**
- [x] 安装依赖：qdrant-client、fastembed、langchain-ollama
- [x] 向量模型：`ollama list` 确认 `qwen3-embedding:0.6b` 已安装，无需改用 bge-m3；运行时探测维度为 1024
- [x] `app/ingest/chunk.py`：父块按 #/##/### 切分，超过 2000 字符按段落再切，少于 200 字符与相邻块合并；子块约 500 字符、重叠 80 字符，优先在句子边界断开；每个块带 parent_id、url、title、topic、heading_path、retrieved_at
- [x] `app/retrieval/embeddings.py`：OllamaEmbeddings 稠密向量 + fastembed `Qdrant/bm25` 稀疏向量，维度运行时探测
- [x] `app/retrieval/store.py`：Qdrant 本地模式（`data/qdrant`），集合含命名的 dense 和 sparse 向量；父块存 `data/parents.sqlite`
- [x] `app/ingest/index.py` 和 `scripts/build_index.py`：按 content_hash 增量建索引，删除已不存在页面的旧块，中文打印统计

**检索与基线**
- [x] `app/retrieval/search.py`：dense、sparse 各取 top 20，RRF 融合，可按 topic 过滤，按 parent_id 去重后回取父块
- [x] `app/llm.py`：ChatOllama 读取 `LLM_MODEL`，调用失败时切换到 `FALLBACK_LLM_MODEL`
- [x] `app/rag/naive.py`：原问题直接检索，资料编号后拼进提示词，生成带 [n] 引用的中文回答，末尾附参考来源和免责声明
- [x] `eval/questions.yaml`：30 道题（中文 20、英文 10；租房 8、打工 8、签证 8、税务 6；其中复合题 3 道、信息不足题 2 道），文件开头注明"标准答案待人工复核"
- [x] `app/eval/metrics.py`：hit@k、MRR
- [x] `scripts/run_eval.py --mode naive --retrieval-only`：结果保存到 `eval/results/naive-retrieval.json` 并提交

**测试**
- [x] 分块：按标题切分与标题路径、四级标题不切分、长块按段落切、短块合并、子块重叠与句子边界、元数据完整、id 稳定
- [x] 父块按顺序回取；增量逻辑：hash 不变时跳过、变化时替换、删除的页面被清理、维度不一致时报错
- [x] 指标（手算样例）、RRF 排序、父块去重、主题过滤、top_k
- [x] 朴素 RAG 的引用编号与来源对应、检索为空时不调用模型

**验收**
- [x] 用真实数据建索引成功：50 个页面，父块 428 个，子块 970 个，耗时 69.4 秒（含向量化）；再次运行时 50 个页面全部判定为未变化，耗时 3.5 秒
- [x] 基线指标已写入下文
- [x] 测试全部通过

## 主要改动
- 新增：`app/ingest/chunk.py`、`app/ingest/index.py`、`app/retrieval/`（`embeddings.py`、`store.py`、`search.py`）、`app/llm.py`、`app/rag/naive.py`、`app/eval/metrics.py`
- 新增脚本：`scripts/build_index.py`、`scripts/run_eval.py`
- 新增评测：`eval/questions.yaml`、`eval/results/naive-retrieval.json`
- 新增测试：`tests/fakes.py`（假向量模型、假对话模型）、`test_chunk.py`、`test_index.py`、`test_search.py`、`test_naive.py`、`test_metrics.py`
- 配置：新增 `SPARSE_MODEL`（默认 `Qdrant/bm25`），同步更新 `.env.example` 和配置测试

## 关键实现说明
- **RRF 融合放在应用代码里做**：Qdrant 支持服务端 prefetch + RRF，但这里选择分别发两次查询（dense、sparse 各 top 20），在 `rrf_fuse()` 里按 `1/(60+rank)` 累加。这样融合逻辑是一个纯函数，可以用手算样例直接测试排序；两次查询的额外开销在本地模式下可以忽略。RRF 只看名次不看原始分数，因为余弦相似度和 BM25 分数量纲不同，不能直接相加。
- **top_k 按父块计数**：融合后先按 parent_id 去重，再取前 top_k 个父块。如果先取 top_k 个子块再去重，同一父块的多个子块会占掉名额，实际给模型的上下文可能只有两三段。代价是候选子块需要多于 top_k，这里直接用两路 prefetch 的全部候选（最多 40 个）。
- **增量索引的写入顺序**：每个页面先删旧向量、写新向量，最后在一个 SQLite 事务里替换父块并记录 content_hash。中途失败时 hash 没写进去，下次运行会重建这个页面；新页面也会先按 url 清理一次，避免上次失败留下残缺的子块。另外，向量化的文本在子块前加了"页面标题 > 标题路径"，让只含细节的子块也带上所属主题，原文 payload 不受影响。

## 测试结果
- `uv run ruff check .`：通过
- `uv run pytest -q`：52 个测试全部通过，0 失败，0 跳过（Day 1 的 26 个 + 今天新增 26 个）

**朴素基线检索指标**（`--top-k 10`，原问题直接检索、不按主题过滤；排名以父块为单位）

| 范围 | 题数 | hit@1 | hit@3 | hit@5 | MRR |
|---|---|---|---|---|---|
| 全部 | 30 | 0.833 | 0.967 | 0.967 | 0.898 |
| 中文 | 20 | 0.900 | 0.950 | 0.950 | 0.930 |
| 英文 | 10 | 0.700 | 1.000 | 1.000 | 0.833 |

## 问题与决策
- **中文问题的表现好于预期**：BM25 对中文问题基本不起作用（页面是英文），但 qwen3-embedding 是多语言模型，稠密检索能直接匹配中英文，所以中文 hit@5 仍有 0.95。唯一未进前 5 的是 v05"签证快到期了……还能合法留在新西兰吗？"，标准页面 Interim Visa 排在第 10 位：口语化的中文提问里没有"interim"这类关键词。Day 3 的英文检索词改写正是针对这种情况。
- **英文问题 hit@1 偏低（0.70）**：e05 先命中"员工权利总览"页，x05 先命中税码页面，v07"How many hours am I allowed to work?"先命中劳动权益页。这几题的正确页面都在第 2–3 名，按主题过滤或改写后有望提升，留到 Day 6 对比。
- **评测题去掉了 4 道**：初稿写了 34 题，删掉了与其他题重复的（假期全职打工）和要点需要推断、页面上没有明说的（留学生能否加入 KiwiSaver），以及预付租金、工资单两道，保持中英文 2:1。
- **朴素 RAG 实测一次**："房东最多可以收多少押金？"回答正确（最多 4 周租金，引用 [3] 新租客须知页），但这次调用耗时 81 秒，偏慢，Day 3 接入 Agent 时观察是否需要调整超时。
- **稀疏模型名放进配置**：项目约定不在代码里写死模型名，所以新增了 `SPARSE_MODEL` 配置项。fastembed 首次使用时会从网络下载 BM25 模型文件（很小），测试中用假模型，不触发下载。
- **qdrant-client 本地模式在进程退出时的告警**：临时脚本没有关闭客户端时，Windows 上退出会打印一条 portalocker 的 `ModuleNotFoundError` 告警，不影响结果。正式脚本都在 `finally` 中关闭了存储。

## 明日计划
Day 3：Agent v1
- LangGraph 状态图：summarize、rewrite（英文检索词 + 主题判断）、retrieve、grade（不足时最多重试 2 次）、generate
- 结构化 JSON 输出与降级逻辑、SQLite checkpointer 多轮会话
- 用真实模型跑 3 个问题，重点看 v05 这类口语化问题改写后能否命中
