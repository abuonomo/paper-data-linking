// src/components/pdfViewer/Annotation.jsx
import React, { useRef, useEffect } from 'react';
import { useValidation } from '../../context/ValidationContext';

const Annotation = ({ annotation, viewport, isFocused = false }) => {
  const {
    validationState,
    highlightedTag,
    highlightAnnotation,
    clearHighlights,
    selectAnnotation
  } = useValidation();

  // Calculate position for annotation overlay
  const calculatePosition = () => {
    const unscaledHeight = viewport.height / viewport.scale;

    // Convert PDF coordinates to viewport coordinates
    const flippedRect = [
      annotation.pdfRect[0],
      unscaledHeight - annotation.pdfRect[3],
      annotation.pdfRect[2],
      unscaledHeight - annotation.pdfRect[1]
    ];

    const rect = viewport.convertToViewportRectangle(flippedRect);

    return {
      left: Math.min(rect[0], rect[2]),
      top: Math.min(rect[1], rect[3]),
      width: Math.abs(rect[0] - rect[2]),
      height: Math.abs(rect[1] - rect[3])
    };
  };

  const position = calculatePosition();

  // Find validation status for this annotation's tag
  const getValidationStatus = () => {
    // Find matching claim ID in validation state
    for (const claimId in validationState) {
      if (claimId.includes(annotation.tag.split('|')[0])) {
        return validationState[claimId];
      }
    }
    return null;
  };

  const validationStatus = getValidationStatus();
  const isHighlighted = highlightedTag === annotation.tag;

  const handleMouseEnter = () => {
    highlightAnnotation(annotation.tag);
    selectAnnotation(annotation);
  };

  const handleMouseLeave = () => {
    clearHighlights();
  };

  const handleClick = () => {
    // This will trigger the sidebar to scroll to the matching claim
    const event = new CustomEvent('scrollToSidebarClaim', {
      detail: { tag: annotation.tag }
    });
    document.dispatchEvent(event);
  };

  // Determine additional CSS classes for multi-line quotes
  const getMultilineClasses = () => {
    if (!annotation.isMultiline) return '';
    
    const classes = ['multiline-quote'];
    
    // Add position indicators for multi-line quotes
    if (annotation.regionIndex === 0) {
      classes.push('multiline-first');
    } else if (annotation.regionIndex === annotation.totalRegions - 1) {
      classes.push('multiline-last');
    } else {
      classes.push('multiline-middle');
    }
    
    return classes.join(' ');
  };

  return (
    <div
      className={`annotation-overlay ${validationStatus || ''} ${isHighlighted ? 'highlight-all' : ''} ${isFocused ? 'focused-quote' : ''} ${getMultilineClasses()}`}
      style={{
        left: position.left,
        top: position.top,
        width: position.width,
        height: position.height
      }}
      data-tag={annotation.tag}
      data-annotation-id={annotation.id}
      data-multiline={annotation.isMultiline || false}
      data-region-index={annotation.regionIndex || 0}
      data-total-regions={annotation.totalRegions || 1}
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
      onClick={handleClick}
      title={annotation.isMultiline ? 
        `Multi-line quote (part ${annotation.regionIndex + 1} of ${annotation.totalRegions})` : 
        'Single-line quote'}
    />
  );
};

export default Annotation;