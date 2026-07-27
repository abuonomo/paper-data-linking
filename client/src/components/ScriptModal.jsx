import React from 'react';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { materialLight } from 'react-syntax-highlighter/dist/esm/styles/prism';

function formatDateTime(dt) {
  if (!dt) return 'Unknown';
  try {
    return new Date(dt).toLocaleString('en-US', {
      year: 'numeric',
      month: 'short',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
      timeZone: 'UTC',
      timeZoneName: 'short',
    });
  } catch {
    return 'Unknown';
  }
}

function HoverNameLabel({ displayText, fullText, tooltipKey, hoveredKey, setHoveredKey }) {
  return (
    <span style={{ position: 'relative', display: 'inline-flex' }}>
      <span
        tabIndex={0}
        onMouseEnter={() => setHoveredKey(tooltipKey)}
        onMouseLeave={() => setHoveredKey(null)}
        onFocus={() => setHoveredKey(tooltipKey)}
        onBlur={() => setHoveredKey(null)}
        aria-label={`Show full name for ${displayText}`}
        style={{
          cursor: 'help',
          textDecorationLine: 'underline',
          textDecorationStyle: 'dotted',
          textDecorationColor: '#9ca3af',
          textDecorationThickness: '1px',
          textUnderlineOffset: '2px',
        }}
      >
        {displayText}
      </span>
      {hoveredKey === tooltipKey && (
        <span
          role="tooltip"
          style={{
            position: 'absolute',
            bottom: 'calc(100% + 6px)',
            left: '50%',
            transform: 'translateX(-50%)',
            whiteSpace: 'nowrap',
            backgroundColor: '#111827',
            color: '#f9fafb',
            fontSize: '11px',
            lineHeight: 1.2,
            padding: '0.25rem 0.4rem',
            borderRadius: '4px',
            boxShadow: '0 2px 6px rgba(0,0,0,0.25)',
            zIndex: 20,
            pointerEvents: 'none',
          }}
        >
          {fullText || displayText}
        </span>
      )}
    </span>
  );
}

export default function ScriptModal({ usage, onClose }) {
  if (!usage) return null;

  const [copySuccess, setCopySuccess] = React.useState(false);
  const [hoveredNameLabelKey, setHoveredNameLabelKey] = React.useState(null);

  const handleOverlayClick = (e) => {
    if (e.target === e.currentTarget) {
      onClose();
    }
  };

  const handleCopyScript = () => {
    if (usage.python_snippet) {
      const cleanScript = usage.python_snippet.replace(/^```python\s+|\s+```$/g, '');
      navigator.clipboard.writeText(cleanScript);
      setCopySuccess(true);
      setTimeout(() => setCopySuccess(false), 2000);
    }
  };

  const getStatusColor = (analysis) => {
    if (!analysis) return '#999';
    if (analysis.is_valid_syntax && analysis.execution_successful) return '#16a085';
    if (analysis.is_valid_syntax && !analysis.execution_successful) return '#e74c3c';
    return '#f39c12';
  };

  const getStatusText = (analysis) => {
    if (!analysis) return 'No analysis available';
    if (analysis.is_valid_syntax && analysis.execution_successful) return 'Valid & Executable';
    if (analysis.is_valid_syntax && !analysis.execution_successful) return 'Valid Syntax, Execution Failed';
    return 'Invalid Syntax';
  };

  const analysis = usage.script_analysis;
  const missionDisplay = usage.observatory?.display_name || 'Unknown';
  const missionFull = usage.observatory?.name || missionDisplay;
  const instrumentDisplay = usage.instrument?.display_name || 'Unknown';
  const instrumentFull = usage.instrument?.full_name || instrumentDisplay;
  const startDisplay = formatDateTime(usage.start_time);
  const endDisplay = formatDateTime(usage.end_time);

  return (
    <div
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        backgroundColor: 'rgba(0, 0, 0, 0.5)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 1000,
        padding: '2rem'
      }}
      onClick={handleOverlayClick}
    >
      <div style={{
        backgroundColor: 'white',
        borderRadius: '8px',
        width: 'min(900px, calc(100vw - 2rem))',
        maxWidth: '100%',
        maxHeight: '80vh',
        overflow: 'visible',
        border: '1px solid #e2e8f0',
        display: 'flex',
        flexDirection: 'column'
      }}>
        {/* Header — compact single row */}
        <div style={{
          padding: '0.75rem 1rem',
          borderBottom: '1px solid #e2e8f0',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
        }}>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: '0.75rem', flexWrap: 'wrap' }}>
            <h2 style={{
              margin: 0,
              fontSize: 'var(--font-lg)',
              fontWeight: '600',
              color: '#2c3e50'
            }}>
              Python Script
            </h2>
            <span style={{ fontSize: 'var(--font-sm)', color: '#888' }}>
              Data Download Script
            </span>
            {analysis && (
              <span style={{
                fontSize: 'var(--font-xs)',
                color: getStatusColor(analysis),
                fontWeight: 500,
                display: 'inline-flex',
                alignItems: 'center',
                gap: '0.3rem',
              }}>
                <span style={{
                  width: '6px',
                  height: '6px',
                  borderRadius: '50%',
                  backgroundColor: getStatusColor(analysis),
                  display: 'inline-block',
                  flexShrink: 0,
                }} />
                {getStatusText(analysis)}
              </span>
            )}
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexShrink: 0 }}>
            {usage.python_snippet && (
              <button
                onClick={handleCopyScript}
                style={{
                  padding: '0.3rem 0.6rem',
                  backgroundColor: copySuccess ? '#16a085' : '#3182ce',
                  color: 'white',
                  border: 'none',
                  borderRadius: '4px',
                  fontSize: 'var(--font-xs)',
                  cursor: 'pointer',
                  transition: 'background-color 0.2s ease',
                }}
                title={copySuccess ? 'Copied!' : 'Copy code'}
              >
                {copySuccess ? 'Copied!' : 'Copy'}
              </button>
            )}
            <button
              onClick={onClose}
              style={{
                background: 'none',
                border: 'none',
                fontSize: 'var(--font-2xl)',
                color: '#999',
                cursor: 'pointer',
                padding: '0 0.25rem',
                lineHeight: 1,
              }}
            >
              &times;
            </button>
          </div>
        </div>

        {/* Context panel */}
        <div style={{
          padding: '0.6rem 1rem 0.7rem 1rem',
          borderBottom: '1px solid #e2e8f0',
          backgroundColor: '#f8fafc',
          color: '#4b5563',
          fontSize: 'var(--font-sm)',
          display: 'grid',
          rowGap: '0.25rem',
        }}>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: '0.35rem', flexWrap: 'wrap', color: '#2c3e50' }}>
            <strong>
              <HoverNameLabel
                displayText={instrumentDisplay}
                fullText={instrumentFull}
                tooltipKey="script-instrument"
                hoveredKey={hoveredNameLabelKey}
                setHoveredKey={setHoveredNameLabelKey}
              />
            </strong>
            <span style={{ fontWeight: 400 }}>on</span>
            <strong>
              <HoverNameLabel
                displayText={missionDisplay}
                fullText={missionFull}
                tooltipKey="script-mission"
                hoveredKey={hoveredNameLabelKey}
                setHoveredKey={setHoveredNameLabelKey}
              />
            </strong>
          </div>
          <div style={{
            display: 'flex',
            alignItems: 'center',
            gap: '0.35rem',
            color: '#374151',
            marginLeft: '0.65rem',
            flexWrap: 'wrap',
          }}>
            <span style={{ color: '#6b7280' }}>from</span>
            <strong>{startDisplay}</strong>
            <span style={{ color: '#6b7280' }}>to</span>
            <strong>{endDisplay}</strong>
          </div>
        </div>

        {/* Script — primary content, fills available space */}
        <div style={{ flex: 1, overflowY: 'auto', overflowX: 'hidden' }}>
          {usage.python_snippet ? (
            <SyntaxHighlighter
              language="python"
              style={materialLight}
              wrapLongLines={true}
              codeTagProps={{
                style: {
                  whiteSpace: 'pre-wrap',
                  overflowWrap: 'anywhere',
                },
              }}
              customStyle={{
                margin: 0,
                padding: '0.75rem 1rem',
                fontSize: 'var(--font-sm)',
                lineHeight: '1.5',
                backgroundColor: '#f8f9fa',
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-word',
                overflowX: 'hidden',
              }}
              showLineNumbers={true}
            >
              {usage.python_snippet.replace(/^```python\s+|\s+```$/g, '')}
            </SyntaxHighlighter>
          ) : (
            <div style={{
              padding: '2rem',
              color: '#666',
              fontStyle: 'italic',
              textAlign: 'center',
            }}>
              No Python script available for this observation.
            </div>
          )}
        </div>

        {/* Status footer — only shown when there are details worth showing */}
        {analysis && (analysis.total_results_found !== null || analysis.syntax_error || analysis.execution_error) && (
          <div style={{
            padding: '0.5rem 1rem',
            borderTop: '1px solid #e2e8f0',
            backgroundColor: '#f8f9fa',
            fontSize: 'var(--font-xs)',
            color: '#666',
            display: 'flex',
            gap: '1rem',
            flexWrap: 'wrap',
          }}>
            {analysis.total_results_found !== null && (
              <span>Expected results: {analysis.total_results_found} records</span>
            )}
            {analysis.syntax_error && (
              <span style={{ color: '#e74c3c', fontFamily: 'monospace' }}>
                Syntax Error: {analysis.syntax_error}
              </span>
            )}
            {analysis.execution_error && (
              <span style={{ color: '#e74c3c', fontFamily: 'monospace' }}>
                Execution Error: {analysis.execution_error}
              </span>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
