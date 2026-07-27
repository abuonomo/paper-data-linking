import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { fetchPublicValidatedPapers, fetchPublicPapersFilterOptions } from '../services/apiPublic';

import FacetedFilters from '../components/FacetedFilters';
import UnifiedSearchBar from '../components/UnifiedSearchBar';

function formatDate(dt) {
  if (!dt) return '';
  try {
    return new Date(dt).toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      timeZone: 'UTC',
    });
  } catch {
    return dt;
  }
}

export default function PublicValidatedPapers() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [papers, setPapers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [isInitialLoad, setIsInitialLoad] = useState(true);
  const [isFiltering, setIsFiltering] = useState(false);
  const [error, setError] = useState(null);
  const [searchQuery, setSearchQuery] = useState(searchParams.get('q') || '');
  const [sortBy, setSortBy] = useState('latest');
  const [pagination, setPagination] = useState({
    count: 0,
    next: null,
    previous: null,
    current_page: 1,
    total_pages: 1
  });
  const [filterOptions, setFilterOptions] = useState(null);
  const [filterLoading, setFilterLoading] = useState(true);
  
  const includeUnvalidated = searchParams.get('include_unvalidated') === 'true';
  const currentPage = parseInt(searchParams.get('page')) || 1;
  
  // Parse filters from URL parameters
  const getFiltersFromParams = () => {
    const missions = searchParams.getAll('missions');
    const instruments = searchParams.getAll('instruments');
    const start_date = searchParams.get('start_date') || '';
    const end_date = searchParams.get('end_date') || '';
    
    return {
      missions,
      instruments,
      start_date,
      end_date
    };
  };
  
  const [filters, setFilters] = useState(getFiltersFromParams);
  const [mobileFiltersOpen, setMobileFiltersOpen] = useState(false);
  const [scrollPosition, setScrollPosition] = useState(0);
  const searchInputRef = useRef(null);

  const handleToggleUnvalidated = (newValue) => {
    if (newValue) {
      searchParams.set('include_unvalidated', 'true');
    } else {
      searchParams.delete('include_unvalidated');
    }
    // Reset to first page when toggling
    searchParams.delete('page');
    setSearchParams(searchParams);
  };
  
  const handlePageChange = (newPage) => {
    if (newPage > 0 && newPage <= pagination.total_pages) {
      searchParams.set('page', newPage.toString());
      setSearchParams(searchParams);
    }
  };
  
  const handleFiltersChange = (newFilters, opts = {}) => {
    // Store current scroll position
    setScrollPosition(window.scrollY);

    // Update local state
    setFilters(newFilters);

    // Update URL parameters
    const newParams = new URLSearchParams(searchParams);

    // Clear existing filter params
    newParams.delete('missions');
    newParams.delete('instruments');
    // We only use the top toggle for validation status on public page
    newParams.delete('validation_status');
    newParams.delete('start_date');
    newParams.delete('end_date');
    newParams.delete('page'); // Reset to first page when filters change

    // Optionally clear search query in the same URL update (avoids race condition)
    if (opts.clearSearch) {
      newParams.delete('q');
      setSearchQuery('');
    }

    // Set new filter params
    if (newFilters.missions) {
      newFilters.missions.forEach(mission => newParams.append('missions', mission));
    }
    if (newFilters.instruments) {
      newFilters.instruments.forEach(instrument => newParams.append('instruments', instrument));
    }
    if (newFilters.start_date) {
      newParams.set('start_date', newFilters.start_date);
    }
    if (newFilters.end_date) {
      newParams.set('end_date', newFilters.end_date);
    }

    setSearchParams(newParams);
  };

  // Load filter options
  useEffect(() => {
    let mounted = true;
    setFilterLoading(true);
    
    fetchPublicPapersFilterOptions(includeUnvalidated)
      .then((data) => {
        if (!mounted) return;
        setFilterOptions(data);
      })
      .catch((err) => {
        if (!mounted) return;
        console.error('Failed to load filter options:', err);
      })
      .finally(() => {
        if (mounted) setFilterLoading(false);
      });
    
    return () => { mounted = false; };
  }, [includeUnvalidated]);

  // Load papers with current filters
  useEffect(() => {
    let mounted = true;
    
    // Only show loading screen on initial load, show filtering indicator for filter changes
    if (isInitialLoad) {
      setLoading(true);
    } else {
      setIsFiltering(true);
    }
    setError(null);
    
    console.log('Fetching papers with filters:', filters); // Debug log
    
    // Include query in the API request so search spans all pages
    fetchPublicValidatedPapers(includeUnvalidated, currentPage, 10, { ...filters, query: (searchParams.get('q') || '').trim() })
      .then((data) => {
        if (!mounted) return;
        const papers = data?.results || [];
        setPapers(papers);
        
        console.log('Received papers:', papers.length); // Debug log
        
        // Update pagination state
        setPagination({
          count: data?.count || 0,
          next: data?.next,
          previous: data?.previous,
          current_page: currentPage,
          total_pages: Math.ceil((data?.count || 0) / 10)
        });
      })
      .catch((err) => {
        if (!mounted) return;
        console.error('Error fetching papers:', err); // Debug log
        setError(err?.message || String(err));
      })
      .finally(() => {
        if (mounted) {
          setLoading(false);
          setIsInitialLoad(false);
          setIsFiltering(false);
        }
      });
    
    return () => { mounted = false; };
  }, [includeUnvalidated, currentPage, filters, isInitialLoad]);

  // Update filters when URL parameters change
  useEffect(() => {
    const newFilters = getFiltersFromParams();
    setFilters(newFilters);
  }, [searchParams]);

  // Restore scroll position after papers are loaded
  useEffect(() => {
    if (!loading && scrollPosition > 0) {
      setTimeout(() => {
        window.scrollTo(0, scrollPosition);
        setScrollPosition(0);
      }, 100);
    }
  }, [loading, scrollPosition]);

  const filteredPapers = useMemo(() => {
    let list = papers;
    // Sorting only; filtering now happens on the server via q= param
    if (sortBy === 'bibcode') {
      list = [...list].sort((a, b) => (a.bibcode || '').localeCompare(b.bibcode || ''));
    } else if (sortBy === 'count') {
      list = [...list].sort((a, b) => (b.validated_count || 0) - (a.validated_count || 0));
    } else if (sortBy === 'title') {
      list = [...list].sort((a, b) => (a.title || '').localeCompare(b.title || ''));
    } else {
      list = [...list].sort((a, b) => new Date(b.latest_end || 0) - new Date(a.latest_end || 0));
    }
    
    return list;
  }, [papers, sortBy]);

  if (loading) {
    return <p style={{ color: '#666', fontStyle: 'italic' }}>Loading papers...</p>;
  }

  if (error) {
    return <p style={{ color: '#c53030' }}>Error loading papers: {error}</p>;
  }

  return (
    <>
      <div>
        {/* Mobile Filter Toggle */}
        <div className="mobile-filter-toggle" style={{
          display: 'block',
          marginBottom: '1rem'
        }}>
          <button
            onClick={() => setMobileFiltersOpen(!mobileFiltersOpen)}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '0.5rem',
              padding: '0.5rem 1rem',
              border: '1px solid #ccc',
              borderRadius: '4px',
              backgroundColor: 'white',
              cursor: 'pointer',
              fontSize: 'var(--font-base)',
            }}
          >
            Filters
            {(() => {
              let count = 0;
              if (filters.missions && filters.missions.length > 0) count += filters.missions.length;
              if (filters.instruments && filters.instruments.length > 0) count += filters.instruments.length;
              if (filters.start_date || filters.end_date) count += 1;
              return count > 0 ? (
                <span style={{
                  fontSize: 'var(--font-sm)',
                  backgroundColor: '#3182ce',
                  color: 'white',
                  padding: '0.2rem 0.4rem',
                  borderRadius: '10px',
                  minWidth: '20px',
                  textAlign: 'center',
                }}>
                  {count}
                </span>
              ) : null;
            })()}
            <span style={{
              marginLeft: 'auto',
              transform: mobileFiltersOpen ? 'rotate(180deg)' : 'rotate(0deg)',
              transition: 'transform 0.2s'
            }}>
              ▼
            </span>
          </button>
        </div>

        <div className="papers-layout" style={{
          display: 'flex',
          gap: '1rem',
          alignItems: 'flex-start',
          minHeight: '70vh',
          flexDirection: 'row'
        }}>
          {/* Filters Sidebar */}
          <div
            className={`filters-sidebar ${mobileFiltersOpen ? 'mobile-open' : ''}`}
            style={{
              '--sidebar-display': mobileFiltersOpen ? 'block' : 'none'
            }}
          >
            <FacetedFilters
              filters={filters}
              onFiltersChange={handleFiltersChange}
              filterOptions={filterOptions}
              loading={filterLoading}
              hideValidationStatus={true}
              includeUnvalidated={includeUnvalidated}
              onToggleUnvalidated={handleToggleUnvalidated}
            />
          </div>

          {/* Main Content */}
          <div style={{ flex: 1, minWidth: 0 }}>
            <UnifiedSearchBar
              filterOptions={filterOptions}
              filters={filters}
              onFiltersChange={handleFiltersChange}
              searchQuery={searchQuery}
              onSearchChange={(val) => {
                setSearchQuery(val);
                const newParams = new URLSearchParams(searchParams);
                if (val && val.trim()) {
                  newParams.set('q', val.trim());
                } else {
                  newParams.delete('q');
                }
                newParams.delete('page');
                setSearchParams(newParams);
              }}
              searchInputRef={searchInputRef}
            />
            <div style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              marginBottom: '0.75rem',
            }}>
              <p style={{ color: '#888', margin: 0, fontSize: 'var(--font-sm)' }}>
                Showing {papers.length} of {pagination.count} papers.
                {pagination.total_pages > 1 && ` Page ${currentPage} of ${pagination.total_pages}.`}
              </p>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                {isFiltering && (
                  <div style={{
                    color: '#666',
                    fontSize: 'var(--font-sm)',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '0.4rem'
                  }}>
                    <div style={{
                      width: '14px',
                      height: '14px',
                      border: '2px solid #ddd',
                      borderTop: '2px solid #3182ce',
                      borderRadius: '50%',
                      animation: 'spin 1s linear infinite'
                    }}></div>
                  </div>
                )}
                <div style={{ display: 'flex', alignItems: 'center', gap: 0 }}>
                  <span style={{
                    padding: '0.35rem 0.5rem',
                    fontSize: 'var(--font-sm)',
                    color: '#555',
                    backgroundColor: '#f5f5f5',
                    border: '1px solid #ccc',
                    borderRight: 'none',
                    borderRadius: '4px 0 0 4px',
                    whiteSpace: 'nowrap',
                    userSelect: 'none',
                  }}>Sort by</span>
                  <select
                    value={sortBy}
                    onChange={e => setSortBy(e.target.value)}
                    style={{
                      padding: '0.35rem 0.5rem',
                      border: '1px solid #ccc',
                      borderRadius: '0 4px 4px 0',
                      fontSize: 'var(--font-sm)',
                      color: '#333',
                      backgroundColor: 'white',
                      cursor: 'pointer',
                      appearance: 'none',
                      WebkitAppearance: 'none',
                      backgroundImage: 'url("data:image/svg+xml,%3Csvg xmlns=\'http://www.w3.org/2000/svg\' width=\'10\' height=\'6\'%3E%3Cpath d=\'M0 0l5 6 5-6z\' fill=\'%23666\'/%3E%3C/svg%3E")',
                      backgroundRepeat: 'no-repeat',
                      backgroundPosition: 'right 0.5rem center',
                      paddingRight: '1.5rem',
                    }}
                  >
                    <option value="latest">Latest Observation</option>
                    <option value="count">Most Observations</option>
                    <option value="title">Title (A–Z)</option>
                    <option value="bibcode">Bibcode</option>
                  </select>
                </div>
              </div>
            </div>

            {/* Papers List */}
            {filteredPapers.length === 0 ? (
              <p style={{ color: '#666', fontStyle: 'italic' }}>
                {searchQuery.trim() ? 'No papers found matching your search.' : 'No papers available.'}
              </p>
            ) : (
              <ul style={{ 
                listStyle: 'none', 
                padding: 0, 
                margin: 0,
                lineHeight: '1.6',
                opacity: isFiltering ? 0.6 : 1,
                transition: 'opacity 0.3s ease-in-out'
              }}>
                {filteredPapers.map((paper) => (
                  <li key={paper.id} style={{
                    marginBottom: '1rem',
                    paddingBottom: '1rem',
                    borderBottom: '1px solid #eee'
                  }}>
                    <h3 style={{
                      margin: '0 0 0.3rem 0',
                      fontSize: 'var(--font-2xl)',
                      fontWeight: '400'
                    }}>
                      <Link 
                        to={`/public/p/${encodeURIComponent(paper.bibcode)}${searchParams.toString() ? `?${searchParams.toString()}` : ''}`}
                        style={{ 
                          color: '#3182ce', 
                          textDecoration: 'underline',
                          textDecorationColor: 'rgba(49, 130, 206, 0.3)'
                        }}
                        onMouseEnter={(e) => {
                          e.target.style.textDecorationColor = '#3182ce';
                        }}
                        onMouseLeave={(e) => {
                          e.target.style.textDecorationColor = 'rgba(49, 130, 206, 0.3)';
                        }}
                      >
                        {paper.title || paper.bibcode}
                      </Link>
                    </h3>
                    
                    {Array.isArray(paper.authors) && paper.authors.length > 0 && (
                      <p style={{ 
                        margin: '0 0 0.3rem 0',
                        color: '#666',
                        fontSize: 'var(--font-base)'
                      }}>
                        {paper.authors.slice(0, 5).join(', ')}
                        {paper.authors.length > 5 && ' et al.'}
                      </p>
                    )}
                    
                    <p style={{ 
                      margin: '0',
                      fontSize: 'var(--font-sm)',
                      color: '#999'
                    }}>
                      <code>{paper.bibcode}</code>
                      {paper.year && ` • ${paper.year}`}
                      {paper.journal && ` • ${paper.journal}`}
                      {paper.validated_count && (
                        includeUnvalidated && paper.total_count && paper.total_count > paper.validated_count
                          ? ` • ${paper.validated_count}/${paper.total_count} reviewed`
                          : ` • ${paper.validated_count} observation${paper.validated_count !== 1 ? 's' : ''}`
                      )}
                      {paper.mission_only_match_count > 0 && !paper.has_matching_dataset_usage && (
                        ` • Mission mention only (${paper.mission_only_match_count})`
                      )}
                      {paper.latest_end && ` • Latest: ${formatDate(paper.latest_end)}`}
                      
                      <span style={{ marginLeft: '1rem' }}>
                        <a
                          href={`https://ui.adsabs.harvard.edu/abs/${encodeURIComponent(paper.bibcode)}/abstract`}
                          target="_blank"
                          rel="noopener noreferrer"
                          style={{ color: '#3182ce', textDecoration: 'none' }}
                        >
                          ADS ↗
                        </a>
                      </span>
                    </p>
                  </li>
                ))}
              </ul>
            )}
            
            {/* Pagination Controls */}
            {pagination.total_pages > 1 && (
              <div style={{ 
                display: 'flex', 
                justifyContent: 'center', 
                alignItems: 'center', 
                gap: '1rem',
                marginTop: '3rem',
                padding: '2rem 0'
              }}>
                <button
                  onClick={() => handlePageChange(currentPage - 1)}
                  disabled={currentPage <= 1}
                  style={{
                    padding: '0.5rem 1rem',
                    border: '1px solid #ccc',
                    borderRadius: '4px',
                    backgroundColor: currentPage <= 1 ? '#f5f5f5' : 'white',
                    color: currentPage <= 1 ? '#999' : '#333',
                    cursor: currentPage <= 1 ? 'not-allowed' : 'pointer',
                    fontSize: 'var(--font-base)'
                  }}
                >
                  ← Previous
                </button>
                
                <div style={{ 
                  display: 'flex', 
                  gap: '0.5rem',
                  alignItems: 'center'
                }}>
                  {Array.from({ length: Math.min(5, pagination.total_pages) }, (_, i) => {
                    let pageNum;
                    if (pagination.total_pages <= 5) {
                      pageNum = i + 1;
                    } else if (currentPage <= 3) {
                      pageNum = i + 1;
                    } else if (currentPage >= pagination.total_pages - 2) {
                      pageNum = pagination.total_pages - 4 + i;
                    } else {
                      pageNum = currentPage - 2 + i;
                    }
                    
                    return (
                      <button
                        key={pageNum}
                        onClick={() => handlePageChange(pageNum)}
                        style={{
                          padding: '0.5rem 0.75rem',
                          border: '1px solid #ccc',
                          borderRadius: '4px',
                          backgroundColor: currentPage === pageNum ? '#3182ce' : 'white',
                          color: currentPage === pageNum ? 'white' : '#333',
                          cursor: 'pointer',
                          fontSize: 'var(--font-base)',
                          minWidth: '40px'
                        }}
                      >
                        {pageNum}
                      </button>
                    );
                  })}
                </div>
                
                <button
                  onClick={() => handlePageChange(currentPage + 1)}
                  disabled={currentPage >= pagination.total_pages}
                  style={{
                    padding: '0.5rem 1rem',
                    border: '1px solid #ccc',
                    borderRadius: '4px',
                    backgroundColor: currentPage >= pagination.total_pages ? '#f5f5f5' : 'white',
                    color: currentPage >= pagination.total_pages ? '#999' : '#333',
                    cursor: currentPage >= pagination.total_pages ? 'not-allowed' : 'pointer',
                    fontSize: 'var(--font-base)'
                  }}
                >
                  Next →
                </button>
              </div>
            )}
          </div>
        </div>
      </div>
    </>
  );
}
