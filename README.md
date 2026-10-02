# KiwiGuide：新西兰留学生生活助手

个人项目。一个基于 Agentic RAG 的问答助手，帮助在新西兰的国际学生查询以下问题：
- 租房
- 打工与劳动权益
- 学生签证条件
- 税务（IRD）

回答依据新西兰政府官网的内容，并附上出处链接。

> 状态：开发中。进度见 [PLAN.md](PLAN.md)，每日记录见 [开发日志](docs/devlog/README.md)，设计见 [docs/design.md](docs/design.md)。

## 计划功能
- 用中文提问，回答附官方出处（标题、链接、抓取日期）和免责声明
- 信息不足时主动反问，例如签证类型、是租客还是合租房客
- 复合问题自动拆成子问题，并行检索
- 父子分块，结合稠密向量和 BM25 做混合检索
- FastAPI 接口（支持流式输出）和中文网页界面
- 朴素 RAG 与 Agent 的对比评测

## 技术栈
Python 3.12 · uv · FastAPI · LangGraph · Ollama（deepseek-v4-flash:cloud、qwen3-embedding）· Qdrant · fastembed · pytest · GitHub Actions

## 免责声明
本项目提供的信息仅供参考，不构成法律、移民或税务建议。具体情况请以政府官网的最新信息为准，或咨询以下机构：
- Tenancy Services
- Employment New Zealand
- Immigration New Zealand
- IRD
- 持牌移民顾问
- 学校的国际学生办公室

## 作者
[sxy4556-ai](https://github.com/sxy4556-ai)
