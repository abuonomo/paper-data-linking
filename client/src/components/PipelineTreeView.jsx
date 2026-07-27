import React, { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { fetchAnalysisPipelineTree } from '../services/apiServices';
import LLMCallDetails from './LLMCallDetails';

const STATUS_COLORS = {
  completed: { bg: '#f2fdf5', fg: '#57606a', border: '#d0d7de', dot: '#3fb950' },
  failed:    { bg: '#ffebe9', fg: '#d1242f', border: '#ff8182', dot: '#d1242f' },
  running:   { bg: '#fff8c5', fg: '#9a6700', border: '#f0c000', dot: '#d4a72c' },
  skipped:   { bg: '#f6f8fa', fg: '#656d76', border: '#d0d7de', dot: '#9b9ea3' },
};

const STAGE_ACCENT = {
  paper_analysis:      '#0969da',
  structuring:         '#8250df',
  instrument:          '#1a7f5a',
  grounding:           '#bc4c00',
  grounding_datasystem:'#cf6f20',
  grounding_substep:   '#6e7781',
  grounding_match:     '#2da44e',
  normalization:       '#bf3989',
  normalizer:          '#9a6700',
};

const STAGE_LABELS = {
  paper_analysis:      'Paper Analysis',
  structuring:         'Structuring',
  instrument:          'Instrument',
  grounding:           'Grounding',
  grounding_datasystem:'Data System',
  grounding_substep:   'Substep',
  grounding_match:     'Match',
  normalization:       'Normalization',
  normalizer:          'Normalizer',
};

const COLLAPSED_BY_DEFAULT = new Set(['grounding_substep', 'normalizer']);

function formatDuration(started, completed) {
  if (!started || !completed) return null;
  const ms = new Date(completed) - new Date(started);
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`;
}

function LLMCallRow({ call, onCallClick }) {
  const cost = parseFloat(call.estimated_cost_usd || 0);
  return (
    <div
      onClick={() => onCallClick(call)}
      style={{
        display: 'grid',
        gridTemplateColumns: '1fr 1fr auto auto',
        gap: '4px 12px',
        padding: '4px 8px',
        fontSize: '12px',
        color: '#57606a',
        borderBottom: '1px solid #f0f0f0',
        cursor: 'pointer',
      }}
      onMouseEnter={e => e.currentTarget.style.background = '#f6f8fa'}
      onMouseLeave={e => e.currentTarget.style.background = ''}
    >
      <span style={{ fontFamily: 'monospace' }}>{call.call_type}</span>
      <span>{call.model_name}</span>
      <span style={{ textAlign: 'right' }}>{(call.total_tokens || 0).toLocaleString()} tok</span>
      <span style={{ textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>
        ${cost.toFixed(4)}
      </span>
    </div>
  );
}

function MetaSummary({ node }) {
  const m = node.metadata || {};
  const style = { fontSize: '11px', color: '#57606a', flexShrink: 0 };

  if (node.stage === 'mission_identification' && m.missions?.length > 0) {
    const shown = m.missions.slice(0, 3).join(', ');
    const extra = m.missions.length > 3 ? ` +${m.missions.length - 3}` : '';
    return <span style={style}>· {shown}{extra}</span>;
  }
  if (node.stage === 'mission_selection' && m.missions?.length > 0) {
    return <span style={style}>· {m.missions.join(', ')}</span>;
  }
  if (node.stage === 'instrument_selection' && m.instruments?.length > 0) {
    return <span style={style}>· {m.instruments.join(', ')}</span>;
  }
  if (node.stage === 'instrument_validation' && m.results?.length > 0) {
    return (
      <span style={{ fontSize: '11px', flexShrink: 0, display: 'flex', gap: '6px' }}>
        {m.results.map(r => (
          <span key={r.code} style={{ color: r.accepted ? '#1a7f5a' : '#d1242f' }}>
            {r.accepted ? '✓' : '✗'} {r.code}
          </span>
        ))}
      </span>
    );
  }
  return null;
}

function getChildrenLayout(children) {
  if (!children?.length) return 'tree';
  const first = children[0].stage;
  if (first === 'grounding_substep') return 'sequential';
  if (first === 'normalizer') return 'parallel';
  return 'tree';
}

const VALIDATION_STATUS_COLORS = {
  pending:      { bg: '#fff8c5', fg: '#9a6700' },
  approved:     { bg: '#dafbe1', fg: '#1a7f37' },
  rejected:     { bg: '#ffebe9', fg: '#d1242f' },
  needs_review: { bg: '#ddf4ff', fg: '#0969da' },
};

function formatDate(iso) {
  if (!iso) return '—';
  return iso.slice(0, 10);
}

function PipelineNode({ node, depth = 0, onCallClick, onNavigate, stepNumber }) {
  const expandKey = `pipeline_node_${node.id}`;
  const [expanded, setExpanded] = useState(() => {
    const saved = sessionStorage.getItem(expandKey);
    return saved !== null ? saved === 'true' : !COLLAPSED_BY_DEFAULT.has(node.stage);
  });
  const [showCalls, setShowCalls] = useState(false);
  const [showUsages, setShowUsages] = useState(() => {
    const saved = sessionStorage.getItem(`pipeline_node_usages_${node.id}`);
    return saved === 'true';
  });

  const toggleExpanded = () => {
    setExpanded(prev => {
      const next = !prev;
      sessionStorage.setItem(expandKey, String(next));
      return next;
    });
  };

  const colors = STATUS_COLORS[node.status] || STATUS_COLORS.skipped;
  const duration = formatDuration(node.started_at, node.completed_at);
  const totalCost = (node.llm_calls || []).reduce(
    (sum, c) => sum + parseFloat(c.estimated_cost_usd || 0), 0
  );
  const totalTokens = (node.llm_calls || []).reduce(
    (sum, c) => sum + (c.total_tokens || 0), 0
  );
  const hasChildren = node.children && node.children.length > 0;
  const hasCalls = node.llm_calls && node.llm_calls.length > 0;

  return (
    <div style={{ marginLeft: depth > 0 ? '16px' : '0', position: 'relative' }}>
      {/* Connector line for non-root nodes */}
      {depth > 0 && (
        <div style={{
          position: 'absolute',
          left: '-12px',
          top: '12px',
          width: '8px',
          height: '1px',
          background: '#d0d7de',
        }} />
      )}

      {/* Node card */}
      <div style={{
        border: `1px solid ${colors.border}`,
        borderLeft: `3px solid ${STAGE_ACCENT[node.stage] || '#d0d7de'}`,
        borderRadius: '6px',
        marginBottom: '4px',
        background: '#fff',
        overflow: 'hidden',
      }}>
        {/* Header row */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '6px',
            padding: '6px 10px',
            background: colors.bg,
            cursor: (hasChildren || hasCalls) ? 'pointer' : 'default',
            userSelect: 'none',
          }}
          onClick={() => hasChildren && toggleExpanded()}
        >
          {/* Expand toggle */}
          {hasChildren && (
            <span style={{ fontSize: '10px', color: '#57606a', minWidth: '10px' }}>
              {expanded ? '▾' : '▸'}
            </span>
          )}
          {!hasChildren && <span style={{ minWidth: '10px' }} />}

          {/* Step number badge for sequential substeps */}
          {stepNumber !== undefined && (
            <span style={{
              fontSize: '9px', fontWeight: 700,
              background: STAGE_ACCENT['grounding_substep'],
              color: '#fff',
              borderRadius: '50%',
              width: '16px', height: '16px', lineHeight: '16px',
              textAlign: 'center',
              flexShrink: 0,
            }}>
              {stepNumber}
            </span>
          )}

          {/* Stage badge — uses accent color for contrast */}
          <span style={{
            fontSize: '10px',
            fontWeight: 600,
            padding: '1px 5px',
            borderRadius: '10px',
            background: `${STAGE_ACCENT[node.stage] || '#57606a'}18`,
            color: STAGE_ACCENT[node.stage] || '#57606a',
            flexShrink: 0,
          }}>
            {STAGE_LABELS[node.stage] || node.stage}
          </span>

          {/* Label */}
          <span style={{ fontSize: '13px', fontWeight: 500, color: '#1f2328', flex: 1 }}>
            {node.label}
          </span>

          {/* Status */}
          <span style={{ display: 'flex', alignItems: 'center', gap: '4px', flexShrink: 0 }}>
            <span style={{
              width: '7px', height: '7px', borderRadius: '50%',
              background: colors.dot, flexShrink: 0,
              animation: node.status === 'running' ? 'pipeline-pulse 1.2s ease-in-out infinite' : undefined,
              display: 'inline-block',
            }} />
            <span style={{ fontSize: '11px', color: colors.fg }}>{node.status}</span>
          </span>

          {/* Duration */}
          {duration && (
            <span style={{ fontSize: '11px', color: '#57606a', flexShrink: 0 }}>
              {duration}
            </span>
          )}

          {/* Cost */}
          {totalCost > 0 && (
            <span style={{ fontSize: '11px', color: '#57606a', flexShrink: 0, fontVariantNumeric: 'tabular-nums' }}>
              ${totalCost.toFixed(4)}
            </span>
          )}

          {/* Token count */}
          {totalTokens > 0 && (
            <span style={{ fontSize: '11px', color: '#57606a', flexShrink: 0 }}>
              {totalTokens.toLocaleString()} tok
            </span>
          )}

          {/* LLM calls toggle */}
          {hasCalls && (
            <button
              onClick={e => { e.stopPropagation(); setShowCalls(s => !s); }}
              style={{
                fontSize: '10px',
                padding: '1px 6px',
                border: `1px solid ${STAGE_ACCENT[node.stage] || '#d0d7de'}`,
                borderRadius: '4px',
                background: 'rgba(255,255,255,0.6)',
                color: STAGE_ACCENT[node.stage] || '#57606a',
                cursor: 'pointer',
                flexShrink: 0,
              }}
            >
              {node.llm_calls.length} call{node.llm_calls.length !== 1 ? 's' : ''}
              {showCalls ? ' ▾' : ' ▸'}
            </button>
          )}

          {/* Skip reason */}
          {node.status === 'skipped' && node.metadata?.skip_reason && (
            <span style={{ fontSize: '11px', color: '#57606a', fontStyle: 'italic' }}>
              {node.metadata.skip_reason}
            </span>
          )}

          {/* Substep metadata summary */}
          <MetaSummary node={node} />

          {/* Dataset usages toggle */}
          {node.dataset_usages?.length > 0 && (
            <button
              onClick={e => {
                e.stopPropagation();
                setShowUsages(s => {
                  const next = !s;
                  sessionStorage.setItem(`pipeline_node_usages_${node.id}`, String(next));
                  return next;
                });
              }}
              style={{
                fontSize: '10px',
                padding: '1px 6px',
                border: `1px solid ${STAGE_ACCENT['grounding_match']}`,
                borderRadius: '4px',
                background: 'rgba(255,255,255,0.6)',
                color: STAGE_ACCENT['grounding_match'],
                cursor: 'pointer',
                flexShrink: 0,
              }}
            >
              {node.dataset_usages.length} usage{node.dataset_usages.length !== 1 ? 's' : ''}
              {showUsages ? ' ▾' : ' ▸'}
            </button>
          )}
        </div>

        {/* Dataset usages panel */}
        {showUsages && node.dataset_usages?.length > 0 && (
          <div style={{ borderTop: `1px solid ${colors.border}` }}>
            <div style={{
              display: 'grid',
              gridTemplateColumns: '1fr 1fr 1fr auto',
              gap: '4px 12px',
              padding: '4px 8px',
              fontSize: '10px',
              fontWeight: 600,
              color: '#57606a',
              background: '#f6f8fa',
              borderBottom: '1px solid #eaecef',
            }}>
              <span>Observatory</span>
              <span>Instrument</span>
              <span>Window</span>
              <span>Status</span>
            </div>
            {node.dataset_usages.map(u => {
              const sc = VALIDATION_STATUS_COLORS[u.validation_status] || VALIDATION_STATUS_COLORS.pending;
              return (
                <div
                  key={u.id}
                  onClick={() => onNavigate(`/papers/${u.paper_id}/validate/${u.id}`)}
                  style={{
                    display: 'grid',
                    gridTemplateColumns: '1fr 1fr 1fr auto',
                    gap: '4px 12px',
                    padding: '4px 8px',
                    fontSize: '12px',
                    color: '#57606a',
                    borderBottom: '1px solid #f0f0f0',
                    cursor: 'pointer',
                  }}
                  onMouseEnter={e => e.currentTarget.style.background = '#f6f8fa'}
                  onMouseLeave={e => e.currentTarget.style.background = ''}
                >
                  <span>{u.observatory_label}</span>
                  <span>{u.instrument_label}</span>
                  <span style={{ fontSize: '11px' }}>{formatDate(u.start_time)} – {formatDate(u.end_time)}</span>
                  <span style={{
                    fontSize: '10px', fontWeight: 600,
                    padding: '1px 5px', borderRadius: '10px',
                    background: sc.bg, color: sc.fg, whiteSpace: 'nowrap',
                  }}>
                    {u.validation_status}
                  </span>
                </div>
              );
            })}
          </div>
        )}

        {/* LLM calls panel */}
        {showCalls && hasCalls && (
          <div style={{ borderTop: `1px solid ${colors.border}` }}>
            <div style={{
              display: 'grid',
              gridTemplateColumns: '1fr 1fr auto auto',
              gap: '4px 12px',
              padding: '4px 8px',
              fontSize: '10px',
              fontWeight: 600,
              color: '#57606a',
              background: '#f6f8fa',
              borderBottom: '1px solid #eaecef',
            }}>
              <span>Type</span>
              <span>Model</span>
              <span style={{ textAlign: 'right' }}>Tokens</span>
              <span style={{ textAlign: 'right' }}>Cost</span>
            </div>
            {node.llm_calls.map(call => (
              <LLMCallRow key={call.id} call={call} onCallClick={onCallClick} />
            ))}
          </div>
        )}
      </div>

      {/* Children */}
      {expanded && hasChildren && (() => {
        const layout = getChildrenLayout(node.children);

        if (layout === 'sequential') {
          return (
            <div style={{ marginLeft: '12px', paddingLeft: '8px', paddingTop: '2px' }}>
              <div style={{ fontSize: '10px', color: '#6e7781', marginBottom: '4px', letterSpacing: '0.02em' }}>
                → sequential
              </div>
              {node.children.map((child, i) => (
                <div key={child.id}>
                  {i > 0 && (
                    <div style={{
                      width: '1px', height: '8px',
                      background: '#d0d7de',
                      marginLeft: '7px', marginBottom: '0',
                    }} />
                  )}
                  <PipelineNode node={child} depth={depth + 1} onCallClick={onCallClick} onNavigate={onNavigate} stepNumber={i + 1} />
                </div>
              ))}
            </div>
          );
        }

        if (layout === 'parallel') {
          return (
            <div style={{ marginLeft: '12px', paddingLeft: '8px', paddingTop: '2px' }}>
              <div style={{ fontSize: '10px', color: '#9a6700', marginBottom: '4px', letterSpacing: '0.02em' }}>
                ‖ parallel
              </div>
              <div style={{ borderLeft: '1px solid #d0d7de', paddingLeft: '4px' }}>
                {node.children.map(child => (
                  <PipelineNode key={child.id} node={child} depth={depth + 1} onCallClick={onCallClick} onNavigate={onNavigate} />
                ))}
              </div>
            </div>
          );
        }

        // Default tree layout
        return (
          <div style={{
            marginLeft: '12px',
            borderLeft: '1px solid #d0d7de',
            paddingLeft: '4px',
          }}>
            {node.children.map(child => (
              <PipelineNode key={child.id} node={child} depth={depth + 1} onCallClick={onCallClick} onNavigate={onNavigate} />
            ))}
          </div>
        );
      })()}
    </div>
  );
}

// Inject pulse keyframe once into the document
if (typeof document !== 'undefined' && !document.getElementById('pipeline-pulse-style')) {
  const style = document.createElement('style');
  style.id = 'pipeline-pulse-style';
  style.textContent = `
    @keyframes pipeline-pulse {
      0%, 100% { opacity: 1; transform: scale(1); }
      50%       { opacity: 0.4; transform: scale(1.5); }
    }
  `;
  document.head.appendChild(style);
}

function hasRunningNode(nodes) {
  if (!nodes) return false;
  for (const n of nodes) {
    if (n.status === 'running') return true;
    if (hasRunningNode(n.children)) return true;
  }
  return false;
}

function PipelineTreeView({ analysisId }) {
  const navigate = useNavigate();
  const containerRef = useRef(null);
  const intervalRef = useRef(null);
  const scrollKey = `pipeline_scroll_${analysisId}`;

  const [tree, setTree] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [selectedCall, setSelectedCall] = useState(null);
  const [showCallDetails, setShowCallDetails] = useState(false);
  const [isLive, setIsLive] = useState(null); // null = unknown until first fetch

  const handleCallClick = (call) => {
    setSelectedCall(call);
    setShowCallDetails(true);
  };

  const handleNavigate = (path) => {
    sessionStorage.setItem(scrollKey, String(window.scrollY));
    navigate(path);
  };

  const loadTree = (isInitial = false) => {
    if (!analysisId) return;
    if (isInitial) setLoading(true);
    fetchAnalysisPipelineTree(analysisId)
      .then(data => {
        // Handle both old list format and new {pipeline_completed_at, nodes} format
        const pipeline_completed_at = data?.pipeline_completed_at ?? null;
        const nodes = Array.isArray(data) ? data : (data?.nodes ?? []);
        setTree(nodes);
        if (isInitial) {
          setLoading(false);
          const saved = sessionStorage.getItem(scrollKey);
          if (saved) {
            requestAnimationFrame(() => window.scrollTo(0, parseInt(saved, 10)));
          }
        }

        if (pipeline_completed_at) {
          // Backend confirmed pipeline is done — stop polling
          setIsLive(false);
          if (intervalRef.current) {
            clearInterval(intervalRef.current);
            intervalRef.current = null;
          }
        } else {
          // Pipeline not done yet — show Live, keep polling
          setIsLive(true);
        }
      })
      .catch(err => {
        if (isInitial) { setError(err.message); setLoading(false); }
      });
  };

  useEffect(() => {
    loadTree(true);
    intervalRef.current = setInterval(() => loadTree(false), 3000);
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [analysisId]);

  if (loading) {
    return <div style={{ padding: '16px', color: '#57606a' }}>Loading pipeline tree...</div>;
  }

  if (error) {
    return <div style={{ padding: '16px', color: '#d1242f' }}>Error: {error}</div>;
  }

  if (!tree || tree.length === 0) {
    return (
      <div style={{ padding: '16px', color: '#57606a' }}>
        No pipeline data available for this analysis. This is an older record from before pipeline
        tracking was implemented — re-run the analysis to see the pipeline tree.
      </div>
    );
  }

  return (
    <div ref={containerRef} style={{ padding: '0 0 16px 0' }}>
      <div style={{ height: 24, marginBottom: 6, display: 'flex', alignItems: 'center' }}>
        {isLive === true && (
          <>
            <span style={{
              width: 8, height: 8, borderRadius: '50%',
              background: '#d4a72c', flexShrink: 0, display: 'inline-block',
              marginRight: 6,
              animation: 'pipeline-pulse 1.2s ease-in-out infinite',
            }} />
            <span style={{ fontSize: 12, color: '#9a6700' }}>Live — updating every 3s</span>
          </>
        )}
        {isLive === false && (
          <>
            <span style={{ fontSize: 12, color: '#3fb950', marginRight: 5 }}>✓</span>
            <span style={{ fontSize: 12, color: '#57606a' }}>Pipeline completed</span>
          </>
        )}
      </div>
      {tree.map(root => (
        <PipelineNode key={root.id} node={root} depth={0} onCallClick={handleCallClick} onNavigate={handleNavigate} />
      ))}
      <LLMCallDetails
        call={selectedCall}
        show={showCallDetails}
        onHide={() => setShowCallDetails(false)}
      />
    </div>
  );
}

export default PipelineTreeView;
