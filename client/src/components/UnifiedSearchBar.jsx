import React, { useEffect, useMemo, useRef, useState } from 'react';

export default function UnifiedSearchBar({
  filterOptions,
  filters,
  onFiltersChange,
  searchQuery,
  onSearchChange,
  searchInputRef: externalRef,
}) {
  const [inputValue, setInputValue] = useState(searchQuery);
  const [isOpen, setIsOpen] = useState(false);
  const [highlightIndex, setHighlightIndex] = useState(-1);
  const [isFocused, setIsFocused] = useState(false);
  const containerRef = useRef(null);
  const inputRef = useRef(null);

  // Merge external ref with internal ref
  const setInputRef = (el) => {
    inputRef.current = el;
    if (externalRef) externalRef.current = el;
  };

  // Keep local value in sync with external searchQuery —
  // but only if there's no committed search chip (committed searches
  // show as a chip, not in the input).
  useEffect(() => {
    if (!searchQuery) setInputValue('');
  }, [searchQuery]);

  // Cmd+K / Ctrl+K to focus
  useEffect(() => {
    const handler = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        inputRef.current?.focus();
      }
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, []);

  // Click outside to close
  useEffect(() => {
    const handler = (e) => {
      if (containerRef.current && !containerRef.current.contains(e.target)) {
        setIsOpen(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  // Build searchable index from filterOptions
  const searchIndex = useMemo(() => {
    if (!filterOptions) return [];
    const items = [];

    const missionsByDs = filterOptions.missions_by_datasource || {};
    const instrumentsByDsAndMission = filterOptions.instruments_by_datasource_and_mission || {};

    for (const [dsSlug, dsGroup] of Object.entries(missionsByDs)) {
      for (const mission of dsGroup.missions) {
        items.push({
          type: 'mission',
          key: mission.key,
          label: mission.display_name || mission.short_name,
          shortName: mission.short_name,
          fullName: mission.name || '',
          datasource: dsSlug.toUpperCase(),
          paperCount: mission.paper_count,
        });

        const instruments = instrumentsByDsAndMission[mission.key] || [];
        for (const inst of instruments) {
          items.push({
            type: 'instrument',
            name: inst.short_name,
            label: inst.display_name || inst.short_name,
            fullName: inst.full_name || '',
            missionKey: mission.key,
            missionLabel: mission.display_name || mission.short_name,
            datasource: dsSlug.toUpperCase(),
            paperCount: inst.paper_count,
          });
        }
      }
    }

    return items;
  }, [filterOptions]);

  // Filter suggestions based on input
  const suggestions = useMemo(() => {
    const q = inputValue.trim().toLowerCase();
    if (!q || q.length < 1) return [];

    const matched = searchIndex.filter((item) => {
      const label = item.label.toLowerCase();
      const shortName = (item.shortName || item.name || '').toLowerCase();
      const fullName = (item.fullName || '').toLowerCase();
      const missionLabel = (item.missionLabel || '').toLowerCase();
      return label.includes(q) || shortName.includes(q) || fullName.includes(q) || missionLabel.includes(q);
    });

    // Group into missions and instruments, limit each
    const missions = matched.filter((m) => m.type === 'mission').slice(0, 5);
    const instruments = matched.filter((m) => m.type === 'instrument').slice(0, 8);

    // Detect date/time range patterns
    const dateItems = [];
    const raw = inputValue.trim();

    // Single year: "2012"
    const singleYear = raw.match(/^(\d{4})$/);
    // Range: "2012-2015" or "2012 2015"
    const yearRange = raw.match(/^(\d{4})\s*[-–—\s]+(\d{4})$/);
    // "after 2012" / "since 2012"
    const afterYear = raw.match(/^(?:after|since|from)\s+(\d{4})$/i);
    // "before 2015" / "until 2015"
    const beforeYear = raw.match(/^(?:before|until|to)\s+(\d{4})$/i);

    if (yearRange) {
      const [, y1, y2] = yearRange;
      dateItems.push({
        type: 'date_range',
        label: `Observations ${y1}–${y2}`,
        start_date: `${y1}-01-01`,
        end_date: `${y2}-12-31`,
      });
    } else if (afterYear) {
      const y = afterYear[1];
      dateItems.push({
        type: 'date_range',
        label: `Observations after ${y}`,
        start_date: `${y}-01-01`,
        end_date: '',
      });
    } else if (beforeYear) {
      const y = beforeYear[1];
      dateItems.push({
        type: 'date_range',
        label: `Observations before ${y}`,
        start_date: '',
        end_date: `${y}-12-31`,
      });
    } else if (singleYear) {
      const y = singleYear[1];
      const yn = parseInt(y, 10);
      if (yn >= 1990 && yn <= 2030) {
        dateItems.push({
          type: 'date_range',
          label: `Observations in ${y}`,
          start_date: `${y}-01-01`,
          end_date: `${y}-12-31`,
        });
        dateItems.push({
          type: 'date_range',
          label: `Observations after ${y}`,
          start_date: `${y}-01-01`,
          end_date: '',
        });
        dateItems.push({
          type: 'date_range',
          label: `Observations before ${y}`,
          start_date: '',
          end_date: `${y}-12-31`,
        });
      }
    }

    return [...missions, ...instruments, ...dateItems];
  }, [inputValue, searchIndex]);

  // Reset highlight when suggestions change
  useEffect(() => {
    setHighlightIndex(-1);
  }, [suggestions]);

  // Build a reverse lookup: instrument short_name → display label
  const instrumentLabels = useMemo(() => {
    const map = {};
    for (const item of searchIndex) {
      if (item.type === 'instrument') {
        map[item.name] = item.label;
      }
    }
    return map;
  }, [searchIndex]);

  // Mission lookup for mission chips and mission suggestions
  const missionLabelMap = useMemo(() => {
    if (!filterOptions) return {};
    const map = {};
    const missionsByDs = filterOptions.missions_by_datasource || {};
    for (const [dsSlug, dsGroup] of Object.entries(missionsByDs)) {
      for (const mission of dsGroup.missions) {
        map[mission.key] = {
          label: mission.display_name || mission.short_name,
          datasource: dsSlug.toUpperCase(),
        };
      }
    }
    return map;
  }, [filterOptions]);

  // Compute chip display from explicit mission + instrument selections
  const chipItems = useMemo(() => {
    const items = [];

    for (const missionKey of (filters.missions || [])) {
      const missionInfo = missionLabelMap[missionKey];
      items.push({
        type: 'mission',
        key: missionKey,
        label: missionInfo?.label || missionKey,
        datasource: missionInfo?.datasource || '',
      });
    }

    for (const name of (filters.instruments || [])) {
      items.push({
        type: 'instrument',
        name,
        label: instrumentLabels[name] || name,
      });
    }

    return items;
  }, [filters.missions, filters.instruments, missionLabelMap, instrumentLabels]);

  const selectSuggestion = (item) => {
    let newFilters;
    if (item.type === 'date_range') {
      newFilters = {
        ...filters,
        start_date: item.start_date || filters.start_date || '',
        end_date: item.end_date || filters.end_date || '',
      };
    } else if (item.type === 'mission') {
      const current = filters.missions || [];
      newFilters = {
        ...filters,
        missions: current.includes(item.key) ? current : [...current, item.key],
      };
    } else {
      // Add single instrument
      const current = filters.instruments || [];
      newFilters = {
        ...filters,
        instruments: current.includes(item.name) ? current : [...current, item.name],
      };
    }
    onFiltersChange(newFilters);
    setIsOpen(false);
    setInputValue('');
    inputRef.current?.focus();
  };

  const removeInstrument = (name) => {
    const newInstruments = (filters.instruments || []).filter((i) => i !== name);
    onFiltersChange({ ...filters, instruments: newInstruments });
    inputRef.current?.focus();
  };

  const removeMission = (missionKey) => {
    const newMissions = (filters.missions || []).filter((m) => m !== missionKey);
    onFiltersChange({ ...filters, missions: newMissions });
    inputRef.current?.focus();
  };

  const removeDateFilter = () => {
    onFiltersChange({ ...filters, start_date: '', end_date: '' });
    inputRef.current?.focus();
  };

  const clearAllChips = () => {
    onFiltersChange({
      ...filters,
      missions: [],
      instruments: [],
      start_date: '',
      end_date: '',
    }, { clearSearch: true });
    setInputValue('');
    inputRef.current?.focus();
  };

  const handleInputChange = (e) => {
    const val = e.target.value;
    setInputValue(val);
    // Only update autocomplete dropdown — don't trigger API text search while typing.
    // Text search commits on Enter (see handleKeyDown).
    if (val.trim()) {
      setIsOpen(true);
    } else {
      setIsOpen(false);
      // Clearing the input clears any active text search
      onSearchChange('');
    }
  };

  const handleKeyDown = (e) => {
    // Backspace on empty input removes last chip (text search first, then last chip)
    if (e.key === 'Backspace' && !inputValue) {
      if (searchQuery) {
        onSearchChange('');
      } else if (filters.start_date || filters.end_date) {
        removeDateFilter();
      } else if (chipItems.length > 0) {
        const lastChip = chipItems[chipItems.length - 1];
        if (lastChip.type === 'mission') {
          removeMission(lastChip.key);
        } else {
          removeInstrument(lastChip.name);
        }
      }
      return;
    }

    if (e.key === 'Enter') {
      e.preventDefault();
      if (isOpen && highlightIndex >= 0 && suggestions.length > 0) {
        // Select highlighted suggestion
        selectSuggestion(suggestions[highlightIndex]);
      } else if (inputValue.trim()) {
        // Commit text as a title/bibcode search — shows as a chip
        setIsOpen(false);
        onSearchChange(inputValue.trim());
        setInputValue('');
      }
      return;
    }

    if (!isOpen || suggestions.length === 0) return;

    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setHighlightIndex((prev) => (prev < suggestions.length - 1 ? prev + 1 : 0));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setHighlightIndex((prev) => (prev > 0 ? prev - 1 : suggestions.length - 1));
    } else if (e.key === 'Escape') {
      setIsOpen(false);
    }
  };

  const hasChips =
    searchQuery ||
    (filters.missions && filters.missions.length > 0) ||
    (filters.instruments && filters.instruments.length > 0) ||
    filters.start_date ||
    filters.end_date;

  return (
    <div ref={containerRef} style={{ position: 'relative', maxWidth: '600px', marginBottom: '0.75rem' }}>
      <div style={{ display: 'flex', alignItems: 'stretch' }}>
      {/* Tag-input container: looks like a single input but contains chips + real input */}
      <div
        onClick={() => inputRef.current?.focus()}
        style={{
          display: 'flex',
          flexWrap: 'wrap',
          alignItems: 'center',
          gap: '0.25rem',
          padding: '0.35rem 0.5rem',
          border: `1px solid ${isFocused ? '#4a90d9' : '#ccc'}`,
          borderRight: 'none',
          borderRadius: '4px 0 0 4px',
          backgroundColor: 'white',
          cursor: 'text',
          minHeight: '36px',
          flex: 1,
        }}
      >
        {/* Text search chip */}
        {searchQuery && (
          <span
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: '0.2rem',
              padding: '0.1rem 0.4rem',
              backgroundColor: '#f0f0f0',
              color: '#444',
              borderRadius: '3px',
              fontSize: 'var(--font-xs)',
              border: '1px solid #d0d0d0',
              whiteSpace: 'nowrap',
              lineHeight: '1.4',
            }}
          >
            &ldquo;{searchQuery}&rdquo;
            <button
              onClick={(e) => { e.stopPropagation(); onSearchChange(''); }}
              style={{
                background: 'none',
                border: 'none',
                color: '#666',
                cursor: 'pointer',
                padding: '0 0.1rem',
                fontSize: 'var(--font-xs)',
                lineHeight: 1,
              }}
            >
              ×
            </button>
          </span>
        )}
        {/* AND connector between text search and instruments/missions */}
        {searchQuery && (chipItems.length > 0 || filters.start_date || filters.end_date) && (
          <span style={{ fontSize: 'var(--font-xs)', color: '#999', fontStyle: 'italic', padding: '0 0.1rem' }}>and</span>
        )}
        {/* Inline chips for active instrument/mission filters with OR connectors */}
        {chipItems.map((chip, idx) => (
          <React.Fragment key={chip.type === 'mission' ? `m-${chip.key}` : `i-${chip.name}`}>
            {idx > 0 && (
              <span style={{ fontSize: 'var(--font-xs)', color: '#999', fontStyle: 'italic', padding: '0 0.1rem' }}>or</span>
            )}
            {chip.type === 'mission' ? (
              <span
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '0.2rem',
                  padding: '0.1rem 0.4rem',
                  backgroundColor: '#e6fffa',
                  color: '#285e61',
                  borderRadius: '3px',
                  fontSize: 'var(--font-xs)',
                  border: '1px solid #b2f5ea',
                  whiteSpace: 'nowrap',
                  lineHeight: '1.4',
                }}
              >
                {chip.label}
                <button
                  onClick={(e) => { e.stopPropagation(); removeMission(chip.key); }}
                  style={{
                    background: 'none',
                    border: 'none',
                    color: '#285e61',
                    cursor: 'pointer',
                    padding: '0 0.1rem',
                    fontSize: 'var(--font-xs)',
                    lineHeight: 1,
                  }}
                >
                  ×
                </button>
              </span>
            ) : (
              <span
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '0.2rem',
                  padding: '0.1rem 0.4rem',
                  backgroundColor: '#ebf4ff',
                  color: '#2b6cb0',
                  borderRadius: '3px',
                  fontSize: 'var(--font-xs)',
                  border: '1px solid #bee3f8',
                  whiteSpace: 'nowrap',
                  lineHeight: '1.4',
                }}
              >
                {chip.label}
                <button
                  onClick={(e) => { e.stopPropagation(); removeInstrument(chip.name); }}
                  style={{
                    background: 'none',
                    border: 'none',
                    color: '#2b6cb0',
                    cursor: 'pointer',
                    padding: '0 0.1rem',
                    fontSize: 'var(--font-xs)',
                    lineHeight: 1,
                  }}
                >
                  ×
                </button>
              </span>
            )}
          </React.Fragment>
        ))}
        {/* AND connector between instruments/missions and date range */}
        {chipItems.length > 0 && (filters.start_date || filters.end_date) && (
          <span style={{ fontSize: 'var(--font-xs)', color: '#999', fontStyle: 'italic', padding: '0 0.1rem' }}>and</span>
        )}
        {/* Date range chip */}
        {(filters.start_date || filters.end_date) && (
          <span
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: '0.2rem',
              padding: '0.1rem 0.4rem',
              backgroundColor: '#fefcbf',
              color: '#744210',
              borderRadius: '3px',
              fontSize: 'var(--font-xs)',
              border: '1px solid #f6e05e',
              whiteSpace: 'nowrap',
              lineHeight: '1.4',
            }}
          >
            {filters.start_date || '…'} – {filters.end_date || '…'}
            <button
              onClick={(e) => { e.stopPropagation(); removeDateFilter(); }}
              style={{
                background: 'none',
                border: 'none',
                color: '#744210',
                cursor: 'pointer',
                padding: '0 0.1rem',
                fontSize: 'var(--font-xs)',
                lineHeight: 1,
              }}
            >
              ×
            </button>
          </span>
        )}
        {/* Actual text input */}
        <input
          ref={setInputRef}
          type="text"
          placeholder={hasChips ? 'Add more...(⌘K)' : 'Search papers, missions, instruments...  (⌘K)'}
          value={inputValue}
          onChange={handleInputChange}
          onFocus={() => {
            setIsFocused(true);
            if (inputValue.trim() && suggestions.length > 0) setIsOpen(true);
          }}
          onBlur={() => setIsFocused(false)}
          onKeyDown={handleKeyDown}
          style={{
            flex: 1,
            minWidth: '120px',
            border: 'none',
            outline: 'none',
            padding: '0.15rem 0.25rem',
            fontSize: 'var(--font-base)',
            backgroundColor: 'transparent',
          }}
        />
        {/* Clear all button */}
        {hasChips && (
          <button
            onClick={(e) => { e.stopPropagation(); clearAllChips(); }}
            style={{
              background: 'none',
              border: 'none',
              color: '#999',
              cursor: 'pointer',
              padding: '0 0.2rem',
              fontSize: 'var(--font-sm)',
              lineHeight: 1,
              flexShrink: 0,
            }}
            title="Clear all filters"
          >
            ×
          </button>
        )}
      </div>
      {/* Search submit button — flush with the input box */}
      <button
        onClick={() => {
          if (inputValue.trim()) {
            setIsOpen(false);
            onSearchChange(inputValue.trim());
            setInputValue('');
          }
          inputRef.current?.focus();
        }}
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          padding: '0 0.65rem',
          backgroundColor: '#2c4a7c',
          color: 'white',
          border: '1px solid #2c4a7c',
          borderRadius: '0 4px 4px 0',
          cursor: 'pointer',
          flexShrink: 0,
        }}
        title="Search"
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="11" cy="11" r="8" />
          <line x1="21" y1="21" x2="16.65" y2="16.65" />
        </svg>
      </button>
      </div>

      {/* Autocomplete dropdown */}
      {isOpen && suggestions.length > 0 && (
        <div
          style={{
            position: 'absolute',
            top: '100%',
            left: 0,
            right: 0,
            backgroundColor: 'white',
            border: '1px solid #ddd',
            borderTop: 'none',
            borderRadius: '0 0 4px 4px',
            boxShadow: '0 4px 12px rgba(0,0,0,0.1)',
            zIndex: 100,
            maxHeight: '320px',
            overflowY: 'auto',
          }}
        >
          {/* Mission suggestions */}
          {suggestions.some((s) => s.type === 'mission') && (
            <>
              <div
                style={{
                  padding: '0.4rem 0.75rem',
                  fontSize: 'var(--font-xs)',
                  color: '#999',
                  fontWeight: '600',
                  textTransform: 'uppercase',
                  letterSpacing: '0.5px',
                  borderBottom: '1px solid #f0f0f0',
                }}
              >
                Missions
              </div>
              {suggestions
                .filter((s) => s.type === 'mission')
                .map((item) => {
                  const idx = suggestions.indexOf(item);
                  return (
                    <div
                      key={`m-${item.key}`}
                      onClick={() => selectSuggestion(item)}
                      style={{
                        padding: '0.4rem 0.75rem',
                        cursor: 'pointer',
                        backgroundColor: highlightIndex === idx ? '#f0f7ff' : 'white',
                        display: 'flex',
                        justifyContent: 'space-between',
                        alignItems: 'center',
                        fontSize: 'var(--font-sm)',
                      }}
                      onMouseEnter={() => setHighlightIndex(idx)}
                    >
                      <span>
                        <strong>{item.label}</strong>
                        {item.fullName && item.fullName !== item.label && (
                          <span style={{ color: '#777', marginLeft: '0.4rem', fontSize: 'var(--font-xs)' }}>
                            {item.fullName}
                          </span>
                        )}
                        <span style={{ color: '#aaa', marginLeft: '0.4rem', fontSize: 'var(--font-xs)' }}>
                          {item.datasource}
                        </span>
                      </span>
                      <span style={{ color: '#999', fontSize: 'var(--font-xs)' }}>
                        {item.paperCount} papers
                      </span>
                    </div>
                  );
                })}
            </>
          )}

          {/* Instrument suggestions */}
          {suggestions.some((s) => s.type === 'instrument') && (
            <>
              <div
                style={{
                  padding: '0.4rem 0.75rem',
                  fontSize: 'var(--font-xs)',
                  color: '#999',
                  fontWeight: '600',
                  textTransform: 'uppercase',
                  letterSpacing: '0.5px',
                  borderBottom: '1px solid #f0f0f0',
                  borderTop: suggestions.some((s) => s.type === 'mission')
                    ? '1px solid #f0f0f0'
                    : 'none',
                }}
              >
                Instruments
              </div>
              {suggestions
                .filter((s) => s.type === 'instrument')
                .map((item) => {
                  const idx = suggestions.indexOf(item);
                  const alreadyActive = (filters.instruments || []).includes(item.name);
                  return (
                    <div
                      key={`i-${item.missionKey}-${item.name}`}
                      onClick={() => !alreadyActive && selectSuggestion(item)}
                      style={{
                        padding: '0.4rem 0.75rem',
                        cursor: alreadyActive ? 'default' : 'pointer',
                        backgroundColor:
                          highlightIndex === idx ? '#f0f7ff' : alreadyActive ? '#f9f9f9' : 'white',
                        display: 'flex',
                        justifyContent: 'space-between',
                        alignItems: 'center',
                        fontSize: 'var(--font-sm)',
                        opacity: alreadyActive ? 0.5 : 1,
                      }}
                      onMouseEnter={() => setHighlightIndex(idx)}
                    >
                      <span>
                        <strong>{item.label}</strong>
                        {item.fullName && item.fullName !== item.label && (
                          <span style={{ color: '#777', marginLeft: '0.4rem', fontSize: 'var(--font-xs)' }}>
                            {item.fullName}
                          </span>
                        )}
                        <span
                          style={{
                            color: '#aaa',
                            marginLeft: '0.4rem',
                            fontSize: 'var(--font-xs)',
                          }}
                        >
                          {item.missionLabel} · {item.datasource}
                        </span>
                      </span>
                      <span style={{ color: '#999', fontSize: 'var(--font-xs)' }}>
                        {alreadyActive ? '✓' : `${item.paperCount} papers`}
                      </span>
                    </div>
                  );
                })}
            </>
          )}

          {/* Time range suggestions */}
          {suggestions.some((s) => s.type === 'date_range') && (
            <>
              <div
                style={{
                  padding: '0.4rem 0.75rem',
                  fontSize: 'var(--font-xs)',
                  color: '#999',
                  fontWeight: '600',
                  textTransform: 'uppercase',
                  letterSpacing: '0.5px',
                  borderBottom: '1px solid #f0f0f0',
                  borderTop: suggestions.some((s) => s.type === 'mission' || s.type === 'instrument')
                    ? '1px solid #f0f0f0'
                    : 'none',
                }}
              >
                Time Range
              </div>
              {suggestions
                .filter((s) => s.type === 'date_range')
                .map((item) => {
                  const idx = suggestions.indexOf(item);
                  return (
                    <div
                      key={`d-${item.label}`}
                      onClick={() => selectSuggestion(item)}
                      style={{
                        padding: '0.4rem 0.75rem',
                        cursor: 'pointer',
                        backgroundColor: highlightIndex === idx ? '#f0f7ff' : 'white',
                        display: 'flex',
                        justifyContent: 'space-between',
                        alignItems: 'center',
                        fontSize: 'var(--font-sm)',
                      }}
                      onMouseEnter={() => setHighlightIndex(idx)}
                    >
                      <span>{item.label}</span>
                      <span style={{ color: '#999', fontSize: 'var(--font-xs)' }}>
                        {item.start_date && item.end_date
                          ? `${item.start_date} – ${item.end_date}`
                          : item.start_date
                            ? `from ${item.start_date}`
                            : `until ${item.end_date}`}
                      </span>
                    </div>
                  );
                })}
            </>
          )}
        </div>
      )}
    </div>
  );
}
