// src/components/PhenomenaValidationInterface.jsx
import React, { useState, useEffect, useCallback } from 'react';
import { toast } from 'react-toastify';
import {
  fetchPhenomenonValidationQueue,
  validatePhenomenonMention,
} from '../services/apiServices';

/**
 * Interface for validating LLM-extracted phenomenon mentions.
 *
 * Shows one mention at a time:
 *   - instrument name + data collection period
 *   - physical_observable text
 *   - supporting quotes
 *   - proposed phenomenon name + IRI
 * Accept / Reject / Needs Review buttons.
 */
const PhenomenaValidationInterface = () => {
  const [queue, setQueue] = useState([]);
  const [currentIndex, setCurrentIndex] = useState(0);
  const [isLoading, setIsLoading] = useState(true);
  const [isValidating, setIsValidating] = useState(false);
  const [error, setError] = useState(null);
  const [validationNotes, setValidationNotes] = useState('');
  const [showNotes, setShowNotes] = useState(false);
  const [totalCount, setTotalCount] = useState(0);
  const [validatedCount, setValidatedCount] = useState(0);

  const loadQueue = useCallback(async () => {
    try {
      setIsLoading(true);
      setError(null);
      const data = await fetchPhenomenonValidationQueue({
        validation_status: 'pending',
        page_size: 100,
      });
      const results = data.results || data || [];
      setQueue(results);
      setTotalCount(data.count || results.length);
      setCurrentIndex(0);
    } catch (err) {
      setError('Failed to load phenomena validation queue.');
      console.error(err);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    loadQueue();
  }, [loadQueue]);

  const currentMention = queue[currentIndex] || null;

  const handleValidate = async (statusValue) => {
    if (!currentMention || isValidating) return;
    setIsValidating(true);
    try {
      await validatePhenomenonMention(
        currentMention.id,
        statusValue,
        validationNotes,
      );

      const statusLabel = statusValue === 'accepted'
        ? 'Accepted'
        : statusValue === 'rejected'
          ? 'Rejected'
          : 'Needs Review';
      toast.success(`${statusLabel}: ${currentMention.phenomenon_name}`);

      setValidatedCount((c) => c + 1);
      setValidationNotes('');
      setShowNotes(false);

      // Advance to next item
      if (currentIndex < queue.length - 1) {
        setCurrentIndex((i) => i + 1);
      } else {
        // Reload to pick up any remaining items
        await loadQueue();
      }
    } catch (err) {
      toast.error('Failed to submit validation. Please try again.');
      console.error(err);
    } finally {
      setIsValidating(false);
    }
  };

  const handleSkip = () => {
    if (currentIndex < queue.length - 1) {
      setCurrentIndex((i) => i + 1);
    }
  };

  const handlePrevious = () => {
    if (currentIndex > 0) {
      setCurrentIndex((i) => i - 1);
    }
  };

  // ----- Render helpers -----

  if (isLoading) {
    return (
      <div className="container mt-4">
        <div className="d-flex justify-content-center align-items-center" style={{ minHeight: '200px' }}>
          <div className="spinner-border text-primary" role="status" />
          <span className="ms-3">Loading phenomena validation queue…</span>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="container mt-4">
        <div className="alert alert-danger">{error}</div>
        <button className="btn btn-primary" onClick={loadQueue}>Retry</button>
      </div>
    );
  }

  if (queue.length === 0) {
    return (
      <div className="container mt-4">
        <div className="card">
          <div className="card-body text-center py-5">
            <i className="bi bi-check-circle text-success" style={{ fontSize: '3rem' }} />
            <h4 className="mt-3">No pending phenomena to validate</h4>
            <p className="text-muted">
              All extracted phenomena have been reviewed, or none have been extracted yet.
            </p>
            <button className="btn btn-outline-primary mt-2" onClick={loadQueue}>
              Refresh
            </button>
          </div>
        </div>
      </div>
    );
  }

  const mention = currentMention;
  const progressPct = queue.length > 0
    ? Math.round(((currentIndex) / queue.length) * 100)
    : 0;

  return (
    <div className="container mt-4" style={{ maxWidth: '860px' }}>
      {/* Header */}
      <div className="d-flex justify-content-between align-items-center mb-3">
        <h4 className="mb-0">Phenomena Validation</h4>
        <span className="text-muted small">
          {currentIndex + 1} / {queue.length} in queue
          {validatedCount > 0 && (
            <span className="ms-2 badge bg-success">{validatedCount} validated this session</span>
          )}
        </span>
      </div>

      {/* Progress bar */}
      <div className="progress mb-4" style={{ height: '6px' }}>
        <div
          className="progress-bar bg-primary"
          style={{ width: `${progressPct}%` }}
          role="progressbar"
          aria-valuenow={progressPct}
          aria-valuemin={0}
          aria-valuemax={100}
        />
      </div>

      {/* Main card */}
      <div className="card shadow-sm">
        <div className="card-header bg-light">
          <div className="d-flex justify-content-between align-items-start flex-wrap gap-2">
            <div>
              <span className="fw-bold">{mention.bibcode}</span>
              <span className="text-muted ms-2 small">paper</span>
            </div>
            <span className={`badge ${mention.validation_status === 'pending' ? 'bg-secondary' : 'bg-primary'}`}>
              {mention.validation_status}
            </span>
          </div>
        </div>

        <div className="card-body">
          {/* Instrument + period */}
          <div className="mb-3">
            <div className="row g-2">
              <div className="col-md-6">
                <label className="text-muted small text-uppercase fw-bold mb-1">Instrument</label>
                <div className="p-2 rounded border bg-light fw-semibold">{mention.instrument_name}</div>
              </div>
              <div className="col-md-6">
                <label className="text-muted small text-uppercase fw-bold mb-1">Data Collection Period</label>
                <div className="p-2 rounded border bg-light">{mention.period_name || 'N/A'}</div>
              </div>
            </div>
          </div>

          {/* Physical observable */}
          <div className="mb-3">
            <label className="text-muted small text-uppercase fw-bold mb-1">Physical Observable</label>
            <div className="p-3 rounded border" style={{ background: '#f8f9fa', fontStyle: 'italic' }}>
              {mention.physical_observable || <span className="text-muted">(none)</span>}
            </div>
          </div>

          {/* Supporting quote */}
          {mention.quote && (
            <div className="mb-3">
              <label className="text-muted small text-uppercase fw-bold mb-1">Supporting Quote</label>
              <blockquote className="blockquote p-3 border-start border-4 border-primary bg-light rounded mb-0">
                <p className="mb-0 fst-italic">"{mention.quote}"</p>
              </blockquote>
            </div>
          )}

          {/* Proposed phenomenon */}
          <div className="mb-4 p-3 rounded border border-primary border-opacity-25 bg-primary bg-opacity-10">
            <label className="text-muted small text-uppercase fw-bold mb-1">Proposed Phenomenon</label>
            <div className="d-flex align-items-center gap-3 flex-wrap mt-1">
              <span className="fs-5 fw-bold">{mention.phenomenon_name}</span>
              <code className="text-muted small">{mention.phenomenon_iri}</code>
            </div>
          </div>

          {/* Validation notes toggle */}
          {showNotes ? (
            <div className="mb-3">
              <label className="text-muted small text-uppercase fw-bold mb-1">Validation Notes</label>
              <textarea
                className="form-control"
                rows={3}
                placeholder="Optional: explain your decision…"
                value={validationNotes}
                onChange={(e) => setValidationNotes(e.target.value)}
              />
              <button
                className="btn btn-sm btn-link text-muted p-0 mt-1"
                onClick={() => { setShowNotes(false); setValidationNotes(''); }}
              >
                Cancel notes
              </button>
            </div>
          ) : (
            <button
              className="btn btn-sm btn-link text-muted p-0 mb-3"
              onClick={() => setShowNotes(true)}
            >
              + Add validation notes
            </button>
          )}

          {/* Action buttons */}
          <div className="d-flex gap-2 flex-wrap">
            <button
              className="btn btn-success"
              onClick={() => handleValidate('accepted')}
              disabled={isValidating}
            >
              {isValidating ? <span className="spinner-border spinner-border-sm me-1" /> : <i className="bi bi-check-lg me-1" />}
              Accept
            </button>
            <button
              className="btn btn-danger"
              onClick={() => handleValidate('rejected')}
              disabled={isValidating}
            >
              <i className="bi bi-x-lg me-1" />
              Reject
            </button>
            <button
              className="btn btn-warning text-white"
              onClick={() => handleValidate('needs_review')}
              disabled={isValidating}
            >
              <i className="bi bi-flag me-1" />
              Needs Review
            </button>
            <div className="ms-auto d-flex gap-2">
              <button
                className="btn btn-outline-secondary btn-sm"
                onClick={handlePrevious}
                disabled={currentIndex === 0 || isValidating}
              >
                <i className="bi bi-chevron-left" /> Prev
              </button>
              <button
                className="btn btn-outline-secondary btn-sm"
                onClick={handleSkip}
                disabled={currentIndex >= queue.length - 1 || isValidating}
              >
                Skip <i className="bi bi-chevron-right" />
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Minimap / queue summary */}
      <div className="mt-3 text-muted small text-center">
        Showing {currentIndex + 1} of {queue.length} pending mentions
        {totalCount > queue.length && (
          <span> ({totalCount} total across all pages)</span>
        )}
      </div>
    </div>
  );
};

export default PhenomenaValidationInterface;
