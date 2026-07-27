// usePDFSearch.js
import { useState, useEffect, useRef, useCallback } from 'react';

export const usePDFSearch = (pdf, numPages) => {
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState([]);
  const [currentMatchIndex, setCurrentMatchIndex] = useState(0);
  const [isSearching, setIsSearching] = useState(false);
  const [isSearchVisible, setIsSearchVisible] = useState(false);
  
  // Cache for extracted text content
  const textContentCache = useRef(new Map());
  const searchDebounceRef = useRef(null);

  // Extract text content from all pages and cache it
  const extractAllText = useCallback(async () => {
    if (!pdf || !numPages) return;

    const textData = [];
    
    for (let pageNum = 1; pageNum <= numPages; pageNum++) {
      if (textContentCache.current.has(pageNum)) {
        textData.push(textContentCache.current.get(pageNum));
        continue;
      }

      try {
        const page = await pdf.getPage(pageNum);
        const textContent = await page.getTextContent();
        
        const pageData = {
          pageNumber: pageNum,
          items: textContent.items.map((item, itemIndex) => ({
            text: item.str,
            itemIndex,
            transform: item.transform,
            fontName: item.fontName
          }))
        };
        
        textContentCache.current.set(pageNum, pageData);
        textData.push(pageData);
      } catch (error) {
        console.error(`Error extracting text from page ${pageNum}:`, error);
      }
    }
    
    return textData;
  }, [pdf, numPages]);

  // Perform search across all extracted text
  const performSearch = useCallback(async (query) => {
    if (!query || query.length < 2) {
      setSearchResults([]);
      setCurrentMatchIndex(0);
      return;
    }

    setIsSearching(true);
    
    try {
      const textData = await extractAllText();
      if (!textData) return;

      const results = [];
      const searchTerm = query.toLowerCase();

      textData.forEach(pageData => {
        pageData.items.forEach((item, itemIndex) => {
          const text = item.text.toLowerCase();
          let startIndex = 0;
          let matchIndex;

          // Find all matches in this text item
          while ((matchIndex = text.indexOf(searchTerm, startIndex)) !== -1) {
            results.push({
              pageNumber: pageData.pageNumber,
              itemIndex,
              matchStart: matchIndex,
              matchEnd: matchIndex + searchTerm.length,
              matchText: item.text.substring(matchIndex, matchIndex + searchTerm.length),
              contextText: item.text,
              transform: item.transform
            });
            startIndex = matchIndex + 1;
          }
        });
      });

      setSearchResults(results);
      setCurrentMatchIndex(results.length > 0 ? 0 : -1);
      console.log('Search results:', results.length, 'matches for:', query);
    } catch (error) {
      console.error('Error performing search:', error);
      setSearchResults([]);
      setCurrentMatchIndex(0);
    } finally {
      setIsSearching(false);
    }
  }, [extractAllText]);

  // Debounced search
  useEffect(() => {
    if (searchDebounceRef.current) {
      clearTimeout(searchDebounceRef.current);
    }

    searchDebounceRef.current = setTimeout(() => {
      performSearch(searchQuery);
    }, 300);

    return () => {
      if (searchDebounceRef.current) {
        clearTimeout(searchDebounceRef.current);
      }
    };
  }, [searchQuery, performSearch]);

  // Navigation functions
  const goToNextMatch = useCallback(() => {
    if (searchResults.length === 0) return;
    
    const nextIndex = (currentMatchIndex + 1) % searchResults.length;
    setCurrentMatchIndex(nextIndex);
  }, [searchResults, currentMatchIndex]);

  const goToPreviousMatch = useCallback(() => {
    if (searchResults.length === 0) return;
    
    const prevIndex = currentMatchIndex === 0 
      ? searchResults.length - 1 
      : currentMatchIndex - 1;
    setCurrentMatchIndex(prevIndex);
  }, [searchResults, currentMatchIndex]);

  const goToMatch = useCallback((index) => {
    if (index >= 0 && index < searchResults.length) {
      setCurrentMatchIndex(index);
    }
  }, [searchResults]);

  // Get current match for scrolling
  const currentMatch = searchResults.length > 0 && currentMatchIndex >= 0 
    ? searchResults[currentMatchIndex] 
    : null;

  // Clear search
  const clearSearch = useCallback(() => {
    setSearchQuery('');
    setSearchResults([]);
    setCurrentMatchIndex(0);
    setIsSearchVisible(false);
  }, []);

  // Show search interface
  const showSearch = useCallback(() => {
    setIsSearchVisible(true);
  }, []);

  // Get matches for a specific page (for highlighting)
  const getMatchesForPage = useCallback((pageNumber) => {
    return searchResults.filter(result => result.pageNumber === pageNumber);
  }, [searchResults]);

  return {
    // Search state
    searchQuery,
    setSearchQuery,
    searchResults,
    currentMatchIndex,
    currentMatch,
    isSearching,
    isSearchVisible,
    
    // Actions
    showSearch,
    clearSearch,
    goToNextMatch,
    goToPreviousMatch,
    goToMatch,
    
    // Utilities
    getMatchesForPage,
    totalMatches: searchResults.length
  };
};