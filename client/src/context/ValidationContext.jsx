// src/context/ValidationContext.jsx
import React, { createContext, useState, useContext, useEffect } from 'react';

const ValidationContext = createContext(null);

export const ValidationProvider = ({ children, bibcode }) => {
  const [validationState, setValidationState] = useState({});
  const [highlightedTag, setHighlightedTag] = useState(null);
  const [selectedAnnotation, setSelectedAnnotation] = useState(null);
  const validationStateKey = `pdf_validation_state_${bibcode}`;

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