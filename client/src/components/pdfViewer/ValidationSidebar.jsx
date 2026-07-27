// src/components/pdfViewer/ValidationSidebar.jsx
import React, { useEffect } from 'react';
import ClaimCard from './ClaimCard';
import { useValidation } from '../../context/ValidationContext';

const ValidationSidebar = ({ claims, annotations }) => {
  const {
    validationState,
    saveValidationState,
    highlightAnnotation,
    clearHighlights
  } = useValidation();

  // Calculate validation statistics
  const calculateStats = () => {
    let validatedCount = 0;
    let rejectedCount = 0;

    Object.values(validationState).forEach(status => {
      if (status === 'validated') validatedCount++;
      else if (status === 'rejected') rejectedCount++;
    });

    const totalClaims = claims.length;
    const progressPercent = totalClaims > 0
      ? ((validatedCount + rejectedCount) / totalClaims * 100)
      : 0;

    return {
      total: totalClaims,
      validated: validatedCount,
      rejected: rejectedCount,
      progressPercent
    };
  };

  const stats = calculateStats();

  // Listen for scroll to claim events
  useEffect(() => {
    const handleScrollToClaim = (event) => {
      const { tag } = event.detail;
      scrollToSidebarClaim(tag);
    };

    document.addEventListener('scrollToSidebarClaim', handleScrollToClaim);
    return () => {
      document.removeEventListener('scrollToSidebarClaim', handleScrollToClaim);
    };
  }, []);

  // Function to scroll to a claim in the sidebar
  const scrollToSidebarClaim = (tag) => {
    const claimElement = document.querySelector(`.claim-card[data-tag*="${tag}"]`);
    if (claimElement) {
      claimElement.scrollIntoView({ behavior: 'auto', block: 'center' });
      claimElement.classList.add('highlight');

      setTimeout(() => {
        claimElement.classList.remove('highlight');
      }, 3000);
    }
  };

  return (
    <div className="validation-sidebar">
      <h2>Validation Dashboard</h2>

      <div className="validation-stats">
        <div>Claims to validate: <span>{stats.total}</span></div>
        <div>Validated: <span>{stats.validated}</span></div>
        <div>Rejected: <span>{stats.rejected}</span></div>
        <div className="progress-bar-container">
          <div
            className="progress-bar"
            style={{ width: `${stats.progressPercent}%` }}
          ></div>
        </div>
      </div>

      <div className="claims-container">
        {claims.map((claim, index) => {
          const relatedAnnotations = annotations.filter(
            ann => ann.tag.includes(claim.tag)
          );

          return (
            <ClaimCard
              key={`claim-${index}`}
              claim={claim}
              hasAnnotations={relatedAnnotations.length > 0}
              onViewInPdf={() => {
                if (relatedAnnotations.length > 0) {
                  highlightAnnotation(claim.tag);
                  // Scroll to the first annotation
                  const element = document.querySelector(
                    `.annotation-overlay[data-tag*="${claim.tag}"]`
                  );
                  if (element) {
                    element.scrollIntoView({ behavior: 'smooth', block: 'center' });
                  }
                }
              }}
            />
          );
        })}
      </div>

      <button
        className="save-button"
        onClick={saveValidationState}
      >
        Save Validations
      </button>
    </div>
  );
};

export default ValidationSidebar;
