import React, { useEffect, useState } from 'react';
import { useParams, Link, useNavigate } from 'react-router-dom';
import LLMCallListItem from '../components/LLMCallListItem';
import LLMCallDetails from '../components/LLMCallDetails';
import PipelineTreeView from '../components/PipelineTreeView';
import { fetchPaperAnalysis, fetchAnalysisById } from '../services/apiServices';

function PaperAnalysisPage() {
  const { paperId, analysisId } = useParams();
  const navigate = useNavigate();
  const [analysis, setAnalysis] = useState(null);
  const [analyses, setAnalyses] = useState([]);
  const [selectedAnalysisId, setSelectedAnalysisId] = useState(null);
  const [loading, setLoading] = useState(true);
  const [selectedCall, setSelectedCall] = useState(null);
  const [showDetails, setShowDetails] = useState(false);
  const [viewMode, setViewMode] = useState('pipeline');
  const [sortField, setSortField] = useState('created_at');
  const [sortDir, setSortDir] = useState('asc');
  const [brkSort, setBrkSort] = useState({ field: 'cost', dir: 'desc' });

  const handleSort = (field) => {
    if (sortField === field) {
      setSortDir(d => d === 'asc' ? 'desc' : 'asc');
    } else {
      setSortField(field);
      setSortDir('asc');
    }
  };

  const sortIndicator = (field) => {
    if (sortField !== field) return '';
    return sortDir === 'asc' ? ' ↑' : ' ↓';
  };

  const getSortValue = (call, field) => {
    switch (field) {
      case 'call_type': return call.call_type || '';
      case 'model_name': return call.model_name || '';
      case 'total_tokens': return call.total_tokens || 0;
      case 'estimated_cost_usd': return parseFloat(call.estimated_cost_usd || 0);
      case 'duration_ms': return call.duration_ms || 0;
      case 'created_at': return new Date(call.created_at).getTime();
      default: return 0;
    }
  };

  const sortedCalls = analysis?.llm_calls
    ? [...analysis.llm_calls].sort((a, b) => {
        const aVal = getSortValue(a, sortField);
        const bVal = getSortValue(b, sortField);
        const cmp = typeof aVal === 'string' ? aVal.localeCompare(bVal) : aVal - bVal;
        return sortDir === 'asc' ? cmp : -cmp;
      })
    : [];

  const totalCost = sortedCalls.reduce((sum, c) => sum + parseFloat(c.estimated_cost_usd || 0), 0);
  const totalTokens = sortedCalls.reduce((sum, c) => sum + (c.total_tokens || 0), 0);
  const totalDurationMs = sortedCalls.reduce((sum, c) => sum + (c.duration_ms || 0), 0);
  const totalDuration = totalDurationMs >= 1000
    ? `${(totalDurationMs / 1000).toFixed(1)}s`
    : `${totalDurationMs}ms`;

  // Group stats by call_type
  const typeStats = sortedCalls.reduce((acc, c) => {
    const t = c.call_type || 'unknown';
    if (!acc[t]) acc[t] = { count: 0, cost: 0 };
    acc[t].count += 1;
    acc[t].cost += parseFloat(c.estimated_cost_usd || 0);
    return acc;
  }, {});
  const handleBrkSort = (field) => {
    setBrkSort(prev => prev.field === field
      ? { field, dir: prev.dir === 'asc' ? 'desc' : 'asc' }
      : { field, dir: 'desc' }
    );
  };
  const brkIndicator = (field) => {
    if (brkSort.field !== field) return '';
    return brkSort.dir === 'asc' ? ' ↑' : ' ↓';
  };
  const typeEntries = Object.entries(typeStats).sort((a, b) => {
    let cmp;
    if (brkSort.field === 'type') cmp = a[0].localeCompare(b[0]);
    else if (brkSort.field === 'count') cmp = a[1].count - b[1].count;
    else cmp = a[1].cost - b[1].cost;
    return brkSort.dir === 'asc' ? cmp : -cmp;
  });
  const maxCount = Math.max(...typeEntries.map(([, s]) => s.count), 1);
  const maxCost = Math.max(...typeEntries.map(([, s]) => s.cost), 0.0001);

  const typeBadgeColor = (t) => {
    if (t === 'paper_analysis') return { bg: '#ddf4ff', fg: '#0969da' };
    if (t === 'structure_analysis') return { bg: '#fbefff', fg: '#8250df' };
    if (t.includes('normalization')) return { bg: '#dafbe1', fg: '#1a7f37' };
    if (t.includes('instrument')) return { bg: '#fff8c5', fg: '#9a6700' };
    return { bg: '#eaeef2', fg: '#656d76' };
  };

  const getConfigDisplayName = (name) => {
    if (!name) return 'Legacy';
    return name.charAt(0).toUpperCase() + name.slice(1);
  };

  const handleCallClick = (call) => {
    setSelectedCall(call);
    setShowDetails(true);
  };

  const handleAnalysisSelection = (selected) => {
    setAnalysis(selected);
    setSelectedAnalysisId(selected.id);
    navigate(`/analyses/${selected.id}`);
  };

  useEffect(() => {
    const loadData = async () => {
      try {
        if (analysisId) {
          const data = await fetchAnalysisById(analysisId);
          setAnalysis(data);
          setSelectedAnalysisId(analysisId);
        } else if (paperId) {
          const data = await fetchPaperAnalysis(paperId);
          setAnalyses(data);
          if (data.length > 0) {
            const std = data.find(a => a.configuration_name === 'standard');
            const selected = std || data[0];
            setAnalysis(selected);
            setSelectedAnalysisId(selected.id);
          }
        }
      } catch (error) {
        console.error('Failed to fetch analysis data:', error);
      } finally {
        setLoading(false);
      }
    };
    loadData();
  }, [paperId, analysisId]);

  if (loading) {
    return (
      <div className="vq-container">
        <div className="vo-breadcrumb">
          <span className="vo-skeleton vo-skeleton-text" style={{ width: '200px' }} />
        </div>
        <div className="vo-skeleton vo-skeleton-text" style={{ width: '120px', height: '1.5rem', marginBottom: '1rem' }} />
        <div className="vq-list">
          <div className="vq-list-header lc-grid-cols">
            <span>Type</span><span>Model</span><span>Tokens</span>
            <span style={{ textAlign: 'right' }}>Cost</span>
            <span style={{ textAlign: 'right' }}>Duration</span>
            <span style={{ textAlign: 'right' }}>Time</span>
          </div>
          {[1, 2, 3, 4].map(i => (
            <div key={i} className="vq-row lc-grid-cols">
              <span><span className="vo-skeleton vo-skeleton-text" style={{ width: '100px' }} /></span>
              <span><span className="vo-skeleton vo-skeleton-text" style={{ width: '80px' }} /></span>
              <span><span className="vo-skeleton vo-skeleton-text" style={{ width: '50px' }} /></span>
              <span><span className="vo-skeleton vo-skeleton-text" style={{ width: '50px' }} /></span>
              <span><span className="vo-skeleton vo-skeleton-text" style={{ width: '40px' }} /></span>
              <span><span className="vo-skeleton vo-skeleton-text" style={{ width: '60px' }} /></span>
            </div>
          ))}
        </div>
      </div>
    );
  }

  if (!analysis && (!analyses || analyses.length === 0)) {
    return (
      <div className="vq-container">
        <div className="lc-empty">No analysis found.</div>
      </div>
    );
  }

  const bibcode = analysis?.paper_bibcode || 'Analysis';
  const resolvedPaperId = paperId || analysis?.paper_id;

  return (
    <>
      <div className="vq-container">
        {/* Breadcrumb */}
        <div className="vo-breadcrumb">
          <Link to="/papers/validation-queue">Validate</Link>
          <span className="vo-breadcrumb-sep">/</span>
          {resolvedPaperId && (
            <>
              <Link to={`/papers/${resolvedPaperId}/validate`}>{bibcode}</Link>
              <span className="vo-breadcrumb-sep">/</span>
            </>
          )}
          <span>LLM Calls</span>
        </div>

        {/* Title + config info */}
        <div style={{ marginBottom: '12px' }}>
          <h2 style={{ fontSize: '20px', fontWeight: 400, color: '#1f2328', margin: '0 0 4px 0' }}>
            LLM Calls
          </h2>
          <div className="lc-summary" style={{ padding: '4px 0' }}>
            <span className="lc-type-badge lc-type-badge--default" style={{ fontWeight: 600 }}>
              {getConfigDisplayName(analysis?.configuration_name)}
            </span>
            {analysis?.created_at && (
              <span>Analyzed {new Date(analysis.created_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}</span>
            )}
          </div>
          {analyses.length > 1 && (
            <div className="lc-config-pills">
              {analyses.map(opt => (
                <button
                  key={opt.id}
                  className={`lc-config-pill ${selectedAnalysisId === opt.id ? 'lc-config-pill--active' : ''}`}
                  onClick={() => handleAnalysisSelection(opt)}
                >
                  {getConfigDisplayName(opt.configuration_name)}
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Summary stats */}
        {sortedCalls.length > 0 && (
          <div className="lc-summary">
            <span><strong>{sortedCalls.length}</strong> calls</span>
            <span><strong>${totalCost.toFixed(4)}</strong> total cost</span>
            <span><strong>{totalTokens.toLocaleString()}</strong> tokens</span>
            <span><strong>{totalDuration}</strong> total duration</span>
          </div>
        )}

        {/* Toolbar with view tabs */}
        <div className="vq-toolbar">
          <div className="vq-tabs">
            <button
              className={`vq-tab ${viewMode === 'pipeline' ? 'vq-tab--active' : ''}`}
              onClick={() => setViewMode('pipeline')}
            >
              Pipeline
            </button>
            <button
              className={`vq-tab ${viewMode === 'list' ? 'vq-tab--active' : ''}`}
              onClick={() => setViewMode('list')}
            >
              List
            </button>
            <button
              className={`vq-tab ${viewMode === 'summary' ? 'vq-tab--active' : ''}`}
              onClick={() => setViewMode('summary')}
            >
              Summary
            </button>
          </div>
        </div>

        {/* Content */}
        {viewMode === 'list' ? (
          <div className="vq-list">
            {sortedCalls.length > 0 ? (
              <>
                <div className="vq-list-header lc-grid-cols">
                  <span onClick={() => handleSort('call_type')} style={{ cursor: 'pointer' }}>
                    Type{sortIndicator('call_type')}
                  </span>
                  <span onClick={() => handleSort('model_name')} style={{ cursor: 'pointer' }}>
                    Model{sortIndicator('model_name')}
                  </span>
                  <span onClick={() => handleSort('total_tokens')} style={{ cursor: 'pointer', textAlign: 'right' }}>
                    Tokens{sortIndicator('total_tokens')}
                  </span>
                  <span onClick={() => handleSort('estimated_cost_usd')} style={{ cursor: 'pointer', textAlign: 'right' }}>
                    Cost{sortIndicator('estimated_cost_usd')}
                  </span>
                  <span onClick={() => handleSort('duration_ms')} style={{ cursor: 'pointer', textAlign: 'right' }}>
                    Duration{sortIndicator('duration_ms')}
                  </span>
                  <span onClick={() => handleSort('created_at')} style={{ cursor: 'pointer', textAlign: 'right' }}>
                    Time{sortIndicator('created_at')}
                  </span>
                </div>
                {sortedCalls.map(call => (
                  <LLMCallListItem key={call.id} call={call} onClick={handleCallClick} />
                ))}
              </>
            ) : (
              <div className="lc-empty">No LLM calls found for this analysis.</div>
            )}
          </div>
        ) : viewMode === 'summary' ? (
          <div>
            {/* Breakdown by call type */}
            {typeEntries.length > 0 && (
              <div className="lc-breakdown">
                <div className="lc-breakdown-header">
                  <span onClick={() => handleBrkSort('type')} style={{ cursor: 'pointer' }}>
                    Call type{brkIndicator('type')}
                  </span>
                  <span onClick={() => handleBrkSort('count')} style={{ cursor: 'pointer' }}>
                    Calls{brkIndicator('count')}
                  </span>
                  <span onClick={() => handleBrkSort('cost')} style={{ cursor: 'pointer' }}>
                    Cost{brkIndicator('cost')}
                  </span>
                </div>
                {typeEntries.map(([type, stats]) => {
                  const colors = typeBadgeColor(type);
                  return (
                    <div key={type} className="lc-breakdown-row">
                      <span>
                        <span className="lc-type-badge" style={{ background: colors.bg, color: colors.fg }}>
                          {type}
                        </span>
                      </span>
                      <span className="lc-breakdown-bar-cell">
                        <span className="lc-breakdown-bar" style={{ width: `${(stats.count / maxCount) * 100}%`, background: colors.fg, opacity: 0.2 }} />
                        <span className="lc-breakdown-val">{stats.count}</span>
                      </span>
                      <span className="lc-breakdown-bar-cell">
                        <span className="lc-breakdown-bar" style={{ width: `${(stats.cost / maxCost) * 100}%`, background: colors.fg, opacity: 0.2 }} />
                        <span className="lc-breakdown-val">${stats.cost.toFixed(4)}</span>
                      </span>
                    </div>
                  );
                })}
              </div>
            )}

            {/* Timeline */}
            {sortedCalls.length > 1 && (() => {
              const times = sortedCalls.map(c => new Date(c.created_at).getTime());
              const minT = Math.min(...times);
              const maxT = Math.max(...times);
              const range = maxT - minT || 1;
              const typeOrder = [...new Set(sortedCalls.map(c => c.call_type))];
              const formatTime = (ms) => {
                const d = new Date(ms);
                return d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
              };
              return (
                <div className="lc-timeline" style={{ marginTop: '16px' }}>
                  <div className="lc-timeline-header">
                    <span className="lc-timeline-label">Timeline</span>
                    <span className="lc-secondary">{formatTime(minT)} — {formatTime(maxT)}</span>
                  </div>
                  <div className="lc-timeline-body">
                    {typeOrder.map(type => {
                      const colors = typeBadgeColor(type);
                      const laneCalls = sortedCalls.filter(c => c.call_type === type);
                      return (
                        <div key={type} className="lc-timeline-lane">
                          <span className="lc-timeline-lane-label" style={{ color: colors.fg }}>{type}</span>
                          <div className="lc-timeline-track">
                            {laneCalls.map(call => {
                              const t = new Date(call.created_at).getTime();
                              const left = ((t - minT) / range) * 100;
                              const dur = call.duration_ms || 0;
                              const widthPct = Math.max((dur / range) * 100, 0.8);
                              return (
                                <div
                                  key={call.id}
                                  className="lc-timeline-bar"
                                  style={{
                                    left: `${left}%`,
                                    width: `${widthPct}%`,
                                    background: colors.fg,
                                  }}
                                  title={`${call.call_type} — ${call.model_name}\n${dur}ms · $${parseFloat(call.estimated_cost_usd || 0).toFixed(4)}`}
                                  onClick={() => handleCallClick(call)}
                                />
                              );
                            })}
                          </div>
                        </div>
                      );
                    })}
                    <div className="lc-timeline-ticks">
                      {[0, 0.25, 0.5, 0.75, 1].map(pct => (
                        <span key={pct} className="lc-timeline-tick" style={{ left: `${pct * 100}%` }}>
                          {formatTime(minT + pct * range)}
                        </span>
                      ))}
                    </div>
                  </div>
                </div>
              );
            })()}
          </div>
        ) : viewMode === 'pipeline' ? (
          <PipelineTreeView analysisId={selectedAnalysisId} />
        ) : null}
      </div>

      <LLMCallDetails
        call={selectedCall}
        show={showDetails}
        onHide={() => setShowDetails(false)}
      />
    </>
  );
}

export default PaperAnalysisPage;
