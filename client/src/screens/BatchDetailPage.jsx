import React, { useEffect, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { fetchBatchPapers } from '../services/apiServices';

const POLL_MS = 10000;
const PAGE_SIZE = 50;

function formatDate(iso) {
  if (!iso) return '—';
  return new Date(iso).toLocaleString('en-US', {
    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
    timeZone: 'UTC', timeZoneName: 'short',
  });
}

function ProgressBar({ done, total }) {
  const pct = total > 0 ? Math.round((done / total) * 100) : 0;
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      <div style={{ flex: 1, height: 6, background: '#eaeef2', borderRadius: 3, overflow: 'hidden' }}>
        <div style={{
          width: `${pct}%`, height: '100%',
          background: pct === 100 ? '#3fb950' : '#0969da',
          transition: 'width 0.4s',
        }} />
      </div>
      <small style={{ whiteSpace: 'nowrap', color: '#57606a', fontSize: 12 }}>
        {done} / {total} pipeline done
      </small>
    </div>
  );
}

const STAGE_ACCENT = {
  paper_analysis:       '#0969da',
  structuring:          '#8250df',
  instrument:           '#1a7f5a',
  grounding:            '#bc4c00',
  grounding_datasystem: '#bc4c00',
  grounding_substep:    '#6e7781',
  grounding_match:      '#2da44e',
  normalization:        '#bf3989',
  normalizer:           '#9a6700',
};

const STAGE_LABELS = {
  paper_analysis:       'Paper Analysis',
  structuring:          'Structuring',
  instrument:           'Instrument',
  grounding:            'Grounding',
  grounding_datasystem: 'Data System',
  grounding_substep:    'Substep',
  grounding_match:      'Match',
  normalization:        'Normalization',
  normalizer:           'Normalizer',
};

function StageBadge({ stage }) {
  if (!stage) return <span style={{ color: '#57606a' }}>—</span>;
  const color = STAGE_ACCENT[stage] || '#57606a';
  return (
    <span style={{
      display: 'inline-block', padding: '1px 7px', borderRadius: 10,
      fontSize: 11, fontWeight: 600,
      background: `${color}18`, color,
    }}>
      {STAGE_LABELS[stage] || stage}
    </span>
  );
}

function StatusDot({ running, failed, completed }) {
  if (completed) return <span style={{ color: '#3fb950', fontSize: 12 }}>✓ done</span>;
  if (failed)    return <span style={{ color: '#d1242f', fontSize: 12 }}>✗ failed</span>;
  if (running)   return <span style={{ color: '#d4a72c', fontSize: 12 }}>● running</span>;
  return <span style={{ color: '#57606a', fontSize: 12 }}>— queued</span>;
}

function statusRank(p) {
  if (p.has_running_nodes) return 0;
  if (!p.pipeline_completed_at && !p.has_failed_nodes) return 1;
  if (p.has_failed_nodes) return 2;
  return 3;
}

function Pagination({ page, numPages, onChange }) {
  if (numPages <= 1) return null;
  return (
    <div style={{ display: 'flex', gap: 4, alignItems: 'center', justifyContent: 'flex-end', marginTop: 12 }}>
      <button onClick={() => onChange(page - 1)} disabled={page <= 1} style={pgBtnStyle(page <= 1)}>
        ← Prev
      </button>
      <span style={{ fontSize: 12, color: '#57606a', padding: '0 6px' }}>
        {page} / {numPages}
      </span>
      <button onClick={() => onChange(page + 1)} disabled={page >= numPages} style={pgBtnStyle(page >= numPages)}>
        Next →
      </button>
    </div>
  );
}

function pgBtnStyle(disabled) {
  return {
    fontSize: 12, padding: '3px 10px', borderRadius: 6,
    border: '1px solid #d0d7de',
    background: disabled ? '#f6f8fa' : '#fff',
    color: disabled ? '#8c959f' : '#1f2328',
    cursor: disabled ? 'default' : 'pointer',
  };
}

export default function BatchDetailPage() {
  const { batchId } = useParams();
  const navigate = useNavigate();

  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [sortCol, setSortCol] = useState(null);
  const [sortDir, setSortDir] = useState('asc');
  const intervalRef = useRef(null);

  const isLive = data && data.papers_pipeline_done < data.total_requests;

  const load = async (pg = page) => {
    try {
      const result = await fetchBatchPapers(batchId, { page: pg, page_size: PAGE_SIZE });
      setData(result);
      setError(null);
    } catch (e) {
      setError('Failed to load batch details');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    setLoading(true);
    load(page);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [batchId, page]);

  // Auto-poll while pipeline is live
  useEffect(() => {
    if (intervalRef.current) clearInterval(intervalRef.current);
    if (isLive) {
      intervalRef.current = setInterval(() => load(page), POLL_MS);
    }
    return () => clearInterval(intervalRef.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isLive, page]);

  const handleSort = (col) => {
    if (sortCol === col) setSortDir(d => d === 'asc' ? 'desc' : 'asc');
    else { setSortCol(col); setSortDir('asc'); }
  };

  const handlePageChange = (pg) => {
    setPage(pg);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  const papers = [...(data?.papers || [])].sort((a, b) => {
    if (!sortCol) return 0;
    let av, bv;
    if (sortCol === 'bibcode') { av = a.bibcode || ''; bv = b.bibcode || ''; }
    else if (sortCol === 'stage') { av = a.current_stage || ''; bv = b.current_stage || ''; }
    else if (sortCol === 'status') { av = statusRank(a); bv = statusRank(b); }
    else if (sortCol === 'completed') { av = a.pipeline_completed_at || ''; bv = b.pipeline_completed_at || ''; }
    const cmp = av < bv ? -1 : av > bv ? 1 : 0;
    return sortDir === 'asc' ? cmp : -cmp;
  });

  const SortIcon = ({ col }) => {
    const active = sortCol === col;
    return (
      <span style={{
        display: 'inline-block', width: 12, textAlign: 'center', marginLeft: 3,
        color: active ? '#0969da' : '#d0d7de',
      }}>
        {active ? (sortDir === 'asc' ? '↑' : '↓') : '⇅'}
      </span>
    );
  };

  if (loading && !data) {
    return (
      <div className="vq-container">
        <div className="vo-breadcrumb">
          <span style={{ cursor: 'pointer', color: '#0969da' }} onClick={() => navigate('/monitoring/batch')}>
            Batch Jobs
          </span>
          <span style={{ color: '#57606a', margin: '0 4px' }}>/</span>
          <span>Loading…</span>
        </div>
        <p style={{ color: '#57606a', fontSize: 13, marginTop: 12 }}>Loading batch details…</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="vq-container">
        <div className="vo-breadcrumb">
          <span style={{ cursor: 'pointer', color: '#0969da' }} onClick={() => navigate('/monitoring/batch')}>
            Batch Jobs
          </span>
          <span style={{ color: '#57606a', margin: '0 4px' }}>/</span>
          <span>Error</span>
        </div>
        <p style={{ color: '#d1242f', fontSize: 13, marginTop: 12 }}>{error}</p>
      </div>
    );
  }

  const done = data?.papers_pipeline_done || 0;
  const total = data?.total_requests || 0;

  return (
    <div className="vq-container">
      {/* Breadcrumb */}
      <div className="vo-breadcrumb">
        <span
          style={{ cursor: 'pointer', color: '#0969da' }}
          onClick={() => navigate('/monitoring/batch')}
        >
          Batch Jobs
        </span>
        <span style={{ color: '#57606a', margin: '0 4px' }}>/</span>
        <span>{data?.configuration_name || 'Batch'}</span>
      </div>

      {/* Batch metadata header */}
      <div style={{
        border: '1px solid #d0d7de', borderRadius: 6, padding: '1rem',
        marginBottom: '1rem', background: '#fff',
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 8 }}>
          <div>
            <span style={{ fontWeight: 600, fontSize: 15, color: '#1f2328' }}>
              {data?.configuration_name}
            </span>
            <span style={{ color: '#57606a', marginLeft: 8 }}>· {data?.provider}</span>
            <span style={{ color: '#57606a', marginLeft: 8, fontSize: 13 }}>· {formatDate(data?.created_at)}</span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            {isLive && (
              <span style={{ color: '#d4a72c', fontWeight: 600, fontSize: 13 }}>● Live</span>
            )}
            <span style={{
              padding: '1px 8px', borderRadius: 10, fontSize: 11, fontWeight: 600,
              background: done >= total && total > 0 ? '#dafbe1' : '#fff8c5',
              color: done >= total && total > 0 ? '#1a7f37' : '#9a6700',
            }}>
              {done >= total && total > 0 ? 'done' : 'in progress'}
            </span>
            <span style={{ fontSize: 13, color: '#57606a' }}>{total} papers</span>
          </div>
        </div>
        <div style={{ marginTop: 10 }}>
          <ProgressBar done={done} total={total} />
        </div>
      </div>

      {/* Paper table */}
      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', fontSize: 13, borderCollapse: 'collapse' }}>
          <thead>
            <tr style={{ borderBottom: '1px solid #d0d7de', color: '#57606a', fontSize: 12, fontWeight: 600 }}>
              <th style={thStyle} onClick={() => handleSort('bibcode')}>
                Bibcode <SortIcon col="bibcode" />
              </th>
              <th style={thStyle} onClick={() => handleSort('stage')}>
                Stage <SortIcon col="stage" />
              </th>
              <th style={thStyle} onClick={() => handleSort('status')}>
                Status <SortIcon col="status" />
              </th>
              <th style={thStyle} onClick={() => handleSort('completed')}>
                Pipeline completed <SortIcon col="completed" />
              </th>
            </tr>
          </thead>
          <tbody>
            {papers.map((p) => {
              const completed = !!p.pipeline_completed_at;
              return (
                <tr key={p.paper_id} style={{ borderBottom: '1px solid #eaeef2' }}>
                  <td style={{ padding: '4px 8px', fontFamily: 'monospace' }}>
                    {p.analysis_id ? (
                      <span
                        onClick={() => navigate(`/analyses/${p.analysis_id}?tab=pipeline`)}
                        style={{ color: '#0969da', cursor: 'pointer', textDecoration: 'underline' }}
                      >
                        {p.bibcode}
                      </span>
                    ) : p.bibcode}
                  </td>
                  <td style={{ padding: '4px 8px' }}>
                    <StageBadge stage={p.current_stage} />
                  </td>
                  <td style={{ padding: '4px 8px' }}>
                    <StatusDot
                      running={p.has_running_nodes}
                      failed={p.has_failed_nodes}
                      completed={completed}
                    />
                  </td>
                  <td style={{ padding: '4px 8px', fontSize: 12, color: completed ? '#1a7f37' : '#57606a' }}>
                    {completed ? formatDate(p.pipeline_completed_at) : '—'}
                  </td>
                </tr>
              );
            })}
            {papers.length === 0 && (
              <tr>
                <td colSpan={4} style={{ padding: '12px 8px', textAlign: 'center', color: '#57606a' }}>
                  No papers found.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <Pagination page={page} numPages={data?.num_pages || 1} onChange={handlePageChange} />

      {data?.count > 0 && (
        <p style={{ fontSize: 12, color: '#57606a', marginTop: 8, textAlign: 'right' }}>
          {data.count} paper{data.count !== 1 ? 's' : ''} total
        </p>
      )}
    </div>
  );
}

const thStyle = {
  padding: '5px 8px', textAlign: 'left', cursor: 'pointer',
  userSelect: 'none', whiteSpace: 'nowrap',
};
