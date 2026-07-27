import React, { useEffect, useMemo, useState } from 'react';
import { useParams, useSearchParams, useNavigate } from 'react-router-dom';
import { ValidationProvider } from '../context/ValidationContext';
import PDFDocument from '../components/pdfViewer/PDFDocument';
import DatasetUsageSidebar from '../components/pdfViewer/DatasetUsageSidebar';
import { usePDF } from '../hooks/usePDF';
import { fetchPublicPaperPDF, fetchPublicDatasetUsageDetail } from '../services/apiPublic';

export default function PublicPDFViewer() {
  const { bibcode, usageId } = useParams();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();

  const [pdfUrl, setPdfUrl] = useState(null);
  const [hasPdf, setHasPdf] = useState(false);
  const [quotes, setQuotes] = useState([]);
  const [annotations, setAnnotations] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [focusedQuoteId, setFocusedQuoteId] = useState(searchParams.get('highlight_quote'));
  const [currentQuoteIndex, setCurrentQuoteIndex] = useState(0);

  // Load public PDF URL and usage quotes
  useEffect(() => {
    let mounted = true;
    async function load() {
      try {
        setLoading(true);
        setError(null);

        const [pdfData, usageDetail] = await Promise.all([
          fetchPublicPaperPDF(bibcode),
          fetchPublicDatasetUsageDetail(usageId),
        ]);

        if (!mounted) return;
        setPdfUrl(pdfData.pdf_url || `/pdfs/${encodeURIComponent(bibcode)}.pdf`);
        setHasPdf(!!pdfData.has_pdf);

        const supporting = usageDetail.supporting_quotes || [];
        setQuotes(supporting);

        const anns = supporting
          .filter(q => q.page_number && q.x_coord_start != null && q.x_coord_end != null && q.y_coord_start != null && q.y_coord_end != null)
          .map(q => ({
            id: q.id,
            page: q.page_number,
            pdfRect: [q.x_coord_start, q.y_coord_start, q.x_coord_end, q.y_coord_end],
            text: q.quote,
            instrument: q.instrument,
            parameter: q.parameter,
            type: 'dataset_usage_quote'
          }));
        setAnnotations(anns);
      } catch (e) {
        if (!mounted) return;
        setError(e?.message || String(e));
      } finally {
        if (mounted) setLoading(false);
      }
    }
    load();
    return () => { mounted = false; };
  }, [bibcode, usageId]);

  const { pdf, numPages, isLoading: pdfLoading, error: pdfError } = usePDF(loading ? null : pdfUrl);
  const isBusy = loading || pdfLoading;
  const err = error || pdfError;

  if (isBusy) {
    return (
      <>

        <p style={{ color: '#666' }}>Loading PDF…</p>
      </>
    );
  }

  if (err) {
    return (
      <>

        <div style={{ color: '#c53030' }}>Error loading PDF: {String(err)}</div>
        {!hasPdf && (
          <div style={{ color: '#666', marginTop: '0.5rem' }}>No PDF available for {bibcode}.</div>
        )}
      </>
    );
  }

  return (
    <>
      <h1 style={{ fontSize: 'var(--font-4xl)', fontWeight: '400', color: '#333', marginBottom: '0.5rem' }}>PDF Viewer</h1>
      <ValidationProvider bibcode={bibcode}>
        <div className="pdf-viewer-container">
          <div className="pdf-content">
            <h2 style={{ marginTop: 0 }}>Dataset Usage Quotes for {bibcode}</h2>
            <PDFDocument
              pdf={pdf}
              numPages={numPages}
              annotations={annotations}
              focusedQuoteId={focusedQuoteId}
              targetPage={searchParams.get('page')}
            />
          </div>
          <DatasetUsageSidebar
            quotes={quotes}
            annotations={annotations}
            datasetUsageId={usageId}
            currentQuoteIndex={currentQuoteIndex}
            onQuoteSelect={(quoteId, index) => {
              setFocusedQuoteId(quoteId);
              setCurrentQuoteIndex(index);
            }}
            onNavigateBack={() => navigate(`/public/p/${encodeURIComponent(bibcode)}`)}
          />
        </div>
      </ValidationProvider>
    </>
  );
}
