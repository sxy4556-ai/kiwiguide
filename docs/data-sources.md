# 数据来源与许可

检查日期：2026-10-02。来源清单见仓库根目录的 `sources.yaml`（共 50 个页面）。

## 汇总

| 站点 | 主题 | 页面数 | 许可 | robots.txt | 结论 |
|---|---|---|---|---|---|
| tenancy.govt.nz（Tenancy Services，MBIE） | 租房 | 15 | Crown copyright，允许个人或非商业用途转载，需注明来源 | 允许抓取，仅禁止 `/admin/`、`/Security/`、生成的 PDF 等 | 可用 |
| employment.govt.nz（Employment New Zealand，MBIE） | 打工与劳动权益 | 14 | Crown copyright，允许个人或非商业用途转载，需注明来源 | 允许抓取，禁止 `/admin`、`/search-results` 等；`Crawl-delay: 5` | 可用，抓取间隔 5 秒 |
| immigration.govt.nz（Immigration New Zealand，MBIE） | 学生签证 | 10 | CC BY 3.0 NZ，需署名 Crown 和该网站 | 允许抓取，禁止 `/admin`、`/_search/` 等 | 可用 |
| ird.govt.nz（Inland Revenue） | 税务 | 11 | CC BY 4.0，需准确转载、注明来源和版权状态，不得用于误导性语境 | 允许抓取，仅禁止 `/temp`、`/sitecore`、`/app_data` | 可用 |

四个站点均未被排除。

## 各站点说明

### Tenancy Services
- 版权页：https://www.tenancy.govt.nz/about-tenancy-services/copyright/
- 要点：个人或非商业用途可免费转载，条件是注明信息来自 Tenancy Services 网站、保留相关免责声明、不出售、不在误导性语境中使用。图片和标志不在许可范围内。

### Employment New Zealand
- 版权页：https://www.employment.govt.nz/employment-new-zealand/copyright
- 要点：条款与 Tenancy Services 相同（同属 MBIE）。
- robots.txt 对所有爬虫设置了 `Crawl-delay: 5`，抓取器按此执行。

### Immigration New Zealand
- 版权页：https://www.immigration.govt.nz/about-us/about-this-site/copyright/
- 要点：内容以 CC BY 3.0 NZ 许可，可复制、分发和改编，需署名 Crown 和 Immigration New Zealand 网站。第三方内容和图片除外。
- 站点的子 sitemap 存在重定向循环，候选页面改为从 `/study/` 等栏目页的链接中筛选。

### Inland Revenue
- 版权页：https://www.ird.govt.nz/about-this-site/conditions-of-use/copyright
- 要点：Crown copyright 内容以 CC BY 4.0 许可，需准确转载、注明来源和版权状态、不用于贬损或误导性语境。标志、设计元素和图片除外。

## 本项目的使用方式
- 抓取器 User-Agent 带项目地址：`KiwiGuideBot/0.1 (+https://github.com/sxy4556-ai/kiwiguide)`。
- 遵守 robots.txt；同一域名请求间隔至少 1 秒，站点声明了更长的 `Crawl-delay` 时以站点为准。
- 只抓取正文文字，不抓取图片和标志。
- 抓取结果只存在本地 `data/` 目录，不提交到仓库，也不再分发；仓库只保存来源清单。
- 每条回答都附原始页面链接和抓取日期，满足署名要求，并附免责声明：信息仅供参考，以官网最新内容为准。
- 本项目为非商业用途。
