import { useEffect, useRef } from 'react'
import { Banner, Diff, Empty, Metric, Section, StatusChip } from './ui'
import type { Diagnosis, Proposal, Trace, VerifyResult } from '../types'

export function DoctorPanel({ trace, diagnosis, busy, live, onLiveChange, onDiagnose, proposal, onSelectProposal,
  onApprove, onReject, verify, verifyBusy, canLive, sourceTrace }: {
  trace: Trace | null
  sourceTrace: Trace | null
  diagnosis: Diagnosis | null
  busy: boolean
  live: boolean
  onLiveChange: (v: boolean) => void
  canLive: boolean
  onDiagnose: () => void
  proposal: Proposal | null
  onSelectProposal: (p: Proposal) => void
  onApprove: () => void
  onReject: () => void
  verify: VerifyResult | null
  verifyBusy: boolean
}) {
  const verifyRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (verify) verifyRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }, [verify])
  return (
    <div className="stack" style={{ gap: 13 }}>
      <div>
        <div style={{ fontWeight: 600 }}>AI Workflow Doctor</div>
        <div className="card-sub">Diagnose the selected trace, review a proposed change, approve it, then verify with
          regression tests. Nothing is applied automatically.</div>
      </div>

      <div className="card flat">
        <div className="row between">
          <span className="small">{trace ? <>Target: <span className="mono">{trace.execution_id}</span></> : 'No trace selected'}</span>
          <StatusChip status={trace?.status || 'pending'} />
        </div>
        {trace && (
          <button className="btn ghost sm" style={{ marginTop: 6, paddingLeft: 0 }} onClick={() => navigator.clipboard?.writeText(trace.execution_id)}>
            copy execution id
          </button>
        )}
      </div>

      <div className="row between">
        <label className="row" style={{ gap: 6, fontSize: 11.5, color: canLive ? 'var(--muted)' : 'var(--dim)' }}>
          <input type="checkbox" checked={live} disabled={!canLive} onChange={(e) => onLiveChange(e.target.checked)} style={{ width: 'auto' }} />
          Use live model diagnosis
        </label>
        <span className={`chip ${live ? 'info' : ''}`}>{live ? 'Claude' : 'deterministic'}</span>
      </div>
      {!canLive && <div className="dim small">No API key on the server — deterministic diagnosis is used and clearly labelled.</div>}

      <button className="btn primary block" disabled={!trace || busy} onClick={() => onDiagnose()}>
        {busy ? <><span className="spinner" /> Analysing trace…</> : trace ? 'Diagnose this execution' : 'Select a failing execution first'}
      </button>

      {!diagnosis && !busy && (
        <Empty icon="✚" title="No diagnosis yet">
          Run the workflow, select an execution, then diagnose it. The Doctor cites concrete evidence from the trace.
        </Empty>
      )}

      {diagnosis && (
        <div className="stack" style={{ gap: 11 }}>
          <div className="row between">
            <span className={`chip ${diagnosis.source === 'claude' ? 'info' : ''}`}>{diagnosis.label}</span>
            <span className="chip">{diagnosis.confidence} confidence</span>
          </div>

          {diagnosis.fallback_reason && <Banner kind="warn">{diagnosis.fallback_reason}</Banner>}

          <div className="card">
            <div className="section-title">Likely cause</div>
            <div style={{ fontSize: 12, lineHeight: 1.55 }}>{diagnosis.summary}</div>
            {diagnosis.failed_node_label && <div className="dim small" style={{ marginTop: 5 }}>Failing node: <b style={{ color: 'var(--muted)' }}>{diagnosis.failed_node_label}</b></div>}
          </div>

          <Section title="Evidence">
            <div className="stack" style={{ gap: 6 }}>
              {diagnosis.evidence.map((e, i) => (
                <div key={i} className="card" style={{ padding: '8px 10px' }}>
                  <div className="row between">
                    <span className="mono dim" style={{ fontSize: 10 }}>{e.source}{e.node ? ` · ${e.node}` : ''}</span>
                  </div>
                  <div style={{ fontSize: 11.5, marginTop: 3 }}>{e.fact}</div>
                  {e.detail && <div className="mono dim" style={{ fontSize: 10.5, marginTop: 3, whiteSpace: 'pre-wrap', maxHeight: 120, overflow: 'auto' }}>{String(e.detail)}</div>}
                </div>
              ))}
            </div>
          </Section>

          {diagnosis.source === 'claude' && diagnosis.usage && (
            <div className="row" style={{ gap: 6 }}>
              <Metric label="Model" value={<span className="mono" style={{ fontSize: 11 }}>{diagnosis.model}</span>} />
              <Metric label="Tokens" value={diagnosis.usage.input_tokens + diagnosis.usage.output_tokens}
                hint={`${diagnosis.usage.input_tokens} in / ${diagnosis.usage.output_tokens} out`} />
              <Metric label="Est. cost" value={diagnosis.cost_usd != null ? `$${diagnosis.cost_usd.toFixed(4)}` : 'n/a'} hint="estimated" />
            </div>
          )}

          {diagnosis.disclaimer && <Banner kind="info">{diagnosis.disclaimer}</Banner>}

          <Section title="Proposed fixes">
            {!diagnosis.proposals.length && <div className="card-sub">No safe configuration change was identified for this failure type.</div>}
            <div className="stack" style={{ gap: 7 }}>
              {diagnosis.proposals.map((p) => (
                <button key={p.id} className={`scenario-item${proposal?.id === p.id ? ' active' : ''}`} onClick={() => onSelectProposal(p)}>
                  <div className="row between">
                    <span className="nm">{p.title}</span>
                    {p.recommended && <span className="chip ok">recommended</span>}
                  </div>
                  <span className="sub">risk: {p.risk} · {p.target_node_label}</span>
                </button>
              ))}
            </div>
          </Section>

          {proposal && (
            <div className="stack" style={{ gap: 9 }}>
              <div className="card">
                <div className="card-title">{proposal.title}</div>
                <div className="card-sub">{proposal.summary}</div>
                <div className="row" style={{ gap: 6, marginTop: 7 }}>
                  <span className={`chip ${proposal.risk === 'high' ? 'err' : proposal.risk === 'medium' ? 'warn' : 'ok'}`}>risk {proposal.risk}</span>
                  <span className="chip">{proposal.confidence} confidence</span>
                </div>
              </div>
              {proposal.diff.map((d, i) => (
                <div key={i}>
                  <div className="section-title">{d.config_key}</div>
                  <Diff before={d.before} after={d.after} />
                </div>
              ))}
              <div className="card-sub">Expected effect: {proposal.expected_effect}</div>
              <div className="btn-row">
                <button className="btn primary grow" disabled={!!verify || verifyBusy} onClick={onApprove}>
                  {verify ? 'Applied ✓' : 'Approve & apply as new version'}
                </button>
                <button className="btn" disabled={!!verify} onClick={onReject}>Reject</button>
              </div>
              <div className="dim small">Applying creates workflow version v{(sourceTrace?.workflow_version ?? 1) + 1}; the original is preserved.</div>
            </div>
          )}
        </div>
      )}

      {verify && (
        <div className="stack" style={{ gap: 10 }} ref={verifyRef}>
          <div className="divider" />
          <div className="row between">
            <div style={{ fontWeight: 600 }}>Regression verification</div>
            <span className={`chip ${verify.ok ? 'ok' : verify.comparison.improved ? 'warn' : 'err'}`}>
              {verify.comparison.after_passed}/{verify.comparison.total}
            </span>
          </div>
          <Banner kind={verify.ok ? 'ok' : verify.comparison.improved ? 'warn' : 'err'}>
            {verify.comparison.summary}
            {verify.comparison.regressed && ' A previously passing check now fails.'}
          </Banner>
          <table className="table">
            <thead><tr><th>Check</th><th>Before</th><th>After</th></tr></thead>
            <tbody>
              {verify.comparison.rows.map((r, i) => (
                <tr key={i}>
                  <td>{r.name}</td>
                  <td><span className={`chip ${r.before === 'PASS' ? 'ok' : 'err'}`}>{r.before}</span></td>
                  <td><span className={`chip ${r.after === 'PASS' ? 'ok' : 'err'}`}>{r.after}</span>
                    {r.changed && <span className="dim" style={{ fontSize: 10, marginLeft: 5 }}>changed</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {verify.repair_execution_id && (
            <div className="dim small">Repaired trace: <span className="mono">{verify.repair_execution_id}</span></div>
          )}
          {verify.remaining_failures.length > 0 && (
            <Banner kind="warn">Still failing: {verify.remaining_failures.join(', ')}</Banner>
          )}
        </div>
      )}

      {verifyBusy && (
        <div className="row small" style={{ color: 'var(--muted)' }}>
          <span className="spinner" /> Running the regression suite on the repaired workflow…
        </div>
      )}
    </div>
  )
}
