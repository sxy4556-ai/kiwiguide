# Day 1：工程骨架与数据采集

- 日期：2026-10-02
- 状态：已完成

## 今日目标
搭好可运行、可测试、能跑 CI 的 FastAPI 项目骨架；从四个新西兰政府网站采集租房、打工、学生签证、税务四个主题的资料，清洗成带元数据的 Markdown。

## 完成情况
**工程骨架**
- [x] 安装依赖：fastapi、uvicorn[standard]、pydantic-settings、httpx、trafilatura、pyyaml；开发依赖 pytest、pytest-asyncio、ruff
- [x] `app/config.py`：pydantic-settings 读取 `.env`，字段与 `.env.example` 一致，`get_settings()` 带缓存
- [x] `app/logging_config.py`：统一日志格式（时间、级别、模块、消息）
- [x] `app/main.py`：`create_app()` 应用工厂；`GET /health` 返回状态、版本、Ollama 是否可达，不可达时返回 `degraded`
- [x] `scripts/check_env.py`：检查 Ollama 服务和三个模型，缺少向量模型时自动 `ollama pull`
- [x] `pyproject.toml`：ruff（line-length 100，E/F/I/UP/B）和 pytest（`pythonpath`、`asyncio_mode = "auto"`）配置
- [x] `.github/workflows/ci.yml`：push 和 pull_request 时运行 ruff 和 pytest
- [x] 测试：`/health` 两种情况、配置默认值与环境变量覆盖

**数据采集**
- [x] 查看四个站点的 robots.txt 和版权页面，结论写入 `docs/data-sources.md`，四个站点都可以使用
- [x] `sources.yaml`：50 个官方页面（租房 15、打工 14、签证 10、税务 11），每个 URL 都先用抓取器验证过页面存在、正文与主题相关
- [x] `app/ingest/fetch.py`：遵守 robots.txt、同域名间隔至少 1 秒（并服从站点的 Crawl-delay）、User-Agent 带项目地址、失败重试 2 次
- [x] `app/ingest/clean.py`：trafilatura 提取正文转 Markdown，保留标题层级，去掉导航和页脚
- [x] 输出到 `data/processed/<topic>/<slug>.json`，字段 url、title、topic、retrieved_at、content_hash、markdown
- [x] `scripts/fetch_sources.py`：中文打印成功、失败、跳过数量
- [x] 离线测试：清洗（标题层级、噪音去除）、slug、content_hash、robots 判断

**验收**
- [x] ruff 和 pytest 全部通过
- [x] `uv run uvicorn app.main:app` 后访问 `/health`，返回 `{"status":"ok","version":"0.1.0","ollama":true}`
- [x] `check_env.py` 如实报告：首次运行发现缺少 `qwen3-embedding:0.6b`，自动下载（639MB）后再次运行全部通过
- [x] 实际抓取 50 个页面，成功 50，失败 0，跳过 0，成功率 100%；`data/` 在 gitignore 中，未提交
- [x] GitHub Actions：见"测试结果"

## 主要改动
- `app/__init__.py`、`app/config.py`、`app/logging_config.py`、`app/main.py`
- `app/ingest/fetch.py`、`app/ingest/clean.py`、`app/ingest/sources.py`
- `scripts/check_env.py`、`scripts/fetch_sources.py`
- `sources.yaml`、`docs/data-sources.md`
- `tests/`：`test_health.py`、`test_config.py`、`test_check_env.py`、`test_fetch.py`、`test_clean.py`、`test_sources.py`，离线样例 `tests/fixtures/bond_page.html`
- `.github/workflows/ci.yml`、`pyproject.toml`、`uv.lock`

## 关键实现说明
- **限速取站点要求和项目下限的较大值**：employment.govt.nz 的 robots.txt 对所有爬虫声明了 `Crawl-delay: 5`。抓取器按域名记录上次请求时间，间隔取 `max(1 秒, Crawl-delay)`。robots.txt 返回 404 时按惯例视为全部允许，返回 5xx 或网络错误时无法确认规则，保守地视为全部禁止。重试只针对网络错误、5xx 和 429；404 这类确定的失败不重试，避免浪费请求。`Fetcher` 的 HTTP 客户端、`sleep` 和时钟都可以注入，测试用 `httpx.MockTransport` 验证重试次数和限速，不访问网络。
- **清洗后再规整空白**：trafilatura 的 Markdown 输出在 IRD 学生页的列表项里留下了大段缩进和空行。在提取之后加了一步规整：压缩行内空白、把只剩列表标记的行与下一行正文合并、连续空行压成一个。代价是嵌套列表的缩进丢失，但对检索没有影响，换来的是 Day 2 分块时不会被空白占满长度。
- **`/health` 不因下游故障报错**：Ollama 检查函数吞掉所有 httpx 异常并返回 False，接口在这种情况下返回 200 和 `degraded`。这样监控能区分"服务本身挂了"和"模型不可用"两种情况。

## 测试结果
- `uv run ruff check .`：通过
- `uv run pytest -q`：26 个测试全部通过，0 失败，0 跳过
- GitHub Actions：推送 `dev/day-01` 分支后触发的运行（提交 7320f35）结论为 success，见 https://github.com/sxy4556-ai/kiwiguide/actions/runs/36955059966

## 问题与决策
- **immigration.govt.nz 的子 sitemap 有重定向循环**（加不加末尾斜杠互相 301），无法从 sitemap 获取页面列表。改为从 `/study/`、`/work/worker-rights/` 等栏目页的链接中筛选候选页面。
- **替换了 4 个内容过薄的栏目页**：验证时发现最低工资、年假、雇佣协议、年终税务这几个栏目页只有导航链接（300–1100 字符），换成了对应的具体内容页（如 "Minimum wage rates and types"、"Taking annual holidays"）。IRD 的 "Students" 页面虽然较短，但直接面向学生，保留。
- **tenancy.govt.nz 和 ird.govt.nz 的页面标题**：页面标题带 "Tenancy Services - " 前缀，正文中也没有一级标题，所以在 `sources.yaml` 里为所有条目手工填写了标题，清洗时优先使用。
- **check_env 的中文输出在管道中会乱码**：Windows 下输出被重定向时 Python 默认用系统代码页编码。在终端中直接运行显示正常；需要重定向时设置 `PYTHONIOENCODING=utf-8`。没有在脚本里强制改编码，避免影响其他终端。
- 部分 tenancy 页面保留了 "View page in:" 语言切换行，属于少量噪音，暂不处理，Day 2 分块时观察影响。

## 明日计划
Day 2：分块、索引与检索基线
- 父子分块、Qdrant 本地库的 dense + BM25 混合索引、按 content_hash 增量更新
- 混合检索（RRF 融合、主题过滤、父块回取）和朴素 RAG 基线
- 基于已抓取数据编写 30 道评测题，计算基线的 hit@5 和 MRR
