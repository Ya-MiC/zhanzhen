# 更新日志（CHANGELOG）

> **上游依据**：[VERSIONING.md](../../VERSIONING.md)（v0.1.0 交付清单）、[README.md](../../README.md) 功能总览、`zhanzhen/` 源码、[LIMITATIONS.md](../../LIMITATIONS.md)。
> **格式**：遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)；版本号语义见 SemVer 2.0.0。
> **读者**：全部用户。技术细节以 ARCHITECTURE.md 与源码为准，本页记录用户可见的能力与变更。
> **文档版本**：v0.1 · 更新日期：2026-08-25 · 状态：已有

本文档收录**用户可见变更**（DOC_MAP 规划口径）；面向开发者的逐提交细节请看 Git 历史。

## [Unreleased]

### Added

- 文档批次：[INSTALL](INSTALL.md) / [CONFIG](CONFIG.md) / [USER_GUIDE](USER_GUIDE.md) /
  [FAQ](FAQ.md) / 本 CHANGELOG / 手机采集[补充检查清单](../MOBILE_WORKFLOW_CHECKLIST.md) /
  [CONTRIBUTING](../dev/CONTRIBUTING.md) / [TESTING](../dev/TESTING.md) /
  [SECURITY](../dev/SECURITY.md) / [PRIVACY](../biz/PRIVACY.md) /
  [CPA_COMPLIANCE](../biz/CPA_COMPLIANCE.md)

_Pending:_

- PaddleOCR adapter 正式接入（图片/扫描件识别）
- Web 端红字冲销入口
- PDF/docx 模板化导出

---

## [0.1.0] - 2026-08-24

Phase-0 单机参考实现（首个公开版本）。对应总纲 Phase 0 技术原型完成；
规范周映射：Week 1 内容 + W5/W6 核心语义提前落地。

### Added

**核心域（零外部依赖，纯标准库）**

- Canonical JSON 序列化与 SHA-256：键名字节序递归排序，全服务唯一实现，拒绝 NaN，
  Unicode 不转义，浮点/整型严格区分（`zhanzhen/canonical.py`）
- append-only 事件日志：同聚合 sequence 严格递增、`previous_event_hash` 链式引用、
  `verify_chain()` 随时可校验篡改（`zhanzhen/events.py`）
- 12 态凭证状态机：CAPTURED → INGESTED → OCR_QUEUED → OCR_COMPLETED/OCR_FAILED →
  NEEDS_REVIEW → REVIEWED → JOURNAL_DRAFTED → JOURNAL_CONFIRMED → RULES_EVALUATED →
  EXPORTED → ARCHIVED；非法迁移抛 `InvalidTransition`，每次迁移强制写事件
  （`zhanzhen/state_machine.py`）
- VoucherJSON v1 结构校验与归一化（`zhanzhen/voucher.py`）
- 分录引擎：科目建议模板、借贷平衡硬校验、单行借贷互斥、负数拒绝、确认后不可变、
  红字冲销关联原分录、行集 `lines_hash` 锁定（`zhanzhen/journal.py`）

**OCR 协议层**

- OCRProvider 协议与三个适配器：文字型 PDF 文本层提取（pdfplumber 主 / pypdf 兜底）、
  确定性 Stub 测试桩、PaddleOCR 探测位（未安装时给出可读安装指引而非静默失败）
- 扫描件无文本层时诚实返回 `no_text_layer_needs_ocr` 并标记人工覆核，不编造数据
- 覆核质量门：置信度低于 `ZZ_REVIEW_THRESHOLD`（默认 0.80）强制进 NEEDS_REVIEW

**规则引擎**

- 三条 MVP 规则（参数外置 `rules_builtin.yaml`）：R-AMT-001 金额一致性（容差 0.01 元）、
  R-DUP-001 疑似重复凭证（同日+对手方+金额+单号全同）、R-CMP-001 完整性
  （必填字段缺失即 high，且可阻断分录确认）
- 12 条完整规则引擎（audit-os engine.py 语义完整移植）：期末突击收入、大额支出、
  方向异常、应收占比、毛利率波动、关联方对挂、供应商集中、周末大额、重复交易、
  短期冲销等；重要性水平随营收规模自动校准；单条规则坏数据隔离不拖垮整体；
  severity 分级输出（`zhanzhen/rules12.py`）
- 发现处置留痕：每条命中必须人工「属实/误报」处置并写事件

**导出**

- 可追溯 HTML 报告：全量凭证索引带 SHA-256、风险清单带证据引用、模板版本与数据截止时间
- 序时账导出 XLSX（openpyxl）/ CSV 自动降级；导出前强制借贷平衡校验
- 导出动作本身写入事件链，凭证推进 EXPORTED 态

**Web 工作台（需 `[web]` extra）**

- REST 端点子集（统一错误信封 `{code, message, details, trace_id}`，修改型请求支持
  Idempotency-Key 头）：凭证上传 / OCR 触发 / 列表详情 / 覆核修正 / 分录草稿·调整·确认 /
  规则运行（3 与 12 条）/ 发现处置 / 双格式导出 / AI 解释 / 完整性查询 / 手机采集包接收 /
  报告风格样本上传与列表 / 示例账套载入
- Vue3 单页工作台五个页签：凭证箱（上传/示例账套/收采集包/逐张 OCR）、覆核（六字段对照
  原值修正）、分录（实时借贷差额提示）、风险（命中表+AI 解释面板）、报告（双格式下载）
- 页头常驻事件链完整性指示器

**AI 助手（可选，默认关闭）**

- OpenAI 兼容端点接入（NVIDIA integrate / OpenRouter / 本地 vLLM 均可），三个 `ZZ_AI_*`
  变量齐备才启用，缺一绝不联网
- 能力边界：解释风险命中、给科目候选；只喂已确认结构化字段；输出 schema 校验不过即丢弃
  转人工；每次调用留痕 prompt 版本/模型/响应哈希/校验结果

**移动采集对接**

- `/v1/vouchers/capture-batch` 接收手机端采集包，逐张 base64 解码后**服务端重算 SHA-256**
  （不信客户端哈希），来源标记 android_camera

**CLI 与开发体验**

- 三个子命令：`zhanzhen demo <dir>` 一键演示全管线（内置 6 张示例账套，含重复对与三角不平
  坏凭证的质量门演示）、`zhanzhen serve [--host --port]` 启动工作台、
  `zhanzhen verify` 校验快照事件链（退出码 0/1/2 区分完整/缺快照/损坏）
- extras 分组：web / excel / pdf / ocr / report / all / dev
- CI：Python 3.10 & 3.12 双版本矩阵；pytest 全量 + **核心测试零第三方依赖自检**
  （unittest discover 裸跑）
- 测试 43 个：canonical 6、capture 2、events 4、journal 7、pipeline 4、rules 5、
  rules12 10、state_machine 5——清单及逐项说明见 [TESTING.md](../dev/TESTING.md)
- DSH 插件接入层 `dsh-plugin/`：zz.vouchers / zz.ocr / zz.review / zz.journal /
  zz.rules / zz.report / zz.integrity 七命令

### Changed

- 无（首个版本）

### Deprecated

- 无

### Removed

- 无

### Fixed

- 无

### Security

安全基线（同版承诺，详见 [SECURITY.md](../dev/SECURITY.md)）：

- 原始文件入库即锁：服务端重算 SHA-256，客户端哈希仅参考
- 事件哈希链 append-only + 可校验；确认分录不可 UPDATE，纠错只能红字冲销
- 错误统一信封，不回传堆栈；日志不落凭证正文
- AI 助手默认关闭；开启也只读已确认数据，无任何写通道

### 配置面速览（本版引入）

| 变量 | 默认 | 说明 |
|------|------|------|
| `ZZ_DATA_DIR` | `.zzdata` | 数据根目录（示例配置/Docker 分别为 ./data 与 /data） |
| `ZZ_TENANT_ID` | `default` | 租户标识，决定快照路径 |
| `ZZ_REVIEW_THRESHOLD` | `0.80` | 覆核质量门阈值 |
| `ZZ_PORT` | `8710` | Web 端口（serve --port 可覆盖） |
| `ZZ_AI_BASE_URL` / `ZZ_AI_API_KEY` / `ZZ_AI_MODEL` | 空=关闭 | AI 助手三件套，缺一不启用 |

逐项作用域与安全提示见 [CONFIG.md](CONFIG.md)。

### 已知限制（诚实清单摘要）

完整内容以 [LIMITATIONS.md](../../LIMITATIONS.md) 为权威源，用户最常撞到的五条：
扫描件/图片 OCR 未就绪、单租户无登录、并发写未加锁、发票不做联网验真、XLSX 缺依赖时
降级 CSV。

[Unreleased]: https://github.com/Ya-MiC/zhanzhen/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/Ya-MiC/zhanzhen/releases/tag/v0.1.0
