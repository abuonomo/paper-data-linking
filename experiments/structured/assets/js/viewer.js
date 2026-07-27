// Global configuration
const scale = 1.5;
pdfjsLib.GlobalWorkerOptions.workerSrc = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/2.16.105/pdf.worker.min.js';

// URLs for PDF and JSON files - using relative paths
const pdfUrl = '../pdfs/' + bibcode + '.pdf';
const jsonUrl = '../pdfs/' + bibcode + '_annotated_with_locations.json';
const validationStateKey = 'pdf_validation_state_' + bibcode;

// Array to store all annotations and validation status
let annotations = [];
let jsonData = null;
let validationState = {};

// Field type configuration - centralized mapping of field properties
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

// Common utility functions

// Safely get a value from a nested object/array
function getNestedValue(obj, key, defaultValue = '') {
  if (!obj) return defaultValue;

  // Check if it's a direct property
  if (key === null) return obj;

  // For array values, join them with commas
  if (obj[key] && Array.isArray(obj[key])) {
    return obj[key].join(', ');
  }

  // If the property exists directly
  if (obj[key] !== undefined) return obj[key];

  // For nested structures like obj.key.value or obj.key.values
  if (obj[key + 's']) return Array.isArray(obj[key + 's']) ? obj[key + 's'].join(', ') : obj[key + 's'];

  // Nested value with obj.key.value
  if (obj[key] && obj[key].value !== undefined) return obj[key].value;

  // Nested value with obj.key.values
  if (obj[key] && obj[key].values) {
    return Array.isArray(obj[key].values) ? obj[key].values.join(', ') : obj[key].values;
  }

  return defaultValue;
}

// Load validation state from localStorage if available
function loadValidationState() {
  const savedState = localStorage.getItem(validationStateKey);
  if (savedState) {
    try {
      validationState = JSON.parse(savedState);
    } catch (e) {
      console.error('Error loading validation state:', e);
      validationState = {};
    }
  }
}

// Save validation state to localStorage
function saveValidationState() {
  localStorage.setItem(validationStateKey, JSON.stringify(validationState));
  alert('Validation state saved successfully!');
}

// Generate a unique ID for each claim to track its validation state
function generateClaimId(instrumentName, periodDescription, claimType, value) {
  return `${instrumentName}|${periodDescription || 'general'}|${claimType}|${value}`.replace(/\s+/g, '_');
}

// Generate a tag to connect claims with annotations
function generateTag(obj, searchKey) {
  if (obj.instrument_name) {
    return obj.instrument_name + '|' + searchKey;
  } else if (obj.description) {
    return obj.description + '|' + searchKey;
  }
  return searchKey;
}

// Get claim type from field type
function getClaimType(fieldType) {
  return fieldConfig[fieldType]?.claimType || fieldType;
}

// Replace the existing createValidationSidebar function
function createValidationSidebar(data) {
  const instrumentsList = document.getElementById('instruments-list');
  instrumentsList.innerHTML = '';

  let allClaims = [];
  let totalClaims = 0;

  if (!data || !data.instrumentation_details || !Array.isArray(data.instrumentation_details)) {
    instrumentsList.innerHTML = '<p>No instrumentation data available.</p>';
    return;
  }

  // First, collect all claims into a flat array structure
  data.instrumentation_details.forEach(instrument => {
    // Add spacecraft claim if it exists
    if (instrument.spacecraft) {
      allClaims.push({
        type: 'spacecraft',
        label: 'Spacecraft',
        value: instrument.spacecraft,
        instrumentName: instrument.instrument_name,
        periodDescription: null,
        excerpt: null,
        fieldObj: null
      });
    }

    // Add other general instrument claims
    for (const [fieldType, config] of Object.entries(fieldConfig)) {
      // Skip spacecraft (already handled) and fields used in data collection periods
      if (fieldType === 'spacecraft' || ['start_time', 'end_time', 'wavelengths', 'physical_observable'].includes(fieldType)) {
        continue;
      }

      const fieldValue = getFieldValue(instrument, fieldType);

      if (fieldValue) {
        // Get excerpt if available
        let excerpt = null;
        let fieldObj = null;

        if (config.parentProperty) {
          fieldObj = instrument[config.parentProperty];
          if (fieldObj && fieldObj.location && fieldObj.location.excerpt) {
            excerpt = fieldObj.location.excerpt;
          }
        }

        allClaims.push({
          type: fieldType,
          label: config.displayName,
          value: fieldValue,
          instrumentName: instrument.instrument_name,
          periodDescription: null,
          excerpt: excerpt,
          fieldObj: fieldObj
        });
      }
    }

    // Process data collection periods
    if (instrument.data_collection_periods && Array.isArray(instrument.data_collection_periods)) {
      instrument.data_collection_periods.forEach((period) => {
        // Process date range
        const startDate = getFieldValue(period, 'start_time') || 'Unknown';
        const endDate = getFieldValue(period, 'end_time') || 'Unknown';

        // Process start time if available
        if (startDate !== 'Unknown') {
          let startExcerpt = (period.start_time && period.start_time.location && period.start_time.location.excerpt) || null;
          allClaims.push({
            type: 'start_time',
            label: 'Start Date',
            value: startDate,
            instrumentName: instrument.instrument_name,
            periodDescription: period.description,
            excerpt: startExcerpt,
            fieldObj: period.start_time
          });
        }

        // Process end time if available
        if (endDate !== 'Unknown') {
          let endExcerpt = (period.end_time && period.end_time.location && period.end_time.location.excerpt) || null;
          allClaims.push({
            type: 'end_time',
            label: 'End Date',
            value: endDate,
            instrumentName: instrument.instrument_name,
            periodDescription: period.description,
            excerpt: endExcerpt,
            fieldObj: period.end_time
          });
        }


        // Process other period fields (wavelengths, physical_observable)
        ['wavelengths', 'physical_observable'].forEach(fieldType => {
          const fieldValue = getFieldValue(period, fieldType);

          if (fieldValue) {
            let excerpt = null;
            let fieldObj = period[fieldConfig[fieldType].parentProperty];

            if (fieldObj && fieldObj.location && fieldObj.location.excerpt) {
              excerpt = fieldObj.location.excerpt;
            }

            allClaims.push({
              type: fieldType,
              label: fieldConfig[fieldType].displayName,
              value: fieldValue,
              instrumentName: instrument.instrument_name,
              periodDescription: period.description,
              excerpt: excerpt,
              fieldObj: fieldObj
            });
          }
        });
      });
    }
  });

  // Now create the flattened, direct claim UI
  const claimsContainer = document.createElement('div');
  claimsContainer.className = 'claims-container';

  // Sort claims by instrument name first, then by type
//  allClaims.sort((a, b) => {
//    if (a.instrumentName !== b.instrumentName) {
//      return a.instrumentName.localeCompare(b.instrumentName);
//    }
//    return a.label.localeCompare(b.label);
//  });

  // Create claim cards for each claim
  allClaims.forEach(claim => {
    const claimCard = createClaimCard(claim);
    claimsContainer.appendChild(claimCard);
    totalClaims++;
  });

  instrumentsList.appendChild(claimsContainer);

  // Update validation stats
  document.getElementById('total-claims').textContent = totalClaims;
  updateValidationStats();
}

// Add this new function for creating claim cards
function createClaimCard(claimData) {
  const { type, label, value, instrumentName, periodDescription, excerpt, fieldObj } = claimData;

  const claimType = getClaimType(type);
  const claimId = generateClaimId(instrumentName, periodDescription, claimType, value);

  // Generate the tag for linking with annotations
  const tag = generateTag({
    instrument_name: instrumentName,
    description: periodDescription
  }, type);

  const claimCard = document.createElement('div');
  claimCard.className = 'claim-card';
  claimCard.dataset.id = claimId;
  claimCard.dataset.tag = tag;

  // Apply saved validation state if exists
  if (validationState[claimId]) {
    claimCard.classList.add(validationState[claimId]);
  }

  // Create header with instrument name and badge
  const headerEl = document.createElement('div');
  headerEl.className = 'claim-card-header';

  const instrumentEl = document.createElement('div');
  instrumentEl.className = 'instrument-name';
  instrumentEl.textContent = 'Instrument: ' + instrumentName;

  headerEl.appendChild(instrumentEl);


  claimCard.appendChild(headerEl);

  // Create claim content
  const contentEl = document.createElement('div');
  contentEl.className = 'claim-card-content';

  // Add period description if available
  if (periodDescription) {
    const periodEl = document.createElement('div');
    periodEl.className = 'period-description';
//    periodEl.textContent = periodDescription;
    periodEl.textContent = 'Period Description: ' + periodDescription;
//    headerEl.appendChild(periodEl);
    contentEl.appendChild(periodEl);
  }

  // Claim label and value
  const claimLabelEl = document.createElement('div');
  claimLabelEl.className = 'claim-card-label';
  claimLabelEl.textContent = label + ': ';

  const claimValueEl = document.createElement('span');
  claimValueEl.className = 'claim-card-value';
  claimValueEl.textContent = value;

  claimLabelEl.appendChild(claimValueEl);
  contentEl.appendChild(claimLabelEl);

  // Add excerpt/quote if available
  if (excerpt) {
    const excerptEl = document.createElement('div');
    excerptEl.className = 'claim-card-quote';
    excerptEl.innerHTML = `<strong>Supporting Quote:</strong> <i class="quote-icon">"</i>${excerpt}<i class="quote-icon">"</i>`;
    contentEl.appendChild(excerptEl);
  }

  claimCard.appendChild(contentEl);

  // Add PDF link if there are related annotations
  const relatedAnnotations = annotations.filter(ann => ann.tag.includes(tag));
  if (relatedAnnotations.length > 0) {
    const linkContainer = document.createElement('div');
    linkContainer.className = 'claim-card-link';

    const pdfLink = document.createElement('button');
    pdfLink.className = 'pdf-link-button';
    pdfLink.innerHTML = '<span class="pdf-icon">📄</span> View in PDF';
    pdfLink.addEventListener('click', () => {
      // Scroll to the first annotation and highlight all related ones
      const firstAnnotation = relatedAnnotations[0];
      const element = document.querySelector(`.annotation-overlay[data-tag*="${tag}"]`);

      if (element) {
        // Remove highlighting from all annotations
        document.querySelectorAll('.annotation-overlay.highlight-all').forEach(el => {
          el.classList.remove('highlight-all');
        });

        // Highlight related annotations
        document.querySelectorAll(`.annotation-overlay[data-tag*="${tag}"]`).forEach(el => {
          el.classList.add('highlight-all');
        });

        // Scroll to the first annotation
        element.scrollIntoView({ behavior: 'smooth', block: 'center' });

        // Display tooltip with details
        showTooltip(firstAnnotation.details, element);
      }
    });

    linkContainer.appendChild(pdfLink);
    claimCard.appendChild(linkContainer);
  }

  // Add validation status if present
  if (validationState[claimId]) {
    const validationStatus = document.createElement('div');
    validationStatus.className = `validation-status status-${validationState[claimId]}`;
    validationStatus.textContent = validationState[claimId] === 'validated' ? '✓ Validated' : '✗ Rejected';
    claimCard.appendChild(validationStatus);
  }

  // Add validation buttons
  const validationButtons = document.createElement('div');
  validationButtons.className = 'validation-buttons';

  const validateButton = document.createElement('button');
  validateButton.className = 'btn btn-validate';
  validateButton.textContent = 'Validate';
  validateButton.addEventListener('click', () => {
    validationState[claimId] = 'validated';
    claimCard.className = 'claim-card validated';
    updateClaimCardStatus(claimCard, 'validated');
    updateValidationStats();
  });

  const rejectButton = document.createElement('button');
  rejectButton.className = 'btn btn-reject';
  rejectButton.textContent = 'Reject';
  rejectButton.addEventListener('click', () => {
    validationState[claimId] = 'rejected';
    claimCard.className = 'claim-card rejected';
    updateClaimCardStatus(claimCard, 'rejected');
    updateValidationStats();
  });

  const resetButton = document.createElement('button');
  resetButton.className = 'btn btn-reset';
  resetButton.textContent = 'Reset';
  resetButton.addEventListener('click', () => {
    delete validationState[claimId];
    claimCard.className = 'claim-card';
    // Remove validation status
    const statusEl = claimCard.querySelector('.validation-status');
    if (statusEl) {
      claimCard.removeChild(statusEl);
    }
    updateValidationStats();
  });

  validationButtons.appendChild(validateButton);
  validationButtons.appendChild(rejectButton);
  validationButtons.appendChild(resetButton);

  claimCard.appendChild(validationButtons);

  return claimCard;
}

// Add this new function for updating claim card status
function updateClaimCardStatus(claimCard, status) {
  // Remove existing status if present
  const existingStatus = claimCard.querySelector('.validation-status');
  if (existingStatus) {
    claimCard.removeChild(existingStatus);
  }

  // Add new status
  const validationStatus = document.createElement('div');
  validationStatus.className = `validation-status status-${status}`;
  validationStatus.textContent = status === 'validated' ? '✓ Validated' : '✗ Rejected';

  // Insert before the validation buttons
  const validationButtons = claimCard.querySelector('.validation-buttons');
  claimCard.insertBefore(validationStatus, validationButtons);
}

// Replace the scrollToSidebarClaim function
function scrollToSidebarClaim(tag) {
  // Find claim cards with matching tag
  const claimCards = document.querySelectorAll(`.claim-card[data-tag*="${tag}"]`);

  if (claimCards.length === 0) {
    return;
  }

  // Get the first matching claim
  const claimCard = claimCards[0];

  // Remove highlight from all claims
  document.querySelectorAll('.claim-card.highlight').forEach(el => {
    el.classList.remove('highlight');
  });

  // Add highlight to this claim
  claimCard.classList.add('highlight');

  // Scroll the sidebar to show this claim
  const sidebar = document.querySelector('#sidebar');
  if (sidebar) {
    // Scroll within the sidebar
    sidebar.scrollTop = claimCard.offsetTop - sidebar.offsetTop - 100;
  } else {
    // Otherwise, just scroll the claim into view
    claimCard.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }

  // Remove highlight after a delay
  setTimeout(() => {
    claimCard.classList.remove('highlight');
  }, 3000);
}

// Helper to get field value in a consistent way
function getFieldValue(obj, fieldType) {
  if (!obj) return null;

  const config = fieldConfig[fieldType];
  if (!config) return null;

  // Direct property (like spacecraft)
  if (config.parentProperty === null) {
    return obj[fieldType];
  }

  // Nested property with value/values
  const parentProp = obj[config.parentProperty];
  if (!parentProp) return null;

  // Get the appropriate value
  if (config.valueProperty === 'value' && parentProp.value) {
    return parentProp.value;
  }

  if (config.valueProperty === 'values' && parentProp.values) {
    return Array.isArray(parentProp.values) ? parentProp.values.join(', ') : parentProp.values;
  }

  // Fallback for direct values
  if (typeof parentProp === 'string' || typeof parentProp === 'number') {
    return parentProp;
  }

  return null;
}

// Create a claim item with validation buttons
function createClaimItem(label, value, instrumentName, periodDescription, fieldType) {
  const claimType = getClaimType(fieldType);
  const claimId = generateClaimId(instrumentName, periodDescription, claimType, value);

  // Generate the tag for linking with annotations
  const tag = generateTag({
    instrument_name: instrumentName,
    description: periodDescription
  }, fieldType);

  const claimItem = document.createElement('div');
  claimItem.className = 'claim-item';
  claimItem.dataset.id = claimId;
  claimItem.dataset.tag = tag; // Add tag for linking with annotations

  // Apply saved validation state if exists
  if (validationState[claimId]) {
    claimItem.className = `claim-item ${validationState[claimId]}`;
  }

  const claimLabel = document.createElement('div');
  claimLabel.className = 'claim-label';
  claimLabel.textContent = label;

  const claimValue = document.createElement('div');
  claimValue.className = 'claim-value';
  claimValue.textContent = value;

  // NEW: Append excerpt if available (using location.excerpt)
  // For top-level fields (like detectors) periodDescription will be null.
  let fieldObj = null;
  const config = fieldConfig[fieldType];
  if (config && config.parentProperty) {
    // If periodDescription is null, we assume this is a top-level field on the instrument.
    if (!periodDescription) {
      const instrument = jsonData.instrumentation_details.find(inst => inst.instrument_name === instrumentName);
      if (instrument) {
        fieldObj = instrument[config.parentProperty];
      }
    } else {
      // For period-specific fields, search within the instrument's data_collection_periods
      const instrument = jsonData.instrumentation_details.find(inst => inst.instrument_name === instrumentName);
      if (instrument && instrument.data_collection_periods) {
        fieldObj = instrument.data_collection_periods.find(period => period.description === periodDescription);
        if (fieldObj) {
          fieldObj = fieldObj[config.parentProperty];
        }
      }
    }
  }

  if (fieldObj && fieldObj.location && fieldObj.location.excerpt) {
    const excerptEl = document.createElement('div');
    excerptEl.className = 'supporting-excerpt';
    excerptEl.textContent = fieldObj.location.excerpt;
    claimItem.appendChild(excerptEl);
  }

  // Add highlight toggle if there are related annotations
  const relatedAnnotations = annotations.filter(ann => ann.tag.includes(tag));

  if (relatedAnnotations.length > 0) {
    const highlightToggle = createHighlightToggle(tag, relatedAnnotations);
    claimLabel.appendChild(highlightToggle);
  }

  // Add validation status if present
  if (validationState[claimId]) {
    const validationStatus = createValidationStatusElement(validationState[claimId]);
    claimItem.appendChild(validationStatus);
  }

  claimItem.appendChild(claimLabel);
  claimItem.appendChild(claimValue);

  // Add validation buttons
  const validationButtons = createValidationButtons(claimId, claimItem);
  claimItem.appendChild(validationButtons);

  return claimItem;
}

// Create validation status element
function createValidationStatusElement(status) {
  const validationStatus = document.createElement('div');
  validationStatus.className = `validation-status status-${status}`;
  validationStatus.textContent = status === 'validated' ? '✓ Validated' : '✗ Rejected';
  return validationStatus;
}

// Create validation buttons
function createValidationButtons(claimId, claimItem) {
  const validationButtons = document.createElement('div');
  validationButtons.className = 'validation-buttons';

  const validateButton = document.createElement('button');
  validateButton.className = 'btn btn-validate';
  validateButton.textContent = 'Validate';
  validateButton.addEventListener('click', () => {
    validationState[claimId] = 'validated';
    claimItem.className = 'claim-item validated';
    updateValidationStatus(claimItem, 'validated');
    updateValidationStats();
  });

  const rejectButton = document.createElement('button');
  rejectButton.className = 'btn btn-reject';
  rejectButton.textContent = 'Reject';
  rejectButton.addEventListener('click', () => {
    validationState[claimId] = 'rejected';
    claimItem.className = 'claim-item rejected';
    updateValidationStatus(claimItem, 'rejected');
    updateValidationStats();
  });

  const resetButton = document.createElement('button');
  resetButton.className = 'btn btn-reset';
  resetButton.textContent = 'Reset';
  resetButton.addEventListener('click', () => {
    delete validationState[claimId];
    claimItem.className = 'claim-item';
    // Remove validation status
    const statusEl = claimItem.querySelector('.validation-status');
    if (statusEl) {
      claimItem.removeChild(statusEl);
    }
    updateValidationStats();
  });

  validationButtons.appendChild(validateButton);
  validationButtons.appendChild(rejectButton);
  validationButtons.appendChild(resetButton);

  return validationButtons;
}

// Create highlight toggle button for claims
function createHighlightToggle(tag, relatedAnnotations) {
  const highlightToggle = document.createElement('span');
  highlightToggle.className = 'highlight-toggle';
  highlightToggle.textContent = 'View in PDF';
  highlightToggle.addEventListener('click', () => {
    // Scroll to the first annotation and highlight all related ones
    const firstAnnotation = relatedAnnotations[0];
    const element = document.querySelector(`.annotation-overlay[data-tag*="${tag}"]`);

    if (element) {
      // Remove highlighting from all annotations
      document.querySelectorAll('.annotation-overlay.highlight-all').forEach(el => {
        el.classList.remove('highlight-all');
      });

      // Highlight related annotations
      document.querySelectorAll(`.annotation-overlay[data-tag*="${tag}"]`).forEach(el => {
        el.classList.add('highlight-all');
      });

      // Scroll to the first annotation
      element.scrollIntoView({ behavior: 'smooth', block: 'center' });

      // Display tooltip with details
      showTooltip(firstAnnotation.details, element);
    }
  });

  return highlightToggle;
}

// Show tooltip with specified content and position
function showTooltip(content, element, duration = 5000) {
  const tooltip = document.getElementById('tooltip');
  if (!tooltip) return;

  tooltip.innerHTML = content;
  tooltip.style.display = 'block';

  const rect = element.getBoundingClientRect();
  tooltip.style.left = (rect.right + 10) + 'px';
  tooltip.style.top = rect.top + 'px';

  // Hide tooltip after specified duration
  if (duration > 0) {
    setTimeout(() => {
      tooltip.style.display = 'none';
    }, duration);
  }
}

// Update validation status element for a claim
function updateValidationStatus(claimItem, status) {
  // Remove existing status if present
  const existingStatus = claimItem.querySelector('.validation-status');
  if (existingStatus) {
    claimItem.removeChild(existingStatus);
  }

  // Add new status
  const validationStatus = createValidationStatusElement(status);

  // Insert at the beginning
  claimItem.insertBefore(validationStatus, claimItem.firstChild);
}

// Update validation statistics
function updateValidationStats() {
  let validatedCount = 0;
  let rejectedCount = 0;

  for (const claimId in validationState) {
    if (validationState[claimId] === 'validated') {
      validatedCount++;
    } else if (validationState[claimId] === 'rejected') {
      rejectedCount++;
    }
  }

  document.getElementById('validated-claims').textContent = validatedCount;
  document.getElementById('rejected-claims').textContent = rejectedCount;

  const totalClaims = parseInt(document.getElementById('total-claims').textContent) || 0;
  const progressPercent = totalClaims > 0 ? ((validatedCount + rejectedCount) / totalClaims * 100) : 0;

  document.getElementById('progress-bar').style.width = `${progressPercent}%`;
}

// Extract annotations from the JSON data
function extractAnnotations(data) {
  if (!data.instrumentation_details || !Array.isArray(data.instrumentation_details)) return;

  // Clear existing annotations
  annotations = [];

  data.instrumentation_details.forEach(instr => {
    // Process all possible fields that might have pdf_locations
    Object.keys(fieldConfig).forEach(fieldType => {
      processFieldAnnotations(instr, fieldType);
    });

    // Process data collection periods
    if (instr.data_collection_periods && Array.isArray(instr.data_collection_periods)) {
      instr.data_collection_periods.forEach(period => {
        // Create combined object with parent properties
        const combined = Object.assign({}, period, {
          instrument_name: instr.instrument_name,
          spacecraft: instr.spacecraft
        });

        // Process period-specific fields
        ['start_time', 'end_time', 'wavelengths', 'physical_observable'].forEach(fieldType => {
          processFieldAnnotations(combined, fieldType);
        });
      });
    }
  });

  // Update the annotation count indicator
  const countIndicator = document.getElementById('annotation-count');
  if (countIndicator) {
    countIndicator.innerHTML = `Annotations: ${annotations.length}`;
  }
}

// Process annotations for a specific field
function processFieldAnnotations(obj, fieldType) {
  const config = fieldConfig[fieldType];
  if (!config) return;

  // Skip direct properties that don't have pdf_locations
  if (config.parentProperty === null) return;

  const fieldObj = obj[config.parentProperty];
  if (!fieldObj) return;

  // Check for pdf_locations
  if (fieldObj.pdf_locations && Array.isArray(fieldObj.pdf_locations)) {
    fieldObj.pdf_locations.forEach(loc => {
      const tag = generateTag(obj, fieldType);
      annotations.push({
        pageNumber: loc.page_number,
        pdfRect: [loc.x0, loc.y0, loc.x1, loc.y1],
        details: buildDetailsString(obj, fieldType),
        tag: tag
      });
    });
  }
}

// Build a details string for tooltip
function buildDetailsString(obj, fieldType) {
  let details = '';

  // Add basic info
  if (obj.instrument_name) {
    details += `<strong>Instrument:</strong> ${obj.instrument_name}<br>`;
  }
  if (obj.spacecraft) {
    details += `<strong>Spacecraft:</strong> ${obj.spacecraft}<br>`;
  }

  // Add period info if available
  if (obj.description) {
    details += `<strong>Data Period:</strong> ${obj.description}<br>`;
  }

  // Add field-specific information
  const config = fieldConfig[fieldType];
  if (config) {
    const fieldValue = getFieldValue(obj, fieldType);
    if (fieldValue) {
      details += `<strong>${config.displayName}:</strong> ${fieldValue}<br>`;
    }
  }

  // Add validation status
  const claimType = getClaimType(fieldType);
  const value = getFieldValue(obj, fieldType) || '';
  const claimId = generateClaimId(obj.instrument_name, obj.description, claimType, value);

  if (validationState[claimId]) {
    const status = validationState[claimId];
    details += `<br><strong>Validation Status:</strong> <span style="color: ${status === 'validated' ? 'green' : 'red'};">
                ${status === 'validated' ? '✓ Validated' : '✗ Rejected'}</span>`;
  }

  // Add supporting quote if available
  const fieldObj = obj[config?.parentProperty];
  if (fieldObj && fieldObj.supporting_quote) {
    details += `<br><strong>Supporting Quote:</strong> ${fieldObj.supporting_quote}<br>`;
  }

  return details;
}

// Load and render the PDF
function loadPdf() {
  const loadingTask = pdfjsLib.getDocument(pdfUrl);
  loadingTask.promise.then(pdf => {
    console.log('PDF loaded with ' + pdf.numPages + ' pages.');
    for (let pageNum = 1; pageNum <= pdf.numPages; pageNum++) {
      renderPage(pdf, pageNum);
    }
  }, function (reason) {
    console.error(reason);
    document.getElementById('pdf-container').innerHTML +=
      `<div style="color: red; padding: 20px;">
        <h2>Error Loading PDF</h2>
        <p>${reason.message}</p>
        <p>Please check that the PDF file exists at: ${pdfUrl}</p>
      </div>`;
  });
}

// Modify your renderPage function in viewer.js
function renderPage(pdf, pageNum) {
  pdf.getPage(pageNum).then(page => {
    const viewport = page.getViewport({ scale: scale });
    const pageContainer = document.createElement('div');
    pageContainer.classList.add('pageContainer');
    pageContainer.style.width = viewport.width + 'px';
    pageContainer.style.height = viewport.height + 'px';
    pageContainer.style.position = 'relative';

    // Create canvas for rendering the page visually
    const canvas = document.createElement('canvas');
    canvas.width = viewport.width;
    canvas.height = viewport.height;
    const context = canvas.getContext('2d');

    // Create text layer div for searchable text
    const textLayerDiv = document.createElement('div');
    textLayerDiv.className = 'textLayer';
    textLayerDiv.style.width = viewport.width + 'px';
    textLayerDiv.style.height = viewport.height + 'px';

    // Add both to page container
    pageContainer.appendChild(canvas);
    pageContainer.appendChild(textLayerDiv);
    document.getElementById('pdf-container').appendChild(pageContainer);

    // Render the page on canvas
    const renderContext = {
      canvasContext: context,
      viewport: viewport
    };

    // Get text content for searchability
    page.getTextContent().then(textContent => {
      // Add annotations first
      page.render(renderContext).promise.then(() => {
        addAnnotationsToPage(pageNum, viewport, pageContainer);
      });

      // Render text layer using the PDF.js viewer components
      const textLayer = new pdfjsViewer.TextLayerBuilder({
        textLayerDiv: textLayerDiv,
        pageIndex: page.pageNumber - 1,
        viewport: viewport
      });

      textLayer.setTextContent(textContent);
      textLayer.render();
    });
  });
}

// Add annotation overlays to a given page
function addAnnotationsToPage(pageNum, viewport, container) {
  const pageAnnotations = annotations.filter(ann => ann.pageNumber === pageNum);

  const unscaledHeight = viewport.height / scale;

  pageAnnotations.forEach(ann => {
    // Convert JSON coordinates (top-left origin) to PDF coordinates (bottom-left origin)
    const flippedRect = [
      ann.pdfRect[0],
      unscaledHeight - ann.pdfRect[3],
      ann.pdfRect[2],
      unscaledHeight - ann.pdfRect[1]
    ];

    // Convert the flipped rectangle to viewport coordinates
    const rect = viewport.convertToViewportRectangle(flippedRect);

    const left = Math.floor(Math.min(rect[0], rect[2]));
    const top = Math.floor(Math.min(rect[1], rect[3]));
    const width = Math.ceil(Math.abs(rect[0] - rect[2]));
    const height = Math.ceil(Math.abs(rect[1] - rect[3]));

    // Create the annotation overlay
    const overlay = createAnnotationOverlay(ann, left, top, width, height);
    container.appendChild(overlay);
  });
}

// Create an annotation overlay element
function createAnnotationOverlay(annotation, left, top, width, height) {
  const overlay = document.createElement('div');
  overlay.classList.add('annotation-overlay');

  // Style the overlay
  overlay.style.backgroundColor = 'rgba(255, 0, 0, 0.3)';
  overlay.style.border = '2px solid red';
  overlay.style.position = 'absolute';
  overlay.style.zIndex = '100';
  overlay.style.cursor = 'pointer';

  overlay.setAttribute('data-tag', annotation.tag);
  overlay.style.left = left + 'px';
  overlay.style.top = top + 'px';
  overlay.style.width = width + 'px';
  overlay.style.height = height + 'px';

  // Add mouse events
  overlay.addEventListener('mouseenter', e => {
    highlightRelatedAnnotations(annotation.tag);
    showTooltipAtEvent(annotation.details, e, 0); // 0 = don't auto-hide
  });

  overlay.addEventListener('mousemove', e => {
    updateTooltipPosition(e);
  });

  overlay.addEventListener('mouseleave', () => {
    unhighlightRelatedAnnotations(annotation.tag);
    hideTooltip();
  });

  // Add click event to scroll to the corresponding claim in the sidebar
  overlay.addEventListener('click', () => {
    scrollToSidebarClaim(annotation.tag);
  });

  return overlay;
}

// Helper functions for annotation interactions

// Highlight all annotations with the same tag
function highlightRelatedAnnotations(tag) {
  document.querySelectorAll(`.annotation-overlay[data-tag="${tag}"]`).forEach(o => {
    o.classList.add('highlight-all');
  });
}

// Remove highlighting from all annotations with the same tag
function unhighlightRelatedAnnotations(tag) {
  document.querySelectorAll(`.annotation-overlay[data-tag="${tag}"]`).forEach(o => {
    o.classList.remove('highlight-all');
  });
}

// Show tooltip at a specific event position
function showTooltipAtEvent(content, event, duration = 5000) {
  const tooltip = document.getElementById('tooltip');
  if (!tooltip) return;

  tooltip.innerHTML = content;
  tooltip.style.display = 'block';
  tooltip.style.left = (event.pageX + 10) + 'px';
  tooltip.style.top = (event.pageY + 10) + 'px';

  // Hide tooltip after specified duration (if > 0)
  if (duration > 0) {
    setTimeout(() => {
      tooltip.style.display = 'none';
    }, duration);
  }
}

// Update tooltip position based on mouse event
function updateTooltipPosition(event) {
  const tooltip = document.getElementById('tooltip');
  if (tooltip && tooltip.style.display !== 'none') {
    tooltip.style.left = (event.pageX + 10) + 'px';
    tooltip.style.top = (event.pageY + 10) + 'px';
  }
}

// Hide the tooltip
function hideTooltip() {
  const tooltip = document.getElementById('tooltip');
  if (tooltip) {
    tooltip.style.display = 'none';
  }
}


// Initialize application
function init() {
  // Set document title
  document.title = `PDF Annotations for ${bibcode}`;

  // Display current bibcode in header
  document.querySelector('h1').textContent = `PDF Annotations for ${bibcode}`;

  // Setup UI elements
  setupUI();

  // Load saved validation state
  loadValidationState();

  // Load JSON and extract annotations
  fetch(jsonUrl)
    .then(response => {
      if (!response.ok) {
        throw new Error(`HTTP error ${response.status}: ${response.statusText}`);
      }
      return response.json();
    })
    .then(data => {
      jsonData = data;

      // First, process the annotations and create the sidebar
      extractAnnotations(data);
      createValidationSidebar(data);

      // Then, load the PDF
      loadPdf();
    })
    .catch(error => {
      console.error("Error loading JSON:", error);
      document.getElementById('pdf-container').innerHTML +=
        `<div style="color: red; padding: 20px;">
          <h2>Error Loading Data</h2>
          <p>${error.message}</p>
          <p>Please check that the following files exist:</p>
          <ul>
            <li>PDF file: ${pdfUrl}</li>
            <li>JSON file: ${jsonUrl}</li>
          </ul>
          <p>Make sure to run the complete annotation process first:</p>
          <code>make process BIBCODE=${bibcode}</code>
        </div>`;
    });
}

// Setup UI elements
function setupUI() {
  // Add tooltip container
  let tooltip = document.createElement('div');
  tooltip.id = 'tooltip';
  tooltip.style.display = 'none';
  document.body.appendChild(tooltip);

  // Add CSS styles
  const style = document.createElement('style');
  style.textContent = `
    .annotation-overlay {
      background-color: rgba(255, 0, 0, 0.3) !important;
      border: 2px solid red !important;
      position: absolute !important;
      z-index: 100 !important;
      cursor: pointer !important;
      transition: background-color 0.3s ease;
    }
    .annotation-overlay:hover {
      background-color: rgba(255, 100, 100, 0.5) !important;
    }
    .annotation-overlay.highlight-all {
      background-color: rgba(255, 255, 0, 0.5) !important;
      border: 2px solid yellow !important;
    }
    #tooltip {
      background-color: rgba(0, 0, 0, 0.8) !important;
      color: white !important;
      padding: 10px !important;
      border-radius: 5px !important;
      z-index: 1001 !important;
      max-width: 400px !important;
      position: absolute !important;
      box-shadow: 0 0 10px rgba(0, 0, 0, 0.5) !important;
    }
    .claim-item.highlight {
      background-color: #ffff99 !important;
      box-shadow: 0 0 10px #ffcc00 !important;
      transition: background-color 0.5s, box-shadow 0.5s;
    }
    .highlight-toggle {
      cursor: pointer;
      color: blue;
      text-decoration: underline;
      margin-left: 10px;
    }
  `;
  document.head.appendChild(style);

  // Add annotation counter
  const countIndicator = document.createElement('div');
  countIndicator.id = 'annotation-count';
  countIndicator.style.position = 'fixed';
  countIndicator.style.bottom = '10px';
  countIndicator.style.right = '10px';
  countIndicator.style.backgroundColor = 'rgba(0, 0, 0, 0.7)';
  countIndicator.style.color = 'white';
  countIndicator.style.padding = '10px';
  countIndicator.style.borderRadius = '5px';
  countIndicator.style.zIndex = '1000';
  countIndicator.innerHTML = 'Annotations: 0';
  document.body.appendChild(countIndicator);

  // Set up save button
  document.getElementById('save-validations').addEventListener('click', saveValidationState);

  // Close tooltip when clicking elsewhere
  document.addEventListener('click', function(e) {
    if (!e.target.closest('.annotation-overlay') && !e.target.closest('.tooltip')) {
      hideTooltip();
    }
  });
}

// Start the application
init();