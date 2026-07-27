import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { Table, Spinner, Alert } from 'react-bootstrap';
import { fetchCostMonitoring, fetchPaperAnalysis } from '../services/apiServices';
import LLMCallDetails from './LLMCallDetails';

// ─── Formatters ───────────────────────────────────────────────────────────────

const fmtCost = (v) => {
  if (v == null) return 'N/A';
  if (v >= 0.01) return `$${v.toFixed(2)}`;
  if (v > 0) return '< $0.01';
  return '$0.00';
};

const fmtCostPrecise = (v) => {
  if (v == null) return 'N/A';
  if (v === 0) return '$0.0000';
  return `$${v.toFixed(4)}`;
};

const fmtTokens = (n) => {
  if (n == null) return '0';
  if (n >= 1e6) return `${(n / 1e6).toFixed(1)}M`;
  if (n >= 1e3) return `${(n / 1e3).toFixed(1)}k`;
  return String(n);
};

const fmtCount = (n) => {
  if (n >= 1e3) return `${(n / 1e3).toFixed(1)}k`;
  return String(n);
};

const fmtCallType = (ct) => ct.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());

// ─── Constants ────────────────────────────────────────────────────────────────

const STAGE_ORDER = ['Extraction', 'Grounding', 'Normalization', 'Other'];

const CONFIG_COLORS = {
  'standard': '#1976D2',
  'budget': '#43A047',
  'super-budget': '#FB8C00',
  'bedrock-test': '#8E24AA',
  'hybrid': '#00ACC1',
  'legacy': '#78909C',
};
const DEFAULT_COLOR = '#90A4AE';

const STAGE_COLORS = ['#1E88E5', '#43A047', '#FB8C00', '#8E24AA', '#00ACC1', '#546E7A'];

const NUM_BINS = 20;

// ─── Helpers ──────────────────────────────────────────────────────────────────

// Handle both old (plain number) and new (dict) paper_costs items
const costVal = (item) => (typeof item === 'object' && item !== null ? item.cost : item);
const bibcodeVal = (item) => (typeof item === 'object' && item !== null ? item.bibcode || '' : '');
const paperIdVal = (item) => (typeof item === 'object' && item !== null ? item.paper_id || '' : '');

// ─── Sub-components ───────────────────────────────────────────────────────────

/**
 * StageCallTypeTree — always-visible stage headers with all call type children.
 * Clicking a stage or call type row fires the provided callbacks.
 */
const fmtCallsPerPaper = (calls, papers) => {
  if (!papers || papers === 0) return '—';
  const v = calls / papers;
  return v % 1 === 0 ? String(v) : v.toFixed(1);
};

const StageCallTypeTree = ({ stages, totalCost, paperCount, activeStage, activeCallType, onStageClick, onCallTypeClick }) => {
  const sortedStages = [...stages].sort((a, b) => {
    const ai = STAGE_ORDER.indexOf(a.stage);
    const bi = STAGE_ORDER.indexOf(b.stage);
    return (ai === -1 ? 999 : ai) - (bi === -1 ? 999 : bi);
  });

  return (
    <div>
      {/* Stacked stage bar */}
      <div style={{ display: 'flex', height: '8px', borderRadius: '4px', overflow: 'hidden', background: '#e9ecef', marginBottom: '0.5rem' }}>
        {sortedStages.map((stage, i) => (
          stage.pct > 0 ? (
            <div
              key={stage.stage}
              style={{ width: `${stage.pct}%`, background: STAGE_COLORS[i % STAGE_COLORS.length], transition: 'width 0.3s', cursor: 'pointer' }}
              title={`${stage.stage}: ${stage.pct}%`}
              onClick={() => onStageClick(stage.stage)}
            />
          ) : null
        ))}
      </div>
      <Table size="sm" className="mb-0" style={{ fontSize: '0.78rem' }}>
        <thead className="table-light">
          <tr>
            <th style={{ width: '38%' }}>Stage / Call Type</th>
            <th style={{ width: '19%' }}>Cost</th>
            <th style={{ width: '12%' }}>Calls</th>
            <th style={{ width: '16%' }}>Calls/Paper</th>
            <th style={{ width: '15%', textAlign: 'right' }}>$/Call</th>
          </tr>
        </thead>
        <tbody>
          {sortedStages.map((stage, si) => {
            const stageColor = STAGE_COLORS[si % STAGE_COLORS.length];
            const isStageActive = activeStage === stage.stage && !activeCallType;
            const stageHasActiveCallType = activeCallType && (stage.breakdown || []).some(ct => ct.call_type === activeCallType);
            return (
              <React.Fragment key={stage.stage}>
                {/* Stage header */}
                <tr
                  onClick={() => onStageClick(stage.stage)}
                  style={{
                    cursor: 'pointer',
                    background: isStageActive ? `${stageColor}18` : stageHasActiveCallType ? `${stageColor}0a` : '#f1f3f5',
                    boxShadow: isStageActive ? `inset 3px 0 0 ${stageColor}` : undefined,
                  }}
                >
                  <td colSpan={5} style={{ padding: '3px 8px', borderLeft: `3px solid ${stageColor}` }}>
                    <strong style={{ fontSize: '0.79rem', color: isStageActive ? stageColor : '#343a40' }}>{stage.stage}</strong>
                    <span style={{ fontWeight: 400, color: '#6c757d', marginLeft: '0.5rem', fontSize: '0.72rem' }}>
                      {fmtCost(stage.cost_usd)} · {fmtCount(stage.calls)} calls · {fmtCallsPerPaper(stage.calls, paperCount)}/paper · {stage.pct?.toFixed(1)}% of total
                    </span>
                    {isStageActive && <span style={{ marginLeft: '0.4rem', fontSize: '0.65rem', color: stageColor }}>● selected</span>}
                  </td>
                </tr>
                {/* Call type rows */}
                {(stage.breakdown || []).map((ct) => {
                  const costPerCall = ct.calls > 0 ? ct.cost_usd / ct.calls : 0;
                  const isCtActive = activeCallType === ct.call_type;
                  return (
                    <tr
                      key={ct.call_type}
                      onClick={() => onCallTypeClick(ct.call_type, stage.stage)}
                      style={{
                        cursor: 'pointer',
                        background: isCtActive ? '#e3f2fd' : '#fff',
                        boxShadow: isCtActive ? 'inset 3px 0 0 #1E88E5' : undefined,
                      }}
                    >
                      <td style={{ paddingLeft: '1.5rem', color: isCtActive ? '#1565C0' : '#495057', fontWeight: isCtActive ? '600' : '400' }}>
                        {fmtCallType(ct.call_type)}
                        {isCtActive && <span style={{ marginLeft: '0.4rem', fontSize: '0.65rem', color: '#1E88E5' }}>● selected</span>}
                      </td>
                      <td style={{ color: '#343a40' }}>{fmtCost(ct.cost_usd)}</td>
                      <td style={{ color: '#6c757d' }}>{fmtCount(ct.calls)}</td>
                      <td style={{ color: '#6c757d' }}>{fmtCallsPerPaper(ct.calls, paperCount)}</td>
                      <td style={{ textAlign: 'right', color: '#6c757d' }}>{fmtCostPrecise(costPerCall)}</td>
                    </tr>
                  );
                })}
              </React.Fragment>
            );
          })}
          {sortedStages.length === 0 && (
            <tr>
              <td colSpan={5} className="text-center text-muted py-3">No stage data.</td>
            </tr>
          )}

        </tbody>
      </Table>
    </div>
  );
};

/**
 * MultiConfigHistogram — one or multiple config cost distributions on a shared axis.
 * Bins are clickable; a 95th-percentile marker line is drawn.
 */
const MultiConfigHistogram = ({ configs, overlay, selectedBin, onBinClick }) => {
  const [hoveredBin, setHoveredBin] = useState(null);

  const { series, maxCount, p95xPct } = useMemo(() => {
    if (!configs || configs.length === 0) return { series: [], maxCount: 0, p95xPct: null };

    const allCosts = configs
      .flatMap((c) => (c.paper_costs || []).map(costVal))
      .filter((v) => v != null && !isNaN(v));
    if (allCosts.length === 0) return { series: [], maxCount: 0, p95xPct: null };

    const globalMin = Math.min(...allCosts);
    const globalMax = Math.max(...allCosts);
    const range = globalMax - globalMin;
    const binWidth = range > 0 ? range / NUM_BINS : 1;
    const binEdges = Array.from({ length: NUM_BINS + 1 }, (_, i) => globalMin + i * binWidth);

    // 95th percentile position as % of grid width
    const sortedAll = [...allCosts].sort((a, b) => a - b);
    const p95val = sortedAll[Math.floor(sortedAll.length * 0.95)] ?? sortedAll[sortedAll.length - 1];
    const p95xPct = range > 0 ? Math.min(100, ((p95val - globalMin) / range) * 100) : null;

    let maxCount = 0;
    const series = configs.map((c) => {
      const costs = (c.paper_costs || []).map(costVal).filter((v) => v != null && !isNaN(v));
      const sorted = [...costs].sort((a, b) => a - b);
      const binCounts = Array(NUM_BINS).fill(0);
      for (const v of sorted) {
        let idx = range > 0 ? Math.floor((v - globalMin) / binWidth) : 0;
        if (idx >= NUM_BINS) idx = NUM_BINS - 1;
        binCounts[idx]++;
      }
      const mc = Math.max(...binCounts, 0);
      if (mc > maxCount) maxCount = mc;

      const mid = Math.floor(sorted.length / 2);
      const median =
        sorted.length > 0
          ? sorted.length % 2 === 0
            ? (sorted[mid - 1] + sorted[mid]) / 2
            : sorted[mid]
          : 0;

      return {
        config: c.configuration,
        displayName: c.display_name,
        color: CONFIG_COLORS[c.configuration] || DEFAULT_COLOR,
        bins: binCounts.map((count, i) => ({ count, low: binEdges[i], high: binEdges[i + 1] })),
        stats: { count: costs.length, median, min: sorted[0] ?? 0, max: sorted[sorted.length - 1] ?? 0 },
      };
    });

    return { series, maxCount, p95xPct };
  }, [configs]);

  if (series.length === 0) {
    return (
      <div style={{ height: 120, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#adb5bd', fontSize: '0.8rem', border: '1px dashed #dee2e6', borderRadius: '4px' }}>
        No distribution data
      </div>
    );
  }

  const showOverlay = overlay && series.length > 1;
  const activeBin = hoveredBin ?? selectedBin?.index ?? null;

  return (
    <div style={{ display: 'flex', flexDirection: 'column' }}>
      {/* Legend / stats */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.1rem 0.6rem', fontSize: '0.7rem', color: '#6c757d', marginBottom: '0.3rem' }}>
        {series.map((s) => (
          <span key={s.config} style={{ display: 'flex', alignItems: 'center', gap: '3px' }}>
            <span style={{ display: 'inline-block', width: '8px', height: '8px', borderRadius: '2px', background: s.color }} />
            {s.displayName}: n={s.stats.count}, med={fmtCost(s.stats.median)}
          </span>
        ))}
      </div>

      {/* Y-axis + bars */}
      <div style={{ display: 'flex', flex: '1 1 0', minHeight: '80px', gap: '3px' }}>
        <div style={{ display: 'flex', flexDirection: 'column', justifyContent: 'space-between', alignItems: 'flex-end', fontSize: '0.6rem', color: '#adb5bd', flexShrink: 0 }}>
          <span>{maxCount}</span>
          <span>{Math.round(maxCount / 2)}</span>
          <span>0</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'flex-end', gap: '1px', flex: '1 1 0', padding: '0 2px', background: '#fafafa', borderRadius: '4px', border: '1px solid #e9ecef', position: 'relative', cursor: 'pointer' }}>
          {Array.from({ length: NUM_BINS }, (_, i) => {
            const isSelected = selectedBin?.index === i;
            return (
              <div
                key={i}
                onMouseEnter={() => setHoveredBin(i)}
                onMouseLeave={() => setHoveredBin(null)}
                onClick={() => onBinClick(i, series[0]?.bins[i])}
                style={{
                  flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'flex-end',
                  alignItems: 'stretch', height: '100%', position: 'relative',
                  background: isSelected ? 'rgba(30,136,229,0.08)' : undefined,
                }}
              >
                {series.map((s) => {
                  const h = maxCount > 0 ? (s.bins[i].count / maxCount) * 92 : 0;
                  return s.bins[i].count > 0 ? (
                    <div
                      key={s.config}
                      style={{
                        position: 'absolute', bottom: 0, left: 0, right: 0,
                        height: `max(${h.toFixed(1)}%, 3px)`,
                        background: s.color,
                        opacity: activeBin === i ? 1 : (showOverlay ? 0.55 : 0.8),
                        borderRadius: '2px 2px 0 0',
                        transition: 'opacity 0.1s',
                      }}
                    />
                  ) : null;
                })}
              </div>
            );
          })}

          {/* 95th percentile marker */}
          {p95xPct !== null && (
            <div style={{ position: 'absolute', top: 0, bottom: 0, left: `${p95xPct}%`, width: '1px', background: '#e53935', pointerEvents: 'none', zIndex: 5 }}>
              <span style={{ position: 'absolute', top: '2px', left: '3px', fontSize: '0.55rem', color: '#e53935', whiteSpace: 'nowrap', fontWeight: 600 }}>p95</span>
            </div>
          )}

          {/* Tooltip */}
          {activeBin !== null && series[0]?.bins[activeBin] && (
            <div style={{ position: 'absolute', bottom: 'calc(100% + 4px)', left: `${((activeBin + 0.5) / NUM_BINS) * 100}%`, transform: 'translateX(-50%)', background: '#1f2328', color: '#fff', padding: '4px 8px', borderRadius: '4px', fontSize: '0.7rem', whiteSpace: 'nowrap', pointerEvents: 'none', zIndex: 10, lineHeight: 1.5 }}>
              <div>{fmtCost(series[0].bins[activeBin].low)}–{fmtCost(series[0].bins[activeBin].high)}</div>
              {series.map((s) => (
                <div key={s.config} style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                  <span style={{ width: '8px', height: '8px', borderRadius: '2px', background: s.color, display: 'inline-block' }} />
                  {s.displayName}: {s.bins[activeBin].count}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* X-axis */}
      <div style={{ display: 'flex', marginTop: '2px', paddingLeft: 'calc(1.5em + 3px)' }}>
        {Array.from({ length: NUM_BINS }, (_, i) => {
          const step = Math.max(1, Math.round(NUM_BINS / 5));
          const show = i === 0 || i === NUM_BINS - 1 || i % step === 0;
          return (
            <div key={i} style={{ flex: 1, fontSize: '0.6rem', color: '#adb5bd', textAlign: 'center', overflow: 'visible', whiteSpace: 'nowrap' }}>
              {show ? fmtCost(series[0]?.bins[i]?.low ?? 0) : ''}
            </div>
          );
        })}
      </div>
    </div>
  );
};

/**
 * BinPapersTable — papers falling in the selected histogram bin.
 */
const BinPapersTable = ({ papers, onRowClick }) => {
  if (papers.length === 0) return null;
  return (
    <Table size="sm" className="mb-0" style={{ fontSize: '0.75rem' }}>
      <thead className="table-light">
        <tr>
          <th style={{ width: '50%' }}>Bibcode</th>
          <th style={{ width: '30%' }}>Config</th>
          <th style={{ width: '20%', textAlign: 'right' }}>Cost</th>
        </tr>
      </thead>
      <tbody>
        {papers.map((item, idx) => {
          const color = CONFIG_COLORS[item.config] || DEFAULT_COLOR;
          return (
            <tr
              key={idx}
              onClick={() => onRowClick && onRowClick(item)}
              style={{ cursor: onRowClick ? 'pointer' : undefined }}
              title={onRowClick ? 'Click to view LLM call' : undefined}
            >
              <td style={{ fontFamily: 'monospace', fontSize: '0.68rem', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: 0 }}>
                {item.bibcode || item.paper_id || '–'}
              </td>
              <td>
                <span style={{ display: 'inline-block', width: '6px', height: '6px', borderRadius: '2px', background: color, marginRight: '4px' }} />
                {item.displayName}
              </td>
              <td style={{ textAlign: 'right' }}><strong>{fmtCost(item.cost)}</strong></td>
            </tr>
          );
        })}
      </tbody>
    </Table>
  );
};

/**
 * BatchSavingsKPI — estimated savings from using batch instead of real-time.
 * Formula: savings = (realtimeCost + batchCost * 2) - totalCost
 */
const BatchSavingsKPI = ({ batchCost, realtimeCost, totalCost }) => {
  const whatIfRealtime = realtimeCost + batchCost * 2;
  const savings = whatIfRealtime - totalCost;
  if (savings <= 0 || batchCost <= 0) return null;
  return (
    <div style={{ textAlign: 'center', lineHeight: 1.2 }}>
      <div style={{ fontWeight: '600', fontSize: '1.05rem', color: '#2e7d32' }}>~{fmtCost(savings)}</div>
      <div style={{ fontSize: '0.68rem', color: '#6c757d', textTransform: 'uppercase', letterSpacing: '0.03em' }}>Batch Savings</div>
      <div style={{ fontSize: '0.63rem', color: '#868e96', marginTop: '1px' }}>
        would cost {fmtCost(whatIfRealtime)} all real-time
      </div>
    </div>
  );
};

/**
 * AccordionSection — collapsible panel with summary line in header.
 */
const AccordionSection = ({ id, title, summary, isOpen, onToggle, children }) => (
  <div style={{ border: '1px solid #dee2e6', borderRadius: '6px', marginBottom: '0.5rem' }}>
    <div
      onClick={() => onToggle(id)}
      style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '0.45rem 0.75rem', cursor: 'pointer', background: isOpen ? '#f1f3f5' : '#fff', borderRadius: isOpen ? '6px 6px 0 0' : '6px' }}
    >
      <span style={{ fontWeight: '600', fontSize: '0.78rem', color: '#343a40' }}>{title}</span>
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
        {summary && <span style={{ fontSize: '0.7rem', color: '#6c757d' }}>{summary}</span>}
        <span style={{ fontSize: '0.7rem' }}>{isOpen ? '▲' : '▼'}</span>
      </div>
    </div>
    {isOpen && <div style={{ padding: '0.75rem', borderTop: '1px solid #dee2e6' }}>{children}</div>}
  </div>
);

// ─── Main Panel ───────────────────────────────────────────────────────────────

const CostMonitoringPanel = () => {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [activeConfig, setActiveConfig] = useState(null);
  const [activeStage, setActiveStage] = useState(null);
  const [activeCallType, setActiveCallType] = useState(null);
  const [overlayHistograms, setOverlayHistograms] = useState(false);
  const [configSort] = useState({ key: 'avg_cost_per_paper', direction: 'desc' });
  const [openAccordion, setOpenAccordion] = useState(null);
  const [selectedBin, setSelectedBin] = useState(null); // { index, low, high }
  const [callModal, setCallModal] = useState({ show: false, call: null, loading: false });

  const loadData = useCallback(() => {
    setLoading(true);
    setError(null);
    fetchCostMonitoring()
      .then((d) => setData(d))
      .catch(() => setError('Failed to load cost data'))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { loadData(); }, [loadData]);

  // ── All useMemo hooks — must be unconditional ──
  const sortedConfigs = useMemo(() => {
    const configs = data?.by_configuration ?? [];
    return [...configs].sort((a, b) => {
      const av = a[configSort.key] ?? 0, bv = b[configSort.key] ?? 0;
      const cmp = typeof av === 'string' ? av.localeCompare(bv) : av - bv;
      return configSort.direction === 'asc' ? cmp : -cmp;
    });
  }, [data, configSort]);

  const maxAvgCost = useMemo(() => {
    const configs = data?.by_configuration ?? [];
    return Math.max(...configs.map((c) => c.avg_cost_per_paper || 0), 0.000001);
  }, [data]);

  const activeConfigData = useMemo(() => {
    const configs = data?.by_configuration ?? [];
    return configs.find((c) => c.configuration === activeConfig) ?? null;
  }, [data, activeConfig]);

  const filteredStages = useMemo(
    () => activeConfigData?.by_stage ?? (data?.by_stage ?? []),
    [activeConfigData, data]
  );

  const displayConfigs = useMemo(() => {
    const by_configuration = data?.by_configuration ?? [];
    // Always scope to the selected config; overlay expands back to all
    const baseConfigs = (activeConfigData && !overlayHistograms)
      ? [activeConfigData]
      : by_configuration;

    if (activeCallType) {
      const result = baseConfigs.map((c) => ({
        ...c,
        paper_costs: (c.by_stage || []).flatMap((s) =>
          (s.breakdown || []).find((ct) => ct.call_type === activeCallType)?.paper_costs || []
        ),
      })).filter((c) => c.paper_costs.length > 0);
      // Fall back to config-level if per-calltype data not yet available (needs backend rebuild)
      return result.length > 0 ? result : baseConfigs.filter((c) => (c.paper_costs || []).length > 0);
    }

    if (activeStage) {
      const result = baseConfigs.map((c) => ({
        ...c,
        paper_costs: (c.by_stage || []).find((s) => s.stage === activeStage)?.paper_costs || [],
      })).filter((c) => c.paper_costs.length > 0);
      // Fall back to config-level if per-stage data not yet available (needs backend rebuild)
      return result.length > 0 ? result : baseConfigs.filter((c) => (c.paper_costs || []).length > 0);
    }

    // No stage/calltype — require a config selection or overlay
    if (!activeConfig && !overlayHistograms) return [];
    return baseConfigs.filter((c) => (c.paper_costs || []).length > 0);
  }, [overlayHistograms, activeConfig, activeConfigData, data, activeStage, activeCallType]);


  const binPapers = useMemo(() => {
    if (!selectedBin || displayConfigs.length === 0) return [];
    return displayConfigs.flatMap((c) =>
      (c.paper_costs || [])
        .map((item) => ({ cost: costVal(item), bibcode: bibcodeVal(item), paper_id: paperIdVal(item), config: c.configuration, displayName: c.display_name }))
        .filter((item) => item.cost != null && item.cost >= selectedBin.low && item.cost <= selectedBin.high)
    ).sort((a, b) => b.cost - a.cost);
  }, [selectedBin, displayConfigs]);

  // ── Early returns (after hooks) ──
  if (loading && !data) {
    return <div className="text-center py-4"><Spinner animation="border" size="sm" /> Loading costs...</div>;
  }
  if (error && !data) {
    return <Alert variant="danger">{error}</Alert>;
  }
  if (!data) return null;

  const { totals, by_mode, by_model, by_configuration = [] } = data;
  const totalCost = totals.total_cost_usd || 0;
  const batchCost = by_mode.batch.cost_usd || 0;
  const realtimeCost = by_mode.realtime.cost_usd || 0;
  const batchPct = totalCost > 0 ? (batchCost / totalCost) * 100 : 0;
  const realtimePct = totalCost > 0 ? (realtimeCost / totalCost) * 100 : 0;

  const toggleAccordion = (key) => setOpenAccordion((prev) => (prev === key ? null : key));

  const handleConfigClick = (config) => {
    setActiveConfig((prev) => (prev === config ? null : config));
    setActiveStage(null);
    setActiveCallType(null);
    setSelectedBin(null);
  };

  const handleStageClick = (stage) => {
    if (activeStage === stage && !activeCallType) {
      setActiveStage(null);
    } else {
      setActiveStage(stage);
      setActiveCallType(null);
    }
    setSelectedBin(null);
  };

  const handleBinClick = (index, bin) => {
    if (!bin) return;
    setSelectedBin((prev) => (prev?.index === index ? null : { index, low: bin.low, high: bin.high }));
  };

  const handleCallTypeClick = (callType, stage) => {
    if (activeCallType === callType) {
      setActiveCallType(null);
    } else {
      setActiveCallType(callType);
      setActiveStage(stage);
    }
    setSelectedBin(null);
  };

  const handleOutlierClick = async (item) => {
    if (!activeCallType || !item.paper_id) return;
    setCallModal({ show: true, call: null, loading: true });
    try {
      const analyses = await fetchPaperAnalysis(item.paper_id);
      let found = null;
      for (const analysis of analyses) {
        const call = (analysis.llm_calls || []).find((c) => c.call_type === activeCallType);
        if (call) { found = call; break; }
      }
      setCallModal({ show: true, call: found, loading: false });
    } catch {
      setCallModal((prev) => ({ ...prev, loading: false }));
    }
  };

  return (
    <div>
      {/* ── 1. Configuration Comparison Table ───────────────── */}
      {by_configuration.length > 0 && (
        <div className="mb-3">
          <div style={{ fontSize: '0.75rem', fontWeight: '600', color: '#495057', marginBottom: '0.4rem' }}>
            Configuration Comparison
            <span style={{ fontWeight: 400, color: '#868e96', marginLeft: '0.5rem', fontSize: '0.7rem' }}>click row to filter</span>
          </div>
          <Table size="sm" className="mb-0" style={{ fontSize: '0.82rem' }}>
            <thead className="table-light">
              <tr>
                <th style={{ width: '30%' }}>Configuration</th>
                <th style={{ width: '35%' }}>Avg/Paper</th>
                <th style={{ width: '20%' }}>Total Cost</th>
                <th style={{ width: '15%' }}>Papers</th>
              </tr>
            </thead>
            <tbody>
              {/* "All" row */}
              <tr
                onClick={() => { setActiveConfig(null); setActiveStage(null); setActiveCallType(null); }}
                style={{ cursor: 'pointer', background: activeConfig === null ? '#e3f2fd' : undefined, boxShadow: activeConfig === null ? 'inset 3px 0 0 #1E88E5' : undefined }}
              >
                <td colSpan={4} style={{ color: activeConfig === null ? '#1E88E5' : '#6c757d', fontWeight: activeConfig === null ? '600' : '400' }}>
                  All configurations
                </td>
              </tr>
              {sortedConfigs.map((c) => {
                const color = CONFIG_COLORS[c.configuration] || DEFAULT_COLOR;
                const isActive = activeConfig === c.configuration;
                const barPct = maxAvgCost > 0 ? (c.avg_cost_per_paper / maxAvgCost) * 100 : 0;
                return (
                  <tr
                    key={c.configuration}
                    onClick={() => handleConfigClick(c.configuration)}
                    style={{ cursor: 'pointer', background: isActive ? `${color}12` : undefined, boxShadow: isActive ? `inset 3px 0 0 ${color}` : undefined }}
                  >
                    <td>
                      <span style={{ display: 'inline-block', width: '8px', height: '8px', borderRadius: '2px', background: color, marginRight: '6px' }} />
                      <strong>{c.display_name}</strong>
                    </td>
                    <td>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                        <span style={{ flexShrink: 0 }}>{fmtCost(c.avg_cost_per_paper)}</span>
                        <div style={{ flex: 1, height: '4px', background: '#e9ecef', borderRadius: '2px', overflow: 'hidden' }}>
                          <div style={{ width: `${barPct}%`, height: '100%', background: color, borderRadius: '2px' }} />
                        </div>
                      </div>
                    </td>
                    <td>{fmtCost(c.cost_usd)}</td>
                    <td>{c.papers}</td>
                  </tr>
                );
              })}
            </tbody>
          </Table>
        </div>
      )}

      {/* ── 3. Main Grid ─────────────────────────────────────── */}
      <div style={{ display: 'flex', gap: '1rem', marginBottom: '0.75rem', flexWrap: 'wrap' }}>
        {/* Left — Stage/call-type tree */}
        <div style={{ flex: '55 1 300px', minWidth: 0 }}>
          <div style={{ fontSize: '0.75rem', fontWeight: '600', color: '#495057', marginBottom: '0.35rem' }}>
            Cost by Pipeline Stage
            {activeConfigData && (
              <span style={{ color: '#868e96', fontWeight: 400, marginLeft: '0.4rem' }}>
                — {activeConfigData.display_name}
              </span>
            )}
          </div>
          <StageCallTypeTree
            stages={filteredStages}
            totalCost={activeConfigData?.cost_usd ?? totalCost}
            paperCount={activeConfigData?.papers ?? totals.distinct_papers}
            activeStage={activeStage}
            activeCallType={activeCallType}
            onStageClick={handleStageClick}
            onCallTypeClick={handleCallTypeClick}
          />
        </div>

        {/* Right — Histogram + Outliers */}
        <div style={{ flex: '45 1 260px', minWidth: 0 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.35rem' }}>
            <span style={{ fontSize: '0.75rem', fontWeight: '600', color: '#495057' }}>
              Cost Distribution
              {activeCallType
                ? ` — ${fmtCallType(activeCallType)}`
                : activeStage
                ? ` — ${activeStage}`
                : activeConfigData
                ? ` — ${activeConfigData.display_name}`
                : displayConfigs.length > 1 ? ' (All Configs)' : ''}
            </span>
            {by_configuration.length > 1 && (
              <div style={{ display: 'flex', gap: '0.3rem' }}>
                {[['Selected', false], ['Overlay all', true]].map(([label, val]) => (
                  <button
                    key={label}
                    onClick={() => setOverlayHistograms(val)}
                    style={{
                      fontSize: '0.65rem', padding: '0.1rem 0.45rem', borderRadius: '10px', cursor: 'pointer',
                      border: overlayHistograms === val ? '1.5px solid #1E88E5' : '1px solid #dee2e6',
                      background: overlayHistograms === val ? '#e3f2fd' : '#fff',
                      color: overlayHistograms === val ? '#1E88E5' : '#6c757d',
                    }}
                  >
                    {label}
                  </button>
                ))}
              </div>
            )}
          </div>

          {displayConfigs.length > 0 ? (
            <MultiConfigHistogram
              configs={displayConfigs}
              overlay={overlayHistograms}
              selectedBin={selectedBin}
              onBinClick={handleBinClick}
            />
          ) : (
            <div style={{ height: 120, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#adb5bd', fontSize: '0.8rem', border: '1px dashed #dee2e6', borderRadius: '4px' }}>
              Select a config, stage, or call type
            </div>
          )}

          {/* Bin papers table */}
          <div style={{ marginTop: '0.75rem', minHeight: '2rem' }}>
            {selectedBin ? (
              <>
                <div style={{ fontSize: '0.72rem', color: '#6c757d', marginBottom: '0.3rem' }}>
                  {fmtCost(selectedBin.low)}–{fmtCost(selectedBin.high)}
                  <span style={{ marginLeft: '0.5rem', color: '#adb5bd' }}>· {binPapers.length} paper{binPapers.length !== 1 ? 's' : ''}</span>
                  <button onClick={() => setSelectedBin(null)} style={{ marginLeft: '0.5rem', background: 'none', border: 'none', color: '#adb5bd', cursor: 'pointer', fontSize: '0.7rem', padding: 0 }}>✕</button>
                </div>
                <BinPapersTable papers={binPapers} onRowClick={activeCallType ? handleOutlierClick : null} />
              </>
            ) : displayConfigs.length > 0 ? (
              <div style={{ fontSize: '0.72rem', color: '#adb5bd' }}>Click a bar to see papers in that range</div>
            ) : null}
          </div>
        </div>
      </div>

      {/* ── 4. Secondary Panels ─────────────────────────────── */}
      <AccordionSection
        id="batch"
        title="Batch Detail"
        summary={`${batchPct.toFixed(0)}% batch · ${fmtCost(batchCost)}`}
        isOpen={openAccordion === 'batch'}
        onToggle={toggleAccordion}
      >
        <div style={{ fontSize: '0.78rem' }}>
          <div style={{ display: 'flex', height: '8px', borderRadius: '4px', overflow: 'hidden', background: '#e9ecef', marginBottom: '0.4rem' }}>
            {batchPct > 0 && <div style={{ width: `${batchPct}%`, background: '#1976D2' }} />}
            {realtimePct > 0 && <div style={{ width: `${realtimePct}%`, background: '#FB8C00' }} />}
          </div>
          <div className="d-flex justify-content-between">
            <div>
              <span style={{ display: 'inline-block', width: '8px', height: '8px', borderRadius: '2px', background: '#1976D2', marginRight: '4px' }} />
              Batch: {fmtCost(batchCost)} ({fmtCount(by_mode.batch.calls)} calls, {batchPct.toFixed(0)}%)
            </div>
            <div>
              <span style={{ display: 'inline-block', width: '8px', height: '8px', borderRadius: '2px', background: '#FB8C00', marginRight: '4px' }} />
              Real-time: {fmtCost(realtimeCost)} ({fmtCount(by_mode.realtime.calls)} calls, {realtimePct.toFixed(0)}%)
            </div>
          </div>
          {by_configuration.length > 0 && (
            <div style={{ marginTop: '0.6rem' }}>
              <div style={{ fontSize: '0.72rem', fontWeight: '600', color: '#6c757d', marginBottom: '0.25rem' }}>Per configuration</div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.4rem' }}>
                {by_configuration.map((c) => {
                  const color = CONFIG_COLORS[c.configuration] || DEFAULT_COLOR;
                  const paperCosts = (c.paper_costs || []).map(costVal);
                  const configBatchPct = c.cost_usd > 0 ? ((batchCost / totalCost) * 100).toFixed(0) : 'N/A';
                  return (
                    <div key={c.configuration} style={{ fontSize: '0.7rem', display: 'flex', alignItems: 'center', gap: '4px' }}>
                      <span style={{ display: 'inline-block', width: '7px', height: '7px', borderRadius: '2px', background: color }} />
                      <span>{c.display_name}:</span>
                      <span style={{ color: '#495057' }}>{fmtCost(c.cost_usd)} · {c.papers} papers · {fmtCost(c.avg_cost_per_paper)}/paper</span>
                      {paperCosts.length > 0 && (
                        <span style={{ color: '#868e96' }}>
                          (n={paperCosts.length})
                        </span>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      </AccordionSection>

      <AccordionSection
        id="models"
        title="Model Efficiency"
        summary={`${by_model.length} model${by_model.length !== 1 ? 's' : ''}`}
        isOpen={openAccordion === 'models'}
        onToggle={toggleAccordion}
      >
        <Table size="sm" className="mb-0" style={{ fontSize: '0.78rem' }}>
          <thead className="table-light">
            <tr>
              <th style={{ width: '26%' }}>Model</th>
              <th style={{ width: '16%' }}>Cost</th>
              <th style={{ width: '9%' }}>Calls</th>
              <th style={{ width: '13%' }}>Prompt</th>
              <th style={{ width: '16%' }}>Completion</th>
              <th style={{ width: '12%' }}>$/1k tok</th>
              <th style={{ width: '8%', textAlign: 'right' }}>%</th>
            </tr>
          </thead>
          <tbody>
            {by_model.map((m) => {
              const totalTok = (m.prompt_tokens || 0) + (m.completion_tokens || 0);
              const costPer1k = totalTok > 0 ? (m.cost_usd / totalTok) * 1000 : 0;
              const completionRatio = totalTok > 0 ? ((m.completion_tokens || 0) / totalTok * 100).toFixed(0) : '0';
              return (
                <tr key={m.model_name}>
                  <td><strong>{m.display_name}</strong></td>
                  <td>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                      <span>{fmtCost(m.cost_usd)}</span>
                      <div style={{ flex: 1, height: '4px', background: '#e9ecef', borderRadius: '2px', overflow: 'hidden' }}>
                        <div style={{ width: `${m.pct}%`, height: '100%', background: '#1E88E5', borderRadius: '2px' }} />
                      </div>
                    </div>
                  </td>
                  <td>{fmtCount(m.calls)}</td>
                  <td>{fmtTokens(m.prompt_tokens)}</td>
                  <td>
                    {fmtTokens(m.completion_tokens)}{' '}
                    <span style={{ color: '#868e96', fontSize: '0.65rem' }}>({completionRatio}%)</span>
                  </td>
                  <td style={{ color: costPer1k > 0.01 ? '#c92a2a' : '#2e7d32' }}>{fmtCost(costPer1k)}</td>
                  <td style={{ textAlign: 'right' }}>{m.pct.toFixed(1)}%</td>
                </tr>
              );
            })}
            {by_model.length === 0 && (
              <tr><td colSpan={7} className="text-center text-muted py-3">No model data.</td></tr>
            )}
          </tbody>
        </Table>
      </AccordionSection>

      <LLMCallDetails
        call={callModal.call}
        show={callModal.show}
        loading={callModal.loading}
        onHide={() => setCallModal({ show: false, call: null, loading: false })}
      />
    </div>
  );
};

export default CostMonitoringPanel;
