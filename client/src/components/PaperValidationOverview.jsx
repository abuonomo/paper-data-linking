// src/components/PaperValidationOverview.jsx
import React, { useState, useEffect } from 'react';
import { useParams, useNavigate, Link } from 'react-router-dom';
import {
  fetchPaperDetails,
  fetchNextPaperInQueue,
  fetchPaperValidationOverview,
} from '../services/apiServices';
import { toast } from 'react-toastify';
import { formatDateTimeCompactUTC } from '../utils/dateUtils';
import { usePaperPDF } from '../hooks/usePaperPDF';
import ReactMarkdown from 'react-markdown';
import { Modal, Button } from 'react-bootstrap';

const PaperValidationOverview = () => {
  const { paperId } = useParams();
  const navigate = useNavigate();
  const [paper, setPaper] = useState(null);
  const [analysisGroups, setAnalysisGroups] = useState([]);
  const [allUsages, setAllUsages] = useState([]);
  const [overallStats, setOverallStats] = useState(null);
  const [paperAnalysis, setPaperAnalysis] = useState(null);
  const [showContextModal, setShowContextModal] = useState(false);
  const [showFullTextModal, setShowFullTextModal] = useState(false);
  const [activeConfigIdx, setActiveConfigIdx] = useState(0);
  const [statusFilter, setStatusFilter] = useState('open');
  const [loading, setLoading] = useState(true);
  const [navigating, setNavigating] = useState(false);
  const [error, setError] = useState(null);

  const { pdfUrl, hasPdf } = usePaperPDF(paper?.bibcode);

  useEffect(() => {
    setNavigating(false);
    setActiveConfigIdx(0);
    if (paperId) loadPaperData();
  }, [paperId]);

  const loadPaperData = async () => {
    try {
      setLoading(true);
      setError(null);
      const [paperData, hierarchicalData] = await Promise.all([
        fetchPaperDetails(paperId),
        fetchPaperValidationOverview(paperId),
      ]);
      setPaper(paperData);
      setAnalysisGroups(hierarchicalData);

      const usages = hierarchicalData.flatMap(g => g.dataset_usages || []);
      setAllUsages(usages);

      const total = usages.length;
      const pending = usages.filter(u => u.validation_status === 'pending').length;
      const approved = usages.filter(u => u.validation_status === 'approved').length;
      const rejected = usages.filter(u => u.validation_status === 'rejected').length;
      const needs_review = usages.filter(u => u.validation_status === 'needs_review').length;
      setOverallStats({ total, pending, approved, rejected, needs_review, validated: approved + rejected });

      if (hierarchicalData.length > 0) {
        const std = hierarchicalData.find(g => g.analysis.configuration_name === 'standard');
        setPaperAnalysis((std || hierarchicalData[0]).analysis);
      }
    } catch (err) {
      console.error('Error loading paper data:', err);
      setError('Failed to load paper validation data');
      toast.error('Failed to load paper validation data');
    } finally {
      setLoading(false);
    }
  };

  const handleUsageClick = (usageId, analysisId) => {
    navigate(`/papers/${paperId}/validate/${analysisId}/${usageId}`);
  };

  const handleNavigatePaper = async (direction) => {
    try {
      setNavigating(true);
      const data = await fetchNextPaperInQueue(paperId, { validation_status: 'pending', direction });
      if (data.next_paper) {
        navigate(`/papers/${data.next_paper.id}/validate`);
      } else {
        toast.info('No more papers in validation queue');
        setNavigating(false);
      }
    } catch (err) {
      console.error(`Error getting ${direction} paper:`, err);
      toast.error(`Failed to get ${direction} paper`);
      setNavigating(false);
    }
  };

  if (loading) {
    return (
      <div className="vq-container">
        <div className="vo-breadcrumb">
          <Link to="/papers/validation-queue">Validate</Link>
          <span className="vo-breadcrumb-sep">/</span>
          <span className="vo-skeleton vo-skeleton-text" style={{ width: '140px' }} />
        </div>
        <div className="vo-header">
          <div className="vo-header-left">
            <div className="vo-skeleton vo-skeleton-text" style={{ width: '200px', height: '1.6rem', marginBottom: '0.5rem' }} />
            <div className="vo-skeleton vo-skeleton-text" style={{ width: '120px', height: '0.9rem' }} />
          </div>
          <div className="vo-header-actions">
            <button className="vo-nav-btn" disabled>← Prev</button>
            <button className="vo-nav-btn" disabled>Next →</button>
          </div>
        </div>
        <div className="vq-toolbar">
          <div className="vq-tabs">
            <span className="vo-skeleton vo-skeleton-text" style={{ width: '80px', height: '1.2rem', margin: '0.5rem 0.75rem' }} />
            <span className="vo-skeleton vo-skeleton-text" style={{ width: '80px', height: '1.2rem', margin: '0.5rem 0.75rem' }} />
          </div>
        </div>
        <div className="vq-list">
          <div className="vo-list-header">
            <span className="vo-col-mission">Mission</span>
            <span className="vo-col-instrument">Instrument</span>
            <span className="vo-col-time">Start</span>
            <span className="vo-col-time">End</span>
            <span className="vo-col-status">Status</span>
          </div>
          {[1, 2, 3, 4, 5].map(i => (
            <div key={i} className="vo-claim-row vo-claim-row--skeleton">
              <span className="vo-col-mission"><span className="vo-skeleton vo-skeleton-text" style={{ width: '60px' }} /></span>
              <span className="vo-col-instrument"><span className="vo-skeleton vo-skeleton-text" style={{ width: '80px' }} /></span>
              <span className="vo-col-time"><span className="vo-skeleton vo-skeleton-text" style={{ width: '100px' }} /></span>
              <span className="vo-col-time"><span className="vo-skeleton vo-skeleton-text" style={{ width: '100px' }} /></span>
              <span className="vo-col-status"><span className="vo-skeleton vo-skeleton-text" style={{ width: '50px' }} /></span>
            </div>
          ))}
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="vq-container">
        <div className="alert alert-danger" role="alert">{error}</div>
      </div>
    );
  }

  const pct = overallStats && overallStats.total > 0
    ? Math.round(overallStats.validated / overallStats.total * 100)
    : 0;

  return (
    <div className="vq-container">
      {/* Breadcrumb */}
      <div className="vo-breadcrumb">
        <Link to="/papers/validation-queue">Validate</Link>
        <span className="vo-breadcrumb-sep">/</span>
        <span>{paper?.bibcode}</span>
      </div>

      {/* Header row */}
      <div className="vo-header">
        <div className="vo-header-left">
          <h1 className="vo-title">{paper?.title || paper?.bibcode}</h1>
          <p className="vo-paper-citation">
            {paper.authors?.length > 0 && (
              <span>{paper.authors.length <= 3 ? paper.authors.join(', ') : `${paper.authors[0]} et al.`}</span>
            )}
            {paper.year && <span> ({paper.year})</span>}
            {paper.journal_abbrev && <span> — {paper.journal_abbrev}</span>}
          </p>
          <div className="vo-meta">
            <code className="vo-bibcode-code" title="Click to copy bibcode" onClick={() => { navigator.clipboard.writeText(paper.bibcode); toast.success('Bibcode copied'); }}>
              {paper.bibcode}
            </code>
            <a href={`https://ui.adsabs.harvard.edu/abs/${encodeURIComponent(paper.bibcode)}`} target="_blank" rel="noopener noreferrer" className="vo-meta-link">ADS</a>
            <a href={`/public/p/${paper.bibcode}?include_unvalidated=true`} target="_blank" rel="noopener noreferrer" className="vo-meta-link">Public page</a>
            {hasPdf && pdfUrl && (
              <a href={pdfUrl} target="_blank" rel="noopener noreferrer" className="vo-meta-link">PDF</a>
            )}
            {paper?.full_text && (
              <button className="vo-meta-link" onClick={() => setShowFullTextModal(true)}>Full text</button>
            )}
          </div>
        </div>
        <div className="vo-header-actions">
          <button className="vo-nav-btn" onClick={() => handleNavigatePaper('prev')} disabled={navigating}>
            ← Prev
          </button>
          <button className="vo-nav-btn" onClick={() => handleNavigatePaper('next')} disabled={navigating}>
            Next →
          </button>
        </div>
      </div>

      {/* Config bar + claims */}
      {analysisGroups.length > 0 ? (() => {
        const activeGroup = analysisGroups[activeConfigIdx] || analysisGroups[0];
        const usages = activeGroup.dataset_usages || [];
        const openCount = usages.filter(u => (u.validation_status || 'pending') === 'pending').length;
        const closedCount = usages.length - openCount;
        const filtered = usages.filter(u => {
          const s = u.validation_status || 'pending';
          return statusFilter === 'open' ? s === 'pending' : s !== 'pending';
        });

        return (
          <>
            {/* Analysis config bar — sits between header and claims toolbar */}
            <div className={`vo-config-bar vo-config-color-${activeConfigIdx % 3}`}>
              <div className="vo-config-pills">
                {analysisGroups.map((group, idx) => {
                  const name = group.analysis.configuration_name || 'legacy';
                  const label = name.charAt(0).toUpperCase() + name.slice(1);
                  return (
                    <button
                      key={group.analysis.id}
                      className={`vo-config-pill vo-config-color-${idx % 3} ${idx === activeConfigIdx ? 'vo-config-pill--active' : ''}`}
                      onClick={() => setActiveConfigIdx(idx)}
                      title={label}
                    >
                      <span className="vo-config-pill-label">{label}</span>
                      <span className="vo-config-pill-count">{group.validation_stats.total_usages}</span>
                    </button>
                  );
                })}
              </div>
              <div
                className="vo-config-actions"
                style={{ marginLeft: `${activeConfigIdx * 136}px` }}
              >
                <button className="vo-config-action" onClick={() => { setPaperAnalysis(activeGroup.analysis); setShowContextModal(true); }}>
                  Context
                </button>
                <button className="vo-config-action" onClick={() => navigate(`/analyses/${activeGroup.analysis.id}`)}>
                  LLM Calls
                </button>
              </div>
            </div>

            {/* Open/Closed toolbar */}
            <div className="vq-toolbar">
              <div className="vq-tabs">
                <button
                  className={`vq-tab ${statusFilter === 'open' ? 'vq-tab--active' : ''}`}
                  onClick={() => setStatusFilter('open')}
                >
                  <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor" style={{ marginRight: 4 }}>
                    <circle cx="8" cy="8" r="7" fill="none" stroke="currentColor" strokeWidth="1.5"/>
                  </svg>
                  {openCount} Open
                </button>
                <button
                  className={`vq-tab ${statusFilter === 'closed' ? 'vq-tab--active' : ''}`}
                  onClick={() => setStatusFilter('closed')}
                >
                  <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor" style={{ marginRight: 4 }}>
                    <path d="M13.78 4.22a.75.75 0 010 1.06l-7.25 7.25a.75.75 0 01-1.06 0L2.22 9.28a.75.75 0 011.06-1.06L6 10.94l6.72-6.72a.75.75 0 011.06 0z"/>
                  </svg>
                  {closedCount} Closed
                </button>
              </div>
            </div>

            {/* Claims list */}
            <div className={`vq-list vo-list-tint-${activeConfigIdx % 3}`}>
              <div className="vo-list-header">
                <span className="vo-col-mission">Mission</span>
                <span className="vo-col-instrument">Instrument</span>
                <span className="vo-col-time">Start</span>
                <span className="vo-col-time">End</span>
                <span className="vo-col-status">Status</span>
              </div>

              {filtered.map((usage) => (
                <div
                  key={usage.id}
                  className="vo-claim-row"
                  onClick={() => handleUsageClick(usage.id, activeGroup.analysis.id)}
                >
                  <span className="vo-col-mission">
                    <span className="vo-mission-name">{usage.observatory_name || usage.observatory_short_name || 'UNKNOWN'}</span>
                  </span>
                  <span className="vo-col-instrument">
                    <span className="vo-instrument-name">{usage.instrument_name || 'Unknown'}</span>
                  </span>
                  <span className="vo-col-time">
                    {usage.start_time ? formatDateTimeCompactUTC(usage.start_time) : <span className="vq-muted">—</span>}
                  </span>
                  <span className="vo-col-time">
                    {usage.end_time ? formatDateTimeCompactUTC(usage.end_time) : <span className="vq-muted">—</span>}
                  </span>
                  <span className="vo-col-status">
                    <span className={`vo-status vo-status-${usage.validation_status || 'pending'}`}>
                      {(usage.validation_status || 'pending').replace('_', ' ')}
                    </span>
                  </span>
                </div>
              ))}
              {filtered.length === 0 && (
                <div style={{ padding: '2rem', textAlign: 'center', color: '#656d76' }}>
                  {statusFilter === 'open' ? 'No open claims — all validated!' : 'No closed claims yet.'}
                </div>
              )}
            </div>
          </>
        );
      })() : (
        <div style={{ padding: '3rem', textAlign: 'center', color: '#656d76' }}>
          No analysis configurations found for this paper.
        </div>
      )}

      {/* Instrument context modal */}
      <Modal show={showContextModal} onHide={() => setShowContextModal(false)} size="lg">
        <Modal.Header closeButton>
          <Modal.Title>Instrument Context</Modal.Title>
        </Modal.Header>
        <Modal.Body>
          {paperAnalysis ? (
            <>
              <div style={{ display: 'flex', gap: '1.5rem', fontSize: '0.8rem', color: '#656d76', marginBottom: '0.75rem', paddingBottom: '0.75rem', borderBottom: '1px solid #d0d7de' }}>
                {paperAnalysis.configuration_name && (
                  <span><strong>Config:</strong> {paperAnalysis.configuration_name.charAt(0).toUpperCase() + paperAnalysis.configuration_name.slice(1)}</span>
                )}
                {paperAnalysis.created_at && (
                  <span><strong>Analyzed:</strong> {new Date(paperAnalysis.created_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC' })}</span>
                )}
                <span><strong>Paper:</strong> {paper?.bibcode}</span>
              </div>
              <div style={{ maxHeight: '600px', overflowY: 'auto', fontSize: '0.9rem', lineHeight: '1.6' }}>
              <ReactMarkdown
                components={{
                  h1: ({ children }) => <h4 className="fw-bold mt-3 mb-2 border-bottom pb-1">{children}</h4>,
                  h2: ({ children }) => <h5 className="fw-bold mt-3 mb-2 border-bottom pb-1">{children}</h5>,
                  h3: ({ children }) => <h6 className="fw-bold mt-2 mb-2">{children}</h6>,
                  p: ({ children }) => <p className="mb-2">{children}</p>,
                  ul: ({ children }) => <ul className="mb-3 ps-3">{children}</ul>,
                  li: ({ children }) => <li className="mb-1">{children}</li>,
                  code: ({ children, className }) => {
                    const isBlock = className?.includes('language-');
                    return isBlock
                      ? <pre className="bg-light p-2 rounded mb-3 border"><code>{children}</code></pre>
                      : <code className="bg-light px-1 rounded">{children}</code>;
                  },
                }}
              >
                {paperAnalysis.instruments_details || 'No instrument details available'}
              </ReactMarkdown>
              </div>
            </>
          ) : (
            <p className="text-muted text-center">No analysis available.</p>
          )}
        </Modal.Body>
        <Modal.Footer>
          <Button variant="secondary" onClick={() => setShowContextModal(false)}>Close</Button>
        </Modal.Footer>
      </Modal>

      {/* Full text modal */}
      <Modal show={showFullTextModal} onHide={() => setShowFullTextModal(false)} size="lg">
        <Modal.Header closeButton>
          <Modal.Title>Full Text — {paper?.bibcode}</Modal.Title>
        </Modal.Header>
        <Modal.Body>
          <pre style={{ maxHeight: '600px', overflowY: 'auto', fontSize: '0.85rem', lineHeight: '1.5', whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
            {paper?.full_text || 'No full text available.'}
          </pre>
        </Modal.Body>
        <Modal.Footer>
          <Button variant="secondary" onClick={() => setShowFullTextModal(false)}>Close</Button>
        </Modal.Footer>
      </Modal>
    </div>
  );
};

export default PaperValidationOverview;
