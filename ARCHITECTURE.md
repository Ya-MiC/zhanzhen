# 架构 / ARCHITECTURE

> 上游：ENGINEERING_SPEC §2 目标架构、§3 领域模型、specs/ 三件套。本程序是规范的**单机可运行参考实现**；server 化（PostgreSQL+MinIO+Celery）按规范 Week2-6 演进，契约不变。

## 数据流

```text
PDF/图片/CSV 上传
      ↓  server 端 SHA-256 重算（storage.py，内容寻址 objects/<sha256>）
INGESTED ──事件: voucher.created──→
      ↓  OCR Provider（ocr.py，可替换 adapter）
OCR_COMPLETED / OCR_FAILED
      ↓  VoucherJSON v1 归一化（voucher.py）+ 质量门（低置信/缺字段→NEEDS_REVIEW）
NEEDS_REVIEW → 人工覆核（改字段记 voucher.field_corrected）→ REVIEWED
      ↓  分录草稿（journal.py，借贷平衡硬校验，lines_hash 锁定）
JOURNAL_DRAFTED → 确认（JOURNAL_CONFIRMED，此后不可变）
      ↓  规则引擎（rules.py × rules_builtin.yaml）
RULES_EVALUATED ──findings（规则ID+严重度+证据引用+处置）──→
      ↓  导出（report.py / journal Excel）
EXPORTED → ARCHIVED
```

任何状态迁移都同步追加哈希链事件（events.py）。导出物必带 template_version/generated_at/export_job_id。

## 模块 ↔ specs 映射

| specs 权威定义 | 本仓库实现 | 状态 |
|---|---|---|
| voucher-json-v1.schema.json | `zhanzhen/voucher.py::validate_voucher_json` | ✅ 校验器 + 归一化 |
| voucher-state-machine-v1.md | `zhanzhen/state_machine.py`（12态全迁移表） | ✅ 含守卫与强制事件 |
| events-v1.md（信封+canonical JSON+hash链） | `zhanzhen/canonical.py` + `zhanzhen/events.py` | ✅ 链校验测试固定 |
| ENGINEERING_SPEC §8.1 三条规则 | `zhanzhen/rules.py` + `rules_builtin.yaml` 参数 | ✅ 参数外置 |
| ENGINEERING_SPEC §9.1 三份导出 | `zhanzhen/report.py`(HTML) + `journal.py::journal_rows`(序时账行集) | ✅ HTML/CSV；XLSX 需 openpyxl |
| ENGINEERING_SPEC §8.2 LLM 守则 | `zhanzhen/ai_assistant.py` | ✅ schema 约束+留痕，默认关 |
| ENGINEERING_SPEC §7.1 API 端点 | `zhanzhen/webapp.py`（子集） | 🟡 单租户开发模式 |

## 设计取舍（为什么这样写）

1. **核心域零依赖**：canonical/events/状态机/规则/分录只用 Python 标准库 → 任何环境 `python -m unittest` 即验，也方便被未来 server 包直接 import。
2. **存储双轨**：`storage.py` 内容寻址对象存储（本地目录）；`store.py` 租户隔离仓储 + JSON 快照持久化。换 PostgreSQL/MinIO 只动这两处，域逻辑不动。
3. **OCR 是协议不是实现**：`OCRProvider` Protocol；文本层提取是默认（真实可用），Stub 用于测试与 demo，PaddleOCR 检测到才启用——专有格式永不渗入 domain。
4. **LLM 只在叶子上**：助手只能读已确认结构化数据、输出必须过 schema；没有 evidence ref 就闭嘴。这是总纲「确定性外壳+概率内核」的直接落地。

## 目录

```text
zhanzhen/           # 核心包
web/index.html      # Vue3 单页工作台（CDN 引入，无构建步骤）
rules_builtin.yaml  # 内置规则参数（DSL 参数层）
dsh-plugin/         # DSH 插件（TS）
tests/              # 纯标准库可跑的单测 + 端到端
```
