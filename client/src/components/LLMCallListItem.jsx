import React from 'react';

const LLMCallListItem = ({ call, onClick }) => {
  const getTypeBadgeClass = (callType) => {
    if (callType === 'paper_analysis') return 'lc-type-badge--paper-analysis';
    if (callType === 'structure_analysis') return 'lc-type-badge--structure-analysis';
    if (callType.includes('normalization')) return 'lc-type-badge--normalization';
    if (callType.includes('instrument')) return 'lc-type-badge--instrument';
    return 'lc-type-badge--default';
  };

  const getStatusDotClass = () => {
    const cost = parseFloat(call.estimated_cost_usd || 0);
    if (cost === 0) return 'lc-status-dot--error';
    if (call.duration_ms > 10000) return 'lc-status-dot--slow';
    return 'lc-status-dot--ok';
  };

  const formatDuration = (ms) => {
    if (!ms) return '—';
    return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`;
  };

  const ts = new Date(call.created_at);
  const dateStr = ts.toLocaleDateString('en-US', { month: 'short', day: 'numeric', timeZone: 'UTC' });
  const timeStr = ts.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'UTC' });

  return (
    <div className="vq-row lc-grid-cols" onClick={() => onClick(call)}>
      <div className="lc-cell-type">
        <span className={`lc-status-dot ${getStatusDotClass()}`} />
        <span className={`lc-type-badge ${getTypeBadgeClass(call.call_type)}`}>
          {call.call_type}
        </span>
      </div>

      <div className="lc-cell-stacked">
        <span className="lc-primary">{call.model_name}</span>
        <span className="lc-secondary">{call.provider}</span>
      </div>

      <div className="lc-cell-stacked" style={{ alignItems: 'flex-end' }}>
        <span className="lc-primary" style={{ fontVariantNumeric: 'tabular-nums' }}>
          {(call.total_tokens || 0).toLocaleString()}
        </span>
        <span className="lc-secondary" style={{ fontVariantNumeric: 'tabular-nums' }}>
          {(call.prompt_tokens || 0).toLocaleString()} / {(call.completion_tokens || 0).toLocaleString()}
        </span>
      </div>

      <div className="lc-num lc-num--bold">
        ${parseFloat(call.estimated_cost_usd || 0).toFixed(4)}
      </div>

      <div className="lc-num">
        {formatDuration(call.duration_ms)}
      </div>

      <div className="lc-cell-stacked" style={{ alignItems: 'flex-end' }}>
        <span className="lc-secondary" style={{ fontSize: '13px', color: '#1f2328' }}>{dateStr}</span>
        <span className="lc-secondary">{timeStr}</span>
      </div>
    </div>
  );
};

export default LLMCallListItem;
