# Day 7：收尾发布

- 日期：2026-10-08
- 状态：已完成

## 今日目标
补上来源更新脚本，把 README 写成别人照着就能跑起来的正式版，汇总 v1.0.0 的更新记录，按 README 从零走一遍，打 `v1.0.0` 标签。

## 完成情况
- [x] `scripts/refresh_sources.py`：复用 `fetch_sources()` 和增量索引 `build_index()`，打印抓取结果和索引变化统计
- [x] 中文 README：项目介绍、架构图（系统架构和 Agent 流程两张 mermaid 图）、快速开始、接口说明、评测结果摘要、数据来源与许可、免责声明
- [x] CHANGELOG 汇总 v1.0.0
- [x] 按 README 从零走一遍：克隆到临时目录，依次执行全部步骤（见下方"关键实现说明"）
- [x] 打 `v1.0.0` 标签

**验收**：`ruff` 和 `pytest` 全部通过；README 的步骤在全新克隆的目录中复现成功。

## 主要改动
- `scripts/refresh_sources.py`：新增
- `app/ingest/refresh.py`：新增 `describe_refresh()`，把抓取摘要和索引统计合成一行中文
- `app/api/service.py`：`/ingest/refresh` 的结果摘要改为调用 `describe_refresh()`，与脚本输出一致
- `README.md`：重写为正式版
- `CHANGELOG.md`：新增 v1.0.0 汇总和 Day 7 条目
- `pyproject.toml`、`app/__init__.py`、`uv.lock`：版本号 0.1.0 → 1.0.0
- 测试：`tests/test_refresh.py` 新增 1 个

## 关键实现说明
- **更新脚本只做组合，不加新逻辑**：抓取（`fetch_sources`）、增量索引（`build_index`，按 content_hash 跳过未变化的页面）在 Day 1、Day 2 已经实现并有测试，脚本只是先抓取再建索引。`/ingest/refresh` 里原来有一段拼摘要的代码，提取成 `describe_refresh()` 后两处共用，命令行和接口给出的统计口径一致，测试也只需要覆盖一处。抓取失败的页面保留上一次的 JSON，不会被当成"已删除"从索引里清掉，避免官网临时故障导致资料丢失。
- **真实运行结果**：在开发目录运行一次 `refresh_sources.py`，50 个来源全部抓取成功，索引更新 1 个页面（tenancy.govt.nz 的押金页面内容有变化）、未变化 49 个，总耗时 149.8 秒，大部分时间花在遵守抓取间隔上。
- **从零复现**：把 `dev/day-07` 分支克隆到临时目录（不带 `data/` 和 `.env`），按 README 依次执行：
  1. `uv sync`：自动准备 Python 3.12 并安装依赖
  2. `uv run ruff check .` 通过；`uv run pytest -q` 96 个通过
  3. `check_env.py`：Ollama、对话模型、备用模型、向量模型均正常
  4. `fetch_sources.py`：50 个来源成功 50，成功率 100%
  5. `build_index.py`：新增 50 个页面，父块 428、子块 969，耗时 80.9 秒
  6. 在 8001 端口启动 `uvicorn app.main:app`：`/health` 返回 ok，`/docs` 返回 200，`/sources` 返回 50 条
  7. `POST /chat` 提问"学生签证在学期中每周最多可以打工多少小时？"，7.5 秒返回答案"每周 25 小时"，附 5 条引用
  8. 提问"我住的地方要涨租了，我有什么权利？"，返回反问"请问您是正式租客、合租房客还是寄宿者？"；用 `/chat/{thread_id}/resume` 回答"正式租客，固定期限租约"后得到附 4 条引用的回答

  未验证的步骤：安装 uv、安装 Ollama 和 `ollama signin` 在本机早已完成，没有在全新系统上重做。

## 测试结果
- `uv run ruff check .`：通过
- `uv run pytest -q`：96 个测试全部通过，0 失败，0 跳过（Day 6 结束时 95 个，今天新增 1 个）

## 问题与决策
- **版本号**：`/health` 返回的版本号来自 `app/__init__.py`，原来是 0.1.0，与 `v1.0.0` 标签不一致，改为 1.0.0，并同步 `pyproject.toml` 和 `uv.lock`。计划中没有单列这一项，属于打标签的配套改动。
- **README 中的并发提醒**：Qdrant 本地库同一时间只允许一个进程打开，服务运行时运行建索引、更新、提问或评测脚本都会失败。README 单独写了"注意"一节，并说明服务运行时改用 `/ingest/refresh`。
- **CHANGELOG 结构**：原来的"未发布"标题改为"v1.0.0"，Day 0–7 的条目都归入这个版本，并在最前面加了汇总。

## 明日计划
Day 8：缓冲（可选）。之前各天的验收标准都已达到，可从 MCP 服务、重排序模型、Dockerfile 中选做，最后写项目总结日志。
