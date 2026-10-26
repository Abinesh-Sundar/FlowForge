import { useEffect, useState } from 'react'
import { Banner, Section } from './ui'
import { NODE_META } from '../workflow'
import type { WFNode } from '../types'

const GOOD_SAMPLE = {
  document: 'ACME INDUSTRIAL SUPPLY\nInvoice No: INV-2041\nVendor: Acme Industrial Supply\nDate: 03/14/2025\nTotal Due: $1,250.00\nTerms: Net 30\n',
  source: 'ap-inbox',
  received_at: '2025-03-17T09:12:00Z',
}
const BAD_SAMPLE = {
  document: 'NORTHWIND PARTS LTD\nInvoice No: INV-2042\nVendor: Northwind Parts Ltd\nDate: 03/15/2025\nTerms: Net 30\n',
  source: 'ap-inbox',
  received_at: '2025-03-18T08:40:00Z',
}

function JsonField({ label, value, onChange, rows = 6 }: { label: string; value: any; onChange: (v: any) => void; rows?: number }) {
  const [text, setText] = useState(() => JSON.stringify(value, null, 2))
  const [err, setErr] = useState<string | null>(null)
  useEffect(() => { setText(JSON.stringify(value, null, 2)); setErr(null) }, [JSON.stringify(value)])
  return (
    <label className="field">
      <span className="row between"><span>{label}</span>{err && <span style={{ color: 'var(--err)' }}>invalid JSON</span>}</span>
      <textarea
        rows={rows}
        value={text}
        spellCheck={false}
        onChange={(e) => {
          setText(e.target.value)
          try { onChange(JSON.parse(e.target.value)); setErr(null) } catch { setErr('invalid') }
        }}
      />
    </label>
  )
}

export default function NodeConfig({ node, onChange, onDelete, onDuplicate }: {
  node: WFNode
  onChange: (n: WFNode) => void
  onDelete: () => void
  onDuplicate: () => void
}) {
  const set = (patch: Record<string, any>) => onChange({ ...node, config: { ...node.config, ...patch } })
  const meta = NODE_META[node.type]
  const c = node.config || {}

  return (
    <div className="stack" style={{ gap: 12 }}>
      <div className="row between">
        <div className="row" style={{ gap: 8 }}>
          <span className="chip">{meta.kind}</span>
          <span className="dim mono" style={{ fontSize: 10.5 }}>{node.id}</span>
        </div>
        <div className="row" style={{ gap: 4 }}>
          <button className="btn ghost sm" onClick={onDuplicate} title="Duplicate node">Duplicate</button>
          <button className="btn danger sm" onClick={onDelete}>Delete</button>
        </div>
      </div>

      <label className="field">
        <span>Node label</span>
        <input type="text" value={node.label} onChange={(e) => onChange({ ...node, label: e.target.value })} />
      </label>

      {node.type === 'input' && (
        <>
          <JsonField label="Sample JSON payload" value={c.sample} onChange={(v) => set({ sample: v })} rows={8} />
          <div className="row" style={{ gap: 6 }}>
            <button className="btn sm" onClick={() => set({ sample: GOOD_SAMPLE })}>Load valid invoice</button>
            <button className="btn sm" onClick={() => set({ sample: BAD_SAMPLE })}>Load failing invoice</button>
          </div>
          <div className="card-sub">The payload this workflow starts with when no run payload is supplied.</div>
        </>
      )}

      {node.type === 'llm' && (
        <>
          <label className="field">
            <span>Prompt</span>
            <textarea rows={7} value={c.prompt || ''} onChange={(e) => set({ prompt: e.target.value })} />
          </label>
          <div className="row" style={{ gap: 8 }}>
            <label className="field grow">
              <span>Output parsing</span>
              <select value={c.output || 'json'} onChange={(e) => set({ output: e.target.value })}>
                <option value="json">Parse as JSON (fails on malformed output)</option>
                <option value="text">Pass raw text through</option>
              </select>
            </label>
            <label className="field" style={{ width: 120 }}>
              <span>Timeout (ms)</span>
              <input type="number" value={c.timeout_ms ?? 30000} onChange={(e) => set({ timeout_ms: Number(e.target.value) })} />
            </label>
          </div>
          <div className="card-sub">
            Mock mode uses a deterministic extractor whose format follows your prompt (e.g. asking for numbers makes
            amounts numeric). Live mode calls the configured model with the server-side key.
          </div>
        </>
      )}

      {node.type === 'validator' && (
        <>
          <JsonField label="Rules" value={c.rules} onChange={(v) => set({ rules: v })} rows={10} />
          <div className="card-sub mono" style={{ fontSize: 10.5 }}>
            field · type (string|number|integer|boolean|object|array) · required · pattern · min · max · not_in
          </div>
        </>
      )}

      {node.type === 'condition' && (
        <div className="stack" style={{ gap: 8 }}>
          <label className="field"><span>Field path</span>
            <input type="text" value={c.field || ''} onChange={(e) => set({ field: e.target.value })} placeholder="amount" />
          </label>
          <div className="row" style={{ gap: 8 }}>
            <label className="field grow"><span>Operator</span>
              <select value={c.operator || '=='} onChange={(e) => set({ operator: e.target.value })}>
                {['==', '!=', '>', '>=', '<', '<=', 'exists', 'contains'].map((o) => <option key={o}>{o}</option>)}
              </select>
            </label>
            <label className="field grow"><span>Value</span>
              <input type="text" value={c.value ?? ''} onChange={(e) => {
                const raw = e.target.value
                const num = Number(raw)
                set({ value: raw.trim() !== '' && !Number.isNaN(num) ? num : raw })
              }} />
            </label>
          </div>
          <div className="card-sub">Routes to the <b style={{ color: 'var(--ok)' }}>true</b> or <b style={{ color: 'var(--warn)' }}>false</b> handle. Both branches may be connected.</div>
        </div>
      )}

      {node.type === 'transform' && (
        <>
          <JsonField label="Operations" value={c.ops} onChange={(v) => set({ ops: v })} rows={10} />
          <div className="card-sub mono" style={{ fontSize: 10.5 }}>
            {`{"op":"pick","fields":[...]} · omit · set(field,value|from) · rename(from,to) · to_number(field) · uppercase/lowercase(field)`}
          </div>
        </>
      )}

      {node.type === 'http' && (
        <>
          <div className="row" style={{ gap: 8 }}>
            <label className="field" style={{ width: 100 }}>
              <span>Method</span>
              <select value={c.method || 'POST'} onChange={(e) => set({ method: e.target.value })}>
                {['GET', 'POST'].map((m) => <option key={m}>{m}</option>)}
              </select>
            </label>
            <label className="field grow"><span>URL</span>
              <input type="text" value={c.url || ''} onChange={(e) => set({ url: e.target.value })} />
            </label>
          </div>
          <label className="field" style={{ width: 140 }}><span>Timeout (ms)</span>
            <input type="number" value={c.timeout_ms ?? 5000} onChange={(e) => set({ timeout_ms: Number(e.target.value) })} />
          </label>
          <Banner kind="info">
            Only <span className="mono">mock://</span> URLs and hosts in <span className="mono">FLOWFORGE_HTTP_ALLOWLIST</span> are
            reachable. Public HTTPS only — private and loopback addresses are blocked. Mock endpoints: <span className="mono">mock://erp/invoices</span>,
            <span className="mono"> mock://status/500</span>, <span className="mono">mock://empty</span>.
          </Banner>
        </>
      )}

      {node.type === 'failure_sim' && (
        <>
          <label className="field"><span>Failure to inject</span>
            <select value={c.failure || 'http_500'} onChange={(e) => set({ failure: e.target.value })}>
              {['missing_field', 'wrong_type', 'wrong_value', 'malformed_json', 'empty_response', 'http_500', 'timeout', 'fail_validation']
                .map((f) => <option key={f}>{f}</option>)}
            </select>
          </label>
          <label className="field"><span>Field (for data faults)</span>
            <input type="text" value={c.field || ''} onChange={(e) => set({ field: e.target.value })} placeholder="amount" />
          </label>
          <label className="row" style={{ gap: 7, fontSize: 12 }}>
            <input type="checkbox" checked={c.enabled !== false} onChange={(e) => set({ enabled: e.target.checked })} style={{ width: 'auto' }} />
            Enabled — when disabled the node is a pass-through
          </label>
          <div className="card-sub">A Failure Simulator node injects a fault into the payload without modifying the upstream nodes, so the rest of the graph runs its real code path.</div>
        </>
      )}

      {node.type === 'output' && (
        <div className="row" style={{ gap: 8 }}>
          <label className="field grow"><span>Outcome</span>
            <select value={c.outcome || 'success'} onChange={(e) => set({ outcome: e.target.value })}>
              {['success', 'review', 'error'].map((o) => <option key={o}>{o}</option>)}
            </select>
          </label>
          <label className="field grow"><span>Note</span>
            <input type="text" value={c.note || ''} onChange={(e) => set({ note: e.target.value })} />
          </label>
        </div>
      )}

      <div className="divider" />
      <Section title="Raw config">
        <JsonField label="" value={c} onChange={(v) => onChange({ ...node, config: v })} rows={6} />
      </Section>
    </div>
  )
}
