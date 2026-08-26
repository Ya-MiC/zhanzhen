# 更新日志（CHANGELOG）

> **上游依据**：[VERSIONING.md](../../VERSIONING.md)（v0.3.0 交付清单）、[README.md](../../README.md) 功能总览、`zhanzhen/` 源码、[LIMITATIONS.md](../../LIMITATIONS.md)。
> **格式**：遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)；版本号语义见 SemVer 2.0.0。
> **读者**：全部用户。技术细节以 ARCHITECTURE.md 与源码为准，本页记录用户可见的能力与变更。
> **文档版本**：v0.2 · 更新日期：2026-08-25 · 状态：已有

本文档收录**用户可见变更**（DOC_MAP 规划口径）；面向开发者的逐提交细节请看 Git 历史。

## [Unreleased]

_Pending:_

- PaddleOCR / PaddleLite 移动端与服务端正式接入（当前为探测位 + 三级降级链路由）
- Web 端红字冲销入口
- PDF/docx 模板化导出

---

## [0.3.0] - 2026-08-25

平台化与多受众交付轮。Web 工作台 **UI 全面改版**属 breaking-level 视觉变更，
按预-1.0 惯例升次版本号。交付清单与路线见 [VERSIONING.md](../../VERSIONING.md)。

### Added

**五受众报告引擎**

- bank / gov / boss / firm / cross 五受众报告模板，jinja2 缺失时纯 Python 兜底渲染；
  注册会计师免责声明强制出现；boss 版每条风险带 rule_id 保证可追溯
- `export_report_v2` 接入管线；新增 Web 端点 `POST /v1/exports/report-v2`（audience 类型校验）
- 五受众模板、免责声明与导出往返均有测试覆盖

**OCR 三级路由**

- 新增 OcrRouter 三级降级链：文字型 PDF→文本层提取、txt→确定性 Stub、
  图片→Tesseract(chi_sim)→PaddleOCR→引擎全缺时返回明确 NEEDS_SERVER 信封（409），绝不编造数据
- `POST /v1/vouchers/{id}/ocr` 支持 `router=auto`，响应回显 engine 与 fallback_chain；
  状态机与事件流保持不变（run_ocr 支持注入 provider_instance）
- TesseractProvider 懒加载 subprocess 复用既有文本抽取管线；三级选路共 14 个用例

**加密层与数据库双后端（需 `[server]` extra）**

- 服务端加密层：PBKDF2-HMAC-SHA256（200k 轮）派生密钥 → Fernet 对称加密，
  encrypt_text / decrypt_text；cryptography 未安装时懒加载报可读安装指引而非崩溃
- Database 双后端：设 `ZZ_DATABASE_URL` 即切 PostgreSQL（psycopg2 懒加载，连接失败可读报错），
  否则零依赖 SQLite（`ZZ_DB_PATH` 可改路径）；内置 ?↔%s 占位符翻译层与 % 转义
- report_assets 报告资产（正文/风格样本）先 encrypt_text 再落库；
  13 个平台用例：加密往返/错钥失败/资产加密落库/sqlite 降级/占位符翻译/quota 不回归等

**DSH 工作流插件分支**

- dsh-plugin 分支承载审计行业 n8n 式七节点工作流引擎（TypeScript workflow-engine.ts）
  + 基础工作流模板 JSON + zz.workflow.list / zz.workflow.run 工具

**安卓直传双轨**

- 免费轨：手机采集包 `POST /v1/vouchers/capture-batch`，逐张**服务端重算 SHA-256**（不信客户端哈希）；
  工作台凭证箱新增「采集包导入」按钮，照片直接流入凭证箱
- 专业轨：大文件分片直传对象存储预签名 URL（`/v1/uploads/initiate`）；双轨口径见
  [MOBILE_WORKFLOW.md](../MOBILE_WORKFLOW.md)

**Windows 免安装 exe**

- desktop.py 启动器 + PyInstaller 单文件打包（zhanzhen.spec）：双击即启动服务并自动打开浏览器，
  自动挑空闲端口，数据保存在 exe 同级 data\ 目录；构建指南 [BUILD_WINDOWS.md](BUILD_WINDOWS.md)

**平台计费与管理台**

- 免费/专业两档订阅：额度扣减 / 升降级 / 冻结生命周期（per PRODUCT_TIERS）
- 角色层 user app 与 admin 分离：免费档本地自动管理员，专业档 API-Key 角色
  （admin/accountant/reviewer/viewer）
- 管理台端点（角色门禁）：平台统计 / 订阅管理（升降级·冻结）/ API-Key 签发
- `GET /v1/me` 当前身份：角色 / 租户 / 订阅状态 / 剩余额度（前端显隐依据）；AuthError 统一 401 信封
- [SERVER_DEPLOY.md](../../SERVER_DEPLOY.md)：境内合规托管选址、三种部署形态、联调排错工作流

### Changed

- **Web 工作台 UI 全面改版**（breaking-level 视觉变更）：登录横幅（Key→localStorage→X-API-Key）、
  按角色显隐页签（viewer 仅报告、admin 增加管理台）、顶栏常驻本月报告额度 x/3 或 ∞、
  品牌色 #0F4C81 + #C9A063
- pyproject 新增 `[server]` extra（psycopg2-binary + cryptography）
- 三角不平凭证覆核批准后可继续做账：suggest_entry 追加显式待处理差额行，不篡改提取值
  （修复长期红着的 e2e 管线测试）
- 用户/开发/合规文档批量补齐 11 篇并同步 DOC_MAP 状态

### Deprecated

- 无

### Removed

- 无

### Fixed

- report_engine 无 jinja2 环境的 boss 模板兜底渲染两连修（多行 f-string 改纯拼接、rule_id 回显）
- ensure_subscription 插入语句占位符数量不匹配（7 占位符 6 绑定值）

### Security

- 报告资产落库前 Fernet 加密；数据库连接经 `ZZ_DATABASE_URL` 注入，凭据不落代码
- 手机采集包逐张服务端重算 SHA-256，客户端哈希仅参考（延续 0.1.0 承诺）

### 配置面速览（本版引入）

| 变量 | 默认 | 说明 |
|------|------|------|
| `ZZ_DATABASE_URL` | 空=SQLite | 设置后切换 PostgreSQL 后端（psycopg2 懒加载） |
| `ZZ_DB_PATH` | `data/zhanzhen.db` | SQLite 库文件路径 |
| `ZZ_ENC_SALT` | 服务端部署时生成一次并持久化 | 加密层 PBKDF2 盐（见 zhanzhen/crypto.py 说明） |
| `ZZ_AUTH_MODE` | 不设=本地单机免费模式 | 设 `users` 进入多角色模式 |
| `ZZ_USERS` | 空 | `key:用户名:角色` 清单，分号分隔 |

逐项作用域与安全提示见 [CONFIG.md](CONFIG.md)。

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

[Unreleased]: https://github.com/Ya-MiC/zhanzhen/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/Ya-MiC/zhanzhen/releases/tag/v0.3.0
[0.1.0]: https://github.com/Ya-MiC/zhanzhen/releases/tag/v0.1.0
