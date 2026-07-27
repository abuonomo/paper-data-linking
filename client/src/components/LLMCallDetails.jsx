import React, { useEffect, useCallback } from 'react';
import ReactMarkdown from 'react-markdown';

const SKEL = {
  display: 'block', borderRadius: '4px',
  background: 'linear-gradient(90deg, #e9ecef 25%, #f1f3f5 50%, #e9ecef 75%)',
  backgroundSize: '200% 100%',
  animation: 'lc-shimmer 1.5s ease-in-out infinite',
};

const LLMCallDetails = ({ call, show, loading, onHide }) => {
  const handleEscape = useCallback((e) => {
    if (e.key === 'Escape') onHide();
  }, [onHide]);

  useEffect(() => {
    if (show) {
      document.addEventListener('keydown', handleEscape);
      return () => document.removeEventListener('keydown', handleEscape);
    }
  }, [show, handleEscape]);

  if (!show) return null;

  const handleOverlayClick = (e) => {
    if (e.target === e.currentTarget) onHide();
  };

  const getTypeBadgeClass = (callType) => {
    if (callType === 'paper_analysis') return 'lc-type-badge--paper-analysis';
    if (callType === 'structure_analysis') return 'lc-type-badge--structure-analysis';
    if (callType.includes('normalization')) return 'lc-type-badge--normalization';
    if (callType.includes('instrument')) return 'lc-type-badge--instrument';
    return 'lc-type-badge--default';
  };

  const handleCopyJson = () => {
    const callData = {
      id: call.id,
      call_type: call.call_type,
      input: call.input_messages,
      output: call.output_content,
      tokens: {
        prompt: call.prompt_tokens,
        completion: call.completion_tokens,
        total: call.total_tokens
      },
      cost: call.estimated_cost_usd,
      duration_ms: call.duration_ms
    };
    navigator.clipboard.writeText(JSON.stringify(callData, null, 2));
  };

  const renderMessages = (messages) => {
    if (!messages || !Array.isArray(messages)) {
      return <span className="lc-secondary">No input messages</span>;
    }
    return messages.map((msg, i) => (
      <div key={i} className="lc-message-block">
        <div className="lc-message-header">
          <span className={`lc-message-role lc-message-role--${msg.role || 'user'}`}>
            {msg.role}
          </span>
          <span>Message {i + 1}</span>
        </div>
        <div className="lc-message-content">
          <ReactMarkdown>{msg.content || 'No content'}</ReactMarkdown>
        </div>
      </div>
    ));
  };

  const renderOutput = (output) => {
    if (!output) return <span className="lc-secondary">No output recorded</span>;
    return (
      <div className="lc-output-content">
        <ReactMarkdown>{output}</ReactMarkdown>
      </div>
    );
  };

  const renderMetadata = (metadata) => {
    if (!metadata || Object.keys(metadata).length === 0) {
      return <span className="lc-secondary">No metadata available</span>;
    }
    return Object.entries(metadata).map(([key, value]) => (
      <div key={key} className="lc-metadata-row">
        <span className="lc-metadata-key">{key}</span>
        <span className="lc-metadata-value">
          <code>{typeof value === 'object' ? JSON.stringify(value, null, 2) : String(value)}</code>
        </span>
      </div>
    ));
  };

  return (
    <>
      <style>{`@keyframes lc-shimmer { 0% { background-position: 200% 0; } 100% { background-position: -200% 0; } }`}</style>
      <div className="lc-modal-overlay" onClick={handleOverlayClick}>
        <div className="lc-modal">
          <div className="lc-modal-header">
            <div className="lc-modal-title">
              {loading || !call ? (
                <span style={{ ...SKEL, width: '120px', height: '1.1rem', display: 'inline-block' }} />
              ) : (
                <>
                  <span className={`lc-type-badge ${getTypeBadgeClass(call.call_type)}`}>
                    {call.call_type}
                  </span>
                  LLM Call Details
                </>
              )}
            </div>
            <button className="lc-modal-close" onClick={onHide}>&times;</button>
          </div>

          <div className="lc-modal-body">
            {loading || !call ? (
              <>
                <div className="lc-detail-section">
                  <div className="lc-detail-section-title">Basic Information</div>
                  <div className="lc-detail-grid">
                    {Array.from({ length: 8 }).map((_, i) => (
                      <div key={i}>
                        <div className="lc-detail-label"><span style={{ ...SKEL, width: '60%', height: '0.75rem' }} /></div>
                        <div className="lc-detail-value"><span style={{ ...SKEL, width: '80%', height: '0.9rem' }} /></div>
                      </div>
                    ))}
                  </div>
                </div>
                <div className="lc-detail-section">
                  <div className="lc-detail-section-title">Input Messages</div>
                  <span style={{ ...SKEL, width: '100%', height: '4rem' }} />
                </div>
                <div className="lc-detail-section">
                  <div className="lc-detail-section-title">Output Content</div>
                  <span style={{ ...SKEL, width: '100%', height: '6rem' }} />
                </div>
              </>
            ) : (
              <>
                <div className="lc-detail-section">
                  <div className="lc-detail-section-title">Basic Information</div>
                  <div className="lc-detail-grid">
                    <div>
                      <div className="lc-detail-label">Model</div>
                      <div className="lc-detail-value"><code>{call.model_name}</code></div>
                    </div>
                    <div>
                      <div className="lc-detail-label">Provider</div>
                      <div className="lc-detail-value">{call.provider}</div>
                    </div>
                    <div>
                      <div className="lc-detail-label">Duration</div>
                      <div className="lc-detail-value">{call.duration_ms}ms</div>
                    </div>
                    <div>
                      <div className="lc-detail-label">Created</div>
                      <div className="lc-detail-value">{new Date(call.created_at).toLocaleString('en-US', { timeZone: 'UTC', timeZoneName: 'short' })}</div>
                    </div>
                    <div>
                      <div className="lc-detail-label">Prompt Tokens</div>
                      <div className="lc-detail-value">{(call.prompt_tokens || 0).toLocaleString()}</div>
                    </div>
                    <div>
                      <div className="lc-detail-label">Completion Tokens</div>
                      <div className="lc-detail-value">{(call.completion_tokens || 0).toLocaleString()}</div>
                    </div>
                    <div>
                      <div className="lc-detail-label">Total Tokens</div>
                      <div className="lc-detail-value" style={{ fontWeight: 600 }}>
                        {(call.total_tokens || 0).toLocaleString()}
                      </div>
                    </div>
                    <div>
                      <div className="lc-detail-label">Estimated Cost</div>
                      <div className="lc-detail-value" style={{ fontWeight: 600 }}>
                        ${parseFloat(call.estimated_cost_usd || 0).toFixed(6)}
                      </div>
                    </div>
                  </div>
                </div>

                <div className="lc-detail-section">
                  <div className="lc-detail-section-title">Input Messages</div>
                  {renderMessages(call.input_messages)}
                </div>

                <div className="lc-detail-section">
                  <div className="lc-detail-section-title">Output Content</div>
                  {renderOutput(call.output_content)}
                </div>

                <div className="lc-detail-section">
                  <div className="lc-detail-section-title">Metadata</div>
                  {renderMetadata(call.metadata)}
                </div>
              </>
            )}
          </div>

          <div className="lc-modal-footer">
            <button className="lc-btn" onClick={onHide}>Close</button>
            {!loading && call && (
              <button className="lc-btn lc-btn--primary" onClick={handleCopyJson}>Copy JSON</button>
            )}
          </div>
        </div>
      </div>
    </>
  );
};

export default LLMCallDetails;
