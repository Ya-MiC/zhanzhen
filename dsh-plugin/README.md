# dsh-plugin-zhanzhen-audit

湛箴审计 OS 的 **DeepSeek Harness 插件**——「一切皆插件」架构的审计能力接入。

- **v1**（`src/index.ts`）：湛箴 REST 能力命令集（凭证箱/OCR/覆核/分录/规则/报告）。
- **v2**（`index.ts` + `workflow-engine.ts`）：「审计行业 n8n」可视化工作流——
  把审计作业建模为 n8n 式模板（节点+连线+触发器），由拓扑排序引擎执行，
  进度按官方 `tool-workflow/*` 事件词表上报，官方 WorkflowRunPanel 可直接渲染。

## 安装

前置：湛箴服务在本地跑着：

```bash
pip install "zhanzhen[web]"
zhanzhen serve            # http://127.0.0.1:8710（ZZ_PORT 可改）
```

然后把本目录作为 DSH 插件装入 Harness（参见 `cordis.yml` overlay 示例与 `dsh.bundle.json`）。

## v1 命令（REST 能力集）

| 命令 | 说明 |
|---|---|
| `zz.vouchers` | 凭证箱总览 |
| `zz.ocr <id>` | OCR 识别指定凭证 |
| `zz.review <id> field=value` | 覆核修正字段（留痕进哈希链） |
| `zz.journal <id>` | 生成分录草稿并确认 |
| `zz.rules` | 运行三条审计规则 |
| `zz.report` | 导出可追溯 HTML 报告 |
| `zz.integrity` | 校验证据链完整性 |

## v2 工作流工具（defineTool，面板/模型可调）

### `zz.workflow.list`

列出全部模板（内置 `audit-basic` + 可选 `templatesDir` 追加），附七种节点类型词表
（trigger/manual/ocr/rules/journal/report/approve）及其输入输出契约。

### `zz.workflow.run`

```text
参数：
  templateId      模板 ID（如 audit-basic）；或用 template 内联 JSON
  template        内联模板（meta+nodes+edges），优先于 templateId
  dryRun          真=内置模拟执行器零副作用（默认 true）
  input           {"vouchers":[…]} 注入触发器节点
  inputNodeParams 按节点 id 覆盖 params，如 {"review":{"autoApprove":false}}
```

执行语义：Kahn 拓扑排序 → 逐节点核对输入契约 → 执行 → 核对输出契约；
任一节点失败即以 `stopReason:'error'` 收场并保留已完成节点记录。

### 内置基础模板 `workflow-template-audit-basic.json`

七节点默认闭环（每节点一个面板 phase）：

```text
拍凭证(采集) → OCR识别(识别) → 人工覆核(覆核) → 账套分录(记账)
            → 12规则扫描(检查) → 报告生成(报告) → CPA签发流转(签发)
```

人工覆核节点：非 dry-run 且未设 `params.autoApprove=true` 时流程挂起等待真人。

## 与官方面板的契合

引擎按 `@deepseek-ai/dsh-tool-workflow` 的持久化事件词表发射进度：
`tool-workflow/run-start` → 每节点 `agent-start`/`agent-end`（seq/label/phase/childId）
→ `run-end`（stopReason ∈ completed/cancelled/error）。每个节点的执行映射为面板上的
一个 member，`phase` 取模板声明的阶段名。

## 工程验证

```bash
npm install
npm run typecheck   # tsc --noEmit 严格类型
npm run smoke       # tsx smoke.ts：加载插件→list→dry-run 七节点→事件对账→三个负例
```
