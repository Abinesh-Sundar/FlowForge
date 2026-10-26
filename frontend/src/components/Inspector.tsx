import { Banner, Json, Metric, Section, StatusChip, fmtMs } from './ui'
import type { Step, Trace } from '../types'

export function NodeInspector({ step, onDiagnose }: { step: Step | null; onDiagnose?: () => void }) {
  if (!step) {
    return (
      <div className="empty">
        <div className="big">◈</div>
        Select a node in the timeline or on the canvas to inspect its inputs, outputs and errors.
      </div>
    )
  }
  const u = step.meta?.usage
  const raw = step.meta?.raw_output
  return (
    <div className="stack" style={{ gap: 13 }}>
      <div className="row between">
        <div>
          <div style={{ fontWeight: 600 }}>{step.label}</div>
          <div className="dim mono" style={{ fontSize: 10.5 }}>{step.node_id} · {step.type}</div>
        </div>
        <StatusChip status={step.status} sim={step.simulated} />
      </div>

      <div className="row" style={{ gap: 6 }}>
        <Metric label="Duration" value={fmtMs(step.duration_ms)} />
        <Metric label="Output" value={step.handle ? step.handle : '—'} hint="handle taken" />
        {u ? <Metric label="Tokens" value={u.input_tokens + u.output_tokens} hint={`${u.input_tokens} in / ${u.output_tokens} out`} />
          : <Metric label="Tokens" value="n/a" hint="not reported" />}
      </div>

      {step.error && (
        <Section title="Error">
          <Banner kind={step.error.simulated ? 'warn' : 'err'}>
            <b>{step.error.type}</b>{step.error.simulated ? ' · simulated failure' : ' · real failure'}<br />
            {step.error.message}
          </Banner>
          {step.error.details?.errors && (
            <table className="table">
              <thead><tr><th>Field</th><th>Code</th><th>Expected</th><th>Actual</th></tr></thead>
              <tbody>
                {step.error.details.errors.map((e: any, i: number) => (
                  <tr key={i}>
                    <td className="mono">{e.field}</td>
                    <td>{e.code}</td>
                    <td className="mono dim">{String(e.expected ?? '—')}</td>
                    <td className="mono" style={{ color: 'var(--err)' }}>{String(e.actual ?? '—')}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {onDiagnose && (
            <button className="btn primary block" onClick={onDiagnose}>Diagnose this failure →</button>
          )}
        </Section>
      )}

      {step.meta?.scenario_fault && (
        <Banner kind="warn">
          Scenario fault injected here: <b>{step.meta.scenario_fault.kind}</b>.{' '}
          {(step.meta.scenario_fault.notes || []).join(' · ')}
        </Banner>
      )}

      {step.meta?.mocked && (
        <Banner kind="info">Mock model output — deterministic stand-in, token usage and cost are unavailable.</Banner>
      )}

      <Section title="Input">
        <Json value={step.input} />
      </Section>

      {raw && (
        <Section title={step.meta?.mocked ? 'Raw model output (mock)' : 'Raw model output'}>
          <Json value={raw} />
        </Section>
      )}

      <Section title="Output">
        <Json value={step.output} />
      </Section>

      <Section title="Node metadata">
        <Json value={step.meta} />
      </Section>
    </div>
  )
}

export function TraceHeader({ trace }: { trace: Trace }) {
  return (
    <div className="card flat" style={{ padding: 10 }}>
      <div className="row between" style={{ marginBottom: 8 }}>
        <div className="row" style={{ gap: 7 }}>
          <StatusChip status={trace.status} />
          {trace.scenario && <span className="chip sim">WhatIf: {trace.scenario.name}</span>}
          <span className={`chip ${trace.llm_mode === 'live' ? 'info' : ''}`}>
            {trace.llm_mode === 'live'
              ? (trace.steps?.find((s) => s.meta?.provider)?.meta?.provider
                  ? `${trace.steps.find((s) => s.meta?.provider)?.meta?.provider.replace(' API', '')} live`
                  : 'live')
              : 'mock model'}
          </span>
        </div>
        <span className="dim mono" style={{ fontSize: 10 }}>{fmtMs(trace.duration_ms)}</span>
      </div>
      <div className="row between">
        <span className="dim mono" style={{ fontSize: 10.5 }}>{trace.execution_id}</span>
        <span className="dim" style={{ fontSize: 10.5 }}>v{trace.workflow_version} · {trace.started_at}</span>
      </div>
      {trace.summary && (
        <div className="row" style={{ gap: 12, marginTop: 8, fontSize: 11, color: 'var(--muted)' }}>
          <span><span className="dot-ok status-dot" /> {trace.summary.nodes_succeeded} ok</span>
          <span><span className="dot-err status-dot" /> {trace.summary.nodes_failed} failed</span>
          <span><span className="dot-dim status-dot" /> {trace.summary.nodes_skipped} skipped</span>
          {trace.summary.handled_failure && <span className="chip warn">error handler engaged</span>}
        </div>
      )}
    </div>
  )
}
