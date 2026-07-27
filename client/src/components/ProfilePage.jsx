import React, { useState, useEffect, useMemo } from 'react';
import { Spinner } from 'react-bootstrap';
import { fetchValidationStats, fetchUserProfile } from '../services/apiServices';

// ─── Heatmap constants ────────────────────────────────────────────────────────

const HEATMAP_COLORS = ['#ebedf0', '#9be9a8', '#40c463', '#30a14e', '#216e39'];
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const CELL = 12;
const GAP = 2;
const NUM_WEEKS = 52;

const colorLevel = (count) => {
  if (!count || count === 0) return 0;
  if (count <= 2) return 1;
  if (count <= 5) return 2;
  if (count <= 10) return 3;
  return 4;
};

// ─── ValidationHeatmap ────────────────────────────────────────────────────────

const ValidationHeatmap = ({ heatmap }) => {
  const [tooltip, setTooltip] = useState(null); // { cell, x, y }

  // Build a grid of 52 weeks × 7 days (Sun–Sat), newest on the right
  const weeks = useMemo(() => {
    if (!heatmap || heatmap.length === 0) return [];
    const byDate = {};
    for (const item of heatmap) byDate[item.date] = item.count;

    const today = new Date();
    today.setHours(0, 0, 0, 0);
    // Align to Saturday (end of current week, so newest column ends today-or-this-week)
    const endSunday = new Date(today);
    endSunday.setDate(today.getDate() - today.getDay() + 6); // this Saturday

    // Start 52 weeks before the Sunday of that week
    const startSunday = new Date(endSunday);
    startSunday.setDate(endSunday.getDate() - (NUM_WEEKS * 7 - 1));

    const ws = [];
    let cur = new Date(startSunday);
    for (let w = 0; w < NUM_WEEKS; w++) {
      const week = [];
      for (let d = 0; d < 7; d++) {
        const dateStr = cur.toISOString().split('T')[0];
        week.push({ date: dateStr, count: byDate[dateStr] || 0 });
        cur.setDate(cur.getDate() + 1);
      }
      ws.push(week);
    }
    return ws;
  }, [heatmap]);

  // Month labels: place label on the first week of each new month
  const monthLabels = useMemo(() => {
    const labels = [];
    let lastMonth = null;
    weeks.forEach((week, i) => {
      const month = new Date(week[0].date + 'T00:00:00').getMonth();
      if (month !== lastMonth) {
        labels.push({ weekIndex: i, label: MONTHS[month] });
        lastMonth = month;
      }
    });
    return labels;
  }, [weeks]);

  const totalContributions = useMemo(
    () => (heatmap || []).reduce((s, d) => s + d.count, 0),
    [heatmap]
  );

  if (!heatmap || heatmap.length === 0) {
    return <div style={{ color: '#adb5bd', fontSize: '0.8rem' }}>No activity data yet.</div>;
  }

  return (
    <div>
      <div style={{ fontSize: '0.8rem', color: '#6c757d', marginBottom: '0.5rem' }}>
        <strong style={{ color: '#1f2328' }}>{totalContributions.toLocaleString()}</strong> validations in the last year
      </div>

      {/* Month labels row */}
      <div style={{ display: 'flex', paddingLeft: '24px', marginBottom: '2px' }}>
        {weeks.map((_, i) => {
          const label = monthLabels.find((m) => m.weekIndex === i);
          return (
            <div key={i} style={{ width: CELL + GAP, fontSize: '0.6rem', color: '#6c757d', flexShrink: 0, overflow: 'visible', whiteSpace: 'nowrap' }}>
              {label?.label || ''}
            </div>
          );
        })}
      </div>

      <div style={{ display: 'flex', gap: 0 }}>
        {/* Day-of-week labels */}
        <div style={{ display: 'flex', flexDirection: 'column', marginRight: '4px', flexShrink: 0 }}>
          {['', 'Mon', '', 'Wed', '', 'Fri', ''].map((label, i) => (
            <div
              key={i}
              style={{ height: CELL + GAP, fontSize: '0.6rem', color: '#6c757d', lineHeight: `${CELL}px`, textAlign: 'right', whiteSpace: 'nowrap' }}
            >
              {label}
            </div>
          ))}
        </div>

        {/* Cell grid */}
        <div style={{ display: 'flex', gap: `${GAP}px` }}>
          {weeks.map((week, wi) => (
            <div key={wi} style={{ display: 'flex', flexDirection: 'column', gap: `${GAP}px` }}>
              {week.map((cell, di) => (
                <div
                  key={di}
                  onMouseEnter={cell.count > 0 ? (e) => {
                    const r = e.currentTarget.getBoundingClientRect();
                    setTooltip({ cell, x: r.left + r.width / 2, y: r.top });
                  } : undefined}
                  onMouseLeave={cell.count > 0 ? () => setTooltip(null) : undefined}
                  style={{
                    width: CELL,
                    height: CELL,
                    borderRadius: '2px',
                    background: HEATMAP_COLORS[colorLevel(cell.count)],
                    cursor: 'default',
                    boxSizing: 'border-box',
                    position: 'relative',
                  }}
                />
              ))}
            </div>
          ))}
        </div>
      </div>

      {/* Legend */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '3px', marginTop: '6px', justifyContent: 'flex-end', fontSize: '0.65rem', color: '#6c757d' }}>
        <span>Less</span>
        {HEATMAP_COLORS.map((color, i) => (
          <div key={i} style={{ width: CELL, height: CELL, borderRadius: '2px', background: color, flexShrink: 0 }} />
        ))}
        <span>More</span>
      </div>

      {/* Fixed tooltip */}
      {tooltip && (
        <div style={{
          position: 'fixed',
          left: tooltip.x,
          top: tooltip.y - 8,
          transform: 'translate(-50%, -100%)',
          background: '#1f2328',
          color: '#fff',
          padding: '4px 8px',
          borderRadius: '4px',
          fontSize: '0.72rem',
          whiteSpace: 'nowrap',
          pointerEvents: 'none',
          zIndex: 9999,
        }}>
          <strong>{tooltip.cell.count}</strong> validation{tooltip.cell.count !== 1 ? 's' : ''} · {tooltip.cell.date}
        </div>
      )}
    </div>
  );
};

// ─── ProfilePage ──────────────────────────────────────────────────────────────

const ProfilePage = () => {
  const [stats, setStats] = useState(null);
  const [profile, setProfile] = useState(null);
  const [loading, setLoading] = useState(true);
  const username = localStorage.getItem('username') || 'User';

  useEffect(() => {
    Promise.all([fetchValidationStats(), fetchUserProfile()])
      .then(([s, p]) => { setStats(s); setProfile(p); })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  return (
    <div>
      {/* Profile header + heatmap */}
      <div style={{ maxWidth: '1400px', margin: '1rem auto 0', padding: '0 1.5rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', marginBottom: '1rem' }}>
          {/* Avatar */}
          <div style={{
            width: '52px', height: '52px', borderRadius: '50%',
            background: '#1E88E5', color: '#fff',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontSize: '1.4rem', fontWeight: '700', flexShrink: 0,
          }}>
            {username[0]?.toUpperCase()}
          </div>
          <div>
            {profile?.first_name || profile?.last_name
              ? <div style={{ fontWeight: '700', fontSize: '1.2rem', color: '#1f2328' }}>{[profile.first_name, profile.last_name].filter(Boolean).join(' ')}</div>
              : <div style={{ fontWeight: '700', fontSize: '1.2rem', color: '#1f2328' }}>{username}</div>
            }
            <div style={{ fontSize: '0.82rem', color: '#6c757d', marginTop: '1px' }}>
              {profile?.first_name || profile?.last_name ? <span style={{ marginRight: '0.5rem' }}>@{username}</span> : null}
              {profile?.email && <span style={{ marginRight: '0.5rem' }}>{profile.email}</span>}
              {profile?.is_staff && <span style={{ background: '#e3f2fd', color: '#1565C0', borderRadius: '4px', padding: '1px 6px', fontSize: '0.72rem', fontWeight: '600', marginRight: '0.5rem' }}>Staff</span>}
              {profile?.date_joined && <span>Member since {new Date(profile.date_joined).toLocaleDateString('en-US', { year: 'numeric', month: 'short', timeZone: 'UTC' })}</span>}
            </div>
            {stats && (
              <div style={{ fontSize: '0.8rem', color: '#6c757d', marginTop: '3px' }}>
                {stats.user_stats.total_validated.toLocaleString()} claims validated &middot;{' '}
                {stats.user_stats.papers_validated_total.toLocaleString()} papers
              </div>
            )}
          </div>
        </div>

        {/* Contribution heatmap */}
        <div style={{
          background: '#fff',
          border: '1px solid #dee2e6',
          borderRadius: '8px',
          padding: '1rem',
          marginBottom: '0',
          overflowX: 'auto',
        }}>
          {loading ? (
            <div className="text-center py-2"><Spinner animation="border" size="sm" /> Loading activity...</div>
          ) : (
            <ValidationHeatmap heatmap={stats?.series?.year_heatmap} />
          )}
        </div>
      </div>

    </div>
  );
};

export default ProfilePage;
