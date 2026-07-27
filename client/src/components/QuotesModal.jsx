import React from 'react';

const categoryStyles = {
  instrument:  { border: '#7e8fa6', bg: '#f0f3f8', color: '#5a6b80', label: 'Instrument' },
  time_range:  { border: '#c49462', bg: '#f8f2ea', color: '#7d6340', label: 'Time Range' },
  wavelength:  { border: '#8da67a', bg: '#f1f6ee', color: '#5e7350', label: 'Wavelength' },
  observable:  { border: '#7a9db0', bg: '#edf3f7', color: '#4e7188', label: 'Observable' },
  general:     { border: '#b0b0b0', bg: '#f4f4f4', color: '#777',    label: 'General' },
};

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

export default function QuotesModal({ usage, onClose, onOpenEvidenceView = null, openEvidenceLabel = 'Open Full Evidence View' }) {
  if (!usage || !usage.supporting_quotes?.length) return null;
  const [hoveredNameLabelKey, setHoveredNameLabelKey] = React.useState(null);

  const handleOverlayClick = (e) => {
    if (e.target === e.currentTarget) {
      onClose();
    }
  };

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
        width: '700px',
        maxHeight: '80vh',
        overflow: 'visible',
        border: '1px solid #e2e8f0',
        display: 'flex',
        flexDirection: 'column'
      }}>
        {/* Header */}
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
              Supporting Quotes
            </h2>
            <span style={{ fontSize: 'var(--font-sm)', color: '#888' }}>
              {usage.supporting_quotes.length} quote{usage.supporting_quotes.length !== 1 ? 's' : ''}
            </span>
            {onOpenEvidenceView && (
              <button
                type="button"
                onClick={() => onOpenEvidenceView(usage)}
                style={{
                  marginLeft: '0.35rem',
                  backgroundColor: '#eef6ff',
                  border: '1px solid #bfdbfe',
                  color: '#1d4ed8',
                  borderRadius: '4px',
                  padding: '0.2rem 0.45rem',
                  fontSize: 'var(--font-xs)',
                  fontWeight: 600,
                  cursor: 'pointer',
                }}
                title="Open full evidence view with PDF navigation"
              >
                {openEvidenceLabel}
              </button>
            )}
          </div>
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
                tooltipKey="quotes-instrument"
                hoveredKey={hoveredNameLabelKey}
                setHoveredKey={setHoveredNameLabelKey}
              />
            </strong>
            <span style={{ fontWeight: 400 }}>on</span>
            <strong>
              <HoverNameLabel
                displayText={missionDisplay}
                fullText={missionFull}
                tooltipKey="quotes-mission"
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

        {/* Quotes list */}
        <div style={{ flex: 1, overflow: 'auto', padding: '0.75rem 1rem' }}>
          {usage.supporting_quotes.map((quote, idx) => {
            const cat = categoryStyles[quote.support_category] || categoryStyles.general;
            return (
              <div key={quote.id} style={{
                marginBottom: idx < usage.supporting_quotes.length - 1 ? '0.75rem' : 0,
                padding: '0.6rem 0.75rem',
                borderLeft: `3px solid ${cat.border}`,
                backgroundColor: cat.bg,
                borderRadius: '0 4px 4px 0',
              }}>
                <div style={{
                  fontStyle: 'italic',
                  color: '#444',
                  lineHeight: '1.5',
                  fontSize: 'var(--font-sm)',
                  marginBottom: '0.35rem',
                }}>
                  &ldquo;{quote.quote}&rdquo;
                </div>
                <div style={{
                  fontSize: 'var(--font-xs)',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '0.5rem',
                  flexWrap: 'wrap',
                }}>
                  <span style={{
                    border: `1px solid ${cat.border}`,
                    color: cat.color,
                    padding: '0.05rem 0.35rem',
                    borderRadius: '3px',
                    fontWeight: 500,
                    fontSize: 'var(--font-xs)',
                  }}>
                    {cat.label}
                  </span>
                  {quote.page_number && (
                    <span style={{ color: '#888' }}>p. {quote.page_number}</span>
                  )}
                  {quote.parameter && (
                    <span style={{ color: '#888' }}>&middot; {quote.parameter}</span>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
