import { Banner, Empty, Json, StatusChip, fmtMs } from './ui'
import type { Scenario, SimResult, Trace } from '../types'

export function WhatIfPanel({ scenarios, result, runTrace, busy, selected, onSelect, onRun, onRunAll, allResults, onOpenTrace }: {
  scenarios: Scenario[]
  result: SimResult | null
  runTrace: Trace | null
  busy: boolean
  selected: string | null
  onSelect: (id: string) => void
  onRun: (id: string) => void
  onRunAll: () => void
  allResults: Record<string, SimResult>
  onOpenTrace: (t: Trace) => void
}) {
  const ranAll = Object.keys(allResults).length
  return (
    <div className="stack" style={{ gap: 13 }}>
      <div className="row between">
        <div>
          <div style={{ fontWeight: 600 }}>WhatIf AI — failure simulation</div>
          <div className="card-sub">Faults are applied on the server through the real node code path, and judged by
            deterministic expectations rather than a model.</div>
        </div>
      </div>

      <div className="btn-row">
        <button className="btn primary" disabled={busy || !scenarios.length} onClick={onRunAll}>
          {busy ? <><span className="spinner" /> Running…</> : `Run all ${scenarios.length} scenarios`}
        </button>
        {ranAll > 0 && (
          <>
            <span className="chip ok">{Object.values(allResults).filter((r) => r.passed).length} pass</span>
            {Object.values(allResults).filter((r) => !r.passed && !r.blocked).length > 0 && (
              <span className="chip err">{Object.values(allResults).filter((r) => !r.passed && !r.blocked).length} fail</span>
            )}
            {Object.values(allResults).filter((r) => r.blocked).length > 0 && (
              <span className="chip warn" title="An earlier failure stopped the fault from reaching its target">
                {Object.values(allResults).filter((r) => r.blocked).length} blocked
              </span>
            )}
          </>
        )}
      </div>

      {!scenarios.length && <Empty title="No scenarios available">Add an LLM, Validator or HTTP node to generate scenarios.</Empty>}

      <div className="stack" style={{ gap: 6 }}>
        {scenarios.map((s) => {
          const r = allResults[s.id]
          return (
            <div key={s.id} style={{ display: 'flex', gap: 6 }}>
              <button className={`scenario-item${selected === s.id ? ' active' : ''}`} onClick={() => { onSelect(s.id); onRun(s.id) }}>
                <div className="row between">
                  <span className="nm">{s.name}</span>
                  {r && <span className={`chip ${r.passed ? 'ok' : r.blocked ? 'warn' : 'err'}`}>{r.passed ? 'pass' : r.blocked ? 'blocked' : 'fail'}</span>}
                </div>
                <span className="sub">{s.target_label || s.target_node_id} · {s.kind}</span>
              </button>
            </div>
          )
        })}
      </div>

      {result && (
        <div className="stack" style={{ gap: 11 }}>
          <div className="divider" />
          <div className="row between">
            <div style={{ fontWeight: 600 }}>{result.scenario.name}</div>
            <StatusChip status={result.passed ? 'succeeded' : 'failed'} />
          </div>

          {result.blocked && <Banner kind="warn"><b>Blocked:</b> {result.blocked_reason}</Banner>}

          <div className="card">
            <div className="section-title">Expected</div>
            <div className="card-sub" style={{ color: 'var(--muted)' }}>{result.expected_behavior}</div>
          </div>
          <div className="card">
            <div className="section-title">Actual</div>
            <div className="card-sub" style={{ color: 'var(--muted)' }}>
              Run status <b>{result.actual_behavior.status}</b>
              {result.actual_behavior.failing_node && <> · failed at <b>{result.actual_behavior.failing_node}</b></>}
              {result.actual_behavior.error && <><br />{result.actual_behavior.error}</>}
            </div>
          </div>

          <table className="table">
            <thead><tr><th>Check</th><th>Expected</th><th>Actual</th><th /></tr></thead>
            <tbody>
              {result.checks.map((c, i) => (
                <tr key={i}>
                  <td>{c.check}</td>
                  <td className="mono dim">{c.detail ?? String(c.expected ?? '—')}</td>
                  <td className="mono">{String(c.actual ?? '—')}</td>
                  <td><span className={`chip ${c.pass ? 'ok' : 'err'}`}>{c.pass ? '✓' : '✕'}</span></td>
                </tr>
              ))}
            </tbody>
          </table>

          <Banner kind="warn">{result.distinction}</Banner>

          <div className="row between">
            <span className="dim" style={{ fontSize: 11 }}>Trace {result.trace.execution_id} · {fmtMs(result.trace.duration_ms)}</span>
            <button className="btn sm" onClick={() => onOpenTrace(result.trace)}>Open in Black Box →</button>
          </div>
        </div>
      )}

      {!result && runTrace && <Banner kind="info">Select a scenario to simulate it against the current workflow.</Banner>}
    </div>
  )
}

export function ExecutionsPanel({ executions, onOpen, activeId }: {
  executions: any[]
  onOpen: (id: string) => void
  activeId?: string | null
}) {
  if (!executions.length) {
    return <Empty title="No executions yet">Run the workflow to record an execution trace.</Empty>
  }
  return (
    <div className="stack" style={{ gap: 6 }}>
      {executions.map((e) => (
        <button key={e.id} className={`scenario-item${activeId === e.id ? ' active' : ''}`} onClick={() => onOpen(e.id)}>
          <div className="row between">
            <span className="nm mono" style={{ fontSize: 10.5 }}>{e.id}</span>
            <span className={`chip ${e.status === 'succeeded' ? 'ok' : e.status === 'degraded' ? 'warn' : 'err'}`}>{e.status}</span>
          </div>
          <span className="sub">
            {e.scenario_name ? `WhatIf · ${e.scenario_name}` : 'Manual run'} · v{e.workflow_version} · {fmtMs(e.duration_ms)}
          </span>
        </button>
      ))}
    </div>
  )
}

export function CompareJson({ before, after }: { before: any; after: any }) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
      <div><div className="section-title">Before</div><Json value={before} /></div>
      <div><div className="section-title">After</div><Json value={after} /></div>
    </div>
  )
}
