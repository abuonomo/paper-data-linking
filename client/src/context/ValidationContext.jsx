// src/context/ValidationContext.jsx
import React, { createContext, useState, useContext, useEffect } from 'react';

const ValidationContext = createContext(null);

/**
 * Returns the anonymous tracking UUID stored in localStorage,
 * creating and persisting one if it doesn't exist yet.
 */
function getOrCreateAnonymousId() {
  const key = 'pdl_anonymous_id';
  let id = localStorage.getItem(key);
  if (!id) {
    // Generate a v4-style UUID without relying on crypto.randomUUID for older browsers
    id = 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
      const r = (Math.random() * 16) | 0;
      const v = c === 'x' ? r : (r & 0x3) | 0x8;
      return v.toString(16);
    });
    localStorage.setItem(key, id);
  }
  return id;
}

export const ValidationProvider = ({ children, bibcode }) => {
  const [validationState, setValidationState] = useState({});
  const [highlightedTag, setHighlightedTag] = useState(null);
  const [selectedAnnotation, setSelectedAnnotation] = useState(null);
  const validationStateKey = `pdf_validation_state_${bibcode}`;

  // Stable anonymous ID for this browser session (created once, persisted)
  const [anonymousId] = useState(() => getOrCreateAnonymousId());

  // Load saved validation state on mount
  useEffect(() => {
    const savedState = localStorage.getItem(validationStateKey);
    if (savedState) {
      try {
        setValidationState(JSON.parse(savedState));
      } catch (e) {
        console.error('Error loading validation state:', e);
      }
    }
  }, [validationStateKey]);

  // Validation actions
  const validateClaim = (claimId) => {
    setValidationState(prev => ({ ...prev, [claimId]: 'validated' }));
  };

  const rejectClaim = (claimId) => {
    setValidationState(prev => ({ ...prev, [claimId]: 'rejected' }));
  };

  const resetClaim = (claimId) => {
    setValidationState(prev => {
      const newState = { ...prev };
      delete newState[claimId];
      return newState;
    });
  };

  const saveValidationState = () => {
    localStorage.setItem(validationStateKey, JSON.stringify(validationState));
    alert('Validation state saved successfully!');
  };

  // Highlighting
  const highlightAnnotation = (tag) => {
    setHighlightedTag(tag);
  };

  const clearHighlights = () => {
    setHighlightedTag(null);
  };

  // Selecting an annotation
  const selectAnnotation = (annotation) => {
    setSelectedAnnotation(annotation);
  };

  const clearSelection = () => {
    setSelectedAnnotation(null);
  };

  return (
    <ValidationContext.Provider value={{
      validationState,
      validateClaim,
      rejectClaim,
      resetClaim,
      saveValidationState,
      highlightedTag,
      highlightAnnotation,
      clearHighlights,
      selectedAnnotation,
      selectAnnotation,
      clearSelection,
      anonymousId,
    }}>
      {children}
    </ValidationContext.Provider>
  );
};

export const useValidation = () => {
  const context = useContext(ValidationContext);
  if (!context) {
    throw new Error('useValidation must be used within a ValidationProvider');
  }
  return context;
};