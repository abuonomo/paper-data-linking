import React, { useState, useEffect, useCallback } from 'react';

export default function FacetedFilters({
  filters,
  onFiltersChange,
  filterOptions,
  loading,
  hideValidationStatus = false,
  includeUnvalidated = false,
  onToggleUnvalidated = null,
}) {
  const [collapsed, setCollapsed] = useState({
    missions: false,
    dates: false,
    status: false
  });
  const [expandedMissions, setExpandedMissions] = useState({});
  const [expandedDatasources, setExpandedDatasources] = useState({});
  const [showAllMissions, setShowAllMissions] = useState({});
  const MISSION_PREVIEW_COUNT = 4;

  // Local state for date inputs so we don't trigger API while typing
  const [localStart, setLocalStart] = useState(filters.start_date || '');
  const [localEnd, setLocalEnd] = useState(filters.end_date || '');

  // Default datasources to expanded when data first loads
  useEffect(() => {
    if (filterOptions?.missions_by_datasource) {
      setExpandedDatasources(prev => {
        if (Object.keys(prev).length > 0) return prev;
        const init = {};
        for (const slug of Object.keys(filterOptions.missions_by_datasource)) {
          init[slug] = true;
        }
        return init;
      });
    }
  }, [filterOptions?.missions_by_datasource]);

  // Keep local state in sync if external filters change (e.g., clear all)
  useEffect(() => {
    setLocalStart(filters.start_date || '');
    setLocalEnd(filters.end_date || '');
  }, [filters.start_date, filters.end_date]);

  const toggleSection = (section) => {
    setCollapsed(prev => ({
      ...prev,
      [section]: !prev[section]
    }));
  };

  // Get all instruments keyed by mission (datasource-aware or legacy)
  const getAvailableInstruments = useCallback(() => {
    return filterOptions?.instruments_by_datasource_and_mission || filterOptions?.instruments_by_mission || {};
  }, [filterOptions]);

  const getMissionCheckState = useCallback((missionKey) => {
    return (filters.missions || []).includes(missionKey);
  }, [filters.missions]);

  const handleMissionChange = (missionKey, checked) => {
    const currentMissions = filters.missions || [];
    const newMissions = checked
      ? (currentMissions.includes(missionKey) ? currentMissions : [...currentMissions, missionKey])
      : currentMissions.filter(m => m !== missionKey);

    onFiltersChange({
      ...filters,
      missions: newMissions
    });
  };

  const handleInstrumentChange = (instrumentName, checked) => {
    const currentInstruments = filters.instruments || [];
    const newInstruments = checked 
      ? [...currentInstruments, instrumentName]
      : currentInstruments.filter(i => i !== instrumentName);
    
    onFiltersChange({
      ...filters,
      instruments: newInstruments
    });
  };

  const handleDateLocalChange = (field, value) => {
    if (field === 'start_date') setLocalStart(value);
    if (field === 'end_date') setLocalEnd(value);
  };

  const commitDateRangeChange = () => {
    // Only commit if changed; empty string clears filter
    const next = { ...filters, start_date: localStart || '', end_date: localEnd || '' };
    if (next.start_date !== filters.start_date || next.end_date !== filters.end_date) {
      onFiltersChange(next);
    }
  };

  const handleStatusChange = (status, checked) => {
    const currentStatuses = filters.validation_status || [];
    const newStatuses = checked 
      ? [...currentStatuses, status]
      : currentStatuses.filter(s => s !== status);
    
    onFiltersChange({
      ...filters,
      validation_status: newStatuses
    });
  };

  const clearAllFilters = () => {
    setLocalStart('');
    setLocalEnd('');
    onFiltersChange({
      missions: [],
      instruments: [],
      start_date: '',
      end_date: '',
      validation_status: []
    });
  };

  const getActiveFilterCount = () => {
    let count = 0;
    if (filters.missions && filters.missions.length > 0) count += filters.missions.length;
    if (filters.instruments && filters.instruments.length > 0) count += filters.instruments.length;
    if (filters.start_date || filters.end_date) count += 1;
    if (!hideValidationStatus && filters.validation_status && filters.validation_status.length > 0) count += filters.validation_status.length;
    return count;
  };

  const activeCount = getActiveFilterCount();

  // Check if the new datasource-grouped API response is available
  const hasDatasourceGroups = !!filterOptions?.missions_by_datasource;

  // Only show the full loading placeholder on initial load (no data yet).
  // During re-fetches (e.g. toggling unreviewed), keep existing content visible.
  const isInitialLoad = loading && !filterOptions;

  if (isInitialLoad) {
    return (
      <div style={{
        width: '300px',
        padding: '1rem',
        borderRight: '1px solid #eee',
        color: '#666',
        fontStyle: 'italic'
      }}>
        Loading filters...
      </div>
    );
  }

  const availableInstruments = getAvailableInstruments();

  return (
    <div style={{
      width: '300px',
      padding: '1rem',
      borderRight: '1px solid #eee',
      backgroundColor: '#fafafa',
      height: 'fit-content',
      position: 'sticky',
      top: '1rem'
    }}>
      {/* Header */}
      <div style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        marginBottom: '1rem',
        paddingBottom: '0.5rem',
        borderBottom: '1px solid #ddd'
      }}>
        <h4 style={{ 
          margin: 0, 
          fontSize: 'var(--font-2xl)', 
          fontWeight: '600' 
        }}>
          Filters
          {activeCount > 0 && (
            <span style={{
              marginLeft: '0.5rem',
              fontSize: 'var(--font-sm)',
              backgroundColor: '#3182ce',
              color: 'white',
              padding: '0.2rem 0.4rem',
              borderRadius: '10px',
              fontWeight: 'normal'
            }}>
              {activeCount}
            </span>
          )}
        </h4>
        <button
          onClick={clearAllFilters}
          style={{
            background: 'none',
            border: 'none',
            color: activeCount > 0 ? '#3182ce' : 'transparent',
            cursor: activeCount > 0 ? 'pointer' : 'default',
            fontSize: 'var(--font-sm)',
            textDecoration: activeCount > 0 ? 'underline' : 'none',
            opacity: activeCount > 0 ? 1 : 0,
            pointerEvents: activeCount > 0 ? 'auto' : 'none'
          }}
        >
          Clear all
        </button>
      </div>

      {/* Include Unreviewed Toggle */}
      {onToggleUnvalidated && (
        <div style={{ marginBottom: '1rem', paddingBottom: '0.75rem', borderBottom: '1px solid #eee' }}>
          <label style={{
            display: 'flex',
            alignItems: 'center',
            cursor: 'pointer',
            fontSize: 'var(--font-sm)',
            color: '#555',
          }}>
            <input
              type="checkbox"
              checked={includeUnvalidated}
              onChange={(e) => onToggleUnvalidated(e.target.checked)}
              style={{ marginRight: '0.5rem' }}
            />
            Include unreviewed observations
          </label>
        </div>
      )}

      {/* Date Range Section */}
      <div style={{ marginBottom: '1.5rem' }}>
        <button
          onClick={() => toggleSection('dates')}
          style={{
            background: 'none',
            border: 'none',
            padding: 0,
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            fontSize: 'var(--font-lg)',
            fontWeight: '600',
            marginBottom: '0.5rem',
            width: '100%',
            textAlign: 'left'
          }}
        >
          <span style={{
            marginRight: '0.5rem',
            transform: collapsed.dates ? 'rotate(-90deg)' : 'rotate(0deg)',
            transition: 'transform 0.2s'
          }}>
            ▼
          </span>
          Observation Time Range
        </button>

        {!collapsed.dates && (
          <div style={{ paddingLeft: '1rem' }}>
            <div style={{ marginBottom: '0.5rem' }}>
              <label style={{
                display: 'block',
                fontSize: 'var(--font-sm)',
                marginBottom: '0.2rem',
                color: '#666'
              }}>
                Start Date
              </label>
              <input
                type="date"
                value={localStart}
                onChange={(e) => handleDateLocalChange('start_date', e.target.value)}
                onBlur={commitDateRangeChange}
                onKeyDown={(e) => { if (e.key === 'Enter') commitDateRangeChange(); }}
                style={{
                  width: '100%',
                  padding: '0.3rem',
                  border: '1px solid #ccc',
                  borderRadius: '3px',
                  fontSize: 'var(--font-sm)'
                }}
              />
            </div>
            <div style={{ marginBottom: '0.5rem' }}>
              <label style={{
                display: 'block',
                fontSize: 'var(--font-sm)',
                marginBottom: '0.2rem',
                color: '#666'
              }}>
                End Date
              </label>
              <input
                type="date"
                value={localEnd}
                onChange={(e) => handleDateLocalChange('end_date', e.target.value)}
                onBlur={commitDateRangeChange}
                onKeyDown={(e) => { if (e.key === 'Enter') commitDateRangeChange(); }}
                style={{
                  width: '100%',
                  padding: '0.3rem',
                  border: '1px solid #ccc',
                  borderRadius: '3px',
                  fontSize: 'var(--font-sm)'
                }}
              />
            </div>
            {filterOptions?.date_range && (
              <div style={{
                fontSize: 'var(--font-xs)',
                color: '#999',
                marginTop: '0.3rem'
              }}>
                Available: {new Date(filterOptions.date_range.earliest).getUTCFullYear()} - {new Date(filterOptions.date_range.latest).getUTCFullYear()}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Missions & Instruments Section */}
      <div style={{ marginBottom: '1.5rem' }}>
        <button
          onClick={() => toggleSection('missions')}
          style={{
            background: 'none',
            border: 'none',
            padding: 0,
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            fontSize: 'var(--font-lg)',
            fontWeight: '600',
            marginBottom: '0.5rem',
            width: '100%',
            textAlign: 'left'
          }}
        >
          <span style={{
            marginRight: '0.5rem',
            transform: collapsed.missions ? 'rotate(-90deg)' : 'rotate(0deg)',
            transition: 'transform 0.2s'
          }}>
            ▼
          </span>
          {hasDatasourceGroups ? 'Data Systems' : 'Missions & Instruments'}
        </button>

        {!collapsed.missions && (
          <div style={{ paddingLeft: '0.5rem' }}>
            {hasDatasourceGroups ? (
              // Grouped by datasource > mission > instruments
              Object.entries(filterOptions.missions_by_datasource).map(([dsSlug, dsGroup]) => {
                const isDsExpanded = !!expandedDatasources[dsSlug];
                return (
                <div key={dsSlug} style={{ marginBottom: '1rem' }}>
                  <button
                    onClick={() => setExpandedDatasources(prev => ({ ...prev, [dsSlug]: !prev[dsSlug] }))}
                    style={{
                      background: 'none',
                      border: 'none',
                      padding: 0,
                      cursor: 'pointer',
                      display: 'flex',
                      alignItems: 'flex-start',
                      width: '100%',
                      textAlign: 'left',
                      fontSize: 'var(--font-sm)',
                      fontWeight: '700',
                      color: '#555',
                      marginBottom: '0.4rem',
                      textTransform: 'uppercase',
                      letterSpacing: '0.5px',
                      borderBottom: '1px solid #e0e0e0',
                      paddingBottom: '0.2rem'
                    }}
                  >
                    <span style={{
                      marginRight: '0.4rem',
                      marginTop: '0.15em',
                      fontSize: 'var(--font-xs)',
                      transform: isDsExpanded ? 'rotate(0deg)' : 'rotate(-90deg)',
                      transition: 'transform 0.15s',
                      display: 'inline-block',
                    }}>
                      ▼
                    </span>
                    <span style={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
                      <span>
                        {dsSlug.toUpperCase()}
                        <span style={{
                          fontWeight: '400',
                          color: '#999',
                          fontSize: 'var(--font-xs)',
                          textTransform: 'none',
                          letterSpacing: 'normal',
                          marginLeft: '0.4rem',
                        }}>
                          {dsGroup.missions.length} mission{dsGroup.missions.length !== 1 ? 's' : ''}
                        </span>
                      </span>
                      <span style={{
                        fontWeight: '400',
                        color: '#aaa',
                        fontSize: 'var(--font-xs)',
                        textTransform: 'none',
                        letterSpacing: 'normal',
                      }}>
                        {dsGroup.datasource_name}
                      </span>
                    </span>
                  </button>
                  {isDsExpanded && (() => {
                    const isShowingAll = !!showAllMissions[dsSlug];
                    const visibleMissions = isShowingAll ? dsGroup.missions : dsGroup.missions.slice(0, MISSION_PREVIEW_COUNT);
                    const hiddenCount = dsGroup.missions.length - MISSION_PREVIEW_COUNT;
                    return (
                      <>
                        {visibleMissions.map(mission => {
                          const missionInstruments = availableInstruments[mission.key] || [];
                          const isExpanded = !!expandedMissions[mission.key];
                          const missionChecked = getMissionCheckState(mission.key);
                          return (
                            <div key={mission.key} style={{ marginBottom: '0.3rem', marginLeft: '0.5rem' }}>
                              <div style={{ display: 'flex', alignItems: 'center', marginBottom: '0.2rem' }}>
                                <input
                                  type="checkbox"
                                  checked={missionChecked}
                                  onChange={(e) => handleMissionChange(mission.key, e.target.checked)}
                                  style={{ marginRight: '0.5rem' }}
                                />
                                <span
                                  onClick={() => setExpandedMissions(prev => ({ ...prev, [mission.key]: !prev[mission.key] }))}
                                  style={{
                                    flex: 1,
                                    cursor: 'pointer',
                                    fontSize: 'var(--font-base)',
                                    fontWeight: '600',
                                    display: 'flex',
                                    alignItems: 'center',
                                  }}
                                >
                                  {missionInstruments.length > 0 && (
                                    <span style={{
                                      marginRight: '0.3rem',
                                      fontSize: 'var(--font-xs)',
                                      transform: isExpanded ? 'rotate(0deg)' : 'rotate(-90deg)',
                                      transition: 'transform 0.15s',
                                      display: 'inline-block',
                                    }}>
                                      ▼
                                    </span>
                                  )}
                                  {mission.display_name || mission.short_name}
                                </span>
                                <span style={{
                                  fontSize: 'var(--font-sm)',
                                  color: '#666',
                                  marginLeft: '0.5rem',
                                  fontWeight: 'normal'
                                }}>
                                  ({mission.paper_count})
                                </span>
                              </div>
                              {isExpanded && missionInstruments.map(instrument => (
                                <label
                                  key={`${mission.key}-${instrument.short_name}`}
                                  style={{
                                    display: 'flex',
                                    alignItems: 'center',
                                    marginBottom: '0.15rem',
                                    marginLeft: '1.8rem',
                                    cursor: 'pointer',
                                    fontSize: 'var(--font-sm)',
                                    color: '#444'
                                  }}
                                >
                                  <input
                                    type="checkbox"
                                    checked={(filters.instruments || []).includes(instrument.short_name)}
                                    onChange={(e) => handleInstrumentChange(instrument.short_name, e.target.checked)}
                                    style={{ marginRight: '0.5rem' }}
                                  />
                                  <span style={{ flex: 1 }}>
                                    {instrument.display_name || instrument.short_name}
                                  </span>
                                  <span style={{
                                    fontSize: 'var(--font-xs)',
                                    color: '#888',
                                    marginLeft: '0.5rem'
                                  }}>
                                    ({instrument.paper_count})
                                  </span>
                                </label>
                              ))}
                            </div>
                          );
                        })}
                        {hiddenCount > 0 && (
                          <button
                            onClick={() => setShowAllMissions(prev => ({ ...prev, [dsSlug]: !prev[dsSlug] }))}
                            style={{
                              background: 'none',
                              border: 'none',
                              padding: '0.2rem 0 0.2rem 0.5rem',
                              cursor: 'pointer',
                              fontSize: 'var(--font-xs)',
                              color: '#3182ce',
                              fontStyle: 'italic',
                            }}
                          >
                            {isShowingAll ? 'Show fewer' : `Show all ${dsGroup.missions.length} missions`}
                          </button>
                        )}
                      </>
                    );
                  })()}
                </div>
                );
              })
            ) : (
              // Fallback: flat mission list with instruments nested
              filterOptions?.missions?.map(mission => {
                const missionInstruments = (filterOptions?.instruments_by_mission || {})[mission.short_name] || [];
                const isExpanded = !!expandedMissions[mission.short_name];
                const missionChecked = getMissionCheckState(mission.short_name);
                return (
                  <div key={mission.short_name} style={{ marginBottom: '0.3rem' }}>
                    <div style={{ display: 'flex', alignItems: 'center', marginBottom: '0.2rem' }}>
                      <input
                        type="checkbox"
                        checked={missionChecked}
                        onChange={(e) => handleMissionChange(mission.short_name, e.target.checked)}
                        style={{ marginRight: '0.5rem' }}
                      />
                      <span
                        onClick={() => setExpandedMissions(prev => ({ ...prev, [mission.short_name]: !prev[mission.short_name] }))}
                        style={{
                          flex: 1,
                          cursor: 'pointer',
                          fontSize: 'var(--font-base)',
                          fontWeight: '600',
                          display: 'flex',
                          alignItems: 'center',
                        }}
                      >
                        {missionInstruments.length > 0 && (
                          <span style={{
                            marginRight: '0.3rem',
                            fontSize: 'var(--font-xs)',
                            transform: isExpanded ? 'rotate(0deg)' : 'rotate(-90deg)',
                            transition: 'transform 0.15s',
                            display: 'inline-block',
                          }}>
                            ▼
                          </span>
                        )}
                        {mission.display_name || mission.short_name}
                      </span>
                      <span style={{
                        fontSize: 'var(--font-sm)',
                        color: '#666',
                        marginLeft: '0.5rem',
                        fontWeight: 'normal'
                      }}>
                        ({mission.paper_count})
                      </span>
                    </div>
                    {isExpanded && missionInstruments.map(instrument => (
                      <label
                        key={`${mission.short_name}-${instrument.short_name}`}
                        style={{
                          display: 'flex',
                          alignItems: 'center',
                          marginBottom: '0.15rem',
                          marginLeft: '1.8rem',
                          cursor: 'pointer',
                          fontSize: 'var(--font-sm)',
                          color: '#444'
                        }}
                      >
                        <input
                          type="checkbox"
                          checked={(filters.instruments || []).includes(instrument.short_name)}
                          onChange={(e) => handleInstrumentChange(instrument.short_name, e.target.checked)}
                          style={{ marginRight: '0.5rem' }}
                        />
                        <span style={{ flex: 1 }}>
                          {instrument.display_name || instrument.short_name}
                        </span>
                        <span style={{
                          fontSize: 'var(--font-xs)',
                          color: '#888',
                          marginLeft: '0.5rem'
                        }}>
                          ({instrument.paper_count})
                        </span>
                      </label>
                    ))}
                  </div>
                );
              })
            )}
          </div>
        )}
      </div>

      {/* Validation Status Section (optional) */}
      {!hideValidationStatus && (
        <div style={{ marginBottom: '1.5rem' }}>
          <button
            onClick={() => toggleSection('status')}
            style={{
              background: 'none',
              border: 'none',
              padding: 0,
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              fontSize: 'var(--font-lg)',
              fontWeight: '600',
              marginBottom: '0.5rem',
              width: '100%',
              textAlign: 'left'
            }}
          >
            <span style={{ 
              marginRight: '0.5rem',
              transform: collapsed.status ? 'rotate(-90deg)' : 'rotate(0deg)',
              transition: 'transform 0.2s'
            }}>
              ▼
            </span>
            Validation Status
          </button>
          
          {!collapsed.status && (
            <div style={{ paddingLeft: '1rem' }}>
              {filterOptions?.validation_statuses?.map(statusInfo => (
                <label 
                  key={statusInfo.status}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    marginBottom: '0.3rem',
                    cursor: 'pointer',
                    fontSize: 'var(--font-base)'
                  }}
                >
                  <input
                    type="checkbox"
                    checked={(filters.validation_status || []).includes(statusInfo.status)}
                    onChange={(e) => handleStatusChange(statusInfo.status, e.target.checked)}
                    style={{ marginRight: '0.5rem' }}
                  />
                  <span style={{ flex: 1, textTransform: 'capitalize' }}>
                    {statusInfo.status.replace('_', ' ')}
                  </span>
                  <span style={{ 
                    fontSize: 'var(--font-sm)', 
                    color: '#666',
                    marginLeft: '0.5rem'
                  }}>
                    ({statusInfo.paper_count})
                  </span>
                </label>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
