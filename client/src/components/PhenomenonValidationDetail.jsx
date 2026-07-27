// src/components/PhenomenonValidationDetail.jsx
import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { fetchPaperDetails, fetchPaperPhenomena, fetchPaperAnalysis, validatePhenomenonMention } from '../services/apiServices';
import PDFDocument from './pdfViewer/PDFDocument';
import { ValidationProvider } from '../context/ValidationContext';
import { usePaperPDF } from '../hooks/usePaperPDF';
import { usePDF } from '../hooks/usePDF';
import { usePDFSearch } from '../hooks/usePDFSearch';
import PDFSearch from './pdfViewer/PDFSearch';
import { mapQuotesToAnnotations } from '../features/evidence/mapQuotesToAnnotations';
import { toast } from 'react-toastify';
import './pdfViewer/PDFViewer.css';
import './StreamlinedValidationInterface.css';

const formatTimeRange = (tr) => {
  if (!tr) return null;
  const fmt = (iso) => iso ? iso.slice(0, 10) : null;
  const start = fmt(tr.start);
  const end = fmt(tr.end);
  if (start && end) return `${start} – ${end}`;
  return start || end || null;
};

const STATUS_LABEL = {
  accepted: 'Accept',
  rejected: 'Reject',
  needs_review: 'Needs Review',
};

const PhenomenonValidationDetail = () => {
  const { paperId, mentionId } = useParams();
  const navigate = useNavigate();

  const [paper, setPaper] = useState(null);
  const [mentions, setMentions] = useState([]);
  const [paperAnalysis, setPaperAnalysis] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isValidating, setIsValidating] = useState(false);
  const [validationNotes, setValidationNotes] = useState('');
  const [showNotes, setShowNotes] = useState(false);
  const [showContextModal, setShowContextModal] = useState(false);
  const [validationAnimation, setValidationAnimation] = useState(null);
  const [localStatuses, setLocalStatuses] = useState({});
  const [scrollTrigger, setScrollTrigger] = useState(0);
  const [currentQuoteIndex, setCurrentQuoteIndex] = useState(0);

  const currentIndex = mentions.findIndex(m => m.id === mentionId);
  const mention = currentIndex >= 0 ? mentions[currentIndex] : null;
  const effectiveStatus = localStatuses[mentionId] ?? mention?.validation_status ?? 'pending';

  // Build annotations from all supporting_quotes
  const { annotations, quoteToAnnotationMap } = useMemo(() => {
    const sqs = mention?.supporting_quotes?.length
      ? mention.supporting_quotes
      : mention?.supporting_quote
        ? [mention.supporting_quote]
        : [];
    if (!sqs.length) return { annotations: [], quoteToAnnotationMap: new Map() };
    return mapQuotesToAnnotations(sqs, mention.instrument_name);
  }, [mention?.supporting_quotes, mention?.supporting_quote, mention?.instrument_name]);

  const focusedQuoteIds = useMemo(() => {
    return annotations
      .filter(a => a.originalQuoteIndex === currentQuoteIndex)
      .map(a => a.id);
  }, [annotations, currentQuoteIndex]);

  const targetPage = useMemo(() => {
    const annotationIndex = quoteToAnnotationMap.get(currentQuoteIndex);
    return annotationIndex !== undefined ? annotations[annotationIndex]?.pageNumber ?? null : null;
  }, [annotations, quoteToAnnotationMap, currentQuoteIndex]);

  const { pdfUrl } = usePaperPDF(paper?.bibcode);
  const { pdf, numPages } = usePDF(pdfUrl);

  const {
    searchQuery, setSearchQuery, searchResults, currentMatchIndex,
    isSearching, isSearchVisible, showSearch, clearSearch,
    goToNextMatch, goToPreviousMatch, getMatchesForPage, totalMatches,
  } = usePDFSearch(pdf, numPages);

  const handleQuoteClick = (quoteIndex) => {
    setCurrentQuoteIndex(quoteIndex);
    setScrollTrigger(prev => prev + 1);
  };

  // Reset quote selection and search when switching mentions
  useEffect(() => {
    setCurrentQuoteIndex(0);
    clearSearch();
  }, [mentionId]);

  // Scroll to the first annotation when the mention changes and has coordinates
  useEffect(() => {
    if (targetPage != null) setScrollTrigger(prev => prev + 1);
  }, [mentionId, targetPage]);

  const load = useCallback(async () => {
    try {
      setIsLoading(true);
      const [paperData, phenomenaData] = await Promise.all([
        fetchPaperDetails(paperId),
        fetchPaperPhenomena(paperId),
      ]);
      setPaper(paperData);
      const mentionList = phenomenaData.mentions || [];
      setMentions(mentionList);
    } catch (err) {
      console.error(err);
      toast.error('Failed to load phenomenon data');
    } finally {
      setIsLoading(false);
    }
  }, [paperId]);

  useEffect(() => { load(); }, [load]);

  // Analysis metadata is non-critical and must not block the page. Request the
  // lightweight phenomena representation rather than full contexts/LLM calls.
  useEffect(() => {
    let cancelled = false;
    const loadAnalysis = async () => {
      try {
        let analyses = await fetchPaperAnalysis(paperId, {
          configuration_name: 'standard',
          view: 'phenomena',
        });
        if (!analyses.length) {
          analyses = await fetchPaperAnalysis(paperId, { view: 'phenomena' });
        }
        if (!cancelled && analyses.length) setPaperAnalysis(analyses[0]);
      } catch { /* non-critical */ }
    };
    loadAnalysis();
    return () => { cancelled = true; };
  }, [paperId]);

  const navigate_to_mention = (id) => navigate(`/papers/${paperId}/validate/phenomena/${id}`);

  const goToPrev = () => {
    if (currentIndex > 0) navigate_to_mention(mentions[currentIndex - 1].id);
  };
  const goToNext = () => {
    if (currentIndex < mentions.length - 1) navigate_to_mention(mentions[currentIndex + 1].id);
    else navigate(`/phenomena-validation/${paperId}`);
  };

  const handleValidate = async (status) => {
    if (!mention || isValidating) return;
    setIsValidating(true);
    try {
      await validatePhenomenonMention(mention.id, status, validationNotes);
      setLocalStatuses(prev => ({ ...prev, [mention.id]: status }));
      setMentions(prev => prev.map(m => m.id === mention.id ? { ...m, validation_status: status } : m));
      setValidationAnimation(status);
      setValidationNotes('');
      setShowNotes(false);
      toast.success('Validation submitted!');
      setTimeout(() => {
        setValidationAnimation(null);
        goToNext();
      }, 600);
    } catch (err) {
      toast.error('Failed to submit validation.');
      console.error(err);
    } finally {
      setIsValidating(false);
    }
  };

  if (isLoading) {
    return (
      <div className="streamlined-validation">
        <div className="validation-main">
          <div className="claim-sidebar">
            <div className="paper-header">
              <div className="paper-info">
                <div className="skeleton-box skeleton-w-60" style={{ height: '1rem' }} />
              </div>
            </div>
          </div>
        </div>
      </div>
    );
  }

  if (!mention) {
    return (
      <div className="vq-container">
        <div className="alert alert-warning">Phenomenon mention not found.</div>
      </div>
    );
  }

  const myVote = localStatuses[mentionId] ?? mention.my_validation_status ?? null;

  return (
    <div className="streamlined-validation">
      <div className="validation-main">
        {/* Left: Phenomenon claim sidebar */}
        <div className="claim-sidebar">
          {/* Header with back link + nav */}
          <div className="paper-header">
            <div className="paper-info">
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <h2 className="paper-title" style={{ margin: 0 }}>
                  <button
                    className="btn btn-link p-0"
                    onClick={() => navigate(`/phenomena-validation/${paperId}`)}
                    style={{ color: '#0969da', fontSize: 'inherit', fontWeight: 'inherit', textDecoration: 'underline' }}
                  >
                    {paper?.bibcode || '…'}
                  </button>
                  <span style={{
                    marginLeft: '0.5rem', padding: '0.1rem 0.4rem', borderRadius: '0.4rem',
                    background: '#fff3cd', color: '#664d03', fontSize: '0.78rem', fontWeight: 600,
                  }}>
                    Phenomenon
                  </span>
                </h2>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                  {paperAnalysis && (
                    <>
                      <button className="vo-config-action" onClick={() => setShowContextModal(true)}>Context</button>
                      <button className="vo-config-action" onClick={() => navigate(`/analyses/${paperAnalysis.id}`)}>LLM Calls</button>
                    </>
                  )}
                  <div className="claim-nav-inline">
                    <button onClick={goToPrev} disabled={currentIndex <= 0} className="claim-nav-arrow">‹</button>
                    <span className="claim-nav-counter">{currentIndex + 1}/{mentions.length}</span>
                    <button onClick={goToNext} disabled={currentIndex >= mentions.length - 1} className="claim-nav-arrow">›</button>
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* Progress bar — one segment per mention */}
          <div className="navigation-section">
            <div className="claim-progress-bar">
              {mentions.map((m, idx) => {
                const s = localStatuses[m.id] ?? m.validation_status ?? 'pending';
                const segClass = s === 'accepted' ? 'status-approved'
                  : s === 'rejected' ? 'status-rejected'
                  : s === 'needs_review' ? 'status-needs_review'
                  : 'status-pending';
                return (
                  <div
                    key={m.id}
                    className={`claim-progress-segment ${segClass} ${idx === currentIndex ? 'is-current' : ''}`}
                    onClick={() => navigate_to_mention(m.id)}
                    title={`${m.phenomenon_name} — ${s}`}
                    style={{ cursor: 'pointer' }}
                  />
                );
              })}
            </div>
          </div>

          {/* Claim card */}
          <div className={`claim-card ${
            myVote ? `status-${myVote === 'accepted' ? 'approved' : myVote === 'rejected' ? 'rejected' : 'needs_review'}`
            : effectiveStatus !== 'pending' ? 'validated-by-others' : ''
          } ${validationAnimation ? `flash-${validationAnimation === 'accepted' ? 'approved' : validationAnimation}` : ''}`}>
            <div className="claim-content">
              <div className="claim-details">
                {/* Phenomenon name */}
                <div className="detail-item compact-mission">
                  <span className="instrument-mission-display">
                    <span className="instrument-name">{mention.phenomenon_name}</span>
                    {mention.phenomenon_iri && (
                      <span className="on-connector"> · </span>
                    )}
                    {mention.phenomenon_iri && (
                      <code style={{ fontSize: '0.75rem', color: '#57606a' }}>{mention.phenomenon_iri}</code>
                    )}
                  </span>
                  {effectiveStatus && effectiveStatus !== 'pending' && (
                    <span className={`validation-status-badge status-${effectiveStatus}`}>
                      {effectiveStatus === 'accepted' ? 'Accepted' : effectiveStatus === 'rejected' ? 'Rejected' : 'Review'}
                    </span>
                  )}
                </div>

                {/* Instrument + grounded time range */}
                <div className="detail-item" style={{ fontSize: '0.85rem', color: '#57606a', marginTop: '0.35rem', display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: '0.3rem' }}>
                  <strong
                    title={mention.grounded_instrument_name ? mention.instrument_name : undefined}
                    style={{ fontFamily: mention.grounded_instrument_name ? 'ui-monospace, monospace' : undefined }}
                  >
                    {mention.grounded_instrument_name
                      ? mention.grounded_instrument_name
                      : (mention.instrument_name?.length > 70
                          ? mention.instrument_name.slice(0, 70) + '…'
                          : mention.instrument_name)
                    }
                  </strong>
                  {!mention.grounded_instrument_name && (
                    <span className="vq-ungrounded-badge">Ungrounded</span>
                  )}
                  {mention.grounded_time_range ? (
                    <span>· {formatTimeRange(mention.grounded_time_range)}</span>
                  ) : mention.period_name ? (
                    <span>· {mention.period_name}</span>
                  ) : null}
                </div>
              </div>

              {/* Supporting quotes — all physobs quotes collected across periods */}
              {(() => {
                const allQuotes = mention.supporting_quotes?.length
                  ? mention.supporting_quotes
                  : mention.supporting_quote
                    ? [mention.supporting_quote]
                    : [];
                if (!allQuotes.length && !mention.quote) return null;
                const displayQuotes = allQuotes.length
                  ? allQuotes
                  : [{ quote: mention.quote, page_number: mention.supporting_quote?.page_number }];
                return (
                  <div className="supporting-quotes" style={{ marginTop: '0.75rem' }}>
                    <h4>Supporting Evidence</h4>
                    <div className="quotes-list">
                      {displayQuotes.map((sq, idx) => (
                        <div
                          key={sq.id ?? idx}
                          className={`quote-item quote-item--physobs ${idx === currentQuoteIndex ? 'active' : ''}`}
                          onClick={() => handleQuoteClick(idx)}
                          title="Click to scroll to this quote in the PDF"
                          style={{ cursor: 'pointer' }}
                        >
                          <div className="quote-meta">
                            <span className="category-badge category-physobs">physical obs</span>
                            {sq.page_number > 0 && (
                              <span className="page-number">Page {sq.page_number}</span>
                            )}
                          </div>
                          <div className="quote-text">"{sq.quote}"</div>
                        </div>
                      ))}
                    </div>
                  </div>
                );
              })()}
            </div>
          </div>

          {/* Validation controls */}
          <div className="validation-section">
            {myVote ? (
              <div className="my-vote-block">
                <div className="my-vote-indicator">
                  Your vote:{' '}
                  <span className={`my-vote-status ${myVote}`}>
                    {myVote === 'accepted' ? 'Accepted' : myVote === 'rejected' ? 'Rejected' : 'Needs Review'}
                  </span>
                </div>
              </div>
            ) : (
              <>
                <div className="validation-notes">
                  {showNotes ? (
                    <textarea
                      value={validationNotes}
                      onChange={e => setValidationNotes(e.target.value)}
                      placeholder="Add a note about this decision..."
                      rows={2}
                      autoFocus
                    />
                  ) : (
                    <button className="add-note-btn" onClick={() => setShowNotes(true)}>+ Add note</button>
                  )}
                </div>
                <div className="validation-controls">
                  <button className="validation-btn approve" onClick={() => handleValidate('accepted')} disabled={isValidating}>
                    Accept
                  </button>
                  <button className="validation-btn reject" onClick={() => handleValidate('rejected')} disabled={isValidating}>
                    Reject
                  </button>
                  <button className="validation-btn review" onClick={() => handleValidate('needs_review')} disabled={isValidating}>
                    Review
                  </button>
                </div>
              </>
            )}
          </div>
        </div>

        {/* Right: PDF viewer */}
        <div className="pdf-section">
          {pdf ? (
            <ValidationProvider bibcode={paper?.bibcode}>
              <div className="pdf-content">
                {isSearchVisible && (
                  <PDFSearch
                    searchQuery={searchQuery}
                    setSearchQuery={setSearchQuery}
                    totalMatches={totalMatches}
                    currentMatchIndex={currentMatchIndex}
                    isSearching={isSearching}
                    onNextMatch={goToNextMatch}
                    onPreviousMatch={goToPreviousMatch}
                    onClose={clearSearch}
                  />
                )}
                <PDFDocument
                  pdf={pdf}
                  numPages={numPages}
                  annotations={annotations}
                  focusedQuoteIds={focusedQuoteIds}
                  targetPage={targetPage}
                  scrollTrigger={scrollTrigger}
                  searchMatches={searchResults}
                  currentMatchIndex={currentMatchIndex}
                  getMatchesForPage={getMatchesForPage}
                />
              </div>
            </ValidationProvider>
          ) : (
            <div className="pdf-loading">
              {pdfUrl ? 'Loading PDF…' : 'No PDF available'}
            </div>
          )}
        </div>
      </div>

      {/* Context modal */}
      {showContextModal && paperAnalysis && (
        <div className="modal-overlay" onClick={(e) => e.target === e.currentTarget && setShowContextModal(false)}>
          <div className="context-modal">
            <div className="context-modal-header">
              <h2>Context</h2>
              {paperAnalysis.configuration_name && (
                <span className="config-badge">
                  {paperAnalysis.configuration_name.charAt(0).toUpperCase() + paperAnalysis.configuration_name.slice(1)}
                </span>
              )}
              <button className="modal-close" onClick={() => setShowContextModal(false)}>&times;</button>
            </div>
            <div className="context-modal-body">
              {paperAnalysis.instruments_details && (
                <div className="context-modal-section">
                  <h4>Instrument Details from Paper Analysis</h4>
                  <div className="markdown-content"
                    dangerouslySetInnerHTML={{
                      __html: paperAnalysis.instruments_details
                        .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
                        .replace(/\*(.*?)\*/g, '<em>$1</em>')
                        .replace(/^### (.+)$/gm, '<h3>$1</h3>')
                        .replace(/^## (.+)$/gm, '<h2>$1</h2>')
                        .replace(/^# (.+)$/gm, '<h1>$1</h1>')
                        .replace(/\n/g, '<br>')
                    }}
                  />
                </div>
              )}
              {!paperAnalysis.instruments_details && (
                <p style={{ color: '#656d76', textAlign: 'center', padding: '1.5rem' }}>No paper analysis data available.</p>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default PhenomenonValidationDetail;
