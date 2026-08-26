/**
 * Smoke test —— 湛箴工作流插件端到端验证：
 * 1. 最小宿主（Context + ToolsService mock），真实加载插件（apply）
 * 2. 断言 zz.workflow.list / zz.workflow.run 注册成功
 * 3. list：内置模板 audit-basic 可见、七节点链完整
 * 4. run（dry-run）：模板加载→校验→拓扑执行→七节点全绿→CPA 签发工件产出
 * 5. 面板事件序列与官方 tool-workflow/* 词表逐一对账
 * 6. 负例：环图被拒、契约断线被拒、人工覆核挂起语义
 *
 * 运行：npx tsx smoke.ts   （退出码 0 = 通过）
 */
import { Context } from '@deepseek-ai/cordis'
import type { ToolDefinition, ToolRunContext } from '@deepseek-ai/dsh-tools'
import { apply as workflowPlugin } from './index.js'

/* ---------------- 最小宿主：ToolsService mock（对齐 hermes 参考模式） ---------------- */

interface HostHarness {
  tools: Map<string, ToolDefinition>
  register(t: ToolDefinition): void
  get(name: string): ToolDefinition | undefined
}

function makeHost(): { harness: HostHarness; ctx: Context; busEvents: { name: string; data: Record<string, unknown> }[] } {
  const registry = new Map<string, ToolDefinition>()
  const harness: HostHarness = {
    tools: registry,
    register(t) { registry.set(t.name, t) },
    get(n) { return registry.get(n) },
  }
  const busEvents: { name: string; data: Record<string, unknown> }[] = []
  const ctx = {
    emit: (n: string, d: unknown) => { busEvents.push({ name: n, data: d as Record<string, unknown> }) },
    tools: harness,
  } as unknown as Context
  return { harness, ctx, busEvents }
}

/** defineTool 包装后的 execute 需要 (args, exec)；本插件不消费 exec，传最小桩。 */
const execStub = {} as unknown as ToolRunContext

function assert(cond: unknown, msg: string): asserts cond {
  if (!cond) throw new Error(`SMOKE 断言失败: ${msg}`)
}

async function main() {
  const { harness, ctx, busEvents } = makeHost()

  /* 1. 加载插件 */
  workflowPlugin(ctx, {})
  console.log('registered tools:', [...harness.tools.keys()].join(', '))
  assert(harness.get('zz.workflow.list'), 'zz.workflow.list 未注册')
  assert(harness.get('zz.workflow.run'), 'zz.workflow.run 未注册')
  assert(harness.tools.size === 2, `应恰好注册 2 个工具，实得 ${harness.tools.size}`)

  /* 2. zz.workflow.list */
  const listed = await harness.get('zz.workflow.list')!.execute({}, execStub) as {
    count: number
    nodeKinds: { kind: string }[]
    templates: { meta: { name: string }; nodes: unknown[]; edges: unknown[] }[]
  }
  console.log(`list → ${listed.count} 模板, ${listed.nodeKinds.length} 种节点类型`)
  assert(listed.count >= 1, '内置模板未收录')
  const basic = listed.templates.find(t => t.meta.name === 'audit-basic')
  assert(basic, 'audit-basic 模板缺失')
  assert(basic!.nodes.length === 7, `audit-basic 应为 7 节点，实得 ${basic!.nodes.length}`)
  assert(basic!.edges.length === 6, `audit-basic 应为 6 条连线，实得 ${basic!.edges.length}`)
  assert(listed.nodeKinds.length === 7, '节点类型词表应为 7 种')

  /* 3. zz.workflow.run —— dry-run 全流程 */
  busEvents.length = 0
  const run = await harness.get('zz.workflow.run')!.execute({
    templateId: 'audit-basic',
    dryRun: true,
    input: { vouchers: [{ voucherId: 'V-E2E-1', source: 'camera' }] },
  }, execStub) as {
    runId: string; status: string; dryRun: boolean
    nodes: { seq: number; kind: string; outcome: string; outputs: Record<string, unknown> }[]
    artifacts: Record<string, Record<string, unknown>>
    eventCount: number
  }
  console.log(`run → ${run.runId} [${run.status}]`)
  assert(run.status === 'completed', `dry-run 应 completed，实得 ${run.status}（${JSON.stringify(run).slice(0, 400)}）`)
  assert(run.dryRun === true, '应标记 dry-run')
  assert(run.nodes.length === 7, `应执行 7 个节点，实得 ${run.nodes.length}`)
  for (const nd of run.nodes) assert(nd.outcome === 'completed', `节点 ${nd.kind} 未完成`)
  // 工件链完整性：从影像到签发终稿。
  for (const a of ['voucher-image', 'ocr-result', 'reviewed-voucher', 'journal-entry', 'rule-findings', 'audit-report', 'signed-report']) {
    assert(run.artifacts[a], `工件缺失: ${a}`)
  }
  const signed = run.artifacts['signed-report']!
  assert(signed.flowStatus === 'issued', 'CPA 签发状态应为 issued')
  assert(typeof signed.signature === 'string' && (signed.signature as string).length > 0, '缺少签章指纹')
  // 输入注入生效：触发器收到 E2E 凭证。
  const img = run.artifacts['voucher-image']!
  assert(img.count === 1, '注入的凭证数量应为 1')
  // 12 规则扫描确实评估了 12 条。
  const findings = run.artifacts['rule-findings']!
  assert(findings.evaluatedCount === 12, `12 规则应评估 12 条，实得 ${String(findings.evaluatedCount)}`)

  /* 4. 官方面板事件词表对账 */
  const names = busEvents.map(e => e.name)
  console.log('panel events:', names.join(' → '))
  assert(names[0] === 'tool-workflow/run-start', '首事件必须是 tool-workflow/run-start')
  assert(names[names.length - 1] === 'tool-workflow/run-end', '尾事件必须是 tool-workflow/run-end')
  const starts = busEvents.filter(e => e.name === 'tool-workflow/agent-start')
  const ends = busEvents.filter(e => e.name === 'tool-workflow/agent-end')
  assert(starts.length === 7 && ends.length === 7, `member 事件应各 7 条，实得 ${starts.length}/${ends.length}`)
  starts.forEach((e, i) => {
    assert(e.data.seq === i + 1, `agent-start seq 应为 ${i + 1}`)
    assert(typeof e.data.label === 'string' && (e.data.label as string).length > 0, 'agent-start 缺 label')
    assert(typeof e.data.phase === 'string' && (e.data.phase as string).length > 0, 'agent-start 缺 phase')
    assert(typeof e.data.childId === 'string', 'agent-start 缺 childId')
    assert(ends[i]!.data.seq === i + 1 && ends[i]!.data.outcome === 'completed', `agent-end #${i + 1} 不符`)
  })
  const lastEnd = busEvents[names.length - 1]!
  assert(lastEnd.data.stopReason === 'completed', 'run-end stopReason 应为 completed')

  /* 5. 负例 A：内联模板带环 → 校验拒绝 */
  let cycleRejected = false
  try {
    await harness.get('zz.workflow.run')!.execute({
      template: {
        schemaVersion: 1,
        meta: { name: 'cyclic', description: '坏模板' },
        nodes: [
          { id: 't', kind: 'trigger' }, { id: 'a', kind: 'ocr' },
          { id: 'b', kind: 'manual' }, { id: 'c', kind: 'journal' },
        ],
        edges: [
          { from: 't', to: 'a' }, { from: 'a', to: 'b' },
          { from: 'b', to: 'a' }, { from: 'c', to: 'b' },
        ],
      },
      dryRun: true,
    }, execStub)
  } catch (e) {
    cycleRejected = /环|拓扑/.test(e instanceof Error ? e.message : String(e))
  }
  assert(cycleRejected, '环图应被校验拒绝并给出可读错误')

  /* 6. 负例 B：契约断线（report 直连 trigger，缺 rule-findings/journal-entry）→ 校验拒绝 */
  let contractRejected = false
  try {
    await harness.get('zz.workflow.run')!.execute({
      template: {
        schemaVersion: 1,
        meta: { name: 'broken-contract', description: '断线模板' },
        nodes: [
          { id: 't', kind: 'trigger' }, { id: 'r', kind: 'report' },
        ],
        edges: [{ from: 't', to: 'r' }],
      },
      dryRun: true,
    }, execStub)
  } catch (e) {
    contractRejected = /rule-findings/.test(e instanceof Error ? e.message : String(e))
  }
  assert(contractRejected, '输入契约违例应被拒绝且指名缺失工件')

  /* 7. 负例 C：非 dry-run 且 manual 未 autoApprove → 人工覆核挂起（error 收场，已完成节点保留） */
  const paused = await harness.get('zz.workflow.run')!.execute({
    template: {
      schemaVersion: 1,
      meta: { name: 'needs-human', description: '等待真人覆核' },
      nodes: [
        { id: 't', kind: 'trigger' },
        { id: 'o', kind: 'ocr' },
        { id: 'rv', kind: 'manual', params: {} },
      ],
      edges: [
        { from: 't', to: 'o' }, { from: 'o', to: 'rv' },
      ],
    },
    dryRun: false,
  }, execStub) as { status: string; error?: string; nodes: { nodeId: string; outcome: string }[] }
  console.log(`pause-semantics → ${paused.status}: ${paused.error ?? ''}`)
  assert(paused.status === 'error' && /等待人工覆核/.test(paused.error ?? ''), 'manual 应在无 autoApprove 且非 dry-run 时挂起')
  assert(paused.nodes.some(n => n.nodeId === 'rv' && n.outcome === 'failed'), '挂起节点应记录 failed')
  assert(paused.nodes.filter(n => n.outcome === 'completed').length === 2, '已完成的前置节点应保留')

  console.log('\n✅ SMOKE PASSED: 模板加载、dry-run 七节点闭环、面板事件词表、三个负例全部通过')
  process.exit(0)
}

main().catch((e) => {
  console.error('❌ SMOKE FAILED:', e)
  process.exit(1)
})
