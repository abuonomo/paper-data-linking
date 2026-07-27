// src/components/PaperValidationDetail.jsx
import React, { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { StreamlinedValidationInterface } from './StreamlinedValidationInterface';
import { 
  fetchPaperDetails, 
  fetchPaperDatasetUsages, 
  fetchAnalysisById,
  fetchPaperValidationOverview
} from '../services/apiServices';
import { toast } from 'react-toastify';

const PaperValidationDetail = () => {
  const { paperId, analysisId, usageId } = useParams();
  const navigate = useNavigate();
  
  const [paper, setPaper] = useState(null);
  const [analysis, setAnalysis] = useState(null); // Store analysis context when available
  const [datasetUsages, setDatasetUsages] = useState([]);
  const [currentUsageIndex, setCurrentUsageIndex] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // Load paper data when component mounts or analysisId changes
  useEffect(() => {
    if (paperId) {
      loadPaperData();
    }
  }, [paperId, analysisId]);

  // Update current usage index when usageId changes
  useEffect(() => {
    if (usageId && datasetUsages.length > 0) {
      const index = datasetUsages.findIndex(usage => usage.id === usageId);
      if (index >= 0) {
        setCurrentUsageIndex(index);
      }
    }
  }, [usageId, datasetUsages]);

  const loadPaperData = async () => {
    try {
      setLoading(true);
      setError(null);
      
      if (analysisId) {
        // Analysis-centric route: load analysis context and filtered dataset usages
        const [paperData, analysisData, hierarchicalData] = await Promise.all([
          fetchPaperDetails(paperId),
          fetchAnalysisById(analysisId),
          fetchPaperValidationOverview(paperId)
        ]);
        
        setPaper(paperData);
        setAnalysis(analysisData);
        
        // Find the specific analysis group and use its dataset usages
        // Convert analysisId to integer for comparison since URL params are strings
        const analysisGroup = hierarchicalData.find(group => group.analysis.id === parseInt(analysisId, 10));
        if (analysisGroup) {
          setDatasetUsages(analysisGroup.dataset_usages || []);
        } else {
          setDatasetUsages([]);
          setError('Analysis not found in paper validation data');
        }
      } else {
        // Legacy paper-centric route: load all dataset usages for the paper
        const [paperData, usagesData] = await Promise.all([
          fetchPaperDetails(paperId),
          // Include usages even without supporting quotes
          fetchPaperDatasetUsages(paperId, { has_quotes: 'false' })
        ]);
        
        setPaper(paperData);
        setAnalysis(null);
        // Extract results from paginated response
        setDatasetUsages(usagesData.results || usagesData);
      }

    } catch (err) {
      console.error('Error loading paper data:', err);
      setError('Failed to load paper validation data');
      toast.error('Failed to load paper validation data');
    } finally {
      setLoading(false);
    }
  };

  const handleNavigateToNext = async () => {
    const nextIndex = currentUsageIndex + 1;
    
    if (nextIndex < datasetUsages.length) {
      // Move to next usage in current paper/analysis
      const nextUsage = datasetUsages[nextIndex];
      const nextUrl = analysisId 
        ? `/papers/${paperId}/validate/${analysisId}/${nextUsage.id}`
        : `/papers/${paperId}/validate/${nextUsage.id}`;
      navigate(nextUrl);
    } else {
      // All usages in current paper/analysis completed
      if (analysisId) {
        // Analysis-centric: return to paper validation overview
        navigate(`/papers/${paperId}/validate`);
        toast.info('Analysis completed! Returning to paper overview.');
      } else {
        // Paper-centric: move to next paper
        try {
          const nextPaperData = await fetchNextPaperInQueue(paperId, { validation_status: 'pending' });
          if (nextPaperData.next_paper) {
            navigate(`/papers/${nextPaperData.next_paper.id}/validate`);
            toast.success(`Moving to next paper: ${nextPaperData.next_paper.bibcode}`);
          } else {
            // No more papers, go back to queue
            navigate('/papers/validation-queue');
            toast.success('All papers completed! Returning to queue.');
          }
        } catch (err) {
          console.error('Error getting next paper:', err);
          // Fallback to paper overview
          navigate(`/papers/${paperId}/validate`);
          toast.info('Paper completed! Returning to paper overview.');
        }
      }
    }
  };

  const handleNavigateToPrevious = () => {
    const prevIndex = currentUsageIndex - 1;
    
    if (prevIndex >= 0) {
      // Move to previous usage in current paper/analysis
      const prevUsage = datasetUsages[prevIndex];
      const prevUrl = analysisId 
        ? `/papers/${paperId}/validate/${analysisId}/${prevUsage.id}`
        : `/papers/${paperId}/validate/${prevUsage.id}`;
      navigate(prevUrl);
    } else {
      // Go back to paper overview
      navigate(`/papers/${paperId}/validate`);
    }
  };

  const handleReturnToPaperOverview = () => {
    navigate(`/papers/${paperId}/validate`);
  };

  const handleReturnToQueue = () => {
    navigate('/papers/validation-queue');
  };

  // Removed Next/Previous Paper handlers; navigation is claim-level only

  // Helper functions for configuration display
  const getConfigurationBadgeClass = (configName) => {
    switch (configName) {
      case 'standard':
        return 'bg-primary text-white';
      case 'budget':
        return 'bg-success text-white';
      default:
        return 'bg-secondary text-white';
    }
  };

  const getConfigurationDisplayName = (configName) => {
    if (!configName) return 'Legacy';
    return configName.charAt(0).toUpperCase() + configName.slice(1);
  };

  // Breadcrumb removed in favor of compact header inside validation panel

  if (loading) {
    return (
      <div className="container-fluid">
        <div className="d-flex justify-content-center align-items-center" style={{ height: '400px' }}>
          <div className="spinner-border" role="status">
            <span className="visually-hidden">Loading...</span>
          </div>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="container-fluid">
        <div className="alert alert-danger" role="alert">
          {error}
        </div>
      </div>
    );
  }

  return (
    <div>
      {/* Use StreamlinedValidationInterface which now shows bibcode, claim count,
          configuration badge, and a Back to Queue control in its own header */}
      <StreamlinedValidationInterface 
        paperContext={{
          paper,
          analysis, // Include analysis context when available
          datasetUsages,
          currentUsageIndex,
          onNavigateNext: handleNavigateToNext,
          onNavigatePrevious: handleNavigateToPrevious,
          onReturnToPaperOverview: handleReturnToPaperOverview,
        }}
      />
    </div>
  );
};

export default PaperValidationDetail;
