import type { ReactNode } from 'react'
import type { Status } from '../types'

export const STATUS_COLOR: Record<string, string> = {
  succeeded: 'var(--ok)', failed: 'var(--err)', skipped: 'var(--dim)', pending: 'var(--dim)', running: 'var(--accent)',
  degraded: 'var(--warn)',
}

export function StatusChip({ status, sim }: { status: string; sim?: boolean }) {
  const cls = status === 'succeeded' ? 'ok' : status === 'failed' ? 'err' : status === 'degraded' ? 'warn'
    : status === 'running' ? 'info' : ''
  return (
    <span className={`chip ${cls}`}>
      <i className={`status-dot dot-${status === 'succeeded' ? 'ok' : status === 'failed' ? 'err'
        : status === 'degraded' ? 'warn' : status === 'running' ? 'run' : 'dim'}`} />
      {status}
      {sim && <span style={{ opacity: .8 }}>· simulated</span>}
    </span>
  )
}

export function Json({ value, tall, empty = '—' }: { value: any; tall?: boolean; empty?: string }) {
  if (value === undefined || value === null) return <pre className="code">{empty}</pre>
  return <pre className={`code${tall ? ' tall' : ''}`}>{typeof value === 'string' ? value : JSON.stringify(value, null, 2)}</pre>
}

export function Section({ title, right, children }: { title: string; right?: ReactNode; children: ReactNode }) {
  return (
    <div className="panel-section">
      <div className="section-title"><span>{title}</span>{right}</div>
      {children}
    </div>
  )
}

export function Empty({ icon = '◌', title, children }: { icon?: string; title: string; children?: ReactNode }) {
  return (
    <div className="empty">
      <div className="big">{icon}</div>
      <div style={{ color: 'var(--muted)', fontWeight: 600, marginBottom: 4 }}>{title}</div>
      <div>{children}</div>
    </div>
  )
}

export function Banner({ kind = 'info', children }: { kind?: 'info' | 'warn' | 'err' | 'ok'; children: ReactNode }) {
  const icon = kind === 'warn' ? '⚠' : kind === 'err' ? '✕' : kind === 'ok' ? '✓' : 'ℹ'
  return <div className={`banner ${kind}`}><span style={{ flex: 'none' }}>{icon}</span><div>{children}</div></div>
}

export function Diff({ before, after }: { before: any; after: any }) {
  const b = typeof before === 'string' ? before : JSON.stringify(before, null, 2)
  const a = typeof after === 'string' ? after : JSON.stringify(after, null, 2)
  return (
    <div className="diff">
      {b.split('\n').map((l, i) => <div key={`b${i}`} className="row del">− {l}</div>)}
      {a.split('\n').map((l, i) => <div key={`a${i}`} className="row add">+ {l}</div>)}
    </div>
  )
}

export function Metric({ label, value, hint, tone }: { label: string; value: ReactNode; hint?: string; tone?: 'ok' | 'err' | 'warn' }) {
  return (
    <div className="card" style={{ padding: '8px 10px', flex: 1, minWidth: 0 }}>
      <div className="dim" style={{ fontSize: 10, textTransform: 'uppercase', letterSpacing: '.06em' }}>{label}</div>
      <div style={{ fontSize: 16, fontWeight: 650, marginTop: 2, color: tone === 'ok' ? 'var(--ok)' : tone === 'err' ? 'var(--err)' : tone === 'warn' ? 'var(--warn)' : undefined }}>
        {value}
      </div>
      {hint && <div className="dim" style={{ fontSize: 10, marginTop: 1 }}>{hint}</div>}
    </div>
  )
}

export function fmtMs(ms: number | null | undefined) {
  if (ms === null || ms === undefined) return '—'
  return ms >= 1000 ? `${(ms / 1000).toFixed(2)}s` : `${Math.round(ms)}ms`
}

export function nodeGlyph(t: string) {
  return ({ input: 'IN', llm: 'AI', transform: 'TR', validator: 'VL', condition: 'IF', http: 'HT', failure_sim: 'FX', output: 'OUT' } as any)[t] || '?'
}

export function nodeColor(t: string) {
  return ({ input: '#5cc8e8', llm: '#8b7bff', transform: '#f5b544', validator: '#3ecf8e', condition: '#ff9f5a', http: '#6aa6ff', failure_sim: '#ff6b6b', output: '#9aa6b6' } as any)[t] || '#9aa6b6'
}

export function summarizeOutput(v: any): string {
  if (v === undefined || v === null) return ''
  if (typeof v === 'string') return v.slice(0, 160)
  try {
    const s = JSON.stringify(v)
    return s.length > 160 ? s.slice(0, 160) + '…' : s
  } catch { return String(v) }
}

export type StepLike = { status: Status }
