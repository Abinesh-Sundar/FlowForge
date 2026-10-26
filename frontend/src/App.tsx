import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from './api'
import Canvas from './components/Canvas'
import NodeConfig from './components/NodeConfig'
import { NodeInspector, TraceHeader } from './components/Inspector'
import { WhatIfPanel, ExecutionsPanel } from './components/WhatIfPanel'
import { DoctorPanel } from './components/DoctorPanel'
import { Banner, Empty, Json, Metric, Section, StatusChip, fmtMs, nodeColor } from './components/ui'
import { NODE_META, clone } from './workflow'
import type {
  Diagnosis, Health, NodeType, Proposal, Scenario, SimResult, Step, Trace, VerifyResult, WFNode, Workflow,
} from './types'

type Tab = 'config' | 'inspector' | 'whatif' | 'blackbox' | 'doctor'

const TABS: { id: Tab; label: string }[] = [
  { id: 'config', label: 'Configure' },
  { id: 'inspector', label: 'Node' },
  { id: 'whatif', label: 'WhatIf AI' },
  { id: 'blackbox', label: 'Black Box' },
  { id: 'doctor', label: 'Doctor' },
]

export default function App() {
  const [health, setHealth] = useState<Health | null>(null)
  const [workflow, setWorkflow] = useState<Workflow | null>(null)
  const [savedVersion, setSavedVersion] = useState<number>(1)
  const [dirty, setDirty] = useState(false)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [tab, setTab] = useState<Tab>('config')
  const [trace, setTrace] = useState<Trace | null>(null)
  const [selectedStepId, setSelectedStepId] = useState<string | null>(null)
  const [revealCount, setRevealCount] = useState<number | null>(null)
  const [running, setRunning] = useState(false)
  const [llmMode, setLlmMode] = useState<'mock' | 'live'>('mock')
  const [toast, setToast] = useState<{ msg: string; kind: 'ok' | 'err' } | null>(null)
  const [scenarios, setScenarios] = useState<Scenario[]>([])
  const [simResult, setSimResult] = useState<SimResult | null>(null)
  const [simAll, setSimAll] = useState<Record<string, SimResult>>({})
  const [simBusy, setSimBusy] = useState(false)
  const [simSelected, setSimSelected] = useState<string | null>(null)
  const [executions, setExecutions] = useState<any[]>([])
  const [doctorTrace, setDoctorTrace] = useState<Trace | null>(null)
  const [diagnosis, setDiagnosis] = useState<Diagnosis | null>(null)
  const [diagBusy, setDiagBusy] = useState(false)
  const [liveDiag, setLiveDiag] = useState(false)
  const [proposal, setProposal] = useState<Proposal | null>(null)
  const [verify, setVerify] = useState<VerifyResult | null>(null)
  const [verifyBusy, setVerifyBusy] = useState(false)
  const [versions, setVersions] = useState<{ version: number; note: string; created_at: string }[]>([])
  const [panelOpen, setPanelOpen] = useState(true)
  const [bootError, setBootError] = useState<string | null>(null)
  const [booting, setBooting] = useState(true)
  const revealTimer = useRef<number | null>(null)

  const notify = useCallback((msg: string, kind: 'ok' | 'err' = 'ok') => {
    setToast({ msg, kind })
    window.setTimeout(() => setToast(null), 3500)
  }, [])

  const fail = useCallback((e: any) => notify(e?.message || String(e), 'err'), [notify])

  // ---------------------------------------------------------------- boot
  const boot = useCallback(async () => {
    setBooting(true)
    setBootError(null)
    try {
      const h = await api.health()
      setHealth(h)
      setLlmMode(h.llm_mode_default)
      const wf = await api.workflow('wf_invoice_demo')
      setWorkflow(wf)
      setSavedVersion(wf.version)
      setVersions(await api.versions(wf.id))
      setScenarios(await api.scenarios(wf))
      setExecutions(await api.executions(wf.id))
    } catch (e: any) {
      // Surface the failure on screen instead of spinning forever with empty panels behind it.
      setBootError(e?.message || String(e))
    } finally { setBooting(false) }
  }, [])

  useEffect(() => { boot() }, [boot])

  const patchWorkflow = useCallback((wf: Workflow) => { setWorkflow(wf); setDirty(true) }, [])

  const refreshScenarios = useCallback(async (wf: Workflow) => {
    try { setScenarios(await api.scenarios(wf)) } catch (e) { fail(e) }
  }, [fail])

  const refreshExecutions = useCallback(async (wf: Workflow) => {
    try { setExecutions(await api.executions(wf.id)) } catch { /* list is non-critical */ }
  }, [])

  const selectedNode = useMemo(() => workflow?.nodes.find((n) => n.id === selectedId) || null, [workflow, selectedId])
  const selectedStep = useMemo(() => trace?.steps.find((s) => s.node_id === selectedStepId) || null, [trace, selectedStepId])

  // ---------------------------------------------------------------- actions
  const playReveal = useCallback((t: Trace) => {
    if (revealTimer.current) window.clearInterval(revealTimer.current)
    setTrace(t)
    setRevealCount(0)
    let i = 0
    revealTimer.current = window.setInterval(() => {
      i += 1
      setRevealCount(i >= t.steps.length ? null : i)
      if (i >= t.steps.length && revealTimer.current) window.clearInterval(revealTimer.current)
    }, 110)
  }, [])

  const doRun = useCallback(async (traceOverride?: Trace) => {
    if (!workflow) return
    if (traceOverride) { playReveal(traceOverride); return }
    setRunning(true)
    try {
      const t = await api.run(workflow, undefined, llmMode)
      // A fresh run supersedes any earlier trace the Doctor was pointed at.
      setDoctorTrace(null); setDiagnosis(null); setProposal(null); setVerify(null)
      playReveal(t)
      const firstFail = t.steps.find((s) => s.status === 'failed')
      setSelectedStepId(firstFail?.node_id || t.steps[t.steps.length - 1]?.node_id || null)
      setTab('inspector')
      await refreshExecutions(workflow)
      notify(`Run ${t.status} · ${t.steps.filter((s) => s.status === 'succeeded').length}/${t.steps.length} nodes ok`, t.status === 'succeeded' ? 'ok' : 'err')
    } catch (e) { fail(e) } finally { setRunning(false) }
  }, [workflow, llmMode, playReveal, refreshExecutions, notify, fail])

  const doSimulate = useCallback(async (id: string) => {
    if (!workflow) return
    setSimBusy(true)
    setSimSelected(id)
    try {
      const r = await api.simulate(workflow, id, undefined, llmMode)
      setSimResult(r)
      setSimAll((prev) => ({ ...prev, [id]: r }))
      setDoctorTrace(null); setDiagnosis(null); setProposal(null); setVerify(null)
      setTrace(r.trace)
      setRevealCount(null)
      setSelectedStepId(r.trace.steps.find((s) => s.status === 'failed')?.node_id || null)
      await refreshExecutions(workflow)
    } catch (e) { fail(e) } finally { setSimBusy(false) }
  }, [workflow, llmMode, refreshExecutions, fail])

  const doSimulateAll = useCallback(async () => {
    if (!workflow || !scenarios.length) return
    setSimBusy(true)
    const results: Record<string, SimResult> = {}
    try {
      for (const s of scenarios) {
        try {
          results[s.id] = await api.simulate(workflow, s.id, undefined, llmMode)
        } catch { /* per-scenario failure keeps the rest running */ }
      }
      setSimAll(results)
      const all = Object.values(results)
      // Prefer a scenario that actually exercised its fault (not one blocked by an earlier failure),
      // so the trace carried into the Doctor is a meaningful one.
      const chosen = all.find((r) => r.scenario.id === 'val-wrong-type' && !r.blocked)
        || all.find((r) => !r.blocked) || all[0]
      if (chosen) {
        setSimResult(chosen); setSimSelected(chosen.scenario.id); setTrace(chosen.trace); setRevealCount(null)
        setDoctorTrace(null); setDiagnosis(null); setProposal(null); setVerify(null)
      }
      await refreshExecutions(workflow)
      const passed = all.filter((r) => r.passed).length
      const blocked = all.filter((r) => r.blocked).length
      notify(`${passed} pass · ${all.length - passed - blocked} fail · ${blocked} blocked (upstream failure)`,
        all.every((r) => r.passed || r.blocked) ? 'ok' : 'err')
    } finally { setSimBusy(false) }
  }, [workflow, scenarios, llmMode, refreshExecutions, notify])

  const openExecution = useCallback(async (id: string) => {
    try {
      const t = await api.execution(id)
      setDoctorTrace(null); setDiagnosis(null); setProposal(null); setVerify(null)
      setTrace(t)
      setRevealCount(null)
      setSelectedStepId(t.steps.find((s) => s.status === 'failed')?.node_id || null)
      setTab('blackbox')
    } catch (e) { fail(e) }
  }, [fail])

  const doDiagnose = useCallback(async (targetArg?: Trace | null) => {
    if (!workflow) return
    // An explicit target wins over whatever is currently displayed on the canvas.
    const target = targetArg || doctorTrace || trace
    if (!target) { notify('Select an execution first', 'err'); return }
    if (targetArg) setDoctorTrace(targetArg)
    if (!target.steps.some((s) => s.status === 'failed')) {
      notify('This execution has no failing node — run the workflow or a WhatIf scenario first', 'err')
      return
    }
    setDiagBusy(true)
    setDiagnosis(null); setProposal(null); setVerify(null)
    try {
      const d = await api.diagnose(workflow, target.execution_id, liveDiag)
      setDiagnosis(d)
      setProposal(d.proposals.find((p) => p.recommended) || d.proposals[0] || null)
    } catch (e) { fail(e) } finally { setDiagBusy(false) }
  }, [workflow, doctorTrace, trace, liveDiag, notify, fail])

  /** Select a trace and immediately diagnose it — what the "Diagnose this run/execution" buttons promise. */
  const diagnoseTrace = useCallback((t: Trace | null) => {
    setDoctorTrace(t)
    setTab('doctor')
    if (t && t.steps.some((s) => s.status === 'failed')) doDiagnose(t)
    else if (t) notify('This execution has no failing node — nothing to diagnose', 'err')
  }, [doDiagnose, notify])

  const doApprove = useCallback(async () => {
    if (!workflow || !proposal) return
    if (!window.confirm(`Apply "${proposal.title}"?\n\nThis creates a new workflow version. The current version is preserved.`)) return
    setVerifyBusy(true)
    try {
      const applied = await api.apply(workflow, proposal)
      const repaired = applied.workflow
      setWorkflow(repaired)
      setSavedVersion(applied.version)
      setDirty(false)
      setVersions(await api.versions(repaired.id))
      const payload = repaired.nodes.find((n) => n.type === 'input')?.config?.sample
      const v = await api.verify(workflow, repaired, payload, llmMode)
      setVerify(v)
      // Show the repaired workflow actually running, so the canvas reflects the verified state.
      try {
        const repairedRun = await api.run(repaired, payload, llmMode)
        playReveal(repairedRun)
        setSelectedStepId(repairedRun.steps.find((s) => s.status === 'failed')?.node_id
          || repairedRun.steps.find((s) => s.type === 'output')?.node_id || null)
      } catch { /* the verification result is still valid without a fresh canvas run */ }
      await refreshScenarios(repaired)
      await refreshExecutions(repaired)
      notify(v.comparison.improved ? `Verified: ${v.comparison.summary}` : v.comparison.summary, v.ok ? 'ok' : 'err')
    } catch (e) { fail(e) } finally { setVerifyBusy(false) }
  }, [workflow, proposal, llmMode, refreshScenarios, refreshExecutions, notify, fail, playReveal])

  const doReject = useCallback(() => {
    setProposal(null)
    notify('Proposal rejected — no changes were made')
  }, [notify])

  const doSave = useCallback(async () => {
    if (!workflow) return
    try {
      const r = await api.save(workflow)
      setSavedVersion(r.version)
      setDirty(false)
      setVersions(await api.versions(workflow.id))
      notify(`Saved as v${r.version}`)
    } catch (e) { fail(e) }
  }, [workflow, notify, fail])

  const doReset = useCallback(async () => {
    if (!workflow) return
    if (!window.confirm('Reset to the seeded demo workflow? Unsaved canvas changes will be lost (history is kept).')) return
    try {
      const wf = await api.reset(workflow.id)
      setWorkflow(wf)
      setSavedVersion(wf.version)
      setDirty(false)
      setVersions(await api.versions(wf.id))
      setTrace(null); setDoctorTrace(null); setDiagnosis(null); setVerify(null); setProposal(null)
      setSimResult(null); setSimAll({}); setSelectedStepId(null); setRevealCount(null)
      await refreshScenarios(wf)
      notify('Reset to the demo baseline')
    } catch (e) { fail(e) }
  }, [workflow, refreshScenarios, notify, fail])

  const loadVersion = useCallback(async (v: number) => {
    if (!workflow) return
    try {
      const wf = await api.version(workflow.id, v)
      const merged: Workflow = { ...wf, version: v }
      setWorkflow(merged)
      setDirty(true)
      // Scenario ids and fault targets are derived from the graph, so they must follow the loaded version.
      await refreshScenarios(merged)
      notify(`Loaded version v${v} into the canvas (unsaved)`)
    } catch (e) { fail(e) }
  }, [workflow, refreshScenarios, notify, fail])

  // ---------------------------------------------------------------- node ops
  const updateNode = useCallback((node: WFNode) => {
    if (!workflow) return
    patchWorkflow({ ...workflow, nodes: workflow.nodes.map((n) => (n.id === node.id ? node : n)) })
  }, [workflow, patchWorkflow])

  const deleteNode = useCallback((id: string) => {
    if (!workflow) return
    patchWorkflow({
      ...workflow,
      nodes: workflow.nodes.filter((n) => n.id !== id),
      edges: workflow.edges.filter((e) => e.source !== id && e.target !== id),
    })
    setSelectedId((cur) => (cur === id ? null : cur))
  }, [workflow, patchWorkflow])

  const duplicateNode = useCallback((node: WFNode) => {
    if (!workflow) return
    const id = `${node.type}_${Date.now().toString(36).slice(-5)}`
    patchWorkflow({
      ...workflow,
      nodes: [...workflow.nodes, { ...clone(node), id, position: { x: node.position.x + 40, y: node.position.y + 60 } }],
    })
    setSelectedId(id)
  }, [workflow, patchWorkflow])

  const onPaletteDrag = (t: NodeType) => (e: React.DragEvent) => {
    e.dataTransfer.setData('application/flowforge-node', t)
    e.dataTransfer.effectAllowed = 'move'
  }

  const addNodeClick = useCallback((t: NodeType) => {
    if (!workflow) return
    const id = `${t}_${Date.now().toString(36).slice(-5)}`
    const meta = NODE_META[t]
    patchWorkflow({
      ...workflow,
      nodes: [...workflow.nodes, {
        id, type: t, label: meta.label,
        position: { x: 120 + Math.random() * 260, y: 420 + Math.random() * 90 },
        config: clone(meta.config),
      }],
    })
    setSelectedId(id)
    setTab('config')
  }, [workflow, patchWorkflow])

  // ---------------------------------------------------------------- render
  if (!workflow) {
    return (
      <div className="app">
        <div className="topbar"><div className="brand"><div className="brand-mark">F</div><div className="brand-name">FlowForge <span>AI</span></div></div></div>
        <div style={{ display: 'grid', placeItems: 'center', padding: 24 }}>
          {booting ? <div className="row" style={{ gap: 9 }}><span className="spinner" /> <span className="dim">Connecting to the backend…</span></div>
            : <div className="stack" style={{ maxWidth: 560, gap: 12 }}>
                <Banner kind="err">
                  <b>Could not reach the FlowForge API.</b><br />
                  {bootError || 'The server did not respond.'}
                </Banner>
                <div className="card-sub">
                  Start the backend from the <span className="mono">backend</span> folder:
                  <pre className="code" style={{ marginTop: 6 }}>uvicorn flowforge.app:app --reload --port 8000</pre>
                  If it runs on another port, point the dev server at it:
                  <pre className="code" style={{ marginTop: 6 }}>VITE_API_TARGET=http://127.0.0.1:8081 npm run dev</pre>
                </div>
                <button className="btn primary" onClick={boot}>Retry connection</button>
              </div>}
        </div>
      </div>
    )
  }

  const failingStep = trace?.steps.find((s) => s.status === 'failed') || null
  const activeDoctorTrace = doctorTrace || trace

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <div className="brand-mark">F</div>
          <div className="brand-name">FlowForge <span>AI</span></div>
        </div>
        <div className="wf-title">
          <b>{workflow.name}</b>
          <small>
            v{savedVersion}{dirty ? ' · unsaved changes' : ''} · {workflow.nodes.length} nodes ·{' '}
            <span title={health?.llm_live_available
              ? `Live provider: ${health.provider} · ${health.model_live}`
              : 'No API key configured — deterministic mock model'}>
              {llmMode === 'live' ? `live · ${health?.provider}` : 'mock model'}
            </span>
          </small>
        </div>

        <div className="stepper" title="The integrated engineering loop">
          {(['Build', 'Simulate', 'Execute', 'Observe', 'Diagnose', 'Approve', 'Retest'] as const).map((st, i, arr) => {
            const stage = !trace ? 0 : diagnosis ? (verify ? 6 : proposal ? 5 : 4) : 3
            const reached = Object.keys(simAll).length ? Math.max(stage, 1) : stage
            return (
              <span key={st} style={{ display: 'contents' }}>
                <span className={i < reached ? 'done' : i === reached ? 'cur' : ''}>{st}</span>
                {i < arr.length - 1 && <span style={{ opacity: .5 }}>›</span>}
              </span>
            )
          })}
        </div>

        <div className="topbar-spacer" />

        <div className="tabs-mini" style={{ width: 190 }}>
          <button className={llmMode === 'mock' ? 'active' : ''} onClick={() => setLlmMode('mock')}>Mock</button>
          <button className={llmMode === 'live' ? 'active' : ''} disabled={!health?.llm_live_available}
            title={health?.llm_live_available
              ? `Call ${health.provider} (${health.model_live}) from the server`
              : 'Set ANTHROPIC_API_KEY, OPENAI_API_KEY, or OPENROUTER_API_KEY in backend/.env to enable'}
            onClick={() => setLlmMode('live')}>
            {health?.llm_live_available && health?.provider && health.provider !== 'none (mock)'
              ? (health.provider.includes('OpenAI') ? 'OpenAI live' : (health.provider.includes('OpenRouter') ? 'OpenRouter live' : 'Claude live'))
              : 'Claude live'}
          </button>
        </div>

        <button className="btn sm" onClick={doSave} disabled={!dirty}>Save</button>
        <button className="btn sm" onClick={doReset} title="Restore the seeded demo workflow">Reset</button>
        <button className="btn sm" title="Clear the canvas run state and the Doctor's target"
          onClick={() => {
            setRevealCount(null); setTrace(null); setSelectedStepId(null)
            setSimResult(null); setDoctorTrace(null); setDiagnosis(null); setProposal(null); setVerify(null)
          }}>Clear run</button>
        <button className="btn primary" disabled={running} onClick={() => doRun()}>
          {running ? <><span className="spinner" /> Running</> : '▶ Run workflow'}
        </button>
      </header>

      <div className={`workspace${panelOpen ? '' : ' panel-collapsed'}`}>
        {/* ---------------------------------------------------- palette */}
        <aside className="sidebar">
          <div className="sidebar-head">Node palette</div>
          <div className="palette">
            {(Object.keys(NODE_META) as NodeType[]).map((t) => (
              <div key={t} className="palette-item" draggable onDragStart={onPaletteDrag(t)} onDoubleClick={() => addNodeClick(t)}
                title="Drag onto the canvas (or double-click to add)">
                <span className="dot" style={{ background: nodeColor(t) }} />
                <div className="txt"><b>{NODE_META[t].label}</b><small>{NODE_META[t].desc}</small></div>
              </div>
            ))}
          </div>
          <div className="sidebar-head">Workflow</div>
          <div className="stack" style={{ padding: '0 10px 12px', gap: 6 }}>
            <div className="card" style={{ padding: '8px 10px' }}>
              <div className="row between"><span className="dim small">Version</span><span className="mono">v{savedVersion}</span></div>
              <div className="row between"><span className="dim small">Saved</span><span className={`chip ${dirty ? 'warn' : 'ok'}`}>{dirty ? 'unsaved' : 'synced'}</span></div>
            </div>
            {versions.slice(0, 4).map((v) => (
              <button key={v.version} className="btn sm" style={{ justifyContent: 'space-between' }}
                onClick={() => loadVersion(v.version)}>
                <span>v{v.version}</span>
                <span className="dim" style={{ fontSize: 10, maxWidth: 118, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{v.note}</span>
              </button>
            ))}
          </div>
          <div className="sidebar-note">
            Drag a node type onto the canvas, or double-click to append it. Connect output → input handles; drag from
            the red bottom handle to build an error path.
          </div>
        </aside>

        {/* ---------------------------------------------------- canvas */}
        <main style={{ display: 'flex', flexDirection: 'column', minWidth: 0, minHeight: 0 }}>
          <div className="canvas-wrap" style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
            <div className="canvas-toolbar">
              <button className="btn sm ghost" onClick={() => setPanelOpen((p) => !p)}>{panelOpen ? 'Hide panel' : 'Show panel'}</button>
              <span className="dim" style={{ fontSize: 11 }}>{workflow.edges.length} edges · {workflow.nodes.length} nodes</span>
              {trace && <span className={`chip ${trace.status === 'succeeded' ? 'ok' : trace.status === 'degraded' ? 'warn' : 'err'}`}>{trace.status}</span>}
            </div>
            <Canvas
              workflow={workflow}
              trace={trace}
              selectedId={selectedId}
              onSelect={(id) => { setSelectedId(id); if (id) setTab('config') }}
              onChange={patchWorkflow}
              onDelete={deleteNode}
              onInvalidConnection={(m) => notify(m, 'err')}
              revealCount={revealCount}
            />
            <div className="canvas-hint">
              Drag to pan · scroll to zoom · <span className="kbd">Del</span> removes selection · mock:// hosts are inert by design
            </div>
          </div>

          {/* ---------------------------------------------------- timeline */}
          <div className="timeline">
            <div className="timeline-head">
              <b style={{ color: 'var(--text)' }}>Execution timeline</b>
              {trace ? (
                <>
                  <span className="mono dim">{trace.execution_id}</span>
                  <span className="dim">{fmtMs(trace.duration_ms)}</span>
                  {trace.scenario && <span className="chip sim">{trace.scenario.name}</span>}
                  <span className="topbar-spacer" />
                  <button className="btn ghost sm" onClick={() => diagnoseTrace(trace)}>
                    Diagnose this run →
                  </button>
                </>
              ) : <span className="dim">No run yet — press Run workflow or simulate a scenario in WhatIf AI.</span>}
            </div>
            <div className="timeline-steps">
              {trace ? trace.steps.map((s, i) => {
                const max = Math.max(...trace.steps.map((x) => x.duration_ms), 1)
                return (
                  <button key={s.node_id} className={`tl-step${selectedStepId === s.node_id ? ' active' : ''}`}
                    onClick={() => { setSelectedStepId(s.node_id); setSelectedId(s.node_id); setTab('inspector') }}
                    style={{ opacity: revealCount === null || i < revealCount ? 1 : 0.35 }}>
                    <div className="nm">{s.label}</div>
                    <div className="mt">
                      <StatusChip status={s.status} sim={s.simulated} />
                    </div>
                    <div className="mt mono" style={{ justifyContent: 'space-between' }}>
                      <span>{fmtMs(s.duration_ms)}</span><span>{s.handle || ''}</span>
                    </div>
                    <div className="bar"><i style={{ width: `${Math.max(4, (s.duration_ms / max) * 100)}%`, background: s.status === 'failed' ? 'var(--err)' : s.status === 'succeeded' ? 'var(--ok)' : 'var(--dim)' }} /></div>
                  </button>
                )
              }) : <div className="dim" style={{ padding: '6px 2px', fontSize: 11 }}>Timeline appears here after a run.</div>}
            </div>
          </div>
        </main>

        {/* ---------------------------------------------------- right panel */}
        {panelOpen && (
          <section className="panel">
            <div className="panel-tabs">
              {TABS.map((t) => (
                <button key={t.id} className={`panel-tab${tab === t.id ? ' active' : ''}`} onClick={() => setTab(t.id)}>
                  {t.label}
                  {t.id === 'doctor' && diagnosis && <span className="status-dot dot-warn" style={{ marginLeft: 6 }} />}
                  {t.id === 'blackbox' && trace && <span className="status-dot dot-run" style={{ marginLeft: 6 }} />}
                </button>
              ))}
            </div>
            <div className="panel-body">
              {tab === 'config' && (selectedNode ? (
                <NodeConfig node={selectedNode} onChange={updateNode} onDelete={() => deleteNode(selectedNode.id)}
                  onDuplicate={() => duplicateNode(selectedNode)} />
              ) : (
                <Empty icon="▤" title="Nothing selected">
                  Click a node on the canvas to configure it. The invoice demo is connected Input → Claude → Validator →
                  Condition → Output, with error handlers on the validator and the ERP call.
                </Empty>
              ))}

              {tab === 'inspector' && (
                <>
                  {trace && <TraceHeader trace={trace} />}
                  <NodeInspector step={selectedStep} onDiagnose={selectedStep?.error ? () => diagnoseTrace(trace) : undefined} />
                  {!trace && <Empty title="No execution yet">Run the workflow to inspect node inputs and outputs.</Empty>}
                </>
              )}

              {tab === 'whatif' && (
                <WhatIfPanel
                  scenarios={scenarios} result={simResult} runTrace={trace} busy={simBusy} selected={simSelected}
                  onSelect={setSimSelected} onRun={doSimulate} onRunAll={doSimulateAll} allResults={simAll}
                  onOpenTrace={(t) => { setDoctorTrace(t); setTrace(t); setRevealCount(null); setTab('blackbox') }}
                />
              )}

              {tab === 'blackbox' && (
                <BlackBox trace={trace} step={selectedStep} executions={executions}
                  onSelectStep={(id) => { setSelectedStepId(id); setSelectedId(id) }}
                  onOpen={openExecution} onDiagnose={() => diagnoseTrace(trace)} />
              )}

              {tab === 'doctor' && (
                <DoctorPanel
                  trace={activeDoctorTrace} sourceTrace={activeDoctorTrace}
                  diagnosis={diagnosis} busy={diagBusy} live={liveDiag} canLive={!!health?.llm_live_available}
                  onLiveChange={setLiveDiag} onDiagnose={() => doDiagnose()}
                  proposal={proposal} onSelectProposal={setProposal}
                  onApprove={doApprove} onReject={doReject}
                  verify={verify} verifyBusy={verifyBusy}
                />
              )}
            </div>
          </section>
        )}
      </div>

      {toast && <div className={`toast ${toast.kind}`}>{toast.kind === 'ok' ? '✓' : '✕'} {toast.msg}</div>}
    </div>
  )
}

// ---------------------------------------------------------------- Black Box tab
function BlackBox({ trace, step, executions, onSelectStep, onOpen, onDiagnose }: {
  trace: Trace | null
  step: Step | null
  executions: any[]
  onSelectStep: (id: string) => void
  onOpen: (id: string) => void
  onDiagnose: () => void
}) {
  const [section, setSection] = useState<'trace' | 'history'>('trace')
  return (
    <div className="stack" style={{ gap: 13 }}>
      <div className="row between">
        <div>
          <div style={{ fontWeight: 600 }}>Agent Black Box</div>
          <div className="card-sub">Every run is recorded: ordered node timeline, inputs/outputs (secrets redacted),
            errors and available model usage.</div>
        </div>
        <div className="tabs-mini" style={{ width: 130 }}>
          <button className={section === 'trace' ? 'active' : ''} onClick={() => setSection('trace')}>Trace</button>
          <button className={section === 'history' ? 'active' : ''} onClick={() => setSection('history')}>History</button>
        </div>
      </div>

      {section === 'history' && <ExecutionsPanel executions={executions} onOpen={onOpen} activeId={trace?.execution_id} />}

      {section === 'trace' && (!trace ? <Empty title="No execution selected">Run the workflow, or open a past execution from History.</Empty> : (
        <div className="stack" style={{ gap: 12 }}>
          <TraceHeader trace={trace} />

          {trace.scenario && (
            <Banner kind="warn">
              This is a <b>WhatIf simulation</b> — the fault was injected at
              {' '}<b>{trace.scenario.target_node_id}</b>. Nodes marked “simulated” did not perform real work; the rest ran normally.
            </Banner>
          )}

          <Section title="Ordered execution">
            <div className="stack" style={{ gap: 4 }}>
              {trace.steps.map((s, i) => (
                <button key={s.node_id} className={`scenario-item${step?.node_id === s.node_id ? ' active' : ''}`}
                  style={{ padding: '7px 9px' }} onClick={() => onSelectStep(s.node_id)}>
                  <div className="row between">
                    <span className="row" style={{ gap: 7 }}>
                      <span className="mono dim" style={{ fontSize: 10 }}>{String(i + 1).padStart(2, '0')}</span>
                      <span className="nm">{s.label}</span>
                    </span>
                    <span className="row" style={{ gap: 5 }}>
                      <span className="mono dim" style={{ fontSize: 10 }}>{fmtMs(s.duration_ms)}</span>
                      <StatusChip status={s.status} sim={s.simulated} />
                    </span>
                  </div>
                  {s.error && <span className="sub" style={{ color: 'var(--err)' }}>{s.error.type}: {s.error.message.slice(0, 110)}</span>}
                </button>
              ))}
            </div>
          </Section>

          {trace.outputs.length > 0 && (
            <Section title="Workflow outputs">
              {trace.outputs.map((o) => (
                <div key={o.node_id} className="card">
                  <div className="row between"><b style={{ fontSize: 12 }}>{o.label}</b><span className="chip">{o.outcome}</span></div>
                  <Json value={o.value} />
                </div>
              ))}
            </Section>
          )}

          <Section title="Model usage">
            <ModelUsage trace={trace} />
          </Section>

          <Section title="Trace record">
            <Json value={{ execution_id: trace.execution_id, workflow: trace.workflow_name, version: trace.workflow_version, status: trace.status, llm_mode: trace.llm_mode, started_at: trace.started_at, duration_ms: trace.duration_ms, summary: trace.summary }} />
          </Section>

          <button className="btn primary block" onClick={onDiagnose}>Diagnose this execution →</button>

          {step && (
            <>
              <div className="divider" />
              <NodeInspector step={step} />
            </>
          )}
        </div>
      ))}
    </div>
  )
}

function ModelUsage({ trace }: { trace: Trace }) {
  const llmSteps = trace.steps.filter((s) => s.type === 'llm')
  if (!llmSteps.length) return <div className="card-sub">This workflow has no model-backed node.</div>
  return (
    <div className="stack" style={{ gap: 8 }}>
      {llmSteps.map((s) => {
        const usage = s.meta?.usage
        return (
          <div key={s.node_id} className="card">
            <div className="row between" style={{ marginBottom: 6 }}>
              <b style={{ fontSize: 12 }}>{s.label}</b>
              <span className={`chip ${s.meta?.mocked ? '' : 'info'}`}>
                {s.meta?.mocked ? 'mock model' : (s.meta?.provider ? `${s.meta.provider.replace(' API', '')} live` : 'live')}
              </span>
            </div>
            <div className="row" style={{ gap: 6 }}>
              <Metric label="Model" value={<span className="mono" style={{ fontSize: 11 }}>{s.meta?.model || '—'}</span>} />
              <Metric label="Tokens" value={usage ? usage.input_tokens + usage.output_tokens : 'n/a'}
                hint={usage ? `${usage.input_tokens} in / ${usage.output_tokens} out` : 'not reported by mock'} />
              <Metric label="Est. cost" value={s.meta?.cost_usd != null ? `$${Number(s.meta.cost_usd).toFixed(5)}` : 'n/a'}
                hint={s.meta?.cost_estimated ? 'estimated from tokens' : 'unavailable'} />
            </div>
          </div>
        )
      })}
    </div>
  )
}
