// src/components/pdfViewer/TooltipPortal.jsx
import React from 'react';
import ReactDOM from 'react-dom';
import { useValidation } from '../../context/ValidationContext';

const TooltipContent = ({ annotation, position }) => {
  if (!annotation) return null;

  return (
    <div
      className="tooltip"
      style={{
        display: 'block',
        left: position.left,
        top: position.top
      }}
    >
      <div><strong>Instrument:</strong> {annotation.instrumentName}</div>
      {annotation.fieldType && (
        <div><strong>{getFieldDisplayName(annotation.fieldType)}:</strong> {annotation.fieldValue}</div>
      )}
      {annotation.excerpt && (
        <div>
          <strong>Supporting Quote:</strong>
          <div className="quote">"{annotation.excerpt}"</div>
        </div>
      )}
    </div>
  );
};

// Helper to get field display name
const getFieldDisplayName = (fieldType) => {
  const displayNames = {
    general_comments: 'General Description',
    detectors: 'Detectors',
    start_time: 'Start Date',
    end_time: 'End Date',
    wavelengths: 'Wavelengths',
    physical_observable: 'Physical Observable',
    spacecraft: 'Spacecraft'
  };

  return displayNames[fieldType] || fieldType;
};

const TooltipPortal = () => {
  const { selectedAnnotation } = useValidation();

  // Calculate position based on mouse or element position
  const position = { left: 100, top: 100 }; // This would be dynamic in a full implementation

  if (!selectedAnnotation) return null;

  return ReactDOM.createPortal(
    <TooltipContent
      annotation={selectedAnnotation}
      position={position}
    />,
    document.body
  );
};

export default TooltipPortal;