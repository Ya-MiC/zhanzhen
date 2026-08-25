# 🐙 湛箴 — 凭证到报告的完整审计作业程序

> **湛箴**，吉祥物符号 🐙（八爪抓证据，一脑管风险）；OZ 仅为内部代号。
> 命名口径与图标设计见 [docs/BRAND_OCTOPUS.md](docs/BRAND_OCTOPUS.md)
> **版本**：v0.1.0 · Phase-0 完成 · 发布路线见 [VERSIONING.md](VERSIONING.md)
> 上游依据：[Ya-MiC/action-tree](https://github.com/Ya-MiC/action-tree) 总纲 §26 MVP 与《ENGINEERING_SPEC》工程规范。
> 定位：上传 PDF/图片凭证 → 图文识别 → 凭证覆核 → 序时账分录 → 规则检查 → **可追溯审计报告**。
> 铁律：**AI 可以推理，但不能偷改证据** —— 所有证据入库即锁 SHA-256，所有状态迁移追加哈希链事件。

## 它是什么

湛箴是一个**纯 Python、pip 可装、开箱即跑**的审计作业程序：

```
上传凭证(PDF/图片/CSV) → OCR/文本层提取 → VoucherJSON 标准化 → 人工覆核
     → 分录草稿(借贷平衡) → 确认 → 三条 MVP 规则检查 → 序时账/附件索引/异常清单 → HTML 报告
```

每一份产出都能反向追溯：`报告结论 → 风险编号 → 触发凭证 → 原始文件 SHA-256`。
内置 AI 助手（可选，默认关闭）：解释风险、建议科目——输出必须过 schema 校验，且永远不能直接改账。

## 快速开始

### 方式一：pip 直接装（Windows/Linux/macOS 通用）

```bash
pip install git+https://github.com/Ya-MiC/zhanzhen.git

# 一键演示：生成示例账套并跑完整管线，输出报告到指定目录
zhanzhen demo /tmp/zz_demo          # Linux/macOS；Windows 用 %TEMP%\zz_demo

# 启动 Web 工作台（浏览器打开 http://localhost:8710；换端口见 .env.example 的 ZZ_PORT）
zhanzhen serve
```

### 方式二：源码开发

```bash
git clone https://github.com/Ya-MiC/zhanzhen.git
cd zhanzhen
pip install -e ".[dev]"
pytest                # 测试全绿（核心测试零外部依赖）
zhanzhen demo out/    # 跑通后打开 out/report.html
```

### 方式三：Docker

```bash
cp .env.example .env
docker compose up --build
# 打开 http://localhost:8710
```

## 双端架构（Android + Windows）

| 端 | 仓库 | 职责（ENGINEERING_SPEC §6） |
|---|---|---|
| 📱 Android 采集端 | [audit-os-mobile](https://github.com/Ya-MiC/audit-os-mobile) | **拍照→本地队列→导出采集包**，不做重计算 |
| 💻 Windows 工作台 | 本仓库 | 批量导入采集包/拖放 PDF → OCR → 覆核 → 序时账 → 规则 → 报告 |

工作流：手机拍凭证 → 导出 `zhanzhen-capture-*.json` → 工作台
`POST /v1/vouchers/capture-batch` 一键收包 → 后续全流程。

## 报告写作支持

- **按甲方分型**：银行/政府/企业老板/事务所/跨境五类版式差异见 [docs/REPORT_KNOWLEDGE.md](docs/REPORT_KNOWLEDGE.md)
- **风格学习**：上传你自己写过的历史报告（`POST /v1/reports/upload-style-sample`），AI 助手按你的笔法起草
- **公开范本地图**：SEC EDGAR / 巨潮年报审计报告 / PCAOB / 中注协准则 —— 免费资源清单同上文档
- **导出**：HTML（交互追溯，已上线）→ PDF/docx 模板（v0.5-beta，weasyprint/docxtpl）

## 功能总览

| 模块 | 能力 | 上游规范 |
|---|---|---|
| `zhanzhen.canonical` | Canonical JSON + SHA-256（键字节序递归排序，全服务唯一实现） | specs/events-v1.md |
| `zhanzhen.events` | append-only 事件日志 + 同聚合哈希链 + 链校验 | specs/events-v1.md |
| `zhanzhen.state_machine` | 12 态凭证状态机，非法迁移抛错，每次迁移强制写事件 | specs/voucher-state-machine-v1.md |
| `zhanzhen.voucher` | VoucherJSON v1 结构校验 + 归一化 | specs/voucher-json-v1.schema.json |
| `zhanzhen.ocr` | OCRProvider 协议：PDF 文本层适配器 / 确定性 Stub / PaddleOCR 可选加载 | ENGINEERING_SPEC §5 |
| `zhanzhen.rules` | 三条 MVP 规则（金额一致性/疑似重复/完整性），参数来自 rules_builtin.yaml | ENGINEERING_SPEC §8.1 |
| `zhanzhen.rules12` | **12 条完整规则引擎**（期末突击收入/大额/方向异常/应收占比/毛利率波动/关联方对挂/供应商集中/周末大额/重复交易/短期冲销），重要性水平自动校准，语义完整移植自 [audit-os](https://github.com/Ya-MiC/audit-os) engine.py | audit-os 12 规则 |
| `zhanzhen.journal` | 分录草稿生成、借贷平衡硬校验、确认后不可变（只能 reversal） | ENGINEERING_SPEC §3.4 |
| `zhanzhen.report` | HTML 可追溯报告（凭证索引带 SHA-256、风险清单带证据引用） | 总纲 §7 |
| `zhanzhen.ai_assistant` | OpenAI 兼容端点接入（NVIDIA/OpenRouter 可配），schema 约束 + model_runs 留痕 | ENGINEERING_SPEC §8.2 |
| `web/index.html` | Vue3 单页工作台：上传/凭证箱/覆核/分录/风险/报告/AI 助手 | ENGINEERING_SPEC §6 |
| `dsh-plugin/` | DSH (DeepSeek Harness) 插件：一切皆插件架构的接入层 | deepseek-harness |

## 安全基线（诚实版）

- ✅ 服务端重算 SHA-256（不信客户端）、原始文件只读、事件链防篡改、确认分录不可 UPDATE
- ✅ 错误统一信封（code/message/details/trace_id），不回传堆栈；日志不落凭证正文
- ⚠️ MVP 为**单租户内存+快照存储**（`ZZ_DATA_DIR`），PostgreSQL/RLS/MinIO 是下一步（见 LIMITATIONS.md）
- ⚠️ AI 助手**默认关闭**；开启需显式配置 `ZZ_AI_*` 环境变量，且只读访问已确认数据

## 文档地图

- [ARCHITECTURE.md](ARCHITECTURE.md) — 架构、模块图、specs↔代码映射表
- [LIMITATIONS.md](LIMITATIONS.md) — **做不到什么、需要人类帮什么**（诚实清单）
- [ACKNOWLEDGEMENTS.md](ACKNOWLEDGEMENTS.md) — 致谢与开源协议（我们站在谁的肩膀上）
- [action-tree 总纲](https://github.com/Ya-MiC/action-tree) — 为什么做、做什么（人类亲笔）

## 许可

MIT © 2026 Ya-MiC。第三方依赖及其协议见 ACKNOWLEDGEMENTS.md。
