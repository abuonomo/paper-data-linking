import React, { useState, useEffect, useMemo, useCallback, useRef } from 'react';
import { Container, Table, Spinner, Alert, Form } from 'react-bootstrap';
import { fetchMonitoringDashboard, fetchAvailableConfigurations } from '../services/apiServices';
import { useAuth } from '../hooks/useAuth';
import CostMonitoringPanel from './CostMonitoringPanel';

const fmtPct = (val) => val != null ? `${(val * 100).toFixed(1)}%` : 'N/A';
const fmtCI = (low, high) => `${(low * 100).toFixed(1)}\u2013${(high * 100).toFixed(1)}%`;

const wilsonCI = (s, n) => {
  if (n === 0) return [0, 0];
  const z = 1.96;
  const p = s / n;
  const d = 1 + z * z / n;
  const c = (p + z * z / (2 * n)) / d;
  const m = (z / d) * Math.sqrt(p * (1 - p) / n + z * z / (4 * n * n));
  return [Math.max(0, c - m), Math.min(1, c + m)];
};

const NR_FORMULAS = {
  exclude: 'approved / (approved + rejected)',
  include: 'approved / (approved + rejected + needs_review)',
};

const PAGE_SIZE = 10;

const SKELETON_STYLE = {
  height: '0.85rem',
  borderRadius: '4px',
  background: 'linear-gradient(90deg, #e9ecef 25%, #f1f3f5 50%, #e9ecef 75%)',
  backgroundSize: '200% 100%',
  animation: 'shimmer 1.5s ease-in-out infinite',
};

const MonitoringDashboard = () => {
  const { isAuthenticated } = useAuth();
  const [data, setData] = useState(null);
  const [initialLoading, setInitialLoading] = useState(true);
  const [tableLoading, setTableLoading] = useState(false);
  const [error, setError] = useState(null);
  const [dashTab, setDashTab] = useState('performance');
  const [tab, setTab] = useState('mission');
  const [sortConfig, setSortConfig] = useState({ key: 'total_validated', direction: 'desc' });
  const [includeNr, setIncludeNr] = useState(false);
  const [configurations, setConfigurations] = useState([]);
  const [selectedConfig, setSelectedConfig] = useState('standard');
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(0);
  const isInitial = useRef(true);

  useEffect(() => {
    fetchAvailableConfigurations().then(setConfigurations).catch(() => {});
  }, []);

  const loadData = useCallback((include, config) => {
    if (isInitial.current) {
      setInitialLoading(true);
    } else {
      setTableLoading(true);
    }
    setError(null);
    fetchMonitoringDashboard({ needsReview: include ? 'as_denominator' : 'exclude', configuration: config || null })
      .then((d) => {
        setData(d);
        isInitial.current = false;
      })
      .catch(() => setError('Failed to load monitoring dashboard data'))
      .finally(() => {
        setInitialLoading(false);
        setTableLoading(false);
      });
  }, []);

  useEffect(() => { loadData(includeNr, selectedConfig); }, [includeNr, selectedConfig, loadData]);

  // Reset sort, search, and page when switching tabs
  const handleTabChange = (t) => {
    setTab(t);
    setSortConfig({ key: 'total_validated', direction: 'desc' });
    setSearch('');
    setPage(0);
  };

  const perMission = useMemo(() => {
    if (!data?.per_instrument) return [];
    const map = {};
    for (const row of data.per_instrument) {
      const key = row.observatory_id;
      if (!map[key]) {
        map[key] = {
          id: key,
          name: row.observatory_display_name || row.observatory_short_name,
          approved: 0, rejected: 0, needs_review: 0, total_validated: 0,
          instrument_count: 0,
        };
      }
      map[key].approved += row.approved;
      map[key].rejected += row.rejected;
      map[key].needs_review += row.needs_review || 0;
      map[key].total_validated += row.total_validated;
      map[key].instrument_count += 1;
    }
    return Object.values(map).map(m => {
      const precision = m.total_validated > 0 ? m.approved / m.total_validated : null;
      const [ci_low, ci_high] = wilsonCI(m.approved, m.total_validated);
      return { ...m, precision, ci_low, ci_high };
    });
  }, [data]);

  const perInstrument = useMemo(() => {
    if (!data?.per_instrument) return [];
    return data.per_instrument.map(r => ({
      id: r.instrument_id,
      name: r.instrument_display_name || r.instrument_short_name,
      mission: r.observatory_display_name || r.observatory_short_name,
      ...r,
    }));
  }, [data]);

  const sortedRows = useMemo(() => {
    const rows = tab === 'mission' ? perMission : perInstrument;
    const s = [...rows];
    s.sort((a, b) => {
      const av = a[sortConfig.key] ?? '', bv = b[sortConfig.key] ?? '';
      const cmp = typeof av === 'string' ? av.localeCompare(bv) : (av - bv);
      return sortConfig.direction === 'asc' ? cmp : -cmp;
    });
    return s;
  }, [tab, perMission, perInstrument, sortConfig]);

  const filteredRows = useMemo(() => {
    if (!search.trim()) return sortedRows;
    const q = search.trim().toLowerCase();
    return sortedRows.filter(row =>
      row.name?.toLowerCase().includes(q) ||
      (tab === 'instrument' && row.mission?.toLowerCase().includes(q))
    );
  }, [sortedRows, search, tab]);

  // Reset page when search or sort changes
  useEffect(() => { setPage(0); }, [search, sortConfig]);

  const totalPages = Math.max(1, Math.ceil(filteredRows.length / PAGE_SIZE));
  const pageRows = filteredRows.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);
  const emptyRowCount = PAGE_SIZE - pageRows.length;
  const showCostsTab = isAuthenticated;

  const handleSort = (key) => {
    setSortConfig(prev => ({
      key,
      direction: prev.key === key && prev.direction === 'desc' ? 'asc' : 'desc',
    }));
  };

  const si = (key) => {
    if (sortConfig.key !== key) return '';
    return sortConfig.direction === 'asc' ? ' \u25B2' : ' \u25BC';
  };

  if (initialLoading) {
    return <Container className="mt-3"><div className="text-center py-4"><Spinner animation="border" size="sm" /> Loading...</div></Container>;
  }
  if (error && !data) {
    return <Container className="mt-3"><Alert variant="danger">{error}</Alert></Container>;
  }

  const { counts, overall_precision: op } = data;
  const colCount = 8;

  const sg = {
    display: 'flex', gap: '1rem', alignItems: 'center',
    padding: '0.5rem 0.75rem',
    background: '#f8f9fa', borderRadius: '6px',
  };
  const ss = { textAlign: 'center', lineHeight: 1.2 };
  const sn = { fontWeight: '600', fontSize: '1.05rem' };
  const sl = { fontSize: '0.7rem', color: '#6c757d', textTransform: 'uppercase', letterSpacing: '0.03em' };
  const dv = { width: '1px', height: '28px', background: '#dee2e6', flexShrink: 0 };

  return (
    <Container fluid className="mt-3 px-4" style={{ maxWidth: '1400px' }}>
      {/* Shimmer keyframes */}
      <style>{`@keyframes shimmer { 0% { background-position: 200% 0; } 100% { background-position: -200% 0; } }`}</style>

      {/* Top-level dashboard tabs */}
      {showCostsTab && (
        <div className="vq-toolbar mb-3">
          <div className="vq-tabs">
            <button className={`vq-tab ${dashTab === 'performance' ? 'vq-tab--active' : ''}`} onClick={() => setDashTab('performance')}>Performance</button>
            <button className={`vq-tab ${dashTab === 'costs' ? 'vq-tab--active' : ''}`} onClick={() => setDashTab('costs')}>Costs</button>
          </div>
        </div>
      )}

      {showCostsTab && dashTab === 'costs' && <CostMonitoringPanel />}

      {dashTab === 'performance' && <div style={{ maxWidth: '700px' }}>

      {/* Summary bar */}
      <div className="d-flex align-items-center gap-3 mb-3 flex-wrap">
        <div style={{ ...sg, background: '#e3f2fd', border: '1px solid #bbdefb' }}>
          <div style={ss}>
            <div style={{ ...sn, fontSize: '1.5rem', color: '#1E88E5' }}>{fmtPct(op.precision)}</div>
            <div style={sl}>precision</div>
            <div style={{ fontSize: '0.65rem', color: '#90a4ae', marginTop: '2px' }}>instrument + time range</div>
          </div>
          <div style={dv} />
          <div style={{ fontSize: '0.78rem', color: '#546e7a', lineHeight: 1.4 }}>
            <div>{op.approved}/{op.total_validated} validated</div>
            <div>CI: {fmtCI(op.ci_low, op.ci_high)}</div>
          </div>
        </div>

        <div style={sg}>
          <div style={ss}><div style={sn}>{counts.total_papers.toLocaleString()}</div><div style={sl}>Papers</div></div>
          <div style={dv} />
          <div style={ss}><div style={sn}>{counts.total_observatories}</div><div style={sl}>Missions</div></div>
          <div style={dv} />
          <div style={ss}><div style={sn}>{counts.total_instruments}</div><div style={sl}>Instruments</div></div>
        </div>

        <div style={sg}>
          <div style={ss}><div style={sn}>{counts.total_dataset_usages.toLocaleString()}</div><div style={sl}>Usages</div></div>
          <div style={dv} />
          <div style={ss}><div style={sn}>{counts.validated_papers}</div><div style={sl}>Papers Val.</div></div>
          <div style={dv} />
          <div style={ss}><div style={{ ...sn, color: '#27ae60' }}>{op.approved}</div><div style={sl}>Approved</div></div>
          <div style={dv} />
          <div style={ss}><div style={{ ...sn, color: '#e74c3c' }}>{op.rejected}</div><div style={sl}>Rejected</div></div>
          {counts.needs_review_total > 0 && <>
            <div style={dv} />
            <div style={ss}><div style={{ ...sn, color: '#f39c12' }}>{counts.needs_review_total}</div><div style={sl}>Needs Rev.</div></div>
          </>}
        </div>
      </div>

      {/* Precision calculation controls */}
      <div className="mb-3 d-flex align-items-center gap-3 flex-wrap" style={{ fontSize: '0.8rem' }}>
        <div>
          <Form.Select
            size="sm"
            value={selectedConfig}
            onChange={(e) => { setSelectedConfig(e.target.value); setPage(0); }}
            style={{ width: '180px', fontSize: '0.8rem' }}
          >
            <option value="">All configurations</option>
            {configurations.map(c => <option key={c} value={c}>{c}</option>)}
          </Form.Select>
        </div>
        <div>
          <Form.Check
            type="switch"
            id="nr-toggle"
            label="Include needs review in denominator"
            checked={includeNr}
            onChange={(e) => setIncludeNr(e.target.checked)}
            style={{ fontSize: '0.8rem', marginBottom: '0.25rem' }}
          />
          <span className="text-muted">
            Precision = <code style={{ fontSize: '0.75rem' }}>{NR_FORMULAS[includeNr ? 'include' : 'exclude']}</code>
          </span>
        </div>
      </div>

      {/* Tab bar + search */}
      <div className="vq-toolbar">
        <div className="vq-tabs">
          <button className={`vq-tab ${tab === 'mission' ? 'vq-tab--active' : ''}`} onClick={() => handleTabChange('mission')}>By Mission ({perMission.length})</button>
          <button className={`vq-tab ${tab === 'instrument' ? 'vq-tab--active' : ''}`} onClick={() => handleTabChange('instrument')}>By Instrument ({perInstrument.length})</button>
        </div>
        <Form.Control
          type="text"
          size="sm"
          placeholder={`Search ${tab === 'mission' ? 'missions' : 'instruments'}...`}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          style={{ width: '180px', fontSize: '0.8rem' }}
        />
      </div>

      {/* Table */}
      <div style={{ border: '1px solid #dee2e6', borderTop: 'none' }}>
        <Table striped hover size="sm" className="mb-0" style={{ fontSize: '0.85rem' }}>
          <thead className="table-light">
            <tr>
              <SortTh label={tab === 'mission' ? 'Mission' : 'Instrument'} sortKey="name" onClick={handleSort} si={si} style={{ width: '22%' }} />
              {tab === 'instrument' && <SortTh label="Mission" sortKey="mission" onClick={handleSort} si={si} style={{ width: '14%' }} />}
              <SortTh label="Precision" sortKey="precision" onClick={handleSort} si={si} style={{ width: '10%' }} />
              <SortTh label="95% CI" sortKey="ci_low" onClick={handleSort} si={si} style={{ width: '14%' }} />
              {tab === 'mission' && <SortTh label="Instr." sortKey="instrument_count" onClick={handleSort} si={si} style={{ width: '8%' }} />}
              <SortTh label="Appr." sortKey="approved" onClick={handleSort} si={si} style={{ width: '8%' }} />
              <SortTh label="Rej." sortKey="rejected" onClick={handleSort} si={si} style={{ width: '8%' }} />
              <SortTh label="N.Rev." sortKey="needs_review" onClick={handleSort} si={si} style={{ width: '8%' }} />
              <SortTh label="Total" sortKey="total_validated" onClick={handleSort} si={si} style={{ width: '8%' }} />
            </tr>
          </thead>
          <tbody>
            {tableLoading ? (
              Array.from({ length: PAGE_SIZE }).map((_, i) => (
                <tr key={`skel-${i}`}>
                  {Array.from({ length: colCount }).map((_, j) => (
                    <td key={j}><div style={{ ...SKELETON_STYLE, width: j === 0 ? '80%' : '60%' }} /></td>
                  ))}
                </tr>
              ))
            ) : (
              <>
                {pageRows.map((row) => (
                  <tr key={row.id}>
                    <td><strong>{row.name}</strong></td>
                    {tab === 'instrument' && <td>{row.mission}</td>}
                    <td><strong>{fmtPct(row.precision)}</strong></td>
                    <td className="text-muted" style={{ whiteSpace: 'nowrap' }}>{fmtCI(row.ci_low, row.ci_high)}</td>
                    {tab === 'mission' && <td>{row.instrument_count}</td>}
                    <td>{row.approved}</td>
                    <td>{row.rejected}</td>
                    <td>{row.needs_review || 0}</td>
                    <td>{row.total_validated}</td>
                  </tr>
                ))}
                {filteredRows.length === 0 && (
                  <tr><td colSpan={colCount} className="text-center text-muted py-3">{search.trim() ? 'No matches.' : 'No validated data yet.'}</td></tr>
                )}
                {emptyRowCount > 0 && filteredRows.length > 0 && Array.from({ length: emptyRowCount }).map((_, i) => (
                  <tr key={`empty-${i}`}>
                    <td colSpan={colCount}>&nbsp;</td>
                  </tr>
                ))}
              </>
            )}
          </tbody>
        </Table>
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="d-flex align-items-center justify-content-between" style={{ fontSize: '0.8rem', padding: '0.4rem 0.25rem', color: '#6c757d' }}>
          <span>{filteredRows.length} result{filteredRows.length !== 1 ? 's' : ''}</span>
          <div className="d-flex align-items-center gap-2">
            <button
              className="btn btn-sm btn-outline-secondary"
              style={{ fontSize: '0.75rem', padding: '0.15rem 0.5rem' }}
              disabled={page === 0}
              onClick={() => setPage(p => p - 1)}
            >Prev</button>
            <span>Page {page + 1} of {totalPages}</span>
            <button
              className="btn btn-sm btn-outline-secondary"
              style={{ fontSize: '0.75rem', padding: '0.15rem 0.5rem' }}
              disabled={page >= totalPages - 1}
              onClick={() => setPage(p => p + 1)}
            >Next</button>
          </div>
        </div>
      )}
      </div>}
    </Container>
  );
};

const SortTh = ({ label, sortKey, onClick, si, style }) => (
  <th onClick={() => onClick(sortKey)} style={{ cursor: 'pointer', userSelect: 'none', whiteSpace: 'nowrap', ...style }}>
    {label}<span style={{ display: 'inline-block', width: '1em', textAlign: 'center' }}>{si(sortKey)}</span>
  </th>
);

export default MonitoringDashboard;
