export type NodeType = 'input' | 'llm' | 'transform' | 'validator' | 'condition' | 'http' | 'failure_sim' | 'output'
export type Status = 'succeeded' | 'failed' | 'skipped' | 'pending' | 'running'

export interface WFNode {
  id: string
  type: NodeType
  label: string
  position: { x: number; y: number }
  config: Record<string, any>
}
export interface WFEdge {
  id: string
  source: string
  target: string
  sourceHandle?: string | null
}
export interface Workflow {
  id: string
  name: string
  description?: string
  version: number
  nodes: WFNode[]
  edges: WFEdge[]
}
export interface Step {
  node_id: string
  label: string
  type: string
  status: Status
  duration_ms: number
  handle: string | null
  input: any
  output: any
  error: { type: string; message: string; details?: any; simulated?: boolean } | null
  meta: Record<string, any>
  simulated: boolean
}
export interface Trace {
  execution_id: string
  workflow_id: string
  workflow_name: string
  workflow_version: number
  status: 'succeeded' | 'failed' | 'degraded'
  started_at: string
  duration_ms: number
  llm_mode: 'mock' | 'live'
  scenario: any
  steps: Step[]
  outputs: { node_id: string; label: string; value: any; outcome: string }[]
  summary: any
}
export interface Scenario {
  id: string
  name: string
  kind: string
  target_node_id: string
  target_label?: string
  field?: string
  description: string
  expected: { status: string; failing_node_id?: string; error_type?: string; text: string }
}
export interface SimResult {
  scenario: Scenario
  expected_behavior: string
  actual_behavior: any
  passed: boolean
  blocked?: boolean
  blocked_reason?: string
  checks: { check: string; expected?: any; actual?: any; pass: boolean; detail?: string }[]
  trace: Trace
  distinction: string
}
export interface Evidence {
  source: string
  node_id?: string
  node?: string
  fact: string
  detail?: string
  expected?: any
  actual?: any
}
export interface Proposal {
  id: string
  title: string
  summary: string
  target_node_id: string
  target_node_label?: string
  confidence: string
  risk: string
  recommended?: boolean
  diff: { config_key: string; before: any; after: any }[]
  expected_effect: string
  apply: any[]
}
export interface Diagnosis {
  source: 'deterministic' | 'claude'
  label: string
  failed_node_id: string | null
  failed_node_label?: string
  confidence: string
  summary: string
  root_cause: string
  evidence: Evidence[]
  proposals: Proposal[]
  fallback_reason?: string
  model?: string
  usage?: { input_tokens: number; output_tokens: number }
  cost_usd?: number | null
  disclaimer?: string
}
export interface RegressionResult {
  suite: string
  ran_at: string
  passed: number
  total: number
  results: { id: string; name: string; passed: boolean; actual_status: string; expected_status: string; outcomes?: string[] }[]
}
export interface VerifyResult {
  comparison: {
    rows: { name: string; before: string; after: string; changed: boolean; before_status: string; after_status: string }[]
    before_passed: number
    after_passed: number
    total: number
    improved: boolean
    regressed: boolean
    summary: string
  }
  before: RegressionResult
  after: RegressionResult
  repair_execution_id: string | null
  remaining_failures: string[]
  ok: boolean
}
export interface Health {
  ok: boolean
  llm_live_available: boolean
  llm_mode_default: 'mock' | 'live'
  provider: string
  model: string
  model_live: string
}
