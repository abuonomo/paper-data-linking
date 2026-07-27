import React, { useState, useEffect, useRef } from 'react';
import Annotation from './Annotation';
import { useValidation } from '../../context/ValidationContext';

const PDFPage = ({ pdf, pageNumber, annotations, focusedQuoteIds = [], searchMatches = [], currentMatchIndex = -1, matchIndexOffset = 0 }) => {
  const [page, setPage] = useState(null);
  const [viewport, setViewport] = useState(null);
  const [pageRendered, setPageRendered] = useState(false);
  const canvasRef = useRef(null);
  const textLayerRef = useRef(null);
  const pageContainerRef = useRef(null);
  const renderTaskRef = useRef(null);
  const scale = 1.5;

  // Clean up render task on unmount
  useEffect(() => {
    return () => {
      if (renderTaskRef.current) {
        renderTaskRef.current.cancel();
        renderTaskRef.current = null;
      }
    };
  }, []);

  // Load the page
  useEffect(() => {
    let isMounted = true;

    const loadPage = async () => {
      try {
        // Cancel any existing render task
        if (renderTaskRef.current) {
          renderTaskRef.current.cancel();
          renderTaskRef.current = null;
        }

        const pdfPage = await pdf.getPage(pageNumber);
        if (!isMounted) return;

        setPage(pdfPage);

        const vp = pdfPage.getViewport({ scale });
        setViewport(vp);
      } catch (err) {
        console.error(`Error loading page ${pageNumber}:`, err);
      }
    };

    if (pdf) {
      loadPage();
    }

    return () => {
      isMounted = false;
    };
  }, [pdf, pageNumber, scale]);

  // Render the page once viewport is set
  useEffect(() => {
    let isMounted = true;

    const renderPage = async () => {
      if (!page || !viewport || !canvasRef.current || !isMounted) return;

      try {
        // Cancel any existing render task
        if (renderTaskRef.current) {
          renderTaskRef.current.cancel();
          renderTaskRef.current = null;
        }

        const canvas = canvasRef.current;
        const context = canvas.getContext('2d');

        if (!context) {
          console.error('Could not get canvas context');
          return;
        }

        canvas.width = viewport.width;
        canvas.height = viewport.height;

        // Store the rendering task so we can cancel it if needed
        const renderTask = page.render({
          canvasContext: context,
          viewport: viewport
        });

        renderTaskRef.current = renderTask;

        await renderTask.promise;
        if (!isMounted) return;

        renderTaskRef.current = null;

        // Handle text layer
        if (textLayerRef.current) {
          try {
            const textContent = await page.getTextContent();
            if (!isMounted) return;
            renderTextLayer(textContent, viewport);
          } catch (err) {
            console.error(`Error rendering text layer for page ${pageNumber}:`, err);
          }
        }

        setPageRendered(true);
      } catch (err) {
        // Only log if still mounted
        if (isMounted) {
          console.error(`Error rendering canvas for page ${pageNumber}:`, err);
        }
      }
    };

    renderPage();

    return () => {
      isMounted = false;
      if (renderTaskRef.current) {
        renderTaskRef.current.cancel();
        renderTaskRef.current = null;
      }
    };
  }, [page, viewport, pageNumber]);

  // Render text layer for searchability with search highlighting
  const renderTextLayer = (textContent, viewport) => {
    if (!textLayerRef.current) return;

    const textLayer = textLayerRef.current;
    textLayer.innerHTML = '';

    textContent.items.forEach((item, itemIndex) => {
      try {
        const textElement = document.createElement('span');
        const styles = textContent.styles[item.fontName];

        // Use the standard PDF.js text layer approach
        const transform = item.transform;
        
        // Calculate font size (height of the text)
        const fontHeight = Math.sqrt(transform[2] * transform[2] + transform[3] * transform[3]);
        
        // Position in PDF coordinates - transform[5] is the baseline Y position
        const left = transform[4];
        const baseline = transform[5];
        
        // Convert baseline position to screen coordinates
        const point = viewport.convertToViewportPoint(left, baseline);
        
        textElement.style.left = `${point[0]}px`;
        textElement.style.top = `${point[1] - fontHeight * viewport.scale}px`; // Subtract font height to align properly
        textElement.style.fontSize = `${fontHeight * viewport.scale}px`;
        
        // Handle text scaling and rotation
        const scaleX = Math.sqrt(transform[0] * transform[0] + transform[1] * transform[1]);
        const scaleY = Math.sqrt(transform[2] * transform[2] + transform[3] * transform[3]);
        
        if (scaleX !== scaleY || transform[1] !== 0 || transform[2] !== 0) {
          const angle = Math.atan2(transform[1], transform[0]) * (180 / Math.PI);
          textElement.style.transform = `rotate(${angle}deg) scaleX(${scaleX / scaleY})`;
        }

        if (styles && styles.fontFamily) {
          textElement.style.fontFamily = styles.fontFamily;
        }

        // Always use textContent for proper text rendering
        textElement.textContent = item.str;
        
        textElement.className = 'text-item';
        // Tag span so highlights can reference precise geometry
        textElement.setAttribute('data-item-index', String(itemIndex));

        textLayer.appendChild(textElement);
      } catch (e) {
        console.error('Error rendering text item:', e);
      }
    });

    // Create search highlight overlays
    if (searchMatches.length > 0) {
      renderSearchHighlights(textContent, viewport);
    }
  };

  // Render search highlight overlays
  const renderSearchHighlights = (textContent, viewport) => {
    if (!pageContainerRef.current) return;

    // Remove existing highlights
    const existingHighlights = pageContainerRef.current.querySelectorAll('.search-highlight-overlay');
    existingHighlights.forEach(el => el.remove());

    let highlightsCreated = 0;

    textContent.items.forEach((item, itemIndex) => {
      const matchesInItem = searchMatches.filter(match => match.itemIndex === itemIndex);
      
      if (matchesInItem.length === 0) return;

      matchesInItem.forEach((match) => {
        // Use the index within the full page's matches array, not within this item's subset
        const pageLocalIndex = searchMatches.indexOf(match);
        const globalMatchIndex = matchIndexOffset + (pageLocalIndex >= 0 ? pageLocalIndex : 0);
        const isCurrentMatch = globalMatchIndex === currentMatchIndex;

        // Create highlight overlay element
        const highlightEl = document.createElement('div');
        highlightEl.className = `search-highlight-overlay ${isCurrentMatch ? 'current-match' : ''}`;
        highlightEl.setAttribute('data-match-index', String(globalMatchIndex));

        // Preferred: compute geometry from the actual rendered text span
        const span = textLayerRef.current?.querySelector(
          `.text-item[data-item-index="${itemIndex}"]`
        );

        let placed = false;
        if (span) {
          const containerRect = pageContainerRef.current.getBoundingClientRect();
          const spanRect = span.getBoundingClientRect();

          const spanWidth = spanRect.width;
          const spanHeight = spanRect.height;
          const spanLeft = spanRect.left - containerRect.left;
          const spanTop = spanRect.top - containerRect.top;

          const itemText = item.str || '';
          const textLen = itemText.length || 1; // avoid div by zero
          const startRatio = Math.min(Math.max(match.matchStart / textLen, 0), 1);
          const widthRatio = Math.min(Math.max((match.matchEnd - match.matchStart) / textLen, 0), 1);

          const hlLeft = spanLeft + spanWidth * startRatio;
          const hlWidth = spanWidth * widthRatio;

          highlightEl.style.position = 'absolute';
          highlightEl.style.left = `${hlLeft}px`;
          highlightEl.style.top = `${spanTop}px`;
          highlightEl.style.width = `${hlWidth}px`;
          highlightEl.style.height = `${spanHeight}px`;
          placed = true;
        }

        // Fallback: approximate using transform (with corrected start offset math)
        if (!placed) {
          const transform = item.transform;
          const fontHeight = Math.sqrt(transform[2] * transform[2] + transform[3] * transform[3]);
          const left = transform[4];
          const baseline = transform[5];
          const point = viewport.convertToViewportPoint(left, baseline);

          const matchText = item.str.substring(match.matchStart, match.matchEnd);
          const charWidth = fontHeight * viewport.scale * 0.6; // rough per-char width
          const textWidth = matchText.length * charWidth;

          highlightEl.style.position = 'absolute';
          // remove extra 0.6 multiplier on start offset
          highlightEl.style.left = `${point[0] + (match.matchStart * charWidth)}px`;
          highlightEl.style.top = `${point[1] - fontHeight * viewport.scale}px`;
          highlightEl.style.width = `${textWidth}px`;
          highlightEl.style.height = `${fontHeight * viewport.scale}px`;
        }

        // Optional debug
        // console.log(`Highlight for page ${pageNumber} item ${itemIndex} [${match.matchStart}, ${match.matchEnd}]`);

        pageContainerRef.current.appendChild(highlightEl);
        highlightsCreated++;
      });
    });

    console.log(`Page ${pageNumber}: Created ${highlightsCreated} highlight overlays`);
  };

  // Re-render highlights when search matches change
  useEffect(() => {
    console.log(`Page ${pageNumber}: ${searchMatches.length} search matches, currentMatchIndex: ${currentMatchIndex}`);
    
    if (pageRendered && page) {
      const textContent = page.getTextContent();
      textContent.then(content => {
        if (searchMatches.length > 0) {
          console.log(`Page ${pageNumber}: Rendering ${searchMatches.length} highlights`);
          renderSearchHighlights(content, viewport);
        } else {
          // Remove all highlights if no search matches
          const existingHighlights = pageContainerRef.current?.querySelectorAll('.search-highlight-overlay');
          existingHighlights?.forEach(el => el.remove());
        }
      }).catch(err => console.error('Error re-rendering search highlights:', err));
    }
  }, [searchMatches, currentMatchIndex, pageRendered, page, viewport]);

  if (!viewport) {
    return <div className="page-loading">Loading page {pageNumber}...</div>;
  }

  return (
    <div
      ref={pageContainerRef}
      className="page-container"
      data-page-number={pageNumber}
      style={{ width: viewport.width, height: viewport.height }}
    >
      <canvas ref={canvasRef}></canvas>

      <div
        ref={textLayerRef}
        className="text-layer"
        style={{ width: viewport.width, height: viewport.height }}
      ></div>

      {pageRendered && annotations.map((annotation, index) => (
        <Annotation
          key={`annotation-${pageNumber}-${index}`}
          annotation={annotation}
          viewport={viewport}
          isFocused={focusedQuoteIds.includes(annotation.id)}
        />
      ))}
    </div>
  );
};

export default PDFPage;
