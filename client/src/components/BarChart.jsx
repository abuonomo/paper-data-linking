// src/components/BarChart.jsx
import React, { useMemo } from 'react';

// Lightweight SVG bar chart with day-based x-axis
// props:
// - data: number[] (counts per day)
// - startDate: ISO string for first day
// - height: chart height (default 80)
// - barWidth: px width per bar (default 6)
// - gap: px gap between bars (default 2)
// - title: optional label displayed above
export default function BarChart({
  data = [],            // backward compatible: single series (claims)
  seriesA = [],         // primary series (e.g., claims)
  seriesB = [],         // secondary series (e.g., papers)
  startDate,
  height = 80,
  barWidth = 6,
  gap = 2,              // gap between day groups
  title,
  labelA = 'Claims',
  labelB = 'Papers',
  colorA = '#4a90e2',
  colorB = '#30a14e',
  minInnerWidth = 0,
}) {
  // Determine series to render (support old prop `data` as seriesA)
  const hasB = Array.isArray(seriesB) && seriesB.length > 0;
  const a = (seriesA && seriesA.length ? seriesA : data) || [];
  const b = hasB ? seriesB : [];
  const len = Math.max(a.length, b.length);

  const max = Math.max(1, ...(a), ...(b.length ? b : [0]));
  // For grouped bars: compute inner width by group size
  const seriesCount = hasB ? 2 : 1;
  const innerGap = seriesCount > 1 ? Math.max(2, Math.floor(barWidth / 3)) : 0; // gap between bars within a group
  const groupSpan = seriesCount * barWidth + (seriesCount - 1) * innerGap;
  const innerWidth = Math.max(minInnerWidth, Math.max(0, len * (groupSpan + gap) - gap));
  const innerHeight = height;
  // Margins for axes and labels
  const margin = { top: 8, right: 12, bottom: 26, left: 36 };
  const svgWidth = innerWidth + margin.left + margin.right;
  const svgHeight = innerHeight + margin.top + margin.bottom;

  // Parse YYYY-MM-DD as a local date (avoid UTC shift)
  const parseISODateLocal = (iso) => {
    if (!iso) return null;
    const parts = String(iso).split('-').map(Number);
    if (parts.length < 3 || parts.some(isNaN)) return null;
    return new Date(parts[0], parts[1] - 1, parts[2]);
  };

  const ticks = useMemo(() => {
    const out = [];
    if (!startDate) return out;
    const start = parseISODateLocal(startDate);
    for (let i = 0; i < len; i++) {
      // For short ranges (<=14 days), tick every day; otherwise, weekly ticks
      const tickEveryDay = len <= 14;
      if (tickEveryDay || i % 7 === 0) {
        const d = new Date(start.getFullYear(), start.getMonth(), start.getDate() + i);
        const label = len <= 7 ? d.toLocaleDateString(undefined, { weekday: 'short' }) : d.toLocaleDateString();
        out.push({ i, label });
      }
    }
    return out;
  }, [len, startDate]);

  // Build y-axis ticks (nice 4-5 ticks)
  const yTicks = useMemo(() => {
    const desired = 4;
    const step = Math.max(1, Math.ceil(max / desired));
    const ticks = [];
    for (let v = 0; v <= max; v += step) ticks.push(v);
    if (ticks[ticks.length - 1] !== max) ticks.push(max);
    return ticks;
  }, [max]);

  return (
    <div className="bar-chart" style={{ display: 'inline-block', border: '1px solid #e9ecef', borderRadius: 6, padding: 8, background: '#fff' }}>
      <div className="d-flex align-items-center gap-3 mb-1">
        {title && <div className="small text-muted">{title}</div>}
        {hasB && (
          <div className="d-flex align-items-center gap-3 small text-muted">
            <span className="d-inline-flex align-items-center"><span style={{ display: 'inline-block', width: 10, height: 10, background: colorA, borderRadius: 2, marginRight: 6 }}></span>{labelA}</span>
            <span className="d-inline-flex align-items-center"><span style={{ display: 'inline-block', width: 10, height: 10, background: colorB, borderRadius: 2, marginRight: 6 }}></span>{labelB}</span>
          </div>
        )}
      </div>
      <div style={{ overflowX: 'auto' }}>
        <svg width={svgWidth} height={svgHeight} role="img" aria-label={title || 'Bar chart'}>
          {/* Plot background */}
          <rect x={margin.left} y={margin.top} width={innerWidth} height={innerHeight} fill="#f8f9fa" rx="4" />

          {/* Grid lines + y-axis labels */}
          {yTicks.map((t, idx) => {
            const y = margin.top + innerHeight - (t / max) * innerHeight;
            return (
              <g key={`yt-${idx}`}>
                <line x1={margin.left} y1={y} x2={margin.left + innerWidth} y2={y} stroke="#e9ecef" />
                <text x={margin.left - 6} y={y + 3} fontSize="10" fill="#6c757d" textAnchor="end">{t}</text>
              </g>
            );
          })}

          {/* Vertical grid lines per day */}
          {Array.from({ length: len }).map((_, i) => {
            const groupX = margin.left + i * (groupSpan + gap);
            const cx = groupX + groupSpan / 2;
            return <line key={`xg-${i}`} x1={cx} y1={margin.top} x2={cx} y2={margin.top + innerHeight} stroke="#f1f3f5" />;
          })}

          {/* Bars */}
          {Array.from({ length: len }).map((_, i) => {
            const vA = a[i] || 0;
            const vB = hasB ? (b[i] || 0) : 0;
            const groupX = margin.left + i * (groupSpan + gap);
            const d0 = parseISODateLocal(startDate);
            const dateLabel = d0 ? new Date(d0.getFullYear(), d0.getMonth(), d0.getDate() + i).toLocaleDateString() : `day ${i + 1}`;

            const bars = [];
            // Series A
            const hA = Math.round((vA / max) * innerHeight);
            const yA = margin.top + innerHeight - hA;
            bars.push(
              <g key={`a-${i}`}>
                <title>{`${labelA}: ${vA} on ${dateLabel}`}</title>
                <rect x={groupX} y={yA} width={barWidth} height={hA} fill={colorA} rx="1" ry="1" />
              </g>
            );
            if (hasB) {
              const hB = Math.round((vB / max) * innerHeight);
              const yB = margin.top + innerHeight - hB;
              const xB = groupX + barWidth + innerGap;
              bars.push(
                <g key={`b-${i}`}>
                  <title>{`${labelB}: ${vB} on ${dateLabel}`}</title>
                  <rect x={xB} y={yB} width={barWidth} height={hB} fill={colorB} rx="1" ry="1" />
                </g>
              );
            }
            return bars;
          })}

          {/* X-axis baseline */}
          <line x1={margin.left} y1={margin.top + innerHeight} x2={margin.left + innerWidth} y2={margin.top + innerHeight} stroke="#bbb" />

          {/* X-axis ticks */}
          {ticks.map(t => {
            const groupX = margin.left + t.i * (groupSpan + gap);
            const cx = groupX + groupSpan / 2;
            return (
              <g key={t.i}>
                <line x1={cx} y1={margin.top + innerHeight} x2={cx} y2={margin.top + innerHeight + 4} stroke="#bbb" />
                <text x={cx} y={margin.top + innerHeight + 14} fontSize="10" fill="#6c757d" textAnchor="middle">{t.label}</text>
              </g>
            );
          })}
        </svg>
      </div>
    </div>
  );
}
