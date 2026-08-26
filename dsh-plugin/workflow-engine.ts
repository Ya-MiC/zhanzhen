/**
 * 湛箴审计 OS —— 「审计行业 n8n」可视化工作流引擎（纯逻辑层）
 *
 * n8n 式模板 = 节点(nodes) + 连线(edges) + 触发器(trigger)。
 * 本文件只依赖标准库类型，不 import cordis/dsh —— 保持可单测、可移植；
 * DSH 封装（defineTool 注册、事件桥接官方面板）见 ./index.ts。
 *
 * 与官方面板的契合：引擎按 `@deepseek-ai/dsh-tool-workflow` 的持久化事件
 * 词表发进度（tool-workflow/run-start → agent-start → agent-end → run-end），
 * 每个节点的执行映射为面板上的一个 member，`phase` 字段用模板声明的阶段名，
 * 因此官方 WorkflowRunPanel 可直接渲染本插件的运行记录。
 *
 * @module zhanzhen-workflow/workflow-engine
 */

/* ============================== 基础 JSON 类型 ============================== */

export type JsonScalar = string | number | boolean | null
export type JsonValue = JsonScalar | JsonValue[] | { [key: string]: JsonValue }
export type JsonObject = { [key: string]: JsonValue }

/** 极小确定性哈希（FNV-1a 32bit），用于证据链指纹；无 node:crypto 依赖。 */
export function fnv1a(input: string): string {
  let h = 0x811c9dc5
  for (let i = 0; i < input.length; i++) {
    h ^= input.charCodeAt(i)
    h = Math.imul(h, 0x01000193) >>> 0
  }
  return h.toString(16).padStart(8, '0')
}

/* ============================== 节点类型定义 ============================== */

/**
 * 七种节点类型（审计作业流水线的工序词表）：
 * - trigger 凭证导入：拍照/上传凭证进入流程（唯一入口，n8n 的 Trigger Node）
 * - ocr     识别：对凭证影像做 OCR 抽取结构化字段
 * - manual  人工覆核：会计对 OCR 结果逐字段确认/修正（可配置自动放行）
 * - journal 分录：覆核后的凭证过账到账套（序时账分录草稿+确认）
 * - rules   规则扫描：对账套跑湛箴 12 条审计规则，产出发现项
 * - report  报告生成：汇总分录与发现项，生成可追溯底稿报告
 * - approve CPA签发流转：执业 CPA 对报告签章，完成流转闭环
 */
export type WorkflowNodeKind =
  | 'trigger' | 'ocr' | 'manual'
  | 'journal' | 'rules' | 'report' | 'approve'

/** 工件类型：节点间连线上流动的数据契约单位。 */
export type ArtifactKind =
  | 'voucher-image'      // 凭证影像（拍凭证/导入 PDF）
  | 'ocr-result'         // OCR 结构化识别结果
  | 'reviewed-voucher'   // 覆核定稿的凭证数据（进哈希链留痕）
  | 'journal-entry'      // 账套序时分录
  | 'rule-findings'      // 12 规则扫描发现项
  | 'audit-report'       // 可追溯底稿报告
  | 'signed-report'      // CPA 签发的终稿

/** 单个节点类型的静态契约与展示元数据。 */
export interface NodeKindContract {
  kind: WorkflowNodeKind
  /** 中文工位名（面板 label 兜底）。 */
  label: string
  /** 一句话职责说明。 */
  description: string
  /** 输入契约：执行前必须全部就绪的工件类型。 */
  inputs: readonly ArtifactKind[]
  /** 输出契约：成功后产出的工件类型。 */
  outputs: readonly ArtifactKind[]
}

/** 节点类型注册表 —— 每种类型的输入/输出契约在此集中声明。 */
export const NODE_KIND_CONTRACTS: Readonly<Record<WorkflowNodeKind, NodeKindContract>> = Object.freeze({
  trigger: {
    kind: 'trigger', label: '凭证导入',
    description: '拍凭证/上传 PDF，把原始凭证影像送入流程',
    inputs: [], outputs: ['voucher-image'],
  },
  ocr: {
    kind: 'ocr', label: 'OCR 识别',
    description: '识别凭证影像：日期、金额、对手方、摘要等字段',
    inputs: ['voucher-image'], outputs: ['ocr-result'],
  },
  manual: {
    kind: 'manual', label: '人工覆核',
    description: '会计逐字段覆核 OCR 结果并修正，留痕哈希链',
    inputs: ['ocr-result'], outputs: ['reviewed-voucher'],
  },
  journal: {
    kind: 'journal', label: '账套分录',
    description: '覆核定稿过账：生成序时账分录草稿并确认入账套',
    inputs: ['reviewed-voucher'], outputs: ['journal-entry'],
  },
  rules: {
    kind: 'rules', label: '12 规则扫描',
    description: '对账套跑湛箴 12 条审计规则，产出发现项清单',
    inputs: ['journal-entry'], outputs: ['rule-findings'],
  },
  report: {
    kind: 'report', label: '报告生成',
    description: '汇总分录与发现项，生成可追溯 HTML 底稿报告',
    inputs: ['journal-entry', 'rule-findings'], outputs: ['audit-report'],
  },
  approve: {
    kind: 'approve', label: 'CPA 签发流转',
    description: '执业 CPA 复核报告并电子签章，完成签发流转',
    inputs: ['audit-report'], outputs: ['signed-report'],
  },
})

/* ============================== 模板数据结构 ============================== */

/**
 * 模板身份块 —— 字段词表对齐官方 WorkflowMeta（name/description/whenToUse/phases），
 * 使 harness 的 listings/进度面板可直接消费；phases 是纯进度词表，
 * 引擎把它作为 agent-start 事件的 phase 上报。
 */
export interface TemplatePhase {
  title: string
  detail?: string
}

export interface TemplateMeta {
  name: string
  description: string
  whenToUse?: string
  phases?: readonly TemplatePhase[]
}

/** 一个流程节点：id 在模板内唯一；params 是该节点执行参数（JSON 数据）。 */
export interface WorkflowNode {
  id: string
  kind: WorkflowNodeKind
  /** 展示名（缺省用 NODE_KIND_CONTRACTS[kind].label）。 */
  name?: string
  /** 进度阶段名（须在 meta.phases 中声明）。 */
  phase?: string
  params?: JsonObject
}

/** 一条连线：from 节点的输出工件流向 to 节点。 */
export interface WorkflowEdge {
  from: string
  to: string
}

/** 模板文件结构（n8n 式：nodes + connections + trigger + meta）。 */
export interface WorkflowTemplate {
  schemaVersion: 1
  meta: TemplateMeta
  nodes: readonly WorkflowNode[]
  edges: readonly WorkflowEdge[]
}

/* ============================== 校验：结构与契约 ============================== */

/** 结构 + 连线契约校验。返回错误列表；空数组即合法。 */
export function validateTemplate(t: WorkflowTemplate): string[] {
  const errors: string[] = []
  if (t.schemaVersion !== 1) errors.push(`schemaVersion 必须为 1，收到 ${String(t.schemaVersion)}`)
  if (!t.meta || typeof t.meta.name !== 'string' || !t.meta.name) errors.push('meta.name 缺失')
  if (!Array.isArray(t.nodes) || t.nodes.length === 0) errors.push('nodes 不能为空')

  const ids = new Set<string>()
  const byId = new Map<string, WorkflowNode>()
  for (const n of t.nodes ?? []) {
    if (!n || typeof n.id !== 'string' || !n.id) { errors.push('存在缺少 id 的节点'); continue }
    if (ids.has(n.id)) errors.push(`节点 id 重复: ${n.id}`)
    ids.add(n.id)
    byId.set(n.id, n)
    const c: NodeKindContract | undefined = NODE_KIND_CONTRACTS[n.kind]
    if (!c) errors.push(`节点 ${n.id} 的类型未知: ${String(n.kind)}`)
    if (n.phase && !(t.meta.phases ?? []).some(p => p.title === n.phase)) {
      errors.push(`节点 ${n.id} 声明了未在 meta.phases 定义的阶段: ${n.phase}`)
    }
  }

  // 连线端点必须存在；触发器是唯一无入边节点；非触发器必须有入边。
  const incoming = new Map<string, number>()
  const outgoingFrom = new Set<string>()
  for (const e of t.edges ?? []) {
    if (!byId.has(e.from)) errors.push(`连线的 from 不存在: ${e.from}`)
    if (!byId.has(e.to)) errors.push(`连线的 to 不存在: ${e.to}`)
    outgoingFrom.add(e.from)
    incoming.set(e.to, (incoming.get(e.to) ?? 0) + 1)
  }
  const triggers = (t.nodes ?? []).filter(n => n.kind === 'trigger')
  if (triggers.length !== 1) errors.push(`trigger 节点必须恰好一个，收到 ${triggers.length}`)
  for (const n of t.nodes ?? []) {
    const hasIn = (incoming.get(n.id) ?? 0) > 0
    if (n.kind === 'trigger' && hasIn) errors.push(`触发器 ${n.id} 不允许有入边`)
    if (n.kind !== 'trigger' && !hasIn) errors.push(`非触发器节点 ${n.id} 没有任何入边（不可达）`)
  }

  // 环检测（Kahn）；有环时后续拓扑排序会抛错，这里先给出友好信息。
  try { topoSort(t.nodes ?? [], t.edges ?? []) } catch (e) {
    errors.push(`连线存在环或不可排序: ${e instanceof Error ? e.message : String(e)}`)
  }

  // 输入输出契约：每个节点的必需输入，必须被其上游集合的输出覆盖。
  const upstreamOutputs = new Map<string, Set<ArtifactKind>>()
  const resolveUp = (id: string, seen = new Set<string>()): Set<ArtifactKind> => {
    const cached = upstreamOutputs.get(id)
    if (cached) return cached
    if (seen.has(id)) return new Set<ArtifactKind>()
    seen.add(id)
    const acc = new Set<ArtifactKind>()
    for (const e of t.edges ?? []) {
      if (e.to !== id) continue
      const up = byId.get(e.from)
      if (!up) continue
      for (const a of resolveUp(e.from, seen)) acc.add(a)
      const uc: NodeKindContract | undefined = NODE_KIND_CONTRACTS[up.kind]
      if (uc) for (const o of uc.outputs) acc.add(o)
    }
    upstreamOutputs.set(id, acc)
    return acc
  }
  for (const n of t.nodes ?? []) {
    const c: NodeKindContract | undefined = NODE_KIND_CONTRACTS[n.kind]
    if (!c) continue
    const have = resolveUp(n.id)
    for (const need of c.inputs) {
      if (!have.has(need)) errors.push(`节点 ${n.id}(${c.label}) 缺少输入工件 ${need}——检查连线是否接对了上游`)
    }
  }
  return errors
}

/* ============================== 拓扑排序（Kahn） ============================== */

/**
 * Kahn 拓扑排序：返回按依赖序排列的节点数组。
 * @throws Error 当存在环或引用了未知节点时（消息列出剩余节点）。
 */
export function topoSort(nodes: readonly WorkflowNode[], edges: readonly WorkflowEdge[]): WorkflowNode[] {
  const byId = new Map<string, WorkflowNode>(nodes.map(n => [n.id, n]))
  const indeg = new Map<string, number>()
  const adj = new Map<string, string[]>()
  for (const n of nodes) { indeg.set(n.id, 0); adj.set(n.id, []) }
  for (const e of edges) {
    if (!byId.has(e.from) || !byId.has(e.to)) throw new Error(`连线引用了未知节点: ${JSON.stringify(e)}`)
    adj.get(e.from)!.push(e.to)
    indeg.set(e.to, (indeg.get(e.to) ?? 0) + 1)
  }
  // 稳定序：同层按 nodes 声明顺序出队。
  const queue: string[] = nodes.filter(n => (indeg.get(n.id) ?? 0) === 0).map(n => n.id)
  const out: WorkflowNode[] = []
  while (queue.length > 0) {
    const id = queue.shift()!
    out.push(byId.get(id)!)
    for (const nxt of adj.get(id) ?? []) {
      const d = (indeg.get(nxt) ?? 0) - 1
      indeg.set(nxt, d)
      if (d === 0) queue.push(nxt)
    }
  }
  if (out.length !== nodes.length) {
    const stuck = nodes.map(n => n.id).filter(id => !out.some(o => o.id === id))
    throw new Error(`图中存在环，无法拓扑排序；卡住的节点: ${stuck.join(', ')}`)
  }
  return out
}

/* ============================== 运行期模型 ============================== */

/** 面板兼容事件名（对齐 @deepseek-ai/dsh-tool-workflow 持久化词表）。 */
export type PanelEventName =
  | 'tool-workflow/run-start' | 'tool-workflow/agent-start'
  | 'tool-workflow/agent-end' | 'tool-workflow/run-end'

/** 引擎产出的面板事件载荷（字段名与官方 ToolWorkflow*Data 一致）。 */
export interface PanelEvent {
  name: PanelEventName
  data: JsonObject
}

/** 单节点执行记录。 */
export interface NodeRunRecord {
  seq: number
  nodeId: string
  kind: WorkflowNodeKind
  label: string
  phase: string
  outcome: 'completed' | 'failed' | 'cancelled'
  dryRun: boolean
  startedAt: string
  durationMs: number
  /** 产出工件（output 契约 → 内容）。失败时为空对象。 */
  outputs: Partial<Record<ArtifactKind, JsonObject>>
  error?: string
}

/** 一次运行的结果。 */
export interface WorkflowRunResult {
  runId: string
  templateName: string
  status: 'completed' | 'cancelled' | 'error'
  stopReason: 'completed' | 'cancelled' | 'error'
  error?: string
  dryRun: boolean
  nodes: readonly NodeRunRecord[]
  /** 全部产出工件（含触发器输入）。 */
  artifacts: Partial<Record<ArtifactKind, JsonObject>>
  /** 面板事件流（run-start…run-end 完整序列）。 */
  events: readonly PanelEvent[]
}

/** 节点执行上下文：传给每个执行器。 */
export interface NodeExecContext {
  readonly node: WorkflowNode
  readonly contract: NodeKindContract
  /** 上游产出 + 触发器输入（按工件类型取用）。 */
  readonly inputs: Readonly<Partial<Record<ArtifactKind, JsonObject>>>
  readonly params: JsonObject
  readonly dryRun: boolean
  readonly runId: string
}

/** 节点执行器：校验过的输入进来，输出契约定义的工件出去。 */
export type NodeExecutor = (ctx: NodeExecContext) => Promise<Partial<Record<ArtifactKind, JsonObject>>>

export class WorkflowNodeError extends Error {
  constructor(nodeId: string, message: string) {
    super(`节点 ${nodeId}: ${message}`)
    this.name = 'WorkflowNodeError'
  }
}

/** 执行器注册表：kind → executor。可用 override 注入真实服务调用。 */
export type ExecutorRegistry = Readonly<Record<WorkflowNodeKind, NodeExecutor>>

/* ============================== 内置（模拟）执行器 ============================== */

const str = (v: JsonValue | undefined, fallback: string): string =>
  typeof v === 'string' ? v : fallback

function requireInput(ctx: NodeExecContext, kind: ArtifactKind): JsonObject {
  const got = ctx.inputs[kind]
  if (!got) throw new WorkflowNodeError(ctx.node.id, `输入工件缺失: ${kind}（契约违例）`)
  return got
}

function assertOutputs(ctx: NodeExecContext, produced: Partial<Record<ArtifactKind, JsonObject>>): void {
  for (const want of ctx.contract.outputs) {
    if (!produced[want]) throw new WorkflowNodeError(ctx.node.id, `执行器未产出契约要求的输出工件: ${want}`)
  }
}

/**
 * 内置模拟执行器集：确定性、零外部依赖，供 dry-run 与离线演示。
 * 真实部署可通过 runWorkflow 的 executors 覆盖为调用湛箴 REST 服务。
 */
export const SIM_EXECUTORS: ExecutorRegistry = Object.freeze({
  async trigger(ctx) {
    const vouchersIn = Array.isArray(ctx.params.vouchers) ? ctx.params.vouchers : []
    const vouchers: JsonObject[] = vouchersIn.length > 0
      ? vouchersIn.filter((v): v is JsonObject => typeof v === 'object' && v !== null && !Array.isArray(v))
      : [{ voucherId: 'V-SIM-0001', source: 'camera', note: '模拟凭证（未提供 params.vouchers 时自动生成）' }]
    const images = vouchers.map(v => ({ ...v, capturedAt: v.capturedAt ?? new Date().toISOString() }))
    return {
      'voucher-image': {
        count: images.length,
        fingerprint: fnv1a(JSON.stringify(images)),
        vouchers: images,
        ...(ctx.dryRun ? { dryRun: true } : {}),
      },
    }
  },

  async ocr(ctx) {
    const image = requireInput(ctx, 'voucher-image')
    const fields: JsonObject = {
      date: new Date().toISOString().slice(0, 10),
      amountInclTax: 0,
      counterparty: '（模拟）对手方名称',
      summary: 'OCR 模拟识别结果——真实实现应调用湛箴 /v1/vouchers/{id}/ocr',
    }
    return {
      'ocr-result': {
        engine: str(ctx.params.engine, 'zhanzhen-ocr-sim'),
        confidence: 0.98,
        fields,
        sourceFingerprint: image.fingerprint ?? null,
        ...(ctx.dryRun ? { dryRun: true } : {}),
      },
    }
  },

  async manual(ctx) {
    const ocr = requireInput(ctx, 'ocr-result')
    // 未显式 autoApprove 的人工节点：流程挂起等待真人（面板可见 cancelled 收场说明）。
    const autoApprove = ctx.params.autoApprove === true
    if (!autoApprove && !ctx.dryRun) {
      throw new WorkflowNodeError(ctx.node.id, '等待人工覆核（设置 params.autoApprove=true 或使用 dry-run 才能自动放行）')
    }
    const reviewer = str(ctx.params.reviewer, ctx.dryRun ? 'dry-run(自动放行)' : 'auto-approve')
    return {
      'reviewed-voucher': {
        basedOnOcrFingerprint: fnv1a(JSON.stringify(ocr)),
        corrections: {},
        reviewedBy: reviewer,
        reviewedAt: new Date().toISOString(),
        chainHash: fnv1a(`review|${reviewer}|${fnv1a(JSON.stringify(ocr))}`),
        ...(ctx.dryRun ? { dryRun: true } : {}),
      },
    }
  },

  async journal(ctx) {
    const voucher = requireInput(ctx, 'reviewed-voucher')
    const entryId = `JE-${ctx.runId.slice(0, 8)}-${ctx.node.id}`
    const lines: JsonObject[] = [
      { side: '借', account: '银行存款', amountInclTax: null },
      { side: '贷', account: '主营业务收入', amountInclTax: null },
      { side: '贷', account: '应交税费—销项', amountInclTax: null },
    ]
    return {
      'journal-entry': {
        entryId,
        lines,
        voucherChainHash: voucher.chainHash ?? null,
        ledger: str(ctx.params.ledger, 'default'),
        postedAt: new Date().toISOString(),
        ...(ctx.dryRun ? { dryRun: true } : {}),
      },
    }
  },

  async rules(ctx) {
    const entry = requireInput(ctx, 'journal-entry')
    const ruleSet = str(ctx.params.ruleSet, 'zhanzhen-rules12')
    const rulesCount = typeof ctx.params.rulesCount === 'number' ? ctx.params.rulesCount : 12
    const evaluated: JsonValue[] = Array.from({ length: rulesCount }, (_, i) => `R${String(i + 1).padStart(2, '0')}`)
    return {
      'rule-findings': {
        ruleSet,
        evaluatedCount: rulesCount,
        rulesEvaluated: evaluated,
        violations: [],
        scannedEntry: entry.entryId ?? null,
        scannedAt: new Date().toISOString(),
        ...(ctx.dryRun ? { dryRun: true } : {}),
      },
    }
  },

  async report(ctx) {
    const entry = requireInput(ctx, 'journal-entry')
    const findings = requireInput(ctx, 'rule-findings')
    const reportId = `RPT-${ctx.runId.slice(0, 8)}`
    const evidenceHash = fnv1a(`${JSON.stringify(entry)}|${JSON.stringify(findings)}`)
    return {
      'audit-report': {
        reportId,
        format: str(ctx.params.format, 'html'),
        traceable: true,
        evidenceHash,
        sections: ['业务概述', '账套抽样', '规则扫描结果', '结论与建议'],
        ...(ctx.dryRun ? { dryRun: true } : {}),
      },
    }
  },

  async approve(ctx) {
    const report = requireInput(ctx, 'audit-report')
    const signer = str(ctx.params.signer, '执业CPA·湛箴')
    const signature = fnv1a(`${signer}|${report.evidenceHash ?? ''}|${report.reportId ?? ''}`)
    return {
      'signed-report': {
        reportId: report.reportId ?? null,
        signedBy: signer,
        signature,
        signedAt: new Date().toISOString(),
        flowStatus: 'issued',
        ...(ctx.dryRun ? { dryRun: true } : {}),
      },
    }
  },
})

/* ============================== 运行引擎 ============================== */

export interface RunWorkflowOptions {
  dryRun?: boolean
  /** 覆盖内置模拟执行器（如接入真实湛箴服务的实现）。 */
  executors?: Partial<ExecutorRegistry>
  /** 进度事件回调（每次运行同时会把完整事件流放进返回值 events）。 */
  onEvent?: (ev: PanelEvent) => void
  /** 运行 ID（缺省自动生成）。 */
  runId?: string
}

let runSeqCounter = 0

/** 生成一次运行的 ID。 */
export function mintRunId(): string {
  runSeqCounter += 1
  const t = Date.now().toString(36)
  return `zzwf-${t}-${runSeqCounter.toString(36).padStart(4, '0')}`
}

/**
 * 执行一个已通过 validateTemplate 的模板：
 * 1. Kahn 拓扑排序得到执行序；
 * 2. 逐节点核对输入契约 → 执行 → 核对输出契约 → 记录工件；
 * 3. 发射官方面板词表的 tool-workflow/* 事件（每节点=member，phase=阶段名）。
 *
 * 任一节点抛错即终止：stopReason='error'（已完成节点保留在结果里）；
 * manual 节点等待人工时同样以 error 收场并在 error 中说明。
 */
export async function runWorkflow(t: WorkflowTemplate, opts: RunWorkflowOptions = {}): Promise<WorkflowRunResult> {
  const dryRun = opts.dryRun ?? false
  const executors: ExecutorRegistry = { ...SIM_EXECUTORS, ...(opts.executors ?? {}) }
  const runId = opts.runId ?? mintRunId()
  const events: PanelEvent[] = []
  const emit = (name: PanelEventName, data: JsonObject) => {
    const ev: PanelEvent = { name, data }
    events.push(ev)
    opts.onEvent?.(ev)
  }

  const order = topoSort(t.nodes, t.edges)
  const artifacts: Partial<Record<ArtifactKind, JsonObject>> = {}
  const records: NodeRunRecord[] = []

  emit('tool-workflow/run-start', { runId, name: t.meta.name })

  let stopReason: WorkflowRunResult['stopReason'] = 'completed'
  let runError: string | undefined
  let seq = 0

  for (const node of order) {
    seq += 1
    const contract = NODE_KIND_CONTRACTS[node.kind]
    const label = node.name ?? contract?.label ?? node.kind
    const phase = node.phase ?? ''
    const childId = `${runId}-m${String(seq).padStart(2, '0')}`
    const startedAtIso = new Date().toISOString()
    const t0 = Date.now()

    emit('tool-workflow/agent-start', {
      runId, seq, label,
      ...(phase ? { phase } : {}),
      childId,
    })

    let record: NodeRunRecord
    try {
      if (!contract) throw new WorkflowNodeError(node.id, `未知节点类型: ${String(node.kind)}`)
      // 输入契约硬校验（运行期兜底，validateTemplate 已提前拦截）。
      for (const need of contract.inputs) {
        if (!artifacts[need]) throw new WorkflowNodeError(node.id, `输入工件缺失: ${need}`)
      }
      const ctx: NodeExecContext = {
        node, contract,
        inputs: { ...artifacts },
        params: node.params ?? {},
        dryRun, runId,
      }
      const produced = await executors[node.kind](ctx)
      assertOutputs(ctx, produced)
      for (const [k, v] of Object.entries(produced)) {
        if (v) artifacts[k as ArtifactKind] = v
      }
      record = {
        seq, nodeId: node.id, kind: node.kind, label, phase,
        outcome: 'completed', dryRun,
        startedAt: startedAtIso, durationMs: Date.now() - t0,
        outputs: produced,
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      record = {
        seq, nodeId: node.id, kind: node.kind, label, phase,
        outcome: 'failed', dryRun,
        startedAt: startedAtIso, durationMs: Date.now() - t0,
        outputs: {}, error: msg,
      }
      records.push(record)
      emit('tool-workflow/agent-end', { runId, seq, outcome: 'failed' })
      stopReason = 'error'
      runError = msg
      break
    }
    records.push(record)
    emit('tool-workflow/agent-end', { runId, seq, outcome: 'completed' })
  }

  emit('tool-workflow/run-end', { runId, stopReason })
  return {
    runId,
    templateName: t.meta.name,
    status: stopReason,
    stopReason,
    ...(runError ? { error: runError } : {}),
    dryRun,
    nodes: records,
    artifacts,
    events,
  }
}
