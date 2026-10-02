# Day 0：项目初始化

- 日期：2026-10-02
- 状态：已完成

## 今日目标
确定项目方向和技术方案，搭好仓库骨架，写出开发计划和设计文档。

## 完成情况
- 确定方向：面向新西兰国际学生的生活问答助手，覆盖租房、打工与劳动权益、学生签证条件、税务四个主题。
- 确定技术方案：
  - Agent 编排：LangGraph
  - 检索：Qdrant 本地库做混合检索（稠密向量加 BM25）
  - 接口：FastAPI
  - 模型：通过 Ollama 调用，对话用 deepseek-v4-flash:cloud，向量用 qwen3-embedding:0.6b
- 初始化 git 仓库和 uv 项目（Python 3.12）。
- 编写开发计划 `PLAN.md`（Day 1–10 加缓冲）、设计文档 `docs/design.md`、README、CHANGELOG。

## 主要改动
- `pyproject.toml`、`.python-version`：uv 项目配置
- `.gitignore`、`.gitattributes`：忽略数据和缓存，统一使用 LF 换行
- `.env.example`：配置示例（不含任何密钥）
- `PLAN.md`、`docs/design.md`、`README.md`、`CHANGELOG.md`、`docs/devlog/`

## 关键实现说明
- **模型统一走 Ollama**：对话模型和向量模型都通过本机 Ollama 调用，项目里不需要保存任何 API 密钥，也就没有密钥泄露的风险。云模型额度不够时，可以在 `.env` 中切换到本地的 qwen3:4b。
- **数据不进仓库**：抓取的网页、向量索引都可以用脚本重新生成。仓库只保存来源清单 `sources.yaml`，这样既避免再分发第三方内容，也让仓库保持轻量。
- **分支和标签分开命名**：开发分支用 `dev/day-NN`，完成后合并到 main 并打 `day-NN` 标签。名字不同，可以避免 git 引用名冲突。

## 测试结果
今天没有业务代码，未运行测试。从 Day 1 开始，每天都运行 ruff 和 pytest。

## 问题与决策
- 显卡只有 6GB 显存，本地只能跑 4B 级别的模型，多步推理效果有限，所以对话模型选了 Ollama 云模型，本地模型作为备用。
- 移民相关的问题只提供官方的一般性信息，并转介到官方渠道或持牌顾问，原因是新西兰对移民建议有执业许可要求。

## 明日计划
Day 1：搭工程骨架，包括 FastAPI 应用和 `/health` 接口、配置与日志、ruff 和 pytest、GitHub Actions CI、环境检查脚本。
