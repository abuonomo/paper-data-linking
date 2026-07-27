import React, { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { fetchBatchJobs } from '../services/apiServices';

const POLL_MS = 15000;

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
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 160 }}>
      <div style={{
        flex: 1, height: 6, background: '#eaeef2', borderRadius: 3, overflow: 'hidden',
      }}>
        <div style={{
          width: `${pct}%`, height: '100%',
          background: pct === 100 ? '#3fb950' : '#0969da',
          transition: 'width 0.4s',
        }} />
      </div>
      <small style={{ whiteSpace: 'nowrap', color: '#57606a', fontSize: 12 }}>
        {done} / {total}
      </small>
    </div>
  );
}

function Pagination({ page, numPages, onChange }) {
  if (numPages <= 1) return null;
  return (
    <div style={{ display: 'flex', gap: 4, alignItems: 'center', justifyContent: 'flex-end', marginTop: 12 }}>
      <button
        onClick={() => onChange(page - 1)}
        disabled={page <= 1}
        style={pgBtnStyle(page <= 1)}
      >← Prev</button>
      <span style={{ fontSize: 12, color: '#57606a', padding: '0 6px' }}>
        {page} / {numPages}
      </span>
      <button
        onClick={() => onChange(page + 1)}
        disabled={page >= numPages}
        style={pgBtnStyle(page >= numPages)}
      >Next →</button>
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

export default function MonitorDashboard() {
  const navigate = useNavigate();
  const [activeTab, setActiveTab] = useState('in_progress');
  const [jobs, setJobs] = useState([]);
  const [count, setCount] = useState(0);
  const [numPages, setNumPages] = useState(1);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [lastRefresh, setLastRefresh] = useState(null);
  const intervalRef = useRef(null);

  // Count in-progress for live indicator (only valid when on in_progress tab)
  const hasLive = activeTab === 'in_progress' && jobs.length > 0;

  const loadJobs = async (pg = page) => {
    try {
      const data = await fetchBatchJobs({ status: activeTab, page: pg, page_size: 25 });
      setJobs(data.results || []);
      setCount(data.count || 0);
      setNumPages(data.num_pages || 1);
      setLastRefresh(new Date());
      setError(null);
    } catch (e) {
      setError('Failed to load batch jobs');
    } finally {
      setLoading(false);
    }
  };

  // Reload when tab or page changes
  useEffect(() => {
    setLoading(true);
    loadJobs(page);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTab, page]);

  // Auto-poll while on in_progress tab
  useEffect(() => {
    if (intervalRef.current) clearInterval(intervalRef.current);
    if (activeTab === 'in_progress') {
      intervalRef.current = setInterval(() => loadJobs(page), POLL_MS);
    }
    return () => clearInterval(intervalRef.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTab, page]);

  const handleTabChange = (tab) => {
    setActiveTab(tab);
    setPage(1);
  };

  const handlePageChange = (pg) => {
    setPage(pg);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  return (
    <div className="vq-container">
      <div className="vo-breadcrumb">
        <span>Batch Jobs</span>
      </div>

      {/* Tabs toolbar */}
      <div className="vq-toolbar">
        <div className="vq-tabs">
          <button
            className={`vq-tab ${activeTab === 'in_progress' ? 'vq-tab--active' : ''}`}
            onClick={() => handleTabChange('in_progress')}
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor" style={{ marginRight: 4 }}>
              <circle cx="8" cy="8" r="7" fill="none" stroke="currentColor" strokeWidth="1.5"/>
            </svg>
            In Progress
          </button>
          <button
            className={`vq-tab ${activeTab === 'completed' ? 'vq-tab--active' : ''}`}
            onClick={() => handleTabChange('completed')}
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor" style={{ marginRight: 4 }}>
              <path d="M13.78 4.22a.75.75 0 010 1.06l-7.25 7.25a.75.75 0 01-1.06 0L2.22 9.28a.75.75 0 011.06-1.06L6 10.94l6.72-6.72a.75.75 0 011.06 0z"/>
            </svg>
            Completed
          </button>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginLeft: 'auto' }}>
          {hasLive && (
            <span style={{ color: '#d4a72c', fontWeight: 600, fontSize: 13 }}>● Live</span>
          )}
          {lastRefresh && (
            <span style={{ fontSize: 12, color: '#57606a' }}>
              Updated {lastRefresh.toLocaleTimeString('en-US', { timeZone: 'UTC' })} UTC
            </span>
          )}
          <button
            onClick={() => loadJobs(page)}
            disabled={loading}
            style={pgBtnStyle(loading)}
          >
            Refresh
          </button>
        </div>
      </div>

      {/* Error */}
      {error && <p style={{ color: '#d1242f', fontSize: 13, marginTop: 8 }}>{error}</p>}

      {/* Table */}
      {loading && jobs.length === 0 ? (
        <p style={{ color: '#57606a', fontSize: 13, marginTop: 12 }}>Loading…</p>
      ) : !loading && jobs.length === 0 && !error ? (
        <p style={{ color: '#57606a', fontSize: 13, marginTop: 12 }}>No batch jobs found.</p>
      ) : (
        <div style={{ overflowX: 'auto', marginTop: 4 }}>
          <table style={{ width: '100%', fontSize: 13, borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ borderBottom: '1px solid #d0d7de', color: '#57606a', fontSize: 12, fontWeight: 600 }}>
                <th style={thStyle}>Configuration</th>
                <th style={thStyle}>Provider</th>
                <th style={thStyle}>Created</th>
                <th style={thStyle}>Papers</th>
                <th style={thStyle}>Pipeline done</th>
              </tr>
            </thead>
            <tbody>
              {jobs.map((job) => {
                const done = job.papers_pipeline_done || 0;
                const total = job.total_requests || 0;
                const isFullyDone = total > 0 && done >= total;
                return (
                  <tr
                    key={job.id}
                    onClick={() => navigate(`/monitoring/batch/${job.id}`)}
                    style={{
                      borderBottom: '1px solid #eaeef2',
                      cursor: 'pointer',
                    }}
                    onMouseEnter={e => e.currentTarget.style.background = '#f6f8fa'}
                    onMouseLeave={e => e.currentTarget.style.background = ''}
                  >
                    <td style={{ padding: '7px 8px', fontWeight: 500, color: '#1f2328' }}>
                      {job.configuration_name}
                    </td>
                    <td style={{ padding: '7px 8px', color: '#57606a' }}>{job.provider}</td>
                    <td style={{ padding: '7px 8px', color: '#57606a' }}>{formatDate(job.created_at)}</td>
                    <td style={{ padding: '7px 8px', color: '#57606a' }}>{total}</td>
                    <td style={{ padding: '7px 8px', minWidth: 180 }}>
                      {total > 0 ? (
                        <ProgressBar done={done} total={total} />
                      ) : (
                        <span style={{ color: '#57606a' }}>—</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <Pagination page={page} numPages={numPages} onChange={handlePageChange} />

      {count > 0 && (
        <p style={{ fontSize: 12, color: '#57606a', marginTop: 8, textAlign: 'right' }}>
          {count} total batch{count !== 1 ? 'es' : ''}
        </p>
      )}
    </div>
  );
}

const thStyle = { padding: '6px 8px', textAlign: 'left', whiteSpace: 'nowrap' };
