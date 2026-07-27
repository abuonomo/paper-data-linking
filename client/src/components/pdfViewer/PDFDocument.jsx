// 5. PDF Document component
// src/components/pdfViewer/PDFDocument.jsx
import React, { useEffect, useMemo, useRef } from 'react';
import PDFPage from './PDFPage';

const PDFDocument = ({ pdf, numPages, annotations, focusedQuoteIds = [], targetPage, scrollTrigger, searchMatches = [], currentMatchIndex = -1, getMatchesForPage }) => {
  const documentRef = useRef(null);

  // Precompute cumulative match offsets per page so we can tag highlights
  // with a global match index that matches currentMatchIndex
  const matchIndexOffsets = useMemo(() => {
    const offsets = {};
    let cumulative = 0;
    for (let page = 1; page <= (numPages || 0); page++) {
      offsets[page] = cumulative;
      const pageMatches = getMatchesForPage ? getMatchesForPage(page) : [];
      cumulative += pageMatches.length;
    }
    return offsets;
  }, [numPages, getMatchesForPage, searchMatches]);

  // Group annotations by page
  const annotationsByPage = annotations.reduce((acc, annotation) => {
    const pageNum = annotation.pageNumber || annotation.page;
    if (!acc[pageNum]) {
      acc[pageNum] = [];
    }
    acc[pageNum].push(annotation);
    return acc;
  }, {});

  // Find the nearest scrollable ancestor of an element
  const findScrollParent = (el) => {
    let node = el.parentElement;
    while (node) {
      const { overflowY } = getComputedStyle(node);
      if (overflowY === 'auto' || overflowY === 'scroll') return node;
      node = node.parentElement;
    }
    return null;
  };

  // Scroll to focused annotation or target page
  useEffect(() => {
    // Prefer scrolling to a specific annotation when available
    // Restart the pulse animation on all focused annotations so re-clicks are visible
    const restartFocusedAnimations = () => {
      document.querySelectorAll('.annotation-overlay.focused-quote').forEach(el => {
        el.style.animation = 'none';
        // Force reflow then re-apply
        void el.offsetHeight;
        el.style.animation = '';
      });
    };

    if (focusedQuoteIds.length > 0) {
      const scrollToAnnotation = () => {
        const el = document.querySelector(`[data-annotation-id="${focusedQuoteIds[0]}"]`);
        if (!el) return false;
        const scrollContainer = findScrollParent(el);
        if (!scrollContainer) {
          el.scrollIntoView({ behavior: 'auto', block: 'center' });
          restartFocusedAnimations();
          return true;
        }
        const containerRect = scrollContainer.getBoundingClientRect();
        const elRect = el.getBoundingClientRect();
        const offsetInContent = scrollContainer.scrollTop + (elRect.top - containerRect.top);
        scrollContainer.scrollTop = offsetInContent - (containerRect.height / 2) + (elRect.height / 2);
        restartFocusedAnimations();
        return true;
      };

      if (!scrollToAnnotation()) {
        // Annotation not in DOM yet — scroll to the page first, then poll until rendered
        if (targetPage) {
          const pageEl = document.querySelector(`[data-page-number="${targetPage}"]`);
          if (pageEl) pageEl.scrollIntoView({ behavior: 'auto', block: 'start' });
        }
        let attempts = 0;
        const poll = () => {
          if (scrollToAnnotation() || ++attempts > 20) return;
          setTimeout(poll, 100);
        };
        requestAnimationFrame(poll);
      }
    } else if (targetPage) {
      const pageElement = document.querySelector(`[data-page-number="${targetPage}"]`);
      if (pageElement) {
        pageElement.scrollIntoView({ behavior: 'auto', block: 'start' });
      }
    }
  }, [targetPage, focusedQuoteIds, scrollTrigger]);

  // Scroll to current search match
  useEffect(() => {
    if (currentMatchIndex >= 0 && searchMatches.length > 0) {
      const currentMatch = searchMatches[currentMatchIndex];
      const matchElement = document.querySelector(`[data-match-index="${currentMatchIndex}"]`);
      
      if (matchElement) {
        matchElement.scrollIntoView({ behavior: 'auto', block: 'center' });
      } else {
        // If element not found, scroll to the page containing the match
        const pageElement = document.querySelector(`[data-page-number="${currentMatch.pageNumber}"]`);
        if (pageElement) {
          pageElement.scrollIntoView({ behavior: 'auto', block: 'center' });
        }
      }
    }
  }, [currentMatchIndex, searchMatches]);

  return (
    <div className="pdf-document" ref={documentRef}>
      {Array.from({ length: numPages }, (_, i) => i + 1).map(pageNum => (
        <PDFPage
          key={`page-${pageNum}`}
          pdf={pdf}
          pageNumber={pageNum}
          annotations={annotationsByPage[pageNum] || []}
          focusedQuoteIds={focusedQuoteIds}
          searchMatches={getMatchesForPage ? getMatchesForPage(pageNum) : []}
          currentMatchIndex={currentMatchIndex}
          matchIndexOffset={matchIndexOffsets[pageNum] || 0}
        />
      ))}
    </div>
  );
};

export default PDFDocument;
