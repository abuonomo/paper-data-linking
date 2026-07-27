import React, { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { fetchPublicValidatedUsages } from '../services/apiPublic';
import ScriptModal from '../components/ScriptModal';
import QuotesModal from '../components/QuotesModal';
import SimilarPapers from '../components/SimilarPapers';
import { useAuth } from '../hooks/useAuth';

function formatDateTime(dt) {
  if (!dt) return { year: '', month: '', day: '', time: '' };
  try {
    const date = new Date(dt);
    return {
      year: date.getUTCFullYear().toString(),
      month: date.toLocaleDateString('en-US', { month: 'short', timeZone: 'UTC' }),
      day: date.getUTCDate().toString().padStart(2, '0'),
      time: date.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'UTC' })
    };
  } catch {
    return { year: '', month: '', day: '', time: '' };
  }
}

function formatSummaryDate(dt) {
  if (!dt) return '';
  try {
    return new Date(dt).toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      timeZone: 'UTC',
    });
  } catch {
    return '';
  }
}

function ObservationActionLink({ icon, label, onClick }) {
  const [isHovered, setIsHovered] = useState(false);
  const [isFocused, setIsFocused] = useState(false);
  const isActive = isHovered || isFocused;

  return (
    <button
      type="button"
      onClick={onClick}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
      onFocus={() => setIsFocused(true)}
      onBlur={() => setIsFocused(false)}
      style={{
        fontSize: 'var(--font-xs)',
        fontWeight: '600',
        color: '#1f6fb2',
        background: 'none',
        border: 'none',
        borderRadius: '4px',
        padding: '0.05rem 0.1rem',
        cursor: 'pointer',
        lineHeight: 1.25,
        textDecoration: isActive ? 'underline' : 'none',
        textUnderlineOffset: '2px',
        boxShadow: isFocused ? '0 0 0 2px rgba(49, 130, 206, 0.35)' : 'none',
      }}
    >
      <span aria-hidden="true" style={{ marginRight: '0.25rem', color: '#4b5563' }}>
        {icon}
      </span>
      <span>{label}</span>
    </button>
  );
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

export default function PublicPaperUsages() {
  const { bibcode } = useParams();
  const navigate = useNavigate();
  const { isAuthenticated } = useAuth();
  const [searchParams, setSearchParams] = useSearchParams();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [selectedUsage, setSelectedUsage] = useState(null);
  const [quotesUsage, setQuotesUsage] = useState(null);
  const [showFullAbstract, setShowFullAbstract] = useState(false);
  const [copiedBibcode, setCopiedBibcode] = useState(false);
  const [hoveredValidationUsageId, setHoveredValidationUsageId] = useState(null);
  const [hoveredNameLabelKey, setHoveredNameLabelKey] = useState(null);
  const includeUnvalidated = searchParams.get('include_unvalidated') === 'true';
  
  const handleToggleUnvalidated = (newValue) => {
    if (newValue) {
      searchParams.set('include_unvalidated', 'true');
    } else {
      searchParams.delete('include_unvalidated');
    }
    setSearchParams(searchParams);
  };

  useEffect(() => {
    let mounted = true;
    setLoading(true);
    setError(null);
    
    fetchPublicValidatedUsages(bibcode, includeUnvalidated)
      .then((json) => { 
        if (mounted) setData(json); 
      })
      .catch((err) => { 
        if (mounted) setError(err.message || String(err)); 
      })
      .finally(() => { 
        if (mounted) setLoading(false); 
      });
    
    return () => { mounted = false; };
  }, [bibcode, includeUnvalidated]);


  const usages = data?.usages || [];
  const paper = data?.paper;
  const missionMentions = data?.mission_mentions || [];

  const overview = useMemo(() => {
    const dsMap = new Map();
    for (const u of usages) {
      const ds = u.datasource || {};
      const dsKey = ds.slug || 'unknown';
      if (!dsMap.has(dsKey)) {
        dsMap.set(dsKey, { datasource: ds, missions: new Map() });
      }
      const dsEntry = dsMap.get(dsKey);
      const obs = u.observatory || {};
      const obsKey = obs.short_name || 'Unknown';
      if (!dsEntry.missions.has(obsKey)) {
        dsEntry.missions.set(obsKey, { observatory: obs, instruments: new Set() });
      }
      const mEntry = dsEntry.missions.get(obsKey);
      const instDisplay = u.instrument?.display_name || u.instrument?.short_name || 'Unknown';
      mEntry.instruments.add(instDisplay);
    }

    // Convert to arrays and sort
    const result = Array.from(dsMap.values()).map(dsEntry => ({
      datasource: dsEntry.datasource,
      missions: Array.from(dsEntry.missions.values()).map(m => ({
        observatory: m.observatory,
        instruments: Array.from(m.instruments).sort((a, b) => a.localeCompare(b)),
      })).sort((a, b) => (a.observatory?.short_name || '').localeCompare(b.observatory?.short_name || '')),
    }));

    return result.sort((a, b) => (a.datasource?.slug || '').localeCompare(b.datasource?.slug || ''));
  }, [usages]);

  const groupedUsages = useMemo(() => {
    const groups = new Map();

    for (const usage of usages) {
      const ds = usage.datasource?.slug || 'unknown';
      const obs = usage.observatory?.short_name || 'Unknown';
      const inst = usage.instrument?.short_name || 'Unknown';
      const key = `${ds}|${obs}|${inst}`;
      if (!groups.has(key)) {
        groups.set(key, {
          datasource: usage.datasource,
          observatory: usage.observatory,
          instrument: usage.instrument,
          usages: []
        });
      }
      groups.get(key).usages.push(usage);
    }

    return Array.from(groups.values())
      .map(group => ({
        ...group,
        // Ascending by start time for consistency with validation sorting
        usages: group.usages.slice().sort((a, b) => new Date(a.start_time || 0) - new Date(b.start_time || 0))
      }))
      // Sort groups by datasource, then observatory, then instrument
      .sort((a, b) => {
        const dsCmp = (a.datasource?.slug || '').localeCompare(b.datasource?.slug || '');
        if (dsCmp !== 0) return dsCmp;
        const obsCmp = (a.observatory?.short_name || '').localeCompare(b.observatory?.short_name || '');
        if (obsCmp !== 0) return obsCmp;
        return (a.instrument?.short_name || '').localeCompare(b.instrument?.short_name || '');
      });
  }, [usages]);

  const groupedUsagesByDatasource = useMemo(() => {
    const byDatasource = new Map();
    for (const group of groupedUsages) {
      const slug = group.datasource?.slug || 'unknown';
      const displayName = group.datasource?.slug || group.datasource?.name || 'unknown';
      if (!byDatasource.has(slug)) {
        byDatasource.set(slug, {
          slug,
          displayName,
          groups: [],
        });
      }
      byDatasource.get(slug).groups.push(group);
    }
    return Array.from(byDatasource.values()).sort((a, b) => a.displayName.localeCompare(b.displayName));
  }, [groupedUsages]);

  const linkedObservationKeys = useMemo(() => {
    const keys = new Set();
    for (const usage of usages) {
      const ds = usage.datasource?.slug || 'unknown';
      const mission = usage.observatory?.short_name;
      const instrument = usage.instrument?.short_name;
      if (!mission || !instrument) continue;
      keys.add(`${ds}|${mission}|${instrument}`);
    }
    return keys;
  }, [usages]);

  const missionMentionsForDisplay = useMemo(() => {
    return missionMentions.filter((mention) => {
      if (mention.match_level !== 'partial') return true;
      const ds = mention.observatory?.datasource?.slug || 'unknown';
      const mission = mention.observatory?.short_name;
      const instrument = mention.instrument?.short_name;
      if (!mission || !instrument) return true;
      return !linkedObservationKeys.has(`${ds}|${mission}|${instrument}`);
    });
  }, [missionMentions, linkedObservationKeys]);

  const groupedMissionMentionsByDatasource = useMemo(() => {
    const groups = new Map();

    for (const mention of missionMentionsForDisplay) {
      const dsSlug = mention.observatory?.datasource?.slug || 'unknown';
      const obsShort = mention.observatory?.short_name || 'unknown';
      const instShort = mention.instrument?.short_name || 'instrument_unresolved';
      const key = `${dsSlug}|${obsShort}|${instShort}`;

      if (!groups.has(key)) {
        groups.set(key, {
          datasource: mention.observatory?.datasource || { slug: dsSlug, name: dsSlug },
          observatory: mention.observatory,
          instrument: mention.instrument,
          mentions: [],
        });
      }
      groups.get(key).mentions.push(mention);
    }

    const groupedMentions = Array.from(groups.values()).sort((a, b) => {
      const dsCmp = (a.datasource?.slug || '').localeCompare(b.datasource?.slug || '');
      if (dsCmp !== 0) return dsCmp;
      const obsCmp = (a.observatory?.short_name || '').localeCompare(b.observatory?.short_name || '');
      if (obsCmp !== 0) return obsCmp;
      return (a.instrument?.short_name || 'instrument_unresolved')
        .localeCompare(b.instrument?.short_name || 'instrument_unresolved');
    });

    const byDatasource = new Map();
    for (const group of groupedMentions) {
      const slug = group.datasource?.slug || 'unknown';
      const displayName = group.datasource?.slug || group.datasource?.name || 'unknown';
      if (!byDatasource.has(slug)) {
        byDatasource.set(slug, {
          slug,
          displayName,
          groups: [],
        });
      }
      byDatasource.get(slug).groups.push(group);
    }

    return Array.from(byDatasource.values()).sort((a, b) => a.displayName.localeCompare(b.displayName));
  }, [missionMentionsForDisplay]);

  const observationSummary = useMemo(() => {
    const missions = new Set();
    const instruments = new Set();
    let earliest = null;
    let latest = null;

    for (const usage of usages) {
      const missionKey = usage.observatory?.short_name || usage.observatory?.display_name || 'Unknown';
      const instrumentKey = `${missionKey}|${usage.instrument?.short_name || usage.instrument?.display_name || 'Unknown'}`;
      missions.add(missionKey);
      instruments.add(instrumentKey);

      if (usage.start_time) {
        const start = new Date(usage.start_time);
        if (!Number.isNaN(start.getTime()) && (!earliest || start < earliest)) {
          earliest = start;
        }
      }
      if (usage.end_time) {
        const end = new Date(usage.end_time);
        if (!Number.isNaN(end.getTime()) && (!latest || end > latest)) {
          latest = end;
        }
      }

    }

    return {
      missionCount: missions.size,
      instrumentCount: instruments.size,
      windowCount: usages.length,
      earliest: earliest ? earliest.toISOString() : '',
      latest: latest ? latest.toISOString() : '',
    };
  }, [usages]);

  if (loading) {
    return (
      <>
        <nav style={{ marginBottom: '1rem' }}>
          <Link to="/public/papers" style={{ color: '#666', textDecoration: 'none', fontSize: 'var(--font-base)', display: 'inline-flex', alignItems: 'center' }}>← Back to Papers</Link>
        </nav>
        <p style={{ color: '#666', fontStyle: 'italic' }}>Loading paper details...</p>
      </>
    );
  }

  if (error) {
    return (
      <>
        <nav style={{ marginBottom: '1rem' }}>
          <Link to="/public/papers" style={{ color: '#666', textDecoration: 'none', fontSize: 'var(--font-base)', display: 'inline-flex', alignItems: 'center' }}>← Back to Papers</Link>
        </nav>
        <p style={{ color: '#c53030' }}>Error loading paper: {error}</p>
      </>
    );
  }

  const adsUrl = `https://ui.adsabs.harvard.edu/abs/${encodeURIComponent(paper?.bibcode || '')}/abstract`;

  return (
    <>
      <nav style={{ marginBottom: '1rem' }}>
        <Link to="/public/papers" style={{ color: '#666', textDecoration: 'none', fontSize: 'var(--font-base)', display: 'inline-flex', alignItems: 'center' }}>← Back to Papers</Link>
      </nav>
      <div className="detail-layout" style={{
        display: 'flex',
        gap: '1.5rem',
        alignItems: 'flex-start',
        flexDirection: 'row',
      }}>
      {/* Sidebar */}
      <aside className="detail-sidebar" style={{
        width: '300px',
        flexShrink: 0,
        padding: '1rem',
        borderRight: '1px solid #eee',
        backgroundColor: '#fafafa',
        height: 'fit-content',
        position: 'sticky',
        top: '1rem',
        fontSize: 'var(--font-sm)',
      }}>
        <label style={{
          display: 'inline-flex',
          alignItems: 'center',
          cursor: 'pointer',
          fontSize: 'var(--font-xs)',
          color: '#666',
          marginBottom: '0.75rem',
        }}>
          <input
            type="checkbox"
            checked={includeUnvalidated}
            onChange={(e) => handleToggleUnvalidated(e.target.checked)}
            style={{ marginRight: '0.4rem' }}
          />
          Include unreviewed
        </label>

        {/* Instruments overview as navigation */}
        {usages.length > 0 && overview.length > 0 && (
          <div style={{ color: '#4b5563' }}>
            {overview.map((ds) => (
              <div key={ds.datasource?.slug || 'unknown'} style={{ marginBottom: '0.5rem' }}>
                <div style={{
                  fontSize: 'var(--font-xs)',
                  color: '#666',
                  fontWeight: 700,
                  textTransform: 'uppercase',
                  letterSpacing: '0.5px',
                  marginBottom: '0.4rem',
                  paddingBottom: '0.25rem',
                  borderBottom: '1px solid #ddd',
                }}>
                  {(ds.datasource?.slug || ds.datasource?.name || 'Unknown datasource').toUpperCase()}
                </div>
                {ds.missions.map((m) => (
                  <div key={`${ds.datasource?.slug || 'unknown'}-${m.observatory?.short_name || 'Unknown'}`} style={{ marginBottom: '0.3rem', marginLeft: '0.25rem' }}>
                    <div style={{ fontSize: 'var(--font-xs)', color: '#aaa', fontWeight: 400 }}>
                      {(m.observatory?.display_name || m.observatory?.short_name || 'Unknown').toUpperCase()}
                    </div>
                    <div style={{ marginLeft: '0.5rem' }}>
                      {m.instruments.map((inst) => {
                        const instKey = inst.toLowerCase().replace(/\s+/g, '-');
                        return (
                          <div
                            key={inst}
                            onClick={() => {
                              const el = document.getElementById(`inst-${instKey}`);
                              if (el) {
                                el.scrollIntoView({ behavior: 'smooth', block: 'start' });
                                el.style.transition = 'none';
                                el.style.backgroundColor = '#fef9c3';
                                requestAnimationFrame(() => {
                                  requestAnimationFrame(() => {
                                    el.style.transition = 'background-color 1s ease';
                                    el.style.backgroundColor = 'transparent';
                                  });
                                });
                              }
                            }}
                            style={{
                              cursor: 'pointer',
                              padding: '0.15rem 0.4rem',
                              borderRadius: '3px',
                              color: '#3182ce',
                              fontSize: 'var(--font-sm)',
                              transition: 'background-color 0.15s',
                            }}
                            onMouseEnter={(e) => { e.currentTarget.style.backgroundColor = '#e8f0fe'; }}
                            onMouseLeave={(e) => { e.currentTarget.style.backgroundColor = 'transparent'; }}
                          >
                            {inst}
                          </div>
                        );
                      })}
                    </div>
                  </div>
                ))}
              </div>
            ))}
          </div>
        )}
      </aside>

      {/* Main content */}
      <div style={{ flex: 1, minWidth: 0 }}>
      {/* Paper Information */}
      <div style={{ marginBottom: '1rem' }}>
        <div style={{
          margin: '0 0 0.3rem 0',
          display: 'flex',
          alignItems: 'baseline',
          gap: '0.6rem',
          flexWrap: 'wrap',
        }}>
          <h2 style={{
            fontSize: 'var(--font-4xl)',
            fontWeight: '400',
            color: '#2c3e50',
            margin: 0,
            lineHeight: '1.3'
          }}>
            <a
              href={adsUrl}
              target="_blank"
              rel="noopener noreferrer"
              style={{ color: '#1f6fb2', textDecoration: 'underline', textUnderlineOffset: '2px' }}
              title="Open paper on ADS"
            >
              {paper?.title || paper?.bibcode || 'Unknown Paper'}
            </a>
          </h2>
        </div>
        <a
          href={adsUrl}
          target="_blank"
          rel="noopener noreferrer"
          style={{
            color: '#6b7280',
            textDecoration: 'none',
            fontSize: 'var(--font-xs)',
            display: 'inline-flex',
            alignItems: 'center',
            gap: '0.25rem',
            marginBottom: '0.45rem',
          }}
        >
          <img
            src="https://ui.adsabs.harvard.edu/help/img/bbb_assets/ads_partial_logo_dark_background.svg"
            alt="ADS"
            style={{ height: '16px', width: '16px', display: 'inline-block', verticalAlign: 'middle' }}
          />
          View on ADS
          ↗
        </a>

        {Array.isArray(paper?.authors) && paper.authors.length > 0 && (
          <p style={{
            margin: '0 0 0.3rem 0',
            color: '#666',
            fontSize: 'var(--font-base)'
          }}>
            {paper.authors.slice(0, 8).join(', ')}
            {paper.authors.length > 8 && ' et al.'}
          </p>
        )}

        <p style={{
          margin: '0',
          fontSize: 'var(--font-base)',
          color: '#999'
        }}>
          <code
            onClick={() => {
              navigator.clipboard.writeText(paper?.bibcode || '').then(() => {
                setCopiedBibcode(true);
                setTimeout(() => setCopiedBibcode(false), 1500);
              });
            }}
            style={{ cursor: 'pointer', position: 'relative', color: '#666', fontSize: 'var(--font-base)' }}
            title="Click to copy bibcode"
          >
            {paper?.bibcode}
            <span style={{
              marginLeft: '0.4rem',
              fontSize: 'var(--font-xs)',
              color: copiedBibcode ? '#38a169' : '#999',
              transition: 'color 0.2s',
            }}>
              {copiedBibcode ? '✓' : '⧉'}
            </span>
          </code>
          {paper?.year && ` • ${paper.year}`}
          {paper?.journal && ` • ${paper.journal}`}
        </p>
      </div>

      {/* Abstract */}
      {paper?.abstract && (
        (() => {
          const maxLen = 700;
          const text = paper.abstract || '';
          const isLong = text.length > maxLen;
          const display = showFullAbstract || !isLong ? text : (text.slice(0, maxLen) + '…');
          return (
            <p style={{ margin: '0.5rem 0 1rem 0', lineHeight: 1.5, color: '#4b5563', fontSize: 'var(--font-sm)' }}>
              <strong style={{ color: '#374151' }}>Abstract:</strong> {display}
              {isLong && !showFullAbstract && (
                <button
                  onClick={() => setShowFullAbstract(true)}
                  style={{
                    background: 'none',
                    border: 'none',
                    color: '#3182ce',
                    textDecoration: 'underline',
                    cursor: 'pointer',
                    marginLeft: '0.5rem',
                    padding: 0
                  }}
                >
                  Read more
                </button>
              )}
              {isLong && showFullAbstract && (
                <button
                  onClick={() => setShowFullAbstract(false)}
                  style={{
                    background: 'none',
                    border: 'none',
                    color: '#3182ce',
                    textDecoration: 'underline',
                    cursor: 'pointer',
                    marginLeft: '0.5rem',
                    padding: 0
                  }}
                >
                  Show less
                </button>
              )}
            </p>
          );
        })()
      )}

      {/* Divider between paper details and observations */}
      <hr style={{
        border: 'none',
        borderTop: '1px solid #e5e7eb',
        margin: '0 0 1rem 0'
      }} />

      {/* Content */}
      {usages.length === 0 ? (
        <p style={{ color: '#666', fontStyle: 'italic' }}>
          No {includeUnvalidated ? '' : 'reviewed '}linked observations found for this paper.
        </p>
      ) : (
        <>
          <div style={{
            margin: '0 0 0.9rem 0',
            padding: 0,
          }}>
            <h3 style={{
              margin: '0 0 0.2rem 0',
              fontSize: 'var(--font-4xl)',
              fontWeight: '600',
              color: '#d64535',
              textTransform: 'uppercase',
              letterSpacing: '0.6px',
            }}>
              Linked Observations
            </h3>
            <p style={{ margin: 0, color: '#6b7280', fontSize: 'var(--font-sm)' }}>
              {observationSummary.instrumentCount} instrument{observationSummary.instrumentCount !== 1 ? 's' : ''} on {observationSummary.missionCount} mission{observationSummary.missionCount !== 1 ? 's' : ''}
            </p>
            <p style={{ margin: '0.2rem 0 0 0', color: '#6b7280', fontSize: 'var(--font-sm)' }}>
              {`from ${formatSummaryDate(observationSummary.earliest) || 'unknown start'} to ${formatSummaryDate(observationSummary.latest) || 'unknown end'}`}
            </p>
          </div>
          <ul style={{
            listStyle: 'none',
            padding: 0,
            margin: 0,
            lineHeight: '1.5'
          }}>
            {groupedUsagesByDatasource.map((dsSection) => (
              <li key={dsSection.slug} style={{ marginBottom: '0.8rem' }}>
                <h4 style={{
                  margin: '0 0 0.45rem 0',
                  fontSize: 'var(--font-sm)',
                  color: '#6b7280',
                  fontWeight: '700',
                  letterSpacing: '0.5px',
                  textTransform: 'uppercase',
                  borderBottom: '1px solid #e5e7eb',
                  paddingBottom: '0.2rem',
                }}>
                  {dsSection.displayName}
                </h4>
                <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>
            {dsSection.groups.map((group, idx) => {
              const instKey = (group.instrument?.display_name || group.instrument?.short_name || 'unknown').toLowerCase().replace(/\s+/g, '-');
              const instrumentDisplay = group.instrument?.display_name || 'Unknown Instrument';
              const instrumentFull = group.instrument?.full_name || instrumentDisplay;
              const missionDisplay = group.observatory?.display_name || 'Unknown Observatory';
              const missionFull = group.observatory?.name || missionDisplay;
              const tooltipBaseKey = `${dsSection.slug}-${instKey}-${idx}`;
              return (
              <li key={idx} id={`inst-${instKey}`} style={{
                marginBottom: '1.1rem',
                padding: '0.45rem 0.7rem 0.85rem',
                borderBottom: idx < dsSection.groups.length - 1 ? '1px solid #eee' : 'none',
                borderRadius: '6px',
              }}>
                <div style={{
                  margin: '0 0 0.4rem 0',
                  display: 'flex',
                  alignItems: 'baseline',
                  flexWrap: 'wrap',
                  gap: '0.35rem',
                  fontSize: 'var(--font-base)',
                  color: '#2c3e50',
                }}>
                  <strong>
                    <HoverNameLabel
                      displayText={instrumentDisplay}
                      fullText={instrumentFull}
                      tooltipKey={`${tooltipBaseKey}-instrument`}
                      hoveredKey={hoveredNameLabelKey}
                      setHoveredKey={setHoveredNameLabelKey}
                    />
                  </strong>
                  <span style={{ fontWeight: 400 }}>on</span>
                  <strong>
                    <HoverNameLabel
                      displayText={missionDisplay}
                      fullText={missionFull}
                      tooltipKey={`${tooltipBaseKey}-mission`}
                      hoveredKey={hoveredNameLabelKey}
                      setHoveredKey={setHoveredNameLabelKey}
                    />
                  </strong>
                </div>

                <div style={{ marginLeft: '0.65rem' }}>
                  {group.usages.map((usage) => {
                    const start = formatDateTime(usage.start_time);
                    const end = formatDateTime(usage.end_time);
                    const startText = `${start.year} ${start.month} ${start.day} ${start.time}`.trim();
                    const endText = `${end.year} ${end.month} ${end.day} ${end.time}`.trim();
                    const isVerified = usage.validation_status === 'approved';
                    const verificationText = 'Validated by a human reviewer';
                    return (
                      <div key={usage.id}>
                        <div style={{
                          marginBottom: '0.35rem',
                          fontSize: 'var(--font-sm)',
                          display: 'grid',
                          gridTemplateColumns: '1.4rem 2rem 17ch 1.3rem 17ch auto',
                          alignItems: 'center',
                          columnGap: '0.35rem',
                          padding: '0.1rem 0',
                        }}>
                        {isVerified ? (
                          <span
                            style={{ position: 'relative', display: 'inline-flex' }}
                            onMouseEnter={() => setHoveredValidationUsageId(usage.id)}
                            onMouseLeave={() => setHoveredValidationUsageId(null)}
                            onFocus={() => setHoveredValidationUsageId(usage.id)}
                            onBlur={() => setHoveredValidationUsageId(null)}
                          >
                            <span
                              style={{
                                fontSize: 'var(--font-sm)',
                                width: '1rem',
                                height: '1rem',
                                display: 'inline-flex',
                                alignItems: 'center',
                                justifyContent: 'center',
                                fontWeight: '700',
                                color: '#15803d',
                                cursor: 'default',
                              }}
                              aria-label={verificationText}
                              tabIndex={0}
                            >
                              ✓
                            </span>
                            {hoveredValidationUsageId === usage.id && (
                              <span
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
                                  {verificationText}
                                </span>
                              )}
                          </span>
                        ) : (
                          <span
                            aria-hidden="true"
                            style={{
                              width: '1rem',
                              height: '1rem',
                              display: 'inline-flex',
                              alignItems: 'center',
                              justifyContent: 'center',
                              color: '#9ca3af',
                              fontSize: '1rem',
                              lineHeight: 1,
                            }}
                          >
                            •
                          </span>
                        )}

                        <span style={{ color: '#6b7280' }}>from</span>
                        <strong style={{ color: '#2c3e50', fontSize: 'var(--font-sm)', fontWeight: 700, whiteSpace: 'nowrap' }}>
                          {startText || 'Unknown'}
                        </strong>
                        <span style={{ color: '#6b7280' }}>to</span>
                        <strong style={{ color: '#2c3e50', fontSize: 'var(--font-sm)', fontWeight: 700, whiteSpace: 'nowrap' }}>
                          {endText || 'Unknown'}
                        </strong>
                        <div style={{
                          display: 'flex',
                          alignItems: 'center',
                          columnGap: '0.7rem',
                          rowGap: '0.2rem',
                          flexWrap: 'wrap',
                          marginLeft: '0.15rem',
                        }}>
                          {usage.supporting_quotes && usage.supporting_quotes.length > 0 && (
                            <ObservationActionLink
                              icon="❝"
                              label="Quotes"
                              onClick={(e) => {
                                e.stopPropagation();
                                setQuotesUsage(usage);
                              }}
                            />
                          )}

                          {usage.python_snippet && (
                            <ObservationActionLink
                              icon="</>"
                              label="Code"
                              onClick={() => setSelectedUsage(usage)}
                            />
                          )}
                        </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </li>
              );
            })}
                </ul>
              </li>
            ))}
          </ul>
        </>
      )}

      {missionMentionsForDisplay.length > 0 && (
        <section style={{ marginTop: '0.65rem', marginBottom: '0.75rem' }}>
          <h3 style={{
            margin: '0 0 0.2rem 0',
            fontSize: 'var(--font-2xl)',
            fontWeight: '500',
            color: '#6b7280',
            textTransform: 'uppercase',
            letterSpacing: '0.4px',
          }}>
            Other Observations
          </h3>
          <p style={{ margin: '0 0 0.3rem 0', color: '#6b7280', fontSize: 'var(--font-sm)' }}>
            Missions and instruments not resolved to a specific usage time window.
          </p>
          <ul style={{
            listStyle: 'none',
            padding: 0,
            margin: 0,
            lineHeight: '1.35'
          }}>
            {groupedMissionMentionsByDatasource.map((dsSection) => (
              <li key={dsSection.slug} style={{ marginBottom: '0.45rem' }}>
                <h4 style={{
                  margin: '0 0 0.2rem 0',
                  fontSize: 'var(--font-sm)',
                  color: '#6b7280',
                  fontWeight: '700',
                  letterSpacing: '0.5px',
                  textTransform: 'uppercase',
                  borderBottom: '1px solid #e5e7eb',
                  paddingBottom: '0.12rem',
                }}>
                  {dsSection.displayName}
                </h4>
                <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>
                  {dsSection.groups.map((group, idx) => {
                    const hasInstrument = !!group.instrument;
                    const instDisplay = group.instrument?.display_name || group.instrument?.short_name || 'Instrument unresolved';
                    const instFull = group.instrument?.full_name || instDisplay;
                    const missionDisplay = group.observatory?.display_name || group.observatory?.short_name || 'Unknown Observatory';
                    const missionFull = group.observatory?.name || missionDisplay;
                    const tooltipBaseKey = `${dsSection.slug}-other-${idx}`;
                    return (
                      <li key={tooltipBaseKey} style={{
                        marginBottom: '0.3rem',
                        padding: '0.18rem 0.45rem 0.25rem',
                        borderRadius: '4px',
                      }}>
                        <div style={{
                          margin: '0',
                          display: 'flex',
                          alignItems: 'baseline',
                          flexWrap: 'wrap',
                          gap: '0.25rem',
                          fontSize: 'var(--font-base)',
                          color: '#2c3e50',
                        }}>
                          {hasInstrument ? (
                            <>
                              <strong>
                                <HoverNameLabel
                                  displayText={instDisplay}
                                  fullText={instFull}
                                  tooltipKey={`${tooltipBaseKey}-instrument`}
                                  hoveredKey={hoveredNameLabelKey}
                                  setHoveredKey={setHoveredNameLabelKey}
                                />
                              </strong>
                              <span style={{ fontWeight: 400 }}>on</span>
                            </>
                          ) : null}
                          <strong>
                            {hasInstrument ? (
                              <HoverNameLabel
                                displayText={missionDisplay}
                                fullText={missionFull}
                                tooltipKey={`${tooltipBaseKey}-mission`}
                                hoveredKey={hoveredNameLabelKey}
                                setHoveredKey={setHoveredNameLabelKey}
                              />
                            ) : (
                              <HoverNameLabel
                                displayText={missionDisplay}
                                fullText={missionFull}
                                tooltipKey={`${tooltipBaseKey}-mission`}
                                hoveredKey={hoveredNameLabelKey}
                                setHoveredKey={setHoveredNameLabelKey}
                              />
                            )}
                          </strong>
                          {group.mentions.length > 1 && (
                            <span style={{ color: '#6b7280', fontSize: 'var(--font-sm)' }}>
                              {group.mentions.length} mentions
                            </span>
                          )}
                        </div>
                      </li>
                    );
                  })}
                </ul>
              </li>
            ))}
          </ul>
        </section>
      )}
      </div>


      {/* Similar Papers (right sidebar) */}
      {bibcode && (
        <aside style={{
          flexShrink: 0,
          borderLeft: '1px solid #eee',
          backgroundColor: '#fafafa',
          height: 'fit-content',
          position: 'sticky',
          top: '1rem',
        }}>
          <SimilarPapers bibcode={bibcode} includeUnvalidated={includeUnvalidated} />
        </aside>
      )}

      </div>

      {/* Script Modal */}
      <ScriptModal
        usage={selectedUsage}
        onClose={() => setSelectedUsage(null)}
      />

      <QuotesModal
        usage={quotesUsage}
        onClose={() => setQuotesUsage(null)}
        openEvidenceLabel={isAuthenticated ? 'Open Validation View' : 'Open Full Evidence View'}
        onOpenEvidenceView={(usage) => {
          if (isAuthenticated && paper?.id) {
            navigate(`/papers/${paper.id}/validate/${usage.id}`);
            return;
          }
          const querySuffix = includeUnvalidated ? '?include_unvalidated=true' : '';
          navigate(`/public/p/${encodeURIComponent(bibcode)}/evidence/${usage.id}${querySuffix}`);
        }}
      />
    </>
  );
}
