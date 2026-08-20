// src/components/CampaignRubricModal.jsx
//
// Renders the campaign rubric — the exact RUBRIC.md the reviewers ratified,
// served by the campaign API — as proper markdown in a modal.
import React, { useEffect, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { fetchCampaignRubric } from '../services/apiServices';
import './CampaignRubricModal.css';

const CampaignRubricModal = ({ slug, onClose }) => {
  const [markdown, setMarkdown] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    fetchCampaignRubric(slug)
      .then(data => { if (!cancelled) setMarkdown(data.markdown); })
      .catch(() => { if (!cancelled) setError('Failed to load rubric.'); });
    return () => { cancelled = true; };
  }, [slug]);

  return (
    <div className="modal-overlay" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="context-modal rubric-modal">
        <div className="context-modal-header">
          <h2>Review Rubric</h2>
          <button className="modal-close" onClick={onClose}>&times;</button>
        </div>
        <div className="context-modal-body rubric-modal-body">
          {error && <p className="rubric-modal-error">{error}</p>}
          {!error && markdown === null && <p className="rubric-modal-loading">Loading…</p>}
          {markdown !== null && (
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{markdown}</ReactMarkdown>
          )}
        </div>
      </div>
    </div>
  );
};

export default CampaignRubricModal;
