import type {
  Diagnosis, Health, RegressionResult, SimResult, Trace, VerifyResult, Workflow,
} from './types'

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(path, {
      ...init,
      headers: { 'content-type': 'application/json', ...(init?.headers || {}) },
    })
  } catch {
    // fetch only rejects on a network-level failure: the API is not reachable at all.
    throw new Error('The FlowForge API is unreachable. Is the backend running? (uvicorn flowforge.app:app --port 8000)')
  }
  // A proxy that cannot reach its target answers with an HTML error page, not JSON.
  const text = await res.text()
  let body: any = null
  try { body = text ? JSON.parse(text) : null } catch { body = text }
  if (!res.ok) {
    if (typeof body === 'string' && /<html/i.test(body)) {
      throw new Error(`The API returned an HTML page (${res.status}) instead of JSON — this origin is serving the UI ` +
        'but not the backend. Make sure uvicorn is running (and that VITE_API_TARGET points at its port).')
    }
    const detail = body?.detail
    const msg = typeof detail === 'string' ? detail
      : detail?.message ? `${detail.message}: ${(detail.issues || []).map((i: any) => i.message).join('; ')}`
      : JSON.stringify(detail ?? body)
    throw new Error(msg || `Request failed (${res.status})`)
  }
  return body as T
}

const post = <T>(path: string, body: any) => req<T>(path, { method: 'POST', body: JSON.stringify(body) })

export const api = {
  health: () => req<Health>('/api/health'),
  workflows: () => req<{ id: string; name: string; version: number; updated_at: string }[]>('/api/workflows'),
  workflow: (id: string) => req<Workflow>(`/api/workflows/${id}`),
  save: (wf: Workflow) => post<{ version: number }>('/api/workflows', wf),
  versions: (id: string) => req<{ version: number; note: string; created_at: string }[]>(`/api/workflows/${id}/versions`),
  version: (id: string, v: number) => req<Workflow>(`/api/workflows/${id}/versions/${v}`),
  reset: (id: string) => post<Workflow>(`/api/workflows/${id}/reset`, {}),
  validate: (wf: Workflow) => post<{ valid: boolean; issues: any[] }>('/api/workflows/validate', wf),
  run: (wf: Workflow, payload: any, llm_mode: string) => post<Trace>('/api/run', { workflow: wf, payload, llm_mode }),
  scenarios: (wf: Workflow) => post<any[]>('/api/scenarios', wf),
  simulate: (wf: Workflow, scenario_id: string, payload: any, llm_mode: string) =>
    post<SimResult>('/api/simulate', { workflow: wf, scenario_id, payload, llm_mode }),
  executions: (workflow_id?: string) =>
    req<any[]>(`/api/executions${workflow_id ? `?workflow_id=${workflow_id}` : ''}`),
  execution: (id: string) => req<Trace>(`/api/executions/${id}`),
  diagnose: (wf: Workflow, execution_id: string, live: boolean) =>
    post<Diagnosis>('/api/diagnose', { workflow: wf, execution_id, live }),
  apply: (wf: Workflow, proposal: any) =>
    post<{ workflow: Workflow; version: number }>('/api/apply', { workflow: wf, proposal }),
  regression: (wf: Workflow, payload: any, llm_mode: string) =>
    post<RegressionResult>('/api/regression', { workflow: wf, payload, llm_mode }),
  verify: (original_workflow: Workflow, repaired_workflow: Workflow, payload: any, llm_mode: string) =>
    post<VerifyResult>('/api/verify', { original_workflow, repaired_workflow, payload, llm_mode }),
}
