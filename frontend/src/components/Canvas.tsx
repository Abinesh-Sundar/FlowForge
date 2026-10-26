import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Background, BackgroundVariant, Controls, MiniMap, ReactFlow, ReactFlowProvider, addEdge,
  useReactFlow, type Connection, type Edge, type Node, type NodeChange, type EdgeChange,
} from '@xyflow/react'
import FlowNode from './FlowNode'
import { NODE_META, defaultNode, nodeSubtitle } from '../workflow'
import type { NodeType, Trace, Workflow } from '../types'

const nodeTypes = { ff: FlowNode }

interface Props {
  workflow: Workflow
  trace: Trace | null
  selectedId: string | null
  onSelect: (id: string | null) => void
  onChange: (wf: Workflow) => void
  onDelete: (id: string) => void
  onInvalidConnection: (msg: string) => void
  revealCount: number | null
}

const VALID_HANDLES: Record<string, string[]> = {
  condition: ['true', 'false', 'error'],
  default: ['out', 'error'],
}

function CanvasInner(props: Props) {
  const { workflow, trace, selectedId, onSelect, onChange, onDelete, onInvalidConnection, revealCount } = props
  const wrapRef = useRef<HTMLDivElement>(null)
  const { screenToFlowPosition } = useReactFlow()

  // Positions are held locally while dragging so a drag does not re-render the whole app per mousemove.
  const [positions, setPositions] = useLocalPositions(workflow)

  const stepMap = useMemo(() => {
    const m = new Map<string, any>()
    if (!trace) return m
    trace.steps.forEach((s, i) => { m.set(s.node_id, { ...s, revealed: revealCount === null || i < revealCount }) })
    return m
  }, [trace, revealCount])

  const rfNodes: Node[] = useMemo(() => workflow.nodes.map((n) => {
    const step = stepMap.get(n.id)
    const status = step ? (step.revealed ? step.status : (revealCount === null ? 'pending' : 'running')) : 'pending'
    return {
      id: n.id,
      type: 'ff',
      position: positions[n.id] || n.position,
      selected: n.id === selectedId,
      data: {
        type: n.type, label: n.label, subtitle: nodeSubtitle(n), status,
        duration: step?.revealed ? step.duration_ms : undefined,
        preview: step?.revealed && step.status !== 'failed' ? step.output : undefined,
        errorMsg: step?.revealed && step.error ? `${step.error.type}: ${step.error.message}` : undefined,
      },
    }
  }), [workflow.nodes, positions, stepMap, selectedId, revealCount])

  const rfEdges: Edge[] = useMemo(() => workflow.edges.map((e) => {
    const srcStep = stepMap.get(e.source)
    const traversed = !!trace && !!srcStep?.revealed && (
      srcStep.status === 'failed' ? (e.sourceHandle || 'out') === 'error' : (e.sourceHandle || 'out') === srcStep.handle)
    const isError = (e.sourceHandle || 'out') === 'error'
    return {
      id: e.id, source: e.source, target: e.target, sourceHandle: e.sourceHandle || 'out',
      type: 'smoothstep',
      className: `${isError ? 'ff-edge-error' : ''}`,
      animated: traversed,
      style: { stroke: isError ? undefined : traversed ? '#6aa6ff' : '#333c48', strokeWidth: traversed ? 2 : 1.4 },
      markerEnd: { type: 'arrowclosed' as any, width: 14, height: 14, color: isError ? '#ff6b6b' : traversed ? '#6aa6ff' : '#333c48' },
    }
  }), [workflow.edges, stepMap, trace])

  const onNodesChange = useCallback((changes: NodeChange[]) => {
    const removed = changes.filter((c) => c.type === 'remove')
    if (removed.length) { removed.forEach((c) => onDelete((c as any).id)); return }
    const pos = changes.filter((c) => c.type === 'position' && (c as any).position) as any[]
    if (pos.length) {
      setPositions((prev) => {
        const next = { ...prev }
        pos.forEach((c) => { next[c.id] = c.position })
        return next
      })
      // Only persist on drag end (dragging:false) to avoid a full state write per mousemove.
      const finished = pos.filter((c) => c.dragging === false)
      if (finished.length) {
        onChange({
          ...workflow,
          nodes: workflow.nodes.map((n) => {
            const ch = finished.find((c) => c.id === n.id)
            return ch ? { ...n, position: ch.position } : n
          }),
        })
      }
    }
  }, [workflow, onChange, onDelete, setPositions])

  const onEdgesChange = useCallback((changes: EdgeChange[]) => {
    const removed = changes.filter((c) => c.type === 'remove')
    if (!removed.length) return
    const ids = new Set(removed.map((c) => (c as any).id))
    onChange({ ...workflow, edges: workflow.edges.filter((e) => !ids.has(e.id)) })
  }, [workflow, onChange])

  const onConnect = useCallback((c: Connection) => {
    if (c.source === c.target) { onInvalidConnection('Self-connections are not allowed'); return }
    const src = workflow.nodes.find((n) => n.id === c.source)
    if (!src) return
    const handle = c.sourceHandle || 'out'
    const allowed = VALID_HANDLES[src.type] || VALID_HANDLES.default
    if (!allowed.includes(handle)) { onInvalidConnection(`Output '${handle}' is not available on ${src.label}`); return }
    const dupe = workflow.edges.some((e) => e.source === c.source && e.target === c.target && (e.sourceHandle || 'out') === handle)
    if (dupe) { onInvalidConnection('That connection already exists'); return }
    const id = `e_${Date.now().toString(36)}${Math.random().toString(36).slice(2, 5)}`
    onChange({ ...workflow, edges: addEdge({ ...c, id, sourceHandle: handle }, workflow.edges) as any })
  }, [workflow, onChange, onInvalidConnection])

  const onDrop = useCallback((ev: React.DragEvent) => {
    ev.preventDefault()
    const type = ev.dataTransfer.getData('application/flowforge-node') as NodeType
    if (!type || !NODE_META[type]) return
    const p = screenToFlowPosition({ x: ev.clientX, y: ev.clientY })
    const id = `n_${type}_${Date.now().toString(36).slice(-5)}`
    onChange({ ...workflow, nodes: [...workflow.nodes, defaultNode(type, id, { x: p.x - 98, y: p.y - 40 })] })
    onSelect(id)
  }, [workflow, onChange, onSelect, screenToFlowPosition])

  return (
    <div ref={wrapRef} style={{ flex: 1, minHeight: 0 }}
      onDrop={onDrop} onDragOver={(e) => { e.preventDefault(); e.dataTransfer.dropEffect = 'move' }}>
      <ReactFlow
        nodes={rfNodes}
        edges={rfEdges}
        nodeTypes={nodeTypes}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        onNodeClick={(_, n) => onSelect(n.id)}
        onPaneClick={() => onSelect(null)}
        fitView
        fitViewOptions={{ padding: 0.06, minZoom: 0.62, maxZoom: 0.9 }}
        minZoom={0.3}
        maxZoom={1.6}
        proOptions={{ hideAttribution: true }}
        deleteKeyCode={['Backspace', 'Delete']}
      >
        <Background variant={BackgroundVariant.Dots} gap={18} size={1} color="#242a33" />
        <Controls showInteractive={false} position="bottom-right" />
        <MiniMap pannable zoomable nodeColor={(n: any) => {
          const st = stepMap.get(n.id)?.status
          return st === 'failed' ? '#ff6b6b' : st === 'succeeded' ? '#3ecf8e' : '#2b323c'
        }} maskColor="rgba(11,13,16,.75)" style={{ width: 120, height: 80 }} />
      </ReactFlow>
    </div>
  )
}

/** Local position state that resets whenever nodes are added, removed or replaced wholesale. */
function useLocalPositions(workflow: Workflow) {
  const [positions, setPositions] = useState<Record<string, { x: number; y: number }>>(
    () => Object.fromEntries(workflow.nodes.map((n) => [n.id, n.position])))
  const key = workflow.nodes.map((n) => n.id).sort().join(',')
  useEffect(() => {
    setPositions(Object.fromEntries(workflow.nodes.map((n) => [n.id, n.position])))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key])
  return [positions, setPositions] as const
}

export default function Canvas(props: Props) {
  return (
    <ReactFlowProvider>
      <CanvasInner {...props} />
    </ReactFlowProvider>
  )
}
