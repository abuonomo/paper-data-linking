export function mapQuotesToAnnotations(quotes = [], instrumentName = undefined) {
  const annotations = [];
  const quoteToAnnotationMap = new Map();

  const filteredQuotes = quotes.filter((quote) => {
    const hasLegacyCoords = quote.x_coord_start !== null &&
      quote.y_coord_start !== null &&
      quote.x_coord_end !== null &&
      quote.y_coord_end !== null;
    const hasCoordinateRegions = Array.isArray(quote.coordinate_regions) && quote.coordinate_regions.length > 0;
    return Boolean(quote.page_number) && (hasLegacyCoords || hasCoordinateRegions);
  });

  filteredQuotes.forEach((quote) => {
    const originalIndex = quotes.findIndex((q) => q.id === quote.id);
    if (originalIndex === -1) return;

    quoteToAnnotationMap.set(originalIndex, annotations.length);

    if (Array.isArray(quote.coordinate_regions) && quote.coordinate_regions.length > 0) {
      quote.coordinate_regions.forEach((region, regionIndex) => {
        annotations.push({
          id: `quote-${quote.id || originalIndex}-region-${regionIndex}`,
          pageNumber: region.page,
          pdfRect: [
            parseFloat(region.x0),
            parseFloat(region.y0),
            parseFloat(region.x1),
            parseFloat(region.y1),
          ],
          tag: `dataset-usage-quote-${originalIndex}`,
          fieldType: 'dataset-usage-quote',
          instrumentName,
          fieldValue: quote.quote,
          excerpt: quote.quote,
          isMultiline: quote.coordinate_regions.length > 1,
          regionIndex,
          totalRegions: quote.coordinate_regions.length,
          originalQuoteIndex: originalIndex,
        });
      });
      return;
    }

    annotations.push({
      id: `quote-${quote.id || originalIndex}`,
      pageNumber: quote.page_number,
      pdfRect: [
        parseFloat(quote.x_coord_start),
        parseFloat(quote.y_coord_start),
        parseFloat(quote.x_coord_end),
        parseFloat(quote.y_coord_end),
      ],
      tag: `dataset-usage-quote-${originalIndex}`,
      fieldType: 'dataset-usage-quote',
      instrumentName,
      fieldValue: quote.quote,
      excerpt: quote.quote,
      isMultiline: false,
      regionIndex: 0,
      totalRegions: 1,
      originalQuoteIndex: originalIndex,
    });
  });

  return { annotations, quoteToAnnotationMap };
}
