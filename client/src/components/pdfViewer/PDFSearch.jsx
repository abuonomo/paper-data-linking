// PDFSearch.jsx
import React, { useRef, useEffect } from 'react';

const PDFSearch = ({
  searchQuery,
  setSearchQuery,
  totalMatches,
  currentMatchIndex,
  isSearching,
  onNextMatch,
  onPreviousMatch,
  onClose
}) => {
  const inputRef = useRef(null);

  // Focus input when component mounts
  useEffect(() => {
    if (inputRef.current) {
      inputRef.current.focus();
    }
  }, []);

  // Handle keyboard shortcuts
  const handleKeyDown = (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      if (e.shiftKey) {
        onPreviousMatch();
      } else {
        onNextMatch();
      }
    } else if (e.key === 'Escape') {
      e.preventDefault();
      onClose();
    }
  };

  const handleInputChange = (e) => {
    setSearchQuery(e.target.value);
  };

  const handleClear = () => {
    setSearchQuery('');
    if (inputRef.current) {
      inputRef.current.focus();
    }
  };

  const resultsText = totalMatches > 0 
    ? `${currentMatchIndex + 1}/${totalMatches}`
    : totalMatches === 0 && searchQuery.length >= 2 
      ? 'No results' 
      : '';

  return (
    <div className="pdf-search">
      <div className="pdf-search-container">
        {/* Search Icon */}
        <div className="search-icon">
          🔍
        </div>
        
        {/* Search Input */}
        <input
          ref={inputRef}
          type="text"
          placeholder="Search PDF..."
          value={searchQuery}
          onChange={handleInputChange}
          onKeyDown={handleKeyDown}
          className="search-input"
          autoComplete="off"
          spellCheck="false"
        />
        
        {/* Clear button (only show when there's text) */}
        {searchQuery && (
          <button
            onClick={handleClear}
            className="search-clear-btn"
            title="Clear search"
            type="button"
          >
            ×
          </button>
        )}
        
        {/* Results counter */}
        {(resultsText || isSearching) && (
          <div className="search-results-counter">
            {isSearching ? (
              <div className="search-loading">
                <div className="search-spinner"></div>
              </div>
            ) : (
              resultsText
            )}
          </div>
        )}
        
        {/* Navigation buttons (only show when there are results) */}
        {totalMatches > 0 && (
          <div className="search-nav-buttons">
            <button
              onClick={onPreviousMatch}
              className="search-nav-btn"
              title="Previous match (Shift+Enter)"
              disabled={isSearching}
              type="button"
            >
              ↑
            </button>
            <button
              onClick={onNextMatch}
              className="search-nav-btn"
              title="Next match (Enter)"
              disabled={isSearching}
              type="button"
            >
              ↓
            </button>
          </div>
        )}
        
        {/* Close button */}
        <button
          onClick={onClose}
          className="search-close-btn"
          title="Close search (Esc)"
          type="button"
        >
          ×
        </button>
      </div>
      
      {/* Keyboard shortcuts hint */}
      {searchQuery && (
        <div className="search-hints">
          <small>
            Press Enter to find next, Shift+Enter for previous, Esc to close
          </small>
        </div>
      )}
    </div>
  );
};

export default PDFSearch;