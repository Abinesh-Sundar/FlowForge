import type { NodeType, WFNode, Workflow } from './types'

export const NODE_META: Record<NodeType, { label: string; kind: string; desc: string; config: Record<string, any> }> = {
  input: {
    label: 'Input', kind: 'Trigger', desc: 'Receives a JSON payload',
    config: { sample: { document: 'Invoice No: INV-3001\nVendor: Example Co\nTotal Due: $99.00', source: 'manual' } },
  },
  llm: {
    label: 'Claude LLM', kind: 'Model', desc: 'Extract or transform with Claude',
    config: { prompt: 'Extract the fields requested and return JSON.', output: 'json', model: 'claude-opus-5-5', timeout_ms: 30000 },
  },
  transform: {
    label: 'Transform', kind: 'Logic', desc: 'Reshape the JSON payload',
    config: { ops: [{ op: 'pick', fields: ['invoice_number', 'vendor', 'amount'] }] },
  },
  validator: {
    label: 'Validator', kind: 'Guard', desc: 'Check required fields and types',
    config: { rules: [{ field: 'amount', type: 'number', required: true, min: 0.01 }] },
  },
  condition: {
    label: 'Condition', kind: 'Routing', desc: 'Deterministic branch',
    config: { field: 'amount', operator: '>', value: 100 },
  },
  http: {
    label: 'HTTP Request', kind: 'Integration', desc: 'Call mock:// or allow-listed https',
    config: { method: 'POST', url: 'mock://erp/invoices', timeout_ms: 5000 },
  },
  failure_sim: {
    label: 'Failure Simulator', kind: 'Test', desc: 'Inject a controlled failure',
    config: { failure: 'http_500', field: 'amount', enabled: true },
  },
  output: {
    label: 'Output', kind: 'Sink', desc: 'Terminal result',
    config: { outcome: 'success', note: '' },
  },
}

export function defaultNode(type: NodeType, id: string, position: { x: number; y: number }): WFNode {
  const meta = NODE_META[type]
  return { id, type, label: meta.label, position, config: JSON.parse(JSON.stringify(meta.config)) }
}

export function nodeSubtitle(n: WFNode): string {
  const c = n.config || {}
  switch (n.type) {
    case 'llm': return c.output === 'text' ? 'text out' : 'json out'
    case 'validator': return `${(c.rules || []).length} rule${(c.rules || []).length === 1 ? '' : 's'}`
    case 'condition': return `${c.field} ${c.operator} ${JSON.stringify(c.value ?? '')}`
    case 'http': return (c.url || '').replace(/^mock:\/\//, 'mock:')
    case 'transform': return (c.ops || []).map((o: any) => o.op).join(', ') || 'no ops'
    case 'failure_sim': return c.failure
    case 'output': return `outcome: ${c.outcome}`
    case 'input': return 'JSON payload'
    default: return ''
  }
}

export function newWorkflowId() {
  return 'wf_' + Math.random().toString(36).slice(2, 10)
}

export function clone<T>(v: T): T {
  return JSON.parse(JSON.stringify(v))
}

export function emptyWorkflow(): Workflow {
  const input = defaultNode('input', 'n_input', { x: 40, y: 160 })
  const llm = defaultNode('llm', 'n_llm', { x: 320, y: 160 })
  const out = defaultNode('output', 'n_out', { x: 600, y: 160 })
  return {
    id: newWorkflowId(), name: 'Untitled workflow', version: 1, description: '',
    nodes: [input, llm, out],
    edges: [
      { id: 'e1', source: 'n_input', target: 'n_llm', sourceHandle: 'out' },
      { id: 'e2', source: 'n_llm', target: 'n_out', sourceHandle: 'out' },
    ],
  }
}
