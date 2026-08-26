/**
 * 湛箴审计 OS —— DSH (DeepSeek Harness) 工作流插件 v2
 *
 * 「审计行业 n8n」：把湛箴七节点审计流水线（拍凭证→OCR→覆核→账套→12规则→报告→CPA签发）
 * 建模为 n8n 式模板（节点+连线+触发器），由拓扑排序引擎执行，并按官方
 * tool-workflow/* 事件词表上报进度 —— 官方 WorkflowRunPanel 可直接渲染。
 *
 * 面板/模型可调工具（defineTool 注册）：
 * - zz.workflow.list  列出全部可用模板（内置 audit-basic + templatesDir 追加）
 * - zz.workflow.run   按模板 ID（或内联 JSON）运行一次流程，支持 dry-run
 *
 * 纯逻辑引擎在 ./workflow-engine.ts；本文件只做 DSH 封装（依赖注入 + defineTool）。
 */
import type { Context } from '@deepseek-ai/cordis'
import { defineTool } from '@deepseek-ai/dsh-tools'
import type { JsonValue } from '@deepseek-ai/dsh-session'
import Schema from '@deepseek-ai/schemastery'
import { existsSync, readFileSync, readdirSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import type {
  JsonObject, PanelEvent, WorkflowTemplate,
} from './workflow-engine.js'
import {
  NODE_KIND_CONTRACTS, runWorkflow, validateTemplate,
} from './workflow-engine.js'

export const name = 'zhanzhen-workflow'
export const inject = ['tools'] as const

export interface Config {
  /** 追加模板目录：其中的 *.json 模板会被 zz.workflow.list 收录。 */
  templatesDir?: string
  /** zz.workflow.run 未显式给 dryRun 时的默认值（默认 true，安全优先）。 */
  defaultDryRun?: boolean
}

export const Config: Schema<Config> = Schema.object({
  templatesDir: Schema.string().description('追加模板目录（可选），收录其中 *.json 模板'),
  defaultDryRun: Schema.boolean().default(true).description('run 工具的默认 dry-run 开关'),
})

/** 内置基础模板路径（与 index.ts 同目录）。 */
const here = dirname(fileURLToPath(import.meta.url))
const BUILTIN_TEMPLATE_PATH = join(here, 'workflow-template-audit-basic.json')

/** 从磁盘加载并解析一个模板文件（含最小形状检查）。 */
function loadTemplateFile(path: string): WorkflowTemplate {
  const raw = JSON.parse(readFileSync(path, 'utf8')) as unknown
  if (typeof raw !== 'object' || raw === null || Array.isArray(raw)) {
    throw new Error(`模板不是对象: ${path}`)
  }
  return raw as WorkflowTemplate
}

/**
 * 收录全部模板：内置 audit-basic 必在；templatesDir 下的 *.json 逐个追加
 * （单个坏文件跳过并提示，不影响其余模板——懒降级而非抛错）。
 */
function collectTemplates(templatesDir?: string): WorkflowTemplate[] {
  const out: WorkflowTemplate[] = []
  if (existsSync(BUILTIN_TEMPLATE_PATH)) out.push(loadTemplateFile(BUILTIN_TEMPLATE_PATH))
  if (templatesDir && existsSync(templatesDir)) {
    for (const f of readdirSync(templatesDir).filter(f => f.endsWith('.json')).sort()) {
      try {
        out.push(loadTemplateFile(join(templatesDir, f)))
      } catch (e) {
        console.error(`[zhanzhen-workflow] 跳过无法解析的模板 ${f}: ${e instanceof Error ? e.message : String(e)}`)
      }
    }
  }
  return out
}

/** 把引擎事件桥接到 cordis 总线（官方面板折叠 tool-workflow/* 事件族）。 */
function bridgeEvents(ctx: Context): (ev: PanelEvent) => void {
  return (ev) => {
    const anyCtx = ctx as unknown as { emit?: (name: string, data: unknown) => void }
    try {
      anyCtx.emit?.(ev.name, ev.data)
    } catch {
      /* 事件桥接失败不阻断流程执行 */
    }
  }
}

interface RunArgs {
  templateId?: string
  template?: JsonValue
  dryRun?: boolean
  input?: JsonObject
  inputNodeParams?: Record<string, JsonObject>
}

/** 解析模板（内联 JSON 优先，其次按 ID 收录表查找）并应用输入注入。 */
function resolveTemplate(args: RunArgs, templatesDir?: string): WorkflowTemplate {
  let template: WorkflowTemplate | undefined
  if (args.template && typeof args.template === 'object' && !Array.isArray(args.template)) {
    template = args.template as unknown as WorkflowTemplate
  } else if (typeof args.templateId === 'string') {
    template = collectTemplates(templatesDir).find(t => t.meta.name === args.templateId)
    if (!template) throw new Error(`找不到模板: ${args.templateId}`)
  } else {
    throw new Error('必须提供 templateId 或 template 之一')
  }

  // 输入注入：input.vouchers 挂到触发器节点 params（约定入口）；per-node params 覆盖。
  const nodes = template.nodes.map(n => {
    let params: JsonObject = n.params ?? {}
    if (n.kind === 'trigger' && args.input && typeof args.input === 'object'
      && !Array.isArray(args.input) && args.input.vouchers !== undefined) {
      params = { ...params, vouchers: args.input.vouchers }
    }
    const override = args.inputNodeParams?.[n.id]
    if (override) params = { ...params, ...override }
    return { ...n, params }
  })
  return { ...template, nodes }
}

export function apply(ctx: Context, config: Config = {}) {
  const defaultDryRun = config.defaultDryRun ?? true

  /* ---------- zz.workflow.list ---------- */
  ctx.tools.register(defineTool({
    name: 'zz.workflow.list',
    description: '列出湛箴审计工作流模板（n8n 式：节点+连线+触发器）：元信息、阶段、节点链、连线；另附可用节点类型词表',
    parameters: {},
    output: {
      schema: { type: 'json' },
      render: (_args, value) => [{ type: 'text', text: renderList(value) }],
    },
    async execute() {
      const templates = collectTemplates(config.templatesDir)
      return {
        count: templates.length,
        nodeKinds: Object.values(NODE_KIND_CONTRACTS).map(c => ({
          kind: c.kind,
          label: c.label,
          description: c.description,
          inputs: [...c.inputs],
          outputs: [...c.outputs],
        })),
        templates: templates.map(summarize),
      } as unknown as JsonValue
    },
  }))

  /* ---------- zz.workflow.run ---------- */
  ctx.tools.register(defineTool({
    name: 'zz.workflow.run',
    description: '运行湛箴审计工作流模板：按拓扑序执行各节点（拍凭证→OCR→覆核→账套→12规则→报告→CPA签发），dry-run 用内置模拟执行器零副作用',
    parameters: {
      templateId: { type: 'string', description: '要运行的模板 ID（如 audit-basic）；与 template 二选一' },
      template: { type: 'json', description: '内联模板 JSON（meta+nodes+edges）；提供时优先于 templateId' },
      dryRun: { type: 'boolean', description: `真=模拟执行零副作用（默认 ${String(defaultDryRun)}）；假=调用真实执行器` },
      input: { type: 'json', description: '运行输入，如 {"vouchers":[…]} 注入触发器节点' },
      inputNodeParams: { type: 'json', description: '按节点 id 覆盖 params，如 {"review":{"autoApprove":false}}' },
    },
    output: {
      schema: { type: 'json' },
      render: (_args, value) => [{ type: 'text', text: renderRun(value) }],
    },
    async execute(args) {
      const a = args as unknown as RunArgs
      const dryRun = a.dryRun ?? defaultDryRun
      const template = resolveTemplate(a, config.templatesDir)

      // 先校验后执行：结构/契约错误以可读清单失败。
      const errs = validateTemplate(template)
      if (errs.length > 0) throw new Error(`模板校验失败:\n- ${errs.join('\n- ')}`)

      const result = await runWorkflow(template, {
        dryRun,
        onEvent: bridgeEvents(ctx),
      })

      return {
        runId: result.runId,
        templateName: result.templateName,
        status: result.status,
        stopReason: result.stopReason,
        ...(result.error ? { error: result.error } : {}),
        dryRun: result.dryRun,
        nodes: result.nodes.map(nd => ({
          seq: nd.seq,
          nodeId: nd.nodeId,
          kind: nd.kind,
          label: nd.label,
          phase: nd.phase,
          outcome: nd.outcome,
          durationMs: nd.durationMs,
          ...(nd.error ? { error: nd.error } : {}),
          outputs: nd.outputs,
        })),
        artifacts: result.artifacts,
        eventCount: result.events.length,
      } as unknown as JsonValue
    },
  }))
}

/* ============================== 渲染辅助（纯函数） ============================== */

interface TemplateSummary {
  meta: {
    name: string
    description: string
    whenToUse?: string
    phases?: readonly { title: string; detail?: string }[]
  }
  nodes: readonly { id: string; kind: string; name?: string; phase?: string }[]
  edges: readonly { from: string; to: string }[]
}

function summarize(t: WorkflowTemplate): TemplateSummary {
  return {
    meta: {
      name: t.meta.name,
      description: t.meta.description,
      ...(t.meta.whenToUse ? { whenToUse: t.meta.whenToUse } : {}),
      ...(t.meta.phases
        ? { phases: t.meta.phases.map(p => ({ title: p.title, ...(p.detail ? { detail: p.detail } : {}) })) }
        : {}),
    },
    nodes: t.nodes.map(n => ({
      id: n.id, kind: n.kind,
      ...(n.name ? { name: n.name } : {}),
      ...(n.phase ? { phase: n.phase } : {}),
    })),
    edges: t.edges.map(e => ({ from: e.from, to: e.to })),
  }
}

function renderList(value: unknown): string {
  const v = value as { count: number; nodeKinds: { kind: string; label: string }[]; templates: TemplateSummary[] }
  const lines: string[] = [`湛箴工作流模板 ×${v.count}`]
  for (const t of v.templates) {
    lines.push('', `## ${t.meta.name}`, t.meta.description)
    lines.push(`节点链: ${t.nodes.map(n => n.name ?? n.kind).join(' → ')}`)
    lines.push(`连线 ×${t.edges.length}`)
    if (t.meta.phases?.length) lines.push(`阶段: ${t.meta.phases.map(p => p.title).join('/')}`)
  }
  lines.push('', `可用节点类型: ${v.nodeKinds.map(k => `${k.kind}(${k.label})`).join(', ')}`)
  return lines.join('\n')
}

function renderRun(value: unknown): string {
  const v = value as {
    runId: string
    status: string
    dryRun: boolean
    error?: string
    nodes: { seq: number; label: string; outcome: string; durationMs: number }[]
  }
  const head = `工作流 ${v.runId} [${v.status}${v.dryRun ? '/dry-run' : ''}]`
  if (v.error) {
    return [head, `失败于第 ${v.nodes.length} 个节点: ${v.error}`,
      ...v.nodes.map(n => `${n.seq}. ${n.label}: ${n.outcome}`)].join('\n')
  }
  return [head, ...v.nodes.map(n => `${n.seq}. ${n.label} → ${n.outcome} (${n.durationMs}ms)`)].join('\n')
}
