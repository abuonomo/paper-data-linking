// src/components/PaperValidationQueue.jsx
import React, { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { fetchPaperValidationQueue, fetchPaperTags, fetchPaperValidationQueueCounts, fetchAvailableConfigurations } from '../services/apiServices';
import { toast } from 'react-toastify';

const VALIDATION_QUEUE_TAGS_STORAGE_KEY = 'pdl.validationQueue.selectedTags';

const loadPersistedTags = () => {
  if (typeof window === 'undefined') return [];
  try {
    const raw = window.sessionStorage.getItem(VALIDATION_QUEUE_TAGS_STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed.filter(tag => typeof tag === 'string') : [];
  } catch {
    return [];
  }
};

const PaperValidationQueue = () => {
  const navigate = useNavigate();
  const [papers, setPapers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [currentPage, setCurrentPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [totalCount, setTotalCount] = useState(0);
  const [pageSize] = useState(25);
  const [tagOptions, setTagOptions] = useState([]);
  const [configOptions, setConfigOptions] = useState([]);
  const [activeTab, setActiveTab] = useState('open');
  const [filters, setFilters] = useState(() => ({
    validation_status: 'pending',
    configuration_name: 'standard',
    ordering: '-validation_progress',
    tags: loadPersistedTags(),
    search: '',
  }));
  const [searchInput, setSearchInput] = useState('');
  const [queueCounts, setQueueCounts] = useState({ pending: 0, complete: 0 });
  const [countsLoading, setCountsLoading] = useState(false);

  // Dropdown state
  const [openDropdown, setOpenDropdown] = useState(null);
  const dropdownRef = useRef(null);

  // Close dropdown on outside click
  useEffect(() => {
    const handleClick = (e) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target)) {
        setOpenDropdown(null);
      }
    };
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, []);

  // Commit search to filters (called on Enter or button click)
  const commitSearch = () => {
    setFilters(prev => ({ ...prev, search: searchInput }));
  };

  // Load available tags and configs on mount
  useEffect(() => {
    (async () => {
      try {
        const tags = await fetchPaperTags();
        setTagOptions(tags);
      } catch (e) {
        console.error('Failed to load tags', e);
      }
    })();
    (async () => {
      try {
        const configs = await fetchAvailableConfigurations();
        setConfigOptions(configs);
      } catch (e) {
        console.error('Failed to load configurations', e);
      }
    })();
  }, []);

  // Handle tab changes
  useEffect(() => {
    if (activeTab === 'open') {
      setFilters(prev => ({
        ...prev,
        validation_status: 'pending',
        ordering: '-validation_progress'
      }));
    } else if (activeTab === 'closed') {
      setFilters(prev => ({
        ...prev,
        validation_status: 'complete',
        ordering: '-latest_validated_at'
      }));
    } else if (activeTab === 'no_usages') {
      setFilters(prev => ({
        ...prev,
        validation_status: 'no_usages',
        ordering: '-latest_analysis_date'
      }));
    }
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }, [activeTab]);

  // Load counts when relevant filters change
  useEffect(() => {
    const loadCounts = async () => {
      try {
        setCountsLoading(true);
        const counts = await fetchPaperValidationQueueCounts({
          configuration_name: filters.configuration_name,
          tags: filters.tags,
        });
        setQueueCounts(counts);
      } catch (e) {
        console.error('Failed to load queue counts', e);
        setQueueCounts({ pending: 0, complete: 0 });
      } finally {
        setCountsLoading(false);
      }
    };
    loadCounts();
  }, [filters.configuration_name, JSON.stringify(filters.tags)]);

  useEffect(() => {
    setCurrentPage(1);
  }, [filters]);

  useEffect(() => {
    loadPapers();
  }, [currentPage, filters.validation_status, filters.configuration_name, filters.ordering, JSON.stringify(filters.tags), filters.search]);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    try {
      window.sessionStorage.setItem(VALIDATION_QUEUE_TAGS_STORAGE_KEY, JSON.stringify(filters.tags));
    } catch {
      // Ignore storage write failures; queue still works without persistence.
    }
  }, [filters.tags]);

  const loadPapers = async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await fetchPaperValidationQueue({
        ...filters,
        page: currentPage,
        page_size: pageSize
      });
      if (data && data.results) {
        setPapers(data.results);
        setTotalCount(data.count || 0);
        setTotalPages(Math.ceil((data.count || 0) / pageSize) || 1);
      } else if (Array.isArray(data)) {
        setPapers(data);
        setTotalCount(data.length);
        setTotalPages(1);
      } else {
        setPapers([]);
        setTotalCount(0);
        setTotalPages(1);
      }
    } catch (err) {
      console.error('Error loading paper validation queue:', err);
      setError('Failed to load papers for validation');
      toast.error('Failed to load papers for validation');
    } finally {
      setLoading(false);
    }
  };

  const handleFilterChange = (key, value) => {
    setFilters(prev => ({ ...prev, [key]: value }));
  };

  const handlePageChange = (page) => {
    setCurrentPage(page);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  const handlePaperClick = (paperId) => navigate(`/papers/${paperId}/validate`);

  const handleSort = (field) => {
    setFilters(prev => {
      const current = prev.ordering || '';
      let next;
      if (current === field) next = `-${field}`;
      else if (current === `-${field}`) next = field;
      else next = field;
      return { ...prev, ordering: next };
    });
  };

  const sortIndicator = (field) => {
    const current = filters.ordering || '';
    if (current === field) return ' ↑';
    if (current === `-${field}`) return ' ↓';
    return '';
  };

  const configLabel = filters.configuration_name
    ? filters.configuration_name.charAt(0).toUpperCase() + filters.configuration_name.slice(1)
    : 'All';

  const activeTagCount = filters.tags.length;

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
        <span>Validate</span>
      </div>
      {/* Toolbar: status tabs + filters on one line */}
      <div className="vq-toolbar" ref={dropdownRef}>
        <div className="vq-tabs">
          <button
            className={`vq-tab ${activeTab === 'open' ? 'vq-tab--active' : ''}`}
            onClick={() => setActiveTab('open')}
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor" style={{ marginRight: 4 }}>
              <circle cx="8" cy="8" r="7" fill="none" stroke="currentColor" strokeWidth="1.5"/>
            </svg>
            {countsLoading ? 'Open' : `${queueCounts.pending} Open`}
          </button>
          <button
            className={`vq-tab ${activeTab === 'closed' ? 'vq-tab--active' : ''}`}
            onClick={() => setActiveTab('closed')}
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor" style={{ marginRight: 4 }}>
              <path d="M13.78 4.22a.75.75 0 010 1.06l-7.25 7.25a.75.75 0 01-1.06 0L2.22 9.28a.75.75 0 011.06-1.06L6 10.94l6.72-6.72a.75.75 0 011.06 0z"/>
            </svg>
            {countsLoading ? 'Closed' : `${queueCounts.complete} Closed`}
          </button>
          <button
            className={`vq-tab ${activeTab === 'no_usages' ? 'vq-tab--active' : ''}`}
            onClick={() => setActiveTab('no_usages')}
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor" style={{ marginRight: 4 }}>
              <path d="M8 0a8 8 0 100 16A8 8 0 008 0zm0 14.5a6.5 6.5 0 110-13 6.5 6.5 0 010 13zm0-8.25a.75.75 0 01.75.75v3.5a.75.75 0 01-1.5 0V7a.75.75 0 01.75-.75zm0-2.5a1 1 0 110 2 1 1 0 010-2z"/>
            </svg>
            No usages
          </button>
        </div>

        <div className="vq-search">
          <input
            className="vq-search-input"
            type="text"
            placeholder="Search bibcode or title…"
            value={searchInput}
            onChange={e => setSearchInput(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && commitSearch()}
          />
          {searchInput && (
            <button className="vq-search-clear" onClick={() => { setSearchInput(''); setFilters(prev => ({ ...prev, search: '' })); }} title="Clear">×</button>
          )}
          <button className="vq-search-btn" onClick={commitSearch}>Search</button>
        </div>

        <div className="vq-filters">
          {/* Configuration dropdown */}
          <div className="vq-dropdown">
            <button
              className="vq-filter-btn"
              onClick={() => setOpenDropdown(openDropdown === 'config' ? null : 'config')}
            >
              Config: {configLabel} <span className="vq-caret">▾</span>
            </button>
            {openDropdown === 'config' && (
              <div className="vq-dropdown-menu">
                {['', ...configOptions].map(val => (
                  <button
                    key={val || 'all'}
                    className={`vq-dropdown-item ${filters.configuration_name === val ? 'vq-dropdown-item--active' : ''}`}
                    onClick={() => { handleFilterChange('configuration_name', val); setOpenDropdown(null); }}
                  >
                    {val ? val.charAt(0).toUpperCase() + val.slice(1) : 'All'}
                    {filters.configuration_name === val && <span className="vq-check">✓</span>}
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Tags dropdown */}
          {tagOptions.length > 0 && (
            <div className="vq-dropdown">
              <button
                className="vq-filter-btn"
                onClick={() => setOpenDropdown(openDropdown === 'tags' ? null : 'tags')}
              >
                Tags{activeTagCount > 0 ? ` (${activeTagCount})` : ''} <span className="vq-caret">▾</span>
              </button>
              {openDropdown === 'tags' && (
                <div className="vq-dropdown-menu">
                  {tagOptions.map(tag => (
                    <button
                      key={tag}
                      className={`vq-dropdown-item ${filters.tags.includes(tag) ? 'vq-dropdown-item--active' : ''}`}
                      onClick={() => {
                        const isSelected = filters.tags.includes(tag);
                        const next = isSelected ? filters.tags.filter(t => t !== tag) : [...filters.tags, tag];
                        handleFilterChange('tags', next);
                      }}
                    >
                      {tag}
                      {filters.tags.includes(tag) && <span className="vq-check">✓</span>}
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Sort dropdown */}
          <div className="vq-dropdown">
            <button
              className="vq-filter-btn"
              onClick={() => setOpenDropdown(openDropdown === 'sort' ? null : 'sort')}
            >
              Sort <span className="vq-caret">▾</span>
            </button>
            {openDropdown === 'sort' && (
              <div className="vq-dropdown-menu">
                {[
                  { field: 'validation_progress', label: 'Validated %' },
                  { field: 'pending_count', label: 'Claims pending' },
                  { field: 'total_usages', label: 'Total claims' },
                  { field: 'latest_analysis_date', label: 'Latest analysis' },
                  { field: 'latest_validated_at', label: 'Latest validation' },
                  { field: 'bibcode', label: 'Bibcode' },
                ].map(({ field, label }) => {
                  const current = filters.ordering || '';
                  const isActive = current === field || current === `-${field}`;
                  const isDesc = current === `-${field}`;
                  return (
                    <button
                      key={field}
                      className={`vq-dropdown-item ${isActive ? 'vq-dropdown-item--active' : ''}`}
                      onClick={() => { handleSort(field); setOpenDropdown(null); }}
                    >
                      {label}
                      {isActive && <span className="vq-check">{isDesc ? '↓' : '↑'}</span>}
                    </button>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* List */}
      <div className="vq-list">
        {/* Column headers */}
        <div className="vq-list-header">
          <span className="vq-col-paper" onClick={() => handleSort('bibcode')} style={{ cursor: 'pointer' }}>
            Paper{sortIndicator('bibcode')}
          </span>
          <span className="vq-col-num" onClick={() => handleSort('pending_count')} style={{ cursor: 'pointer' }}>
            Open{sortIndicator('pending_count')}
          </span>
          <span className="vq-col-num" onClick={() => handleSort('total_usages')} style={{ cursor: 'pointer' }}>
            Closed{sortIndicator('total_usages')}
          </span>
          <span className="vq-col-num" onClick={() => handleSort('validation_progress')} style={{ cursor: 'pointer' }}>
            %{sortIndicator('validation_progress')}
          </span>
          <span className="vq-col-date" onClick={() => handleSort('latest_analysis_date')} style={{ cursor: 'pointer' }}>
            Analyzed{sortIndicator('latest_analysis_date')}
          </span>
          <span className="vq-col-date" onClick={() => handleSort('latest_validated_at')} style={{ cursor: 'pointer' }}>
            Validated{sortIndicator('latest_validated_at')}
          </span>
        </div>

        {loading ? (
          Array.from({ length: 8 }).map((_, i) => (
            <div key={i} className="vq-row vq-row--skeleton">
              <span className="vq-col-paper">
                <span className="vo-skeleton" style={{ width: `${100 + (i % 3) * 40}px`, height: '14px', borderRadius: '4px' }} />
                <span className="vo-skeleton" style={{ width: `${180 + (i % 4) * 30}px`, height: '12px', borderRadius: '4px' }} />
              </span>
              <span className="vq-col-num"><span className="vo-skeleton" style={{ width: '24px', height: '13px', borderRadius: '4px' }} /></span>
              <span className="vq-col-num"><span className="vo-skeleton" style={{ width: '24px', height: '13px', borderRadius: '4px' }} /></span>
              <span className="vq-col-num"><span className="vo-skeleton" style={{ width: '32px', height: '13px', borderRadius: '4px' }} /></span>
              <span className="vq-col-date"><span className="vo-skeleton" style={{ width: '70px', height: '13px', borderRadius: '4px' }} /></span>
              <span className="vq-col-date"><span className="vo-skeleton" style={{ width: '70px', height: '13px', borderRadius: '4px' }} /></span>
            </div>
          ))
        ) : papers.length === 0 ? (
          <div style={{ padding: '2rem', textAlign: 'center', color: '#656d76' }}>
            No papers found with the current filters.
          </div>
        ) : (
          <>
            {papers.map((paper) => {
              const stats = paper.validation_stats;
              const total = stats.total_usages || 0;
              const pending = stats.pending || 0;
              const closed = total - pending;
              const pct = total > 0 ? Math.round(stats.validation_progress || 0) : 0;
              return (
                <div
                  key={paper.id}
                  className="vq-row"
                  onClick={() => handlePaperClick(paper.id)}
                >
                  <span className="vq-col-paper">
                    <span className="vq-bibcode">{paper.bibcode}</span>
                    {paper.title && <span className="vq-paper-title">{paper.title}</span>}
                  </span>
                  <span className="vq-col-num">{pending}</span>
                  <span className="vq-col-num">{closed}</span>
                  <span className="vq-col-num">{pct}%</span>
                  <span className="vq-col-date">
                    {paper.latest_analysis_date
                      ? formatDate(paper.latest_analysis_date)
                      : <span className="vq-muted">—</span>}
                  </span>
                  <span className="vq-col-date">
                    {paper.latest_validated_at
                      ? formatDate(paper.latest_validated_at)
                      : <span className="vq-muted">—</span>}
                  </span>
                </div>
              );
            })}
          </>
        )}
      </div>

      {/* Pagination */}
      {papers.length > 0 && totalPages > 1 && (
        <div className="vq-pagination">
          <button
            className="vq-page-btn"
            disabled={currentPage === 1}
            onClick={() => handlePageChange(currentPage - 1)}
          >
            ← Previous
          </button>
          <span className="vq-page-info">
            Page {currentPage} of {totalPages}
          </span>
          <button
            className="vq-page-btn"
            disabled={currentPage === totalPages}
            onClick={() => handlePageChange(currentPage + 1)}
          >
            Next →
          </button>
        </div>
      )}
    </div>
  );
};

function formatDate(dateStr) {
  const d = new Date(dateStr);
  const now = new Date();
  const diff = now - d;
  const days = Math.floor(diff / 86400000);
  if (days === 0) return 'today';
  if (days === 1) return 'yesterday';
  if (days < 30) return `${days} days ago`;
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC' });
}

export default PaperValidationQueue;
