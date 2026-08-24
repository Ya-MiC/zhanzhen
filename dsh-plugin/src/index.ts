/**
 * 湛箴 ZhanZhen Audit OS —— DSH (DeepSeek Harness) 插件
 *
 * 架构：一切皆插件（deepseek-harness）。本插件把湛箴审计能力挂到 Harness 上：
 * 上传 PDF 凭证 → OCR → 查看凭证 → 序时账分录 → 规则检查 → 报告。
 * 前置：本地或远端跑着 zhanzhen 服务（`pip install zhanzhen[web] && zhanzhen serve`）。
 */
import type { Context } from '@deepseek-ai/cordis'

export const name = 'zhanzhen-audit'
export const description = '湛箴审计OS：PDF凭证上传/OCR识别/序时账/规则检查/可追溯报告'

export interface Config {
  /** 湛箴服务基址 */
  baseUrl?: string
  /** 可选 API token（预留鉴权） */
  token?: string
}

/** 注入 axios/fetch 的轻量封装（不引入额外依赖，用全局 fetch） */
class ZhanZhenClient {
  constructor(private base: string, private token?: string) {}
  async call(path: string, init?: RequestInit): Promise<any> {
    const res = await fetch(this.base.replace(/\/$/, '') + path, {
      ...init,
      headers: {
        ...(init?.headers || {}),
        ...(this.token ? { Authorization: `Bearer ${this.token}` } : {}),
        'Content-Type': 'application/json',
      },
    })
    if (!res.ok) {
      let msg = `HTTP ${res.status}`
      try { const j = await res.json(); msg = j.message || j.detail || msg } catch {}
      throw new Error(`湛箴调用失败: ${msg}`)
    }
    const ct = res.headers.get('content-type') || ''
    return ct.includes('json') ? res.json() : res.text()
  }
  listVouchers() { return this.call('/v1/vouchers') }
  runOcr(id: string) { return this.call(`/v1/vouchers/${id}/ocr`, { method: 'POST' }) }
  review(id: string, corrections: Record<string, unknown>) {
    return this.call(`/v1/vouchers/${id}/review`, {
      method: 'POST', body: JSON.stringify({ corrections }) })
  }
  draftJournal(id: string) { return this.call(`/v1/vouchers/${id}/journal-draft`, { method: 'POST' }) }
  confirmJournal(id: string) { return this.call(`/v1/vouchers/${id}/journal-confirm`, { method: 'POST' }) }
  runRules() { return this.call('/v1/rule-runs', { method: 'POST' }) }
  findings() { return this.call('/v1/findings') }
  integrity() { return this.call('/v1/integrity') }
  exportReportUrl() { return this.base.replace(/\/$/, '') + '/v1/exports/report' }
}

export function apply(ctx: Context, config: Config = {}) {
  const base = config.baseUrl ?? process.env.ZHANZHEN_BASE_URL ?? 'http://127.0.0.1:8000'
  const client = new ZhanZhenClient(base, config.token)

  // 注册工具：凭证箱总览
  ctx.effect(() => {
    ctx.command('zz.vouchers', '查看湛箴凭证箱（全部凭证与状态）')
      .action(async () => {
        const list = await client.listVouchers()
        if (!Array.isArray(list) || list.length === 0) return '凭证箱为空'
        return list.map(v =>
          `[${String(v.voucher_id).slice(0, 8)}] ${v.state} ${v.date ?? '-'} ` +
          `${v.counterparty ?? '-'} ¥${v.amount_incl_tax ?? '-'}`).join('\n')
      })

    ctx.command('zz.ocr <voucherId>', '对指定凭证执行 OCR 识别')
      .action(async (_args, voucherId: string) => {
        const r = await client.runOcr(voucherId)
        const txn = r?.voucher_json?.transaction ?? {}
        return `识别完成(${r.state})：日期=${txn.date ?? '-'} 含税=${txn.amount_incl_tax ?? '-'} ` +
               `对手=${r?.voucher_json?.counterparty?.name ?? '-'}`
      })

    ctx.command('zz.review <voucherId> [field=value]', '覆核修正字段，如 zz.review <id> counterparty.name=甲公司')
      .action(async (_args, voucherId: string, kv?: string) => {
        const corrections: Record<string, unknown> = {}
        if (kv) {
          const [k, v] = kv.split('=')
          corrections[k] = isNaN(Number(v)) ? v : Number(v)
        }
        await client.review(voucherId, corrections)
        return `已记录覆核修正并批准: ${voucherId}`
      })

    ctx.command('zz.journal <voucherId>', '生成并确认分录（草稿→确认）')
      .action(async (_args, voucherId: string) => {
        const d = await client.draftJournal(voucherId)
        const lines = (d.lines ?? []).map((l: any) =>
          `  ${l.account} 借${l.debit} / 贷${l.credit}`).join('\n')
        const c = await client.confirmJournal(voucherId)
        return `分录已确认 ${c.entry_id.slice(0, 8)}:\n${lines}\nlines_hash=${c.lines_hash.slice(0, 16)}…`
      })

    ctx.command('zz.rules', '运行三条 MVP 审计规则并列出命中')
      .action(async () => {
        const r = await client.runRules()
        const fs = r.findings ?? []
        if (!fs.length) return '无风险命中'
        return fs.map((f: any) => `[${f.severity}] ${f.rule_id}: ${f.explanation}`).join('\n')
      })

    ctx.command('zz.report', '导出可追溯 HTML 报告并返回链接')
      .action(async () => `报告下载: ${client.exportReportUrl()}（浏览器打开即存）`)

    ctx.command('zz.integrity', '校验证据哈希链完整性')
      .action(async () => {
        const r = await client.integrity()
        return (r.chain_ok ? '✔ 链完整' : '✘ 链损坏: ' + (r.errors ?? []).join('; '))
          + `（共 ${r.event_count} 条事件）`
      })
  })
}
