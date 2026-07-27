import { useState, useEffect } from 'react';
import { fetchDatasetUsageDetail } from '../services/apiServices';

export const useDatasetUsageQuotes = (datasetUsageId) => {
  const [quotes, setQuotes] = useState([]);
  const [annotations, setAnnotations] = useState([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!datasetUsageId) {
      setQuotes([]);
      setAnnotations([]);
      setIsLoading(false);
      setError(null);
      return;
    }

    const fetchQuotes = async () => {
      setIsLoading(true);
      setError(null);

      try {
        const detailData = await fetchDatasetUsageDetail(datasetUsageId);
        const supportingQuotes = detailData.supporting_quotes || [];
        
        setQuotes(supportingQuotes);
        
        // Convert quotes to annotation format for PDF display
        const quotesAnnotations = supportingQuotes
          .filter(quote => quote.x_coord_start !== null && quote.page_number)
          .map(quote => ({
            id: quote.id,
            page: quote.page_number,
            pdfRect: [
              quote.x_coord_start,
              quote.y_coord_start,
              quote.x_coord_end,
              quote.y_coord_end
            ],
            text: quote.quote,
            instrument: quote.instrument,
            parameter: quote.parameter,
            type: 'dataset_usage_quote'
          }));

        setAnnotations(quotesAnnotations);
      } catch (err) {
        console.error('Error fetching dataset usage quotes:', err);
        setError(err.message || 'Failed to load dataset usage quotes');
      } finally {
        setIsLoading(false);
      }
    };

    fetchQuotes();
  }, [datasetUsageId]);

  return {
    quotes,
    annotations,
    isLoading,
    error
  };
};