// src/components/ContribHeatmap.jsx
import React from 'react';

// Simple GitHub-style contribution heatmap
// props:
// - data: array of daily counts (length = weeks*7)
// - startDate: ISO date string for first cell
// - title: optional string shown above
// - max: maximum value for scaling (optional)
// - size: square size in px (default 12)
// - gap: gap between squares in px (default 2)
export default function ContribHeatmap({ data = [], startDate, title = 'Activity', max, size = 12, gap = 2 }) {
  const days = data.length;
  const weeks = Math.ceil(days / 7);
  const computedMax = max || Math.max(1, ...data);

  const colorFor = (value) => {
    if (!value) return '#ebedf0'; // empty
    const ratio = Math.min(1, value / computedMax);
    // 4-step green scale similar to GitHub
    if (ratio < 0.25) return '#9be9a8';
    if (ratio < 0.5) return '#40c463';
    if (ratio < 0.75) return '#30a14e';
    return '#216e39';
  };

  // Build grid by columns (weeks)
  const columns = [];
  const start = startDate ? new Date(startDate) : null;
  for (let w = 0; w < weeks; w++) {
    const col = [];
    for (let d = 0; d < 7; d++) {
      const index = w * 7 + d;
      if (index >= days) break;
      const val = data[index] || 0;
      const cellDate = start ? new Date(start.getFullYear(), start.getMonth(), start.getDate() + index) : null;
      const dateLabel = cellDate ? cellDate.toLocaleDateString() : `day ${index + 1}`;
      const style = {
        display: 'inline-block',
        width: size,
        height: size,
        backgroundColor: colorFor(val),
        borderRadius: 2,
        verticalAlign: 'top',
      };
      const label = `${val} on ${dateLabel}`;
      col.push(
        <abbr
          key={index}
          className="contrib-cell"
          title={label}
          aria-label={label}
          style={style}
        />
      );
    }
    columns.push(
      <div key={w} className="contrib-col" style={{ display: 'flex', flexDirection: 'column', gap }}>
        {col}
      </div>
    );
  }

  return (
    <div className="contrib-heatmap">
      {title && <div className="mb-2 small text-muted">{title}</div>}
      <div className="contrib-grid" style={{ display: 'flex', gap }}>
        {columns}
      </div>
    </div>
  );
}
