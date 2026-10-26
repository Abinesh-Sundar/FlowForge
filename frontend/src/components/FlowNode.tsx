import { Handle, Position, type NodeProps } from '@xyflow/react'
import { STATUS_COLOR, nodeColor, nodeGlyph, summarizeOutput, fmtMs } from './ui'

export default function FlowNode({ data, selected }: NodeProps) {
  const d = data as any
  const status: string = d.status || 'pending'
  const isCondition = d.type === 'condition'
  return (
    <div className={`ff-node${selected ? ' selected' : ''} status-${status}`}>
      {d.type !== 'input' && <Handle type="target" position={Position.Left} id="in" />}
      <div className="ff-node-head">
        <div className="glyph" style={{ color: nodeColor(d.type), background: `${nodeColor(d.type)}1a` }}>{nodeGlyph(d.type)}</div>
        <div className="t">
          <b>{d.label}</b>
          <small>{d.type.replace('_', ' ')}</small>
        </div>
        <span className="ff-node-status" style={{ color: STATUS_COLOR[status] }}>
          <i className="status-dot" style={{ background: STATUS_COLOR[status] }} />
          {status === 'pending' ? '' : status}
        </span>
      </div>
      <div className="ff-node-body">
        <div className="kv"><span>model</span><span className="mono">{d.subtitle || '—'}</span></div>
        {d.duration !== undefined && d.duration !== null && (
          <div className="kv"><span>duration</span><span className="mono">{fmtMs(d.duration)}</span></div>
        )}
        {d.preview && <div className="preview">{summarizeOutput(d.preview)}</div>}
        {d.errorMsg && <div className="preview" style={{ color: '#ffb3b3', borderColor: 'rgba(255,107,107,.3)' }}>{d.errorMsg}</div>}
      </div>
      {isCondition ? (
        <>
          <Handle type="source" position={Position.Right} id="true" style={{ top: '38%', background: '#3ecf8e' }} />
          <Handle type="source" position={Position.Right} id="false" style={{ top: '72%', background: '#f5b544' }} />
          <span className="handle-label" style={{ right: -34, top: '30%' }}>true</span>
          <span className="handle-label" style={{ right: -36, top: '64%' }}>false</span>
        </>
      ) : (
        <Handle type="source" position={Position.Right} id="out" />
      )}
      {d.type !== 'output' && d.type !== 'input' && (
        <Handle type="source" position={Position.Bottom} id="error" style={{ background: '#ff6b6b', left: '50%' }} />
      )}
    </div>
  )
}
