// src/hooks/usePDF.js
import { useState, useEffect } from 'react';
import * as pdfjs from 'pdfjs-dist';

// Different worker configuration based on environment
if (import.meta.env.DEV) {
  // Development environment - use Vite's import.meta.url for resolving
  pdfjs.GlobalWorkerOptions.workerSrc = new URL(
    'pdfjs-dist/build/pdf.worker.min.mjs',
    import.meta.url
  ).toString();
} else {
  // Production environment (Docker) - use a static path
  pdfjs.GlobalWorkerOptions.workerSrc = '/pdf.worker.min.js';
}

export const usePDF = (pdfUrl) => {
  const [pdf, setPdf] = useState(null);
  const [numPages, setNumPages] = useState(0);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!pdfUrl) {
      setIsLoading(false);
      return;
    }

    const loadPDF = async () => {
      try {
        setIsLoading(true);
        const loadingTask = pdfjs.getDocument(pdfUrl);
        const pdfDocument = await loadingTask.promise;
        setNumPages(pdfDocument.numPages);
        setPdf(pdfDocument);
        setIsLoading(false);
      } catch (err) {
        console.error('Error loading PDF:', err);
        setError(err.message || 'Error loading PDF');
        setIsLoading(false);
      }
    };

    loadPDF();

    return () => {
      // Cleanup if needed
    };
  }, [pdfUrl]);

  return { pdf, numPages, isLoading, error };
};