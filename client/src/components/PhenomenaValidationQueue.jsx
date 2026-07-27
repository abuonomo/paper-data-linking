// src/components/PhenomenaValidationQueue.jsx
import React, { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { fetchPhenomenaQueuePapers } from '../services/apiServices';
import { toast } from 'react-toastify';

const PhenomenaValidationQueue = () => {
  const navigate = useNavigate();
  const [papers, setPapers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [currentPage, setCurrentPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [totalCount, setTotalCount] = useState(0);
  const [pageSize] = useState(25);
  const [activeTab, setActiveTab] = useState('open');
  const [searchInput, setSearchInput] = useState('');
  const [search, setSearch] = useState('');

  const validationStatus = activeTab === 'open' ? 'pending' : 'complete';

  useEffect(() => {
    setCurrentPage(1);
  }, [activeTab, search]);

  useEffect(() => {
    loadPapers();
  }, [currentPage, validationStatus, search]);

  const loadPapers = async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await fetchPhenomenaQueuePapers({
        validation_status: validationStatus,
        search,
        page: currentPage,
        page_size: pageSize,
      });
      setPapers(data.results || []);
      setTotalCount(data.count || 0);
      setTotalPages(Math.ceil((data.count || 0) / pageSize) || 1);
    } catch (err) {
      console.error('Error loading phenomena queue:', err);
      setError('Failed to load phenomena validation queue');
      toast.error('Failed to load phenomena validation queue');
    } finally {
      setLoading(false);
    }
  };

  const commitSearch = () => setSearch(searchInput);

  if (error) {
    return (
      <div className="vq-container">
        <div className="alert alert-danger" role="alert">{error}</div>
      </div>
    );
  }

  return (
    <div className="vq-container">
      <div className="vo-breadcrumb">
        <span>Phenomena Validation</span>
      </div>

      <div className="vq-toolbar">
        <div className="vq-tabs">
          <button
            className={`vq-tab ${activeTab === 'open' ? 'vq-tab--active' : ''}`}
            onClick={() => setActiveTab('open')}
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor" style={{ marginRight: 4 }}>
              <circle cx="8" cy="8" r="7" fill="none" stroke="currentColor" strokeWidth="1.5"/>
            </svg>
            Open
          </button>
          <button
            className={`vq-tab ${activeTab === 'closed' ? 'vq-tab--active' : ''}`}
            onClick={() => setActiveTab('closed')}
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor" style={{ marginRight: 4 }}>
              <path d="M13.78 4.22a.75.75 0 010 1.06l-7.25 7.25a.75.75 0 01-1.06 0L2.22 9.28a.75.75 0 011.06-1.06L6 10.94l6.72-6.72a.75.75 0 011.06 0z"/>
            </svg>
            Closed
          </button>
        </div>

        <div className="vq-search">
          <input
            className="vq-search-input"
            type="text"
            placeholder="Search bibcode…"
            value={searchInput}
            onChange={e => setSearchInput(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && commitSearch()}
          />
          {searchInput && (
            <button
              className="vq-search-clear"
              onClick={() => { setSearchInput(''); setSearch(''); }}
              title="Clear"
            >×</button>
          )}
          <button className="vq-search-btn" onClick={commitSearch}>Search</button>
        </div>
      </div>

      <div className="vq-list">
        <div className="vq-list-header">
          <span className="vq-col-paper">Paper</span>
          <span className="vq-col-num">Open</span>
          <span className="vq-col-num">Accepted</span>
          <span className="vq-col-num">Total</span>
        </div>

        {loading ? (
          Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="vq-row vq-row--skeleton">
              <span className="vq-col-paper">
                <span className="vo-skeleton" style={{ width: `${120 + (i % 3) * 40}px`, height: '14px', borderRadius: '4px' }} />
              </span>
              <span className="vq-col-num"><span className="vo-skeleton" style={{ width: '24px', height: '13px', borderRadius: '4px' }} /></span>
              <span className="vq-col-num"><span className="vo-skeleton" style={{ width: '24px', height: '13px', borderRadius: '4px' }} /></span>
              <span className="vq-col-num"><span className="vo-skeleton" style={{ width: '24px', height: '13px', borderRadius: '4px' }} /></span>
            </div>
          ))
        ) : papers.length === 0 ? (
          <div style={{ padding: '2rem', textAlign: 'center', color: '#656d76' }}>
            {activeTab === 'open'
              ? 'No papers with pending phenomenon mentions.'
              : 'No papers with fully validated phenomenon mentions.'}
          </div>
        ) : (
          papers.map(paper => (
            <div
              key={paper.id}
              className="vq-row"
              onClick={() => navigate(`/phenomena-validation/${paper.id}`)}
              style={{ cursor: 'pointer' }}
            >
              <span className="vq-col-paper">
                <span className="vq-bibcode">{paper.bibcode}</span>
                {paper.title && <span className="vq-paper-title">{paper.title}</span>}
              </span>
              <span className="vq-col-num">{paper.pending_mentions}</span>
              <span className="vq-col-num">{paper.accepted_mentions}</span>
              <span className="vq-col-num">{paper.total_mentions}</span>
            </div>
          ))
        )}
      </div>

      {!loading && totalPages > 1 && (
        <div className="vq-pagination">
          <button
            className="vq-page-btn"
            disabled={currentPage === 1}
            onClick={() => { setCurrentPage(p => p - 1); window.scrollTo({ top: 0, behavior: 'smooth' }); }}
          >
            ← Previous
          </button>
          <span className="vq-page-info">Page {currentPage} of {totalPages} ({totalCount} papers)</span>
          <button
            className="vq-page-btn"
            disabled={currentPage === totalPages}
            onClick={() => { setCurrentPage(p => p + 1); window.scrollTo({ top: 0, behavior: 'smooth' }); }}
          >
            Next →
          </button>
        </div>
      )}
    </div>
  );
};

export default PhenomenaValidationQueue;
