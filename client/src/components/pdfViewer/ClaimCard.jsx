// src/components/pdfViewer/ClaimCard.jsx
import React from 'react';
import { useValidation } from '../../context/ValidationContext';

const ClaimCard = ({ claim, hasAnnotations, onViewInPdf }) => {
  const {
    validationState,
    validateClaim,
    rejectClaim,
    resetClaim
  } = useValidation();

  const status = validationState[claim.id];

  return (
    <div
      className={`claim-card ${status || ''}`}
      data-id={claim.id}
      data-tag={claim.tag}
    >
      <div className="claim-card-header">
        <div className="instrument-name">
          Instrument: {claim.instrumentName}
        </div>
      </div>

      <div className="claim-card-content">
        {claim.periodDescription && (
          <div className="period-description">
            Period Description: {claim.periodDescription}
          </div>
        )}

        <div className="claim-card-label">
          {claim.label}: <span className="claim-card-value">{claim.value}</span>
        </div>

        {claim.excerpt && (
          <div className="claim-card-quote">
            <strong>Supporting Quote:</strong> <i className="quote-icon">"</i>
            {claim.excerpt}
            <i className="quote-icon">"</i>
          </div>
        )}
      </div>

      {hasAnnotations && (
        <div className="claim-card-link">
          <button
            className="pdf-link-button"
            onClick={onViewInPdf}
          >
            <span className="pdf-icon">📄</span> View in PDF
          </button>
        </div>
      )}

      {status && (
        <div className={`validation-status status-${status}`}>
          {status === 'validated' ? '✓ Validated' : '✗ Rejected'}
        </div>
      )}

      <div className="validation-buttons">
        <button
          className="btn btn-validate"
          onClick={() => validateClaim(claim.id)}
        >
          Validate
        </button>
        <button
          className="btn btn-reject"
          onClick={() => rejectClaim(claim.id)}
        >
          Reject
        </button>
        <button
          className="btn btn-reset"
          onClick={() => resetClaim(claim.id)}
        >
          Reset
        </button>
      </div>
    </div>
  );
};

export default ClaimCard;