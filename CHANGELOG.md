# 更新记录

## 未发布

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
