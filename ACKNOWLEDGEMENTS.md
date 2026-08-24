# 致谢 / ACKNOWLEDGEMENTS

湛箴站在开源社区的肩膀上。本仓库**只依赖这些项目、未复制其受版权保护的代码与模板**；若未来引入代码片段，将在此列明并保留原版权声明。

## 运行时依赖

| 项目 | 用途 | 协议 |
|---|---|---|
| [FastAPI](https://github.com/fastapi/fastapi) | REST API 层 | MIT |
| [Pydantic](https://github.com/pydantic/pydantic) | 数据校验 | MIT |
| [Uvicorn](https://github.com/encode/uvicorn) | ASGI 服务器 | BSD-3 |
| [PyYAML](https://github.com/yaml/pyyaml) | 规则 DSL 加载 | MIT |
| [pdfplumber](https://github.com/jsvine/pdfplumber) / [pypdf](https://github.com/py-pdf/pypdf) | PDF 文本层提取 | MIT / BSD-3 |
| [openpyxl](https://foss.heptapod.net/openpyxl/openpyxl) | 序时账 XLSX 导出 | MIT |
| [Vue.js](https://github.com/vuejs/core)（前端 CDN 引用） | 工作台 UI | MIT |
| [PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR)（可选 `[ocr]` extra） | 图片/扫描件图文识别 | Apache-2.0 |

## 方法论与灵感来源

| 来源 | 我们学了什么 | 边界 |
|---|---|---|
| 四大/八大审计方法论（公开准则：中国注册会计师审计准则体系） | 风险导向审计流程、证据要求 → 机器可执行规则 | 只学方法，不复制任何底稿模板/专有格式（spec §9.2） |
| [DeepSeek Harness (DSH)](https://github.com/Ya-MiC/deepseek-harness) | 「一切皆插件」架构 → `dsh-plugin/` 接入层 | 插件为本仓库原创 |
| 金蝶/用友 | 数据对接兼容思维：读它们的导出格式，做它们不做的审计层，**兼容不对抗** | 不复制其软件任何部分 |
| [action-tree](https://github.com/Ya-MiC/action-tree) | 本项目的唯一规格权威（总纲/specs/ADR） | 创始人亲笔 |

## 协议合规承诺

1. 本仓库 MIT 开源；依赖各自协议随分发要求保留声明（见 pyproject / 本文件）。
2. Vue.js 经 CDN 引用不修改不分发其源码。
3. PaddleOCR 为可选依赖，用户自行安装时适用其 Apache-2.0 及模型许可。
