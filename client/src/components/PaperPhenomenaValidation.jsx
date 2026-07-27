// src/components/PaperPhenomenaValidation.jsx
import React, { useState, useEffect } from 'react';
import { useParams, useNavigate, Link } from 'react-router-dom';
import { fetchPaperDetails, fetchPaperPhenomena, fetchNextPaperInQueue } from '../services/apiServices';
import { toast } from 'react-toastify';

// Group a flat list of mentions by instrument_name, preserving insertion order
const groupByInstrument = (mentionList) => {
  const map = new Map();
  for (const m of mentionList) {
    const key = m.instrument_name;
    if (!map.has(key)) {
      map.set(key, { key, grounded: m.grounded_instrument_name, mentions: [] });
    }
    map.get(key).mentions.push(m);
  }
  return Array.from(map.values());
};

const statusClass = (status) => {
  if (status === 'accepted') return 'approved';
  return status || 'pending';
};

const PaperPhenomenaValidation = () => {
  const { paperId } = useParams();
  const navigate = useNavigate();
  const [paper, setPaper] = useState(null);
  const [mentions, setMentions] = useState([]);
  const [statusFilter, setStatusFilter] = useState('open');
  const [loading, setLoading] = useState(true);
  const [navigating, setNavigating] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    setNavigating(false);
    if (paperId) load();
  }, [paperId]);

  const load = async () => {
    try {
      setLoading(true);
      setError(null);
      const [paperData, phenomenaData] = await Promise.all([
        fetchPaperDetails(paperId),
        fetchPaperPhenomena(paperId),
      ]);
      setPaper(paperData);
      setMentions(phenomenaData.mentions || []);
    } catch (err) {
      console.error('Error loading paper phenomena:', err);
      setError('Failed to load phenomena for this paper.');
      toast.error('Failed to load phenomena for this paper.');
    } finally {
      setLoading(false);
    }
  };

  const handleNavigatePaper = async (direction) => {
    try {
      setNavigating(true);
      const data = await fetchNextPaperInQueue(paperId, {
        validation_status: 'pending',
        queue: 'phenomena',
        direction,
      });
      if (data.next_paper) {
        navigate(`/phenomena-validation/${data.next_paper.id}`);
      } else {
        toast.info('No more papers in phenomena validation queue');
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
          <Link to="/phenomena-validation">Phenomena Validation</Link>
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
          <div className="vq-phenom-list-header">
            <span className="vq-phenom-col">Instrument / Phenomenon</span>
            <span className="vq-status-col">Status</span>
          </div>
          {[1, 2, 3, 4, 5].map(i => (
            <div key={i} className="vq-grouped-row vo-claim-row--skeleton">
              <span className="vq-phenom-col"><span className="vo-skeleton vo-skeleton-text" style={{ width: '80px' }} /></span>
              <span className="vq-status-col"><span className="vo-skeleton vo-skeleton-text" style={{ width: '50px' }} /></span>
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

  const openMentions = mentions.filter(m => m.validation_status === 'pending');
  const closedMentions = mentions.filter(m => m.validation_status !== 'pending');
  const filtered = statusFilter === 'open' ? openMentions : closedMentions;
  const groups = groupByInstrument(filtered);

  return (
    <div className="vq-container">
      {/* Breadcrumb */}
      <div className="vo-breadcrumb">
        <Link to="/phenomena-validation">Phenomena Validation</Link>
        <span className="vo-breadcrumb-sep">/</span>
        <span>{paper?.bibcode}</span>
      </div>

      {/* Header */}
      <div className="vo-header">
        <div className="vo-header-left">
          <h1 className="vo-title">{paper?.title || paper?.bibcode}</h1>
          <p className="vo-paper-citation">
            {paper?.authors?.length > 0 && (
              <span>{paper.authors.length <= 3 ? paper.authors.join(', ') : `${paper.authors[0]} et al.`}</span>
            )}
            {paper?.year && <span> ({paper.year})</span>}
            {paper?.journal_abbrev && <span> — {paper.journal_abbrev}</span>}
          </p>
          <div className="vo-meta">
            <code
              className="vo-bibcode-code"
              title="Click to copy bibcode"
              onClick={() => { navigator.clipboard.writeText(paper.bibcode); toast.success('Bibcode copied'); }}
            >
              {paper?.bibcode}
            </code>
            <a
              href={`https://ui.adsabs.harvard.edu/abs/${encodeURIComponent(paper?.bibcode || '')}`}
              target="_blank"
              rel="noopener noreferrer"
              className="vo-meta-link"
            >
              ADS
            </a>
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
            {openMentions.length} Open
          </button>
          <button
            className={`vq-tab ${statusFilter === 'closed' ? 'vq-tab--active' : ''}`}
            onClick={() => setStatusFilter('closed')}
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor" style={{ marginRight: 4 }}>
              <path d="M13.78 4.22a.75.75 0 010 1.06l-7.25 7.25a.75.75 0 01-1.06 0L2.22 9.28a.75.75 0 011.06-1.06L6 10.94l6.72-6.72a.75.75 0 011.06 0z"/>
            </svg>
            {closedMentions.length} Closed
          </button>
        </div>
      </div>

      {/* Mentions list grouped by instrument */}
      <div className="vq-list">
        <div className="vq-phenom-list-header">
          <span className="vq-phenom-col">Instrument / Phenomenon</span>
          <span className="vq-status-col">Status</span>
        </div>

        {groups.map(group => (
          <React.Fragment key={group.key}>
            {/* Instrument group header */}
            <div className="vq-group-header">
              {group.grounded ? (
                <span className="vq-group-code" title={group.key}>{group.grounded}</span>
              ) : (
                <>
                  <span
                    className="vq-group-ungrounded"
                    title={group.key}
                  >
                    {group.key.length > 60 ? group.key.slice(0, 60) + '…' : group.key}
                  </span>
                  <span className="vq-ungrounded-badge">Ungrounded</span>
                </>
              )}
              <span className="vq-group-count">{group.mentions.length}</span>
            </div>

            {/* Rows for this instrument */}
            {group.mentions.map(mention => (
              <div
                key={mention.id}
                className="vq-grouped-row"
                onClick={() => navigate(`/papers/${paperId}/validate/phenomena/${mention.id}`)}
              >
                <span className="vq-phenom-col">
                  <span className="vo-instrument-name">{mention.phenomenon_name}</span>
                </span>
                <span className="vq-status-col">
                  <span className={`vo-status vo-status-${statusClass(mention.validation_status)}`}>
                    {(mention.validation_status || 'pending').replace('_', ' ')}
                  </span>
                </span>
              </div>
            ))}
          </React.Fragment>
        ))}

        {filtered.length === 0 && (
          <div style={{ padding: '2rem', textAlign: 'center', color: '#656d76' }}>
            {statusFilter === 'open' ? 'No open phenomena — all validated!' : 'No closed phenomena yet.'}
          </div>
        )}
      </div>
    </div>
  );
};

export default PaperPhenomenaValidation;
