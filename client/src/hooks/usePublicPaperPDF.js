import { useEffect, useState } from 'react';
import { fetchPublicPaperPDF } from '../services/apiPublic';

export const usePublicPaperPDF = (bibcode) => {
  const [pdfUrl, setPdfUrl] = useState(null);
  const [hasPdf, setHasPdf] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!bibcode) {
      setPdfUrl(null);
      setHasPdf(false);
      setError(null);
      setIsLoading(false);
      return;
    }

    const fetchPdfUrl = async () => {
      try {
        setIsLoading(true);
        setError(null);
        const data = await fetchPublicPaperPDF(bibcode);
        setPdfUrl(data.pdf_url || null);
        setHasPdf(Boolean(data.has_pdf));
      } catch (err) {
        console.error('Error fetching public PDF URL:', err);
        setError(err?.message || 'Failed to fetch PDF URL');
        setPdfUrl(null);
        setHasPdf(false);
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
    error,
  };
};
