# 用户操作手册（USER_GUIDE）

> **上游依据**：`web/index.html`（Vue3 工作台）、`zhanzhen/webapp.py`（REST 端点）、`zhanzhen/service.py`（业务编排）、`zhanzhen/state_machine.py`（12 态迁移表）、[LIMITATIONS.md](../../LIMITATIONS.md)。
> **读者**：用湛箴做凭证→报告全流程作业的会计师/审计助理。按章节顺序操作即可完成一次完整作业。
> **文档版本**：v0.1 · 更新日期：2026-08-25 · 状态：已有

---

## 0. 开始之前

启动工作台（安装见 [INSTALL.md](INSTALL.md)）：

```bash
zhanzhen serve            # http://127.0.0.1:8710
```

界面是一条五个页签的流水线，与凭证状态机的可见子集一一对应：

```
┌──────────┬──────────┬──────────┬──────────┬──────────┐
│  凭证箱  │   覆核   │   分录   │   风险   │   报告   │
│ 上传/OCR │ 改字段批 | 草稿调整 │ 3+12规则 │ 导出文件 │
└──────────┴──────────┴──────────┴──────────┴──────────┘
   INGESTED → (NEEDS_REVIEW) → REVIEWED → JOURNAL_DRAFTED
   → JOURNAL_CONFIRMED → RULES_EVALUATED → EXPORTED
```

右上角常驻「事件链: ✔ 完整 / N 条事件」指示器——它变红请立即停止作业并查 FAQ。
页面顶部标语即产品铁律：**AI 可以推理，但不能偷改证据**。

没有现成 PDF？先点「载入示例账套」拿 6 张演示凭证练一遍全程（其中故意含 1 张坏凭证）。

---

## 1. 上传凭证（凭证箱）

### 操作

1. 「凭证箱」页签 → 点「上传凭证（PDF）」选择文件；或直接把 PDF 拖到上传区。
2. 列表立即出现一行新凭证，状态 `INGESTED`，末列显示证据哈希前 12 位。

### 此刻发生了什么

- 服务端**重算 SHA-256** 并把原始文件存入对象存储——不信任客户端哈希（spec §4.2）；
- 追加 `voucher.created` 事件，进入事件哈希链；
- 空文件会被拒绝（「空文件不能入库」）。

### 边界（诚实版）

- v0.1.0 文件选择器只接受 `.pdf`；**图片与扫描件**需要 PaddleOCR adapter（v0.2.0-alpha，
  见 LIMITATIONS.md #1）。扫描型 PDF 会走到 OCR 步骤后报 `no_text_layer_needs_ocr`。
- 手机拍的凭证走采集包通道，见 [§7 手机采集包](#7-手机采集包导入)。

### API 等价调用

```bash
curl -s -X POST http://127.0.0.1:8710/v1/vouchers/upload \
  -H "Idempotency-Key: demo-001" \
  -F "file=@发票.pdf"
# → {"voucher_id": "<uuid>", "state": "INGESTED"}
```

`Idempotency-Key` 头可选但推荐：重复点击上传时便于对账排重，键值会落进事件 payload。

---

## 2. OCR / 字段提取（仍在凭证箱）

### 操作

1. 在状态为 `INGESTED` 的行点「OCR识别」。
2. 结果两种走向：
   - 置信度 ≥ `ZZ_REVIEW_THRESHOLD`（默认 0.80）且字段完整 → 直通 `REVIEWED` 分支；
   - 置信度不足或缺关键字段 → 状态变 `NEEDS_REVIEW`，行内出现「覆核」按钮。

### 此刻发生了什么

- 按文件类型选 Provider：`.pdf` → 文本层提取（关键词驱动抽取 价税合计/税额/日期/单号/名称）；
  不编造识别不出的内容——抽不到就是空，等人工补。
- 每个抽取字段带 confidence 与来源文本快照，写入 VoucherJSON 的 `fields[]`；
- 迁移强制写事件，链上可回放谁在何时跑了哪次 OCR。

### 常见失败

| 报错 | 含义 | 出路 |
|------|------|------|
| `no_text_layer_needs_ocr` | 扫描件无文本层，程序诚实拒绝 | 等待图片 OCR 能力或改用文字型 PDF |
| 「暂不支持的文件类型」 | 上传了非 PDF | 先转文字型 PDF |
| 提取出的金额为 `-` | 版面关键词未命中 | 进覆核页手补，属正常人工兜底 |

---

## 3. 人工覆核（覆核页签）

### 操作

1. 从凭证箱点「覆核」进入。六个可编辑字段逐项对照原件：
   交易日期 / 含税金额 / 未税金额 / 税额 / 对手方名称 / 凭证类型；
   每项右侧灰字显示**原值**，方便比对 OCR 抄了什么。
2. 改完点「保存并批准」。系统自动跳转分录页签。

### 此刻发生了什么（重要）

- 你的每次修改都写入 `voucher.field_corrected` 哈希链事件：**谁改的、改了什么、原值是什么，永久留痕**；
- 这是全流程唯一允许修改凭证字段的窗口；批准后再想改，只能红字冲销重来（见 §4）；
- 未覆核（`NEEDS_REVIEW`）的凭证**不可能**生成分录——非法迁移会抛
  `invalid_state_transition`（HTTP 409），这是设计而非 bug。

### API 等价调用

```bash
curl -s -X POST http://127.0.0.1:8710/v1/vouchers/<voucher_id>/review \
  -H "Content-Type: application/json" \
  -d '{"corrections": {"transaction.amount_incl_tax": 11300}, "reviewer": "张会计", "approve": true}'
```

---

## 4. 序时账分录（分录页签）

### 操作

1. 批准覆核后系统已生成草稿：科目来自按凭证类型的映射模板（不是你的企业会计政策，
   LIMITATIONS.md #5——确认前必须逐行看）。
2. 可编辑每行的科目名、借方、贷方金额。
3. 按钮实时显示借贷差额：不平则显示「借贷不平 X 元，不能确认」且按钮禁用；
   平衡后变为「确认分录（借贷平衡 ✔）」，点击确认。

### 此刻发生了什么

- 确认瞬间计算 `lines_hash` 锁定行内容；分录状态进入 `JOURNAL_CONFIRMED`；
- **确认后的分录不可修改、不可删除**——发现错误只能红字冲销：生成一笔方向相反的平衡分录，
  关联原分录号，两笔永久并存（审计惯例：改错留痕，不做物理删改）；
- 完整性规则 R-CMP-001 带 `block_confirmed_journal` 参数：缺日期/含税金额/对手方的凭证
  根本不允许确认分录。

### Web 没有的入口（诚实声明）

红字冲销在 v0.1.0 的 Web 界面**尚未暴露按钮**，可用 Python API：

```python
from zhanzhen.service import AuditService
svc = AuditService(tenant_id="demo-tenant")     # ZZ_DATA_DIR 按需设置
svc.reverse_journal("<voucher_id>", reason="录入错误")
```

Web 冲销端点在路线图中（VERSIONING.md v0.5-beta 批次）。

---

## 5. 规则检查（风险页签）

### 操作

1. 点「运行三条规则」→ 表格列出命中：规则号 / 严重度（high 红 / medium 黄）/ 解释 /
   证据哈希引用 / 处置按钮。
2. 每条命中必须人工处置：点「属实」或「误报」，结果写回发现记录。
3. （进阶）`GET /v1/findings12` 提供 audit-os 移植的 **12 条完整规则引擎**结果：
   期末突击收入、大额、方向异常、应收占比、毛利率波动、关联方对挂、供应商集中、
   周末大额、重复交易、短期冲销等，重要性水平自动校准。

### 三条 MVP 规则速查（参数权威源 `rules_builtin.yaml`）

| 规则 | 逻辑 | 默认参数 |
|------|------|----------|
| R-AMT-001 金额一致性 | 含税 ≈ 未税 + 税额 | 容差 0.01 元 |
| R-DUP-001 疑似重复 | 同日 + 对手方 + 含税金额 + 单号全同即命中第二张 | 零容差、同日窗口 |
| R-CMP-001 完整性 | 必填：交易日期、含税金额；对手方必需 | 缺失即 high，且阻断分录确认 |

规则语义的规范级解释规划在 docs/user/RULES_GUIDE.md（DOC_MAP 已立项），本章只给作业速查。

### AI 解释（可选，默认关闭）

选中一条 finding 后点「AI 解释选中风险」。未配置 `ZZ_AI_*` 时会收到
`ai_disabled_or_invalid` 提示——这是预期行为。开启方法与出网边界见
[CONFIG.md](CONFIG.md) §3.5 与 [PRIVACY.md](PRIVACY.md)。
AI 只解释与建议科目，**永远不能直接改账**。

---

## 6. 导出报告与序时账（报告页签）

### 操作

1. 「导出可追溯 HTML 报告」→ 下载 `report.html`，浏览器打开；
2. 「导出序时账 Excel/CSV」→ 未装 openpyxl 时自动降级 CSV（不算故障）。

### 报告里能点到什么

- 全量凭证索引，每条带 **SHA-256**；风险清单每条带证据引用；
- 反向追溯路径：`报告结论 → 风险编号 → 触发凭证 → 原始文件哈希`；
- 页脚含模板版本与数据截止时间；⚠ 声明：**报告是分析初稿，不构成审计意见，签字权属于人**
  ——执业边界全文见 [CPA_COMPLIANCE.md](../biz/CPA_COMPLIANCE.md)。

### 导出前发生了什么

- 导出动作本身写事件，凭证推进 `EXPORTED`；
- 序时账导出前**强制借贷平衡校验**，不平衡直接拒绝导出。

---

## 7. 手机采集包导入

手机端拍照→导出 `zhanzhen-capture-*.json` 采集包的完整链路见
[MOBILE_WORKFLOW.md](../MOBILE_WORKFLOW.md)，逐项检查清单见
[MOBILE_WORKFLOW_CHECKLIST.md](../MOBILE_WORKFLOW_CHECKLIST.md)。工作台侧只需两步：

1. 凭证箱点「📥 收手机采集包」选择 `.json` 包；
2. 弹窗提示「已收入 N 张凭证」→ 回列表逐张点 OCR。

服务端会对每张照片**重算 SHA-256** 校验完整性；包格式不对会提示「不是湛箴采集包」。

API 直收（供自研客户端对接）：

```bash
curl -s -X POST http://127.0.0.1:8710/v1/vouchers/capture-batch \
  -H "Content-Type: application/json" \
  -d '{"items": [{"filename": "p1.jpg", "content_b64": "<base64>",
                  "captured_at": "2026-08-25T10:28:12+08:00", "note": "餐费"}]}'
```

注意字段名以当前实现为准是 `content_b64`（移动端文档历史稿写作 `content_base64`，以 API 为准）。

---

## 8. 完整性与命令行速查

随时自检证据链是否被动过：

```bash
zhanzhen verify        # ✔ N 条事件，链完整（退出码 0）
curl -s http://127.0.0.1:8710/v1/integrity
```

| 任务 | 命令 |
|------|------|
| 一键演示全流程 | `zhanzhen demo ./out` |
| 启动工作台 | `zhanzhen serve [--host 127.0.0.1] [--port 8710]` |
| 校验事件链 | `zhanzhen verify` |
| 列出全部凭证（JSON） | `curl -s "http://127.0.0.1:8710/v1/vouchers?status=NEEDS_REVIEW"` |
| 跑 12 条完整规则 | `curl -s http://127.0.0.1:8710/v1/findings12` |

## 9. 一次完整作业的自检清单

- [ ] 右上角事件链 ✔ 完整贯穿始终
- [ ] 每张凭证都经过人眼覆核（无 NEEDS_REVIEW 遗留）
- [ ] 每条风险命中都有「属实/误报」处置记录
- [ ] AI 建议（如有）仅作参考且未被直接采纳为事实
- [ ] 报告页脚免责声明完整未被裁剪
- [ ] 导出文件已归档，`zhanzhen verify` 最终退出码 0
