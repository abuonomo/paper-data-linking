// src/hooks/usePaperPDF.js
import { useState, useEffect } from 'react';
import { fetchPaperPDF } from '../services/apiServices';

export const usePaperPDF = (bibcode) => {
  const [pdfUrl, setPdfUrl] = useState(null);
  const [hasPdf, setHasPdf] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!bibcode) {
      setIsLoading(false);
      return;
    }

    const fetchPdfUrl = async () => {
      try {
        setIsLoading(true);
        const data = await fetchPaperPDF(bibcode);
        
        setPdfUrl(data.pdf_url);
        setHasPdf(data.has_pdf);
        
        if (!data.has_pdf) {
          console.warn(`No PDF found for paper ${bibcode}:`, data.message);
        }
      } catch (err) {
        console.error('Error fetching PDF URL:', err);
        
        // Handle different error types
        if (err.response && err.response.status === 404) {
          setError(`Paper ${bibcode} not found`);
        } else {
          setError(err.message || 'Failed to fetch PDF URL');
        }
      } finally {
        setIsLoading(false);
      }
    };

    fetchPdfUrl();
  }, [bibcode]);

  return {
    pdfUrl,
    hasPdf,
    isLoading,
    error
  };
};