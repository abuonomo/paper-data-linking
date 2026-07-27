import React, { useState } from 'react';
import { Button, Card, Badge, Form, InputGroup } from 'react-bootstrap';
import { 
  ArrowLeft, 
  ChevronUp, 
  ChevronDown, 
  Search,
  Quote,
  FileText
} from 'react-bootstrap-icons';

const DatasetUsageSidebar = ({ 
  quotes, 
  annotations, 
  datasetUsageId,
  currentQuoteIndex,
  onQuoteSelect,
  onNavigateBack 
}) => {
  const [searchTerm, setSearchTerm] = useState('');

  // Filter quotes based on search term
  const filteredQuotes = quotes.filter(quote =>
    quote.quote.toLowerCase().includes(searchTerm.toLowerCase()) ||
    (quote.instrument && quote.instrument.toLowerCase().includes(searchTerm.toLowerCase())) ||
    (quote.parameter && quote.parameter.toLowerCase().includes(searchTerm.toLowerCase()))
  );

  const scrollToQuote = (quote, index) => {
    onQuoteSelect(quote.id, index);
    
    // Scroll to the annotation in the PDF
    const annotationElement = document.querySelector(`[data-annotation-id="${quote.id}"]`);
    if (annotationElement) {
      annotationElement.scrollIntoView({ behavior: 'auto', block: 'center' });
    }
  };

  const navigateToQuote = (direction) => {
    const newIndex = direction === 'next' 
      ? Math.min(currentQuoteIndex + 1, filteredQuotes.length - 1)
      : Math.max(currentQuoteIndex - 1, 0);
    
    if (newIndex !== currentQuoteIndex && filteredQuotes[newIndex]) {
      scrollToQuote(filteredQuotes[newIndex], newIndex);
    }
  };

  return (
    <div className="validation-sidebar">
      <div className="sidebar-header">
        <div className="d-flex align-items-center mb-3">
          <Button 
            variant="outline-secondary" 
            size="sm" 
            onClick={onNavigateBack}
            className="me-2"
          >
            <ArrowLeft className="me-1" />
            Back to Dashboard
          </Button>
          <h5 className="mb-0 flex-grow-1">Dataset Usage Quotes</h5>
        </div>

        {/* Search */}
        <InputGroup className="mb-3" size="sm">
          <InputGroup.Text>
            <Search />
          </InputGroup.Text>
          <Form.Control
            type="text"
            placeholder="Search quotes..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
          />
        </InputGroup>

        {/* Navigation Controls */}
        {filteredQuotes.length > 0 && (
          <div className="d-flex align-items-center justify-content-between mb-3">
            <small className="text-muted">
              {currentQuoteIndex + 1} of {filteredQuotes.length} quotes
            </small>
            <div className="btn-group" size="sm">
              <Button 
                variant="outline-secondary" 
                size="sm"
                disabled={currentQuoteIndex === 0}
                onClick={() => navigateToQuote('prev')}
              >
                <ChevronUp />
              </Button>
              <Button 
                variant="outline-secondary" 
                size="sm"
                disabled={currentQuoteIndex === filteredQuotes.length - 1}
                onClick={() => navigateToQuote('next')}
              >
                <ChevronDown />
              </Button>
            </div>
          </div>
        )}
      </div>

      <div className="sidebar-content">
        {filteredQuotes.length === 0 ? (
          <div className="text-center text-muted py-4">
            <FileText size={48} className="mb-2" />
            <p>No quotes found matching your search.</p>
          </div>
        ) : (
          filteredQuotes.map((quote, index) => (
            <Card 
              key={quote.id} 
              className={`mb-3 quote-card ${index === currentQuoteIndex ? 'active' : ''}`}
              style={{ cursor: 'pointer' }}
              onClick={() => scrollToQuote(quote, index)}
            >
              <Card.Body className="py-2">
                <div className="d-flex justify-content-between align-items-start mb-2">
                  <div>
                    <Badge bg="light" text="dark" className="me-2">
                      Page {quote.page_number}
                    </Badge>
                    {quote.instrument && (
                      <Badge bg="info" className="me-2">
                        {quote.instrument}
                      </Badge>
                    )}
                    {quote.parameter && (
                      <Badge bg="secondary">
                        {quote.parameter}
                      </Badge>
                    )}
                  </div>
                  <small className="text-muted">#{index + 1}</small>
                </div>
                
                <div className="quote-text">
                  <Quote className="text-muted me-1" style={{ fontSize: '0.8em' }} />
                  <small className="text-muted" style={{ lineHeight: '1.4' }}>
                    "{quote.quote}"
                  </small>
                </div>
                
                {(quote.x_coord_start || quote.y_coord_start) && (
                  <div className="mt-2 text-muted" style={{ fontSize: '0.7em' }}>
                    Position: ({quote.x_coord_start?.toFixed(1)}, {quote.y_coord_start?.toFixed(1)}) - 
                    ({quote.x_coord_end?.toFixed(1)}, {quote.y_coord_end?.toFixed(1)})
                  </div>
                )}
              </Card.Body>
            </Card>
          ))
        )}
      </div>

      <style>{`
        .quote-card {
          transition: all 0.2s ease;
          border-left: 3px solid transparent;
        }
        
        .quote-card:hover {
          border-left-color: #007bff;
          box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        
        .quote-card.active {
          border-left-color: #28a745;
          background-color: rgba(40, 167, 69, 0.05);
        }
        
        .quote-text {
          display: flex;
          align-items: flex-start;
        }
        
        .sidebar-content {
          max-height: calc(100vh - 250px);
          overflow-y: auto;
        }
        
        .sidebar-header {
          border-bottom: 1px solid #dee2e6;
          padding-bottom: 1rem;
          margin-bottom: 1rem;
        }
      `}</style>
    </div>
  );
};

export default DatasetUsageSidebar;
