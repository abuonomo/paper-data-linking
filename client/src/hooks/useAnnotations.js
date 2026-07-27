// src/hooks/useAnnotations.js
import { useState, useEffect } from 'react';
import { fetchPaperPDFAnnotations } from '../services/apiServices';

// Field type configuration
const fieldConfig = {
  general_comments: {
    displayName: 'General Description',
    valueProperty: 'value',
    parentProperty: 'general_comments',
  },
  detectors: {
    displayName: 'Detectors',
    valueProperty: 'values',
    parentProperty: 'detectors',
  },
  start_time: {
    displayName: 'Start Date',
    valueProperty: 'value',
    parentProperty: 'start_time',
    claimType: 'date_range',
  },
  end_time: {
    displayName: 'End Date',
    valueProperty: 'value',
    parentProperty: 'end_time',
    claimType: 'date_range',
  },
  wavelengths: {
    displayName: 'Wavelengths',
    valueProperty: 'values',
    parentProperty: 'wavelengths',
  },
  physical_observable: {
    displayName: 'Physical Observable',
    valueProperty: 'value',
    parentProperty: 'physical_observable',
  },
  spacecraft: {
    displayName: 'Spacecraft',
    valueProperty: null, // Direct value
    parentProperty: null, // Direct property
  }
};

// Unique ID generator with a counter for guarantee uniqueness.
let claimCounter = 0;
function generateClaimId(instrumentName, periodDescription, claimType, value) {
  return `${instrumentName}|${periodDescription || 'general'}|${claimType}|${value}|${claimCounter++}`.replace(/\s+/g, '_');
}

export const useAnnotations = (jsonUrl, bibcode = null) => {
  const [jsonData, setJsonData] = useState(null);
  const [annotations, setAnnotations] = useState([]);
  const [claims, setClaims] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    // Skip if no data source provided
    if (!jsonUrl && !bibcode) {
      setIsLoading(false);
      return;
    }

    const fetchData = async () => {
      try {
        setIsLoading(true);
        let data;
        
        // Try database-backed API first if bibcode is provided
        if (bibcode) {
          console.log('Fetching PDF annotations from database for bibcode:', bibcode);
          try {
            data = await fetchPaperPDFAnnotations(bibcode);
            console.log('Successfully fetched database annotations:', data);
          } catch (dbError) {
            console.log('No database annotations found, falling back to static JSON');
            // Fall back to static JSON if database has no data
            if (jsonUrl) {
              const staticResponse = await fetch(jsonUrl);
              if (!staticResponse.ok) {
                throw new Error(`No annotations found for ${bibcode}`);
              }
              data = await staticResponse.json();
            } else {
              throw new Error(`No annotations found for ${bibcode}`);
            }
          }
        } else {
          // Use static JSON file
          console.log('Fetching annotations from static JSON:', jsonUrl);
          const response = await fetch(jsonUrl);
          if (!response.ok) {
            throw new Error(`HTTP error ${response.status}`);
          }
          data = await response.json();
        }

        setJsonData(data);

        // Process annotations
        const extractedAnnotations = extractAnnotationsFromData(data);
        setAnnotations(extractedAnnotations);

        // Process claims
        const extractedClaims = extractClaimsFromData(data);
        setClaims(extractedClaims);

        setIsLoading(false);
      } catch (err) {
        console.error('Error fetching annotation data:', err);
        setError(err.message);
        setIsLoading(false);
      }
    };

    fetchData();
  }, [jsonUrl, bibcode]);

  // Extract annotations from the JSON data
  const extractAnnotationsFromData = (data) => {
    console.log('Starting annotation extraction from data:', data);
    const annotations = [];

    if (!data?.instrumentation_details) {
      console.warn('No instrumentation_details found in JSON data');
      return annotations;
    }

    console.log(`Found ${data.instrumentation_details.length} instruments in data`);

    data.instrumentation_details.forEach((instrument, instIndex) => {
      console.log(`Processing instrument ${instIndex + 1}: ${instrument.instrument_name}`);

      // Process all possible fields that might have pdf_locations
      Object.keys(fieldConfig).forEach(fieldType => {
        const config = fieldConfig[fieldType];

        // Skip direct properties
        if (!config.parentProperty) return;

        const fieldObj = instrument[config.parentProperty];
        if (!fieldObj) {
          console.log(`Field ${fieldType} not found in instrument ${instrument.instrument_name}`);
          return;
        }

        // Check for pdf_locations
        if (!fieldObj.pdf_locations || !Array.isArray(fieldObj.pdf_locations)) {
          console.log(`No pdf_locations for ${fieldType} in instrument ${instrument.instrument_name}`);
          return;
        }

        console.log(`Found ${fieldObj.pdf_locations.length} pdf_locations for ${fieldType}`);

        // Process each location
        fieldObj.pdf_locations.forEach(loc => {
          if (!loc.page_number || !Number.isFinite(loc.x0) || !Number.isFinite(loc.y0) ||
              !Number.isFinite(loc.x1) || !Number.isFinite(loc.y1)) {
            console.warn(`Invalid coordinates in pdf_location for ${fieldType}:`, loc);
            return;
          }

          const tag = `${instrument.instrument_name}|${fieldType}`;

          annotations.push({
            pageNumber: loc.page_number,
            pdfRect: [loc.x0, loc.y0, loc.x1, loc.y1],
            tag,
            fieldType,
            instrumentName: instrument.instrument_name,
            fieldValue: getFieldValue(instrument, fieldType, config),
            excerpt: fieldObj.location?.excerpt
          });

          console.log(`Added annotation for ${fieldType} on page ${loc.page_number} at [${loc.x0}, ${loc.y0}, ${loc.x1}, ${loc.y1}]`);
        });
      });

      // Process data collection periods
      if (instrument.data_collection_periods && Array.isArray(instrument.data_collection_periods)) {
        console.log(`Processing ${instrument.data_collection_periods.length} data collection periods`);

        instrument.data_collection_periods.forEach((period, periodIndex) => {
          console.log(`Processing period ${periodIndex + 1}: ${period.description}`);

          // Create combined object with parent properties
          const combined = {
            ...period,
            instrument_name: instrument.instrument_name,
            spacecraft: instrument.spacecraft
          };

          // Process period-specific fields
          ['start_time', 'end_time', 'wavelengths', 'physical_observable'].forEach(fieldType => {
            const config = fieldConfig[fieldType];
            if (!config) return;

            const fieldObj = combined[config.parentProperty];
            if (!fieldObj) {
              console.log(`Field ${fieldType} not found in period ${period.description}`);
              return;
            }

            // Check for pdf_locations
            if (!fieldObj.pdf_locations || !Array.isArray(fieldObj.pdf_locations)) {
              console.log(`No pdf_locations for ${fieldType} in period ${period.description}`);
              return;
            }

            console.log(`Found ${fieldObj.pdf_locations.length} pdf_locations for ${fieldType} in period`);

            // Process each location
            fieldObj.pdf_locations.forEach(loc => {
              if (!loc.page_number || !Number.isFinite(loc.x0) || !Number.isFinite(loc.y0) ||
                  !Number.isFinite(loc.x1) || !Number.isFinite(loc.y1)) {
                console.warn(`Invalid coordinates in pdf_location for period ${fieldType}:`, loc);
                return;
              }

              const tag = `${instrument.instrument_name}|${period.description}|${fieldType}`;

              annotations.push({
                pageNumber: loc.page_number,
                pdfRect: [loc.x0, loc.y0, loc.x1, loc.y1],
                tag,
                fieldType,
                instrumentName: instrument.instrument_name,
                periodDescription: period.description,
                fieldValue: getFieldValue(combined, fieldType, config),
                excerpt: fieldObj.location?.excerpt
              });

              console.log(`Added period annotation for ${fieldType} on page ${loc.page_number} at [${loc.x0}, ${loc.y0}, ${loc.x1}, ${loc.y1}]`);
            });
          });
        });
      }
    });

    console.log(`Total annotations extracted: ${annotations.length}`);
    return annotations;
  };

  // Extract claims from the JSON data with unique IDs
  const extractClaimsFromData = (data) => {
    const claims = [];

    if (!data?.instrumentation_details || !Array.isArray(data.instrumentation_details)) {
      console.warn('No instrumentation_details found in JSON data');
      return claims;
    }

    // Process each instrument
    data.instrumentation_details.forEach(instrument => {
      // --- Instrument-level claims ---
      // Add spacecraft claim if available
      if (instrument.spacecraft) {
        const tag = `${instrument.instrument_name}|spacecraft`;
        const id = generateClaimId(instrument.instrument_name, null, 'spacecraft', instrument.spacecraft);
        claims.push({
          id,
          type: 'spacecraft',
          label: fieldConfig.spacecraft.displayName,
          value: instrument.spacecraft,
          instrumentName: instrument.instrument_name,
          periodDescription: null,
          excerpt: null,
          tag: tag,
        });
      }

      // Process other fields on the instrument (skip spacecraft and period fields)
      Object.keys(fieldConfig).forEach(fieldType => {
        if (fieldType === 'spacecraft' || ['start_time', 'end_time', 'wavelengths', 'physical_observable'].includes(fieldType)) {
          return;
        }
        const config = fieldConfig[fieldType];
        const fieldValue = getFieldValue(instrument, fieldType, config);
        if (fieldValue) {
          let excerpt = null;
          if (config.parentProperty && instrument[config.parentProperty] &&
              instrument[config.parentProperty].location &&
              instrument[config.parentProperty].location.excerpt) {
            excerpt = instrument[config.parentProperty].location.excerpt;
          }
          const tag = `${instrument.instrument_name}|${fieldType}`;
          const id = generateClaimId(instrument.instrument_name, null, fieldType, fieldValue);
          claims.push({
            id,
            type: fieldType,
            label: config.displayName,
            value: fieldValue,
            instrumentName: instrument.instrument_name,
            periodDescription: null,
            excerpt: excerpt,
            tag: tag,
          });
        }
      });

      // --- Period-specific claims ---
      if (instrument.data_collection_periods && Array.isArray(instrument.data_collection_periods)) {
        instrument.data_collection_periods.forEach(period => {
          // Process start_time claim
          const startConfig = fieldConfig.start_time;
          const startValue = getFieldValue(period, 'start_time', startConfig);
          if (startValue) {
            let excerpt = null;
            if (period.start_time && period.start_time.location && period.start_time.location.excerpt) {
              excerpt = period.start_time.location.excerpt;
            }
            const tag = `${instrument.instrument_name}|${period.description}|start_time`;
            const id = generateClaimId(instrument.instrument_name, period.description, 'start_time', startValue);
            claims.push({
              id,
              type: 'start_time',
              label: startConfig.displayName,
              value: startValue,
              instrumentName: instrument.instrument_name,
              periodDescription: period.description,
              excerpt: excerpt,
              tag: tag,
            });
          }

          // Process end_time claim
          const endConfig = fieldConfig.end_time;
          const endValue = getFieldValue(period, 'end_time', endConfig);
          if (endValue) {
            let excerpt = null;
            if (period.end_time && period.end_time.location && period.end_time.location.excerpt) {
              excerpt = period.end_time.location.excerpt;
            }
            const tag = `${instrument.instrument_name}|${period.description}|end_time`;
            const id = generateClaimId(instrument.instrument_name, period.description, 'end_time', endValue);
            claims.push({
              id,
              type: 'end_time',
              label: endConfig.displayName,
              value: endValue,
              instrumentName: instrument.instrument_name,
              periodDescription: period.description,
              excerpt: excerpt,
              tag: tag,
            });
          }

          // Process additional period fields (wavelengths and physical_observable)
          ['wavelengths', 'physical_observable'].forEach(fieldType => {
            const config = fieldConfig[fieldType];
            const value = getFieldValue(period, fieldType, config);
            if (value) {
              let excerpt = null;
              if (period[config.parentProperty] &&
                  period[config.parentProperty].location &&
                  period[config.parentProperty].location.excerpt) {
                excerpt = period[config.parentProperty].location.excerpt;
              }
              const tag = `${instrument.instrument_name}|${period.description}|${fieldType}`;
              const id = generateClaimId(instrument.instrument_name, period.description, fieldType, value);
              claims.push({
                id,
                type: fieldType,
                label: config.displayName,
                value: value,
                instrumentName: instrument.instrument_name,
                periodDescription: period.description,
                excerpt: excerpt,
                tag: tag,
              });
            }
          });
        });
      }
    });

    return claims;
  };

  // Helper function to get field value
  const getFieldValue = (obj, fieldType, config) => {
    if (!obj) return null;

    // Direct property
    if (!config.parentProperty) {
      return obj[fieldType];
    }

    // Nested property
    const parentProp = obj[config.parentProperty];
    if (!parentProp) return null;

    if (config.valueProperty === 'value' && parentProp.value) {
      return parentProp.value;
    }

    if (config.valueProperty === 'values' && parentProp.values) {
      return Array.isArray(parentProp.values)
        ? parentProp.values.join(', ')
        : parentProp.values;
    }

    return null;
  };

  return {
    jsonData,
    annotations,
    claims,
    isLoading,
    error
  };
};
