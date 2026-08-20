// src/components/StreamlinedValidationInterface.jsx
import React, { useState, useEffect, useMemo, useRef } from 'react';
import { useParams, useNavigate, useSearchParams } from 'react-router-dom';
import { fetchValidationQueue, fetchValidationStats, validateDatasetUsage, fetchPaperAnalysis, fetchDatasetUsageDetail, fetchPaperDatasetUsages, fetchPaperDetails, fetchDatasetUsageValidations, fetchCampaignPaperClaims, validateCampaignClaim, fetchCampaignOverview } from '../services/apiServices';
import PDFDocument from './pdfViewer/PDFDocument';
import { ValidationProvider } from '../context/ValidationContext';
import { usePaperPDF } from '../hooks/usePaperPDF';
import { usePublicPaperPDF } from '../hooks/usePublicPaperPDF';
import { usePDF } from '../hooks/usePDF';
import { toast } from 'react-toastify';
import { formatDateTimeCompactUTC } from '../utils/dateUtils';
import { usePDFSearch } from '../hooks/usePDFSearch';
import PDFSearch from './pdfViewer/PDFSearch';
import { mapQuotesToAnnotations } from '../features/evidence/mapQuotesToAnnotations';

// Helper function to format datetime without UTC suffix
const formatDateTimeNoUTC = (isoString) => {
  if (!isoString) return 'N/A';
  
  const date = new Date(isoString);
  
  // Format as "YYYY-MM-DD HH:mm" (without UTC suffix)
  const year = date.getUTCFullYear();
  const month = String(date.getUTCMonth() + 1).padStart(2, '0');
  const day = String(date.getUTCDate()).padStart(2, '0');
  const hours = String(date.getUTCHours()).padStart(2, '0');
  const minutes = String(date.getUTCMinutes()).padStart(2, '0');
  
  return `${year}-${month}-${day} ${hours}:${minutes}`;
};

// Helper function to format datetime with colored date and time parts
const formatColoredDateTime = (dateTimeString) => {
  const formatted = formatDateTimeNoUTC(dateTimeString);
  // Split on space to separate date and time
  const parts = formatted.split(' ');
  if (parts.length >= 2) {
    return {
      date: parts[0], // e.g., "2023-01-01"
      time: parts[1] // e.g., "12:00"
    };
  }
  return { date: formatted, time: '' };
};
import './pdfViewer/PDFViewer.css';
import './StreamlinedValidationInterface.css';
import ScriptModal from './ScriptModal';


export const StreamlinedValidationInterface = ({ paperContext, mode = 'validate' }) => {
  const navigate = useNavigate();
  const { usageId, paperId, bibcode } = useParams();
  const [searchParams] = useSearchParams();
  const isReadOnly = mode === 'readonly';
  // Campaign mode (?campaign=<slug>): claim-level blinded review against the
  // deduplicated cross-config claim union. Claims come from the campaign API
  // (which excludes config/consensus/other-reviewer data by construction),
  // verdicts propagate server-side to all member usages, and the UI adds
  // per-component checkmarks (mission / instrument / window).
  const campaignSlug = searchParams.get('campaign') || null;
  const isCampaign = !!campaignSlug;
  // Campaign phase (?phase=calibration): scopes the in-paper queue to the
  // paper's calibration claims only (so a reviewer cannot wander onto bulk
  // claims before the rubric freeze) and drives cross-paper advancement
  // through the calibration list.
  const campaignPhase = searchParams.get('phase') || null;
  // Blind-review mode (?blind=1): hides everything that reveals which LLM
  // configuration produced this claim (config badge, Context modal with model
  // names) so validation campaigns can be config-blind. See VALIDATION_PROTOCOL.
  // Campaign mode is always blind.
  const isBlind = isCampaign || searchParams.get('blind') === '1';
  
  const [validationQueue, setValidationQueue] = useState([]);
  const [currentUsage, setCurrentUsage] = useState(null);
  const usageCacheRef = useRef({});
  const [currentIndex, setCurrentIndex] = useState(0);
  const [currentQuoteIndex, setCurrentQuoteIndex] = useState(0);
  const [validationHistory, setValidationHistory] = useState([]);
  const [paperProgress, setPaperProgress] = useState(null);
  const [stats, setStats] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);
  const [isValidating, setIsValidating] = useState(false);
  const [validationNotes, setValidationNotes] = useState('');
  const [showValidationNotes, setShowValidationNotes] = useState(false);
  const [scrollTrigger, setScrollTrigger] = useState(0);
  const [validationAnimation, setValidationAnimation] = useState(null);
  const [showScriptModal, setShowScriptModal] = useState(false);
  const [showContextModal, setShowContextModal] = useState(false);
  const [isNavigating, setIsNavigating] = useState(false);
  const [paperAnalysis, setPaperAnalysis] = useState(null);
  const [paperAnalysisLoading, setPaperAnalysisLoading] = useState(false);
  const [showInstrumentTooltip, setShowInstrumentTooltip] = useState(false);
  const [tooltipPosition, setTooltipPosition] = useState(null);
  const [showParamsModal, setShowParamsModal] = useState(false);
  const [showMoreMenu, setShowMoreMenu] = useState(false);
  const [statusOverrides, setStatusOverrides] = useState({});
  const [paperStatusMap, setPaperStatusMap] = useState({});
  const [showFullTextModal, setShowFullTextModal] = useState(false);
  const [paperFullText, setPaperFullText] = useState(null);
  const [fullTextLoading, setFullTextLoading] = useState(false);
  const [validationCounts, setValidationCounts] = useState(null);
  const [showPreviousValidations, setShowPreviousValidations] = useState(false);
  const [wantsToRevalidate, setWantsToRevalidate] = useState(false);
  // Campaign per-component checkmarks (mission / instrument / window).
  // Default all checked so a clean claim is a one-click approve. The checks
  // are only shown inside the reject panel — verdict first, detail second.
  const [claimChecks, setClaimChecks] = useState({ mission: true, instrument: true, window: true });
  const [showRejectPanel, setShowRejectPanel] = useState(false);
  const [rejectReason, setRejectReason] = useState(null);
  const [showRejectHelp, setShowRejectHelp] = useState(false);
  // Prefetched overview promise for campaign end-of-paper advancement — kicked
  // off at vote time so the network round trip overlaps the vote flash.
  const campaignAdvancePrefetchRef = useRef(null);

  // Helper: display name for configuration
  const getConfigurationDisplayName = (configName) => {
    if (!configName) return 'Legacy';
    return configName.charAt(0).toUpperCase() + configName.slice(1);
  };

  // Helper function to detect if we have lightweight data (missing paper object)
  const isLightweightData = (usage) => {
    return usage && !usage.paper && !usage.supporting_quotes;
  };

  // Helper function to fetch full dataset usage detail
  const fetchFullUsageData = async (usageId) => {
    if (isReadOnly) {
      return null;
    }
    try {
      const fullData = await fetchDatasetUsageDetail(usageId);
      return fullData;
    } catch (error) {
      console.error('Error fetching full usage data:', error);
      return null;
    }
  };

  // Filters - Order by paper for grouping related validations
  const [filters] = useState({
    validation_status: searchParams.get('status') || 'all',
    has_quotes: searchParams.get('has_quotes') || 'true',
    // Group by paper, then order claims by observatory > instrument > start time with deterministic tie-breakers
    ordering: 'paper__bibcode,instrument__observatory__datasource__slug,instrument__observatory__short_name,instrument__short_name,start_lower,end_upper,id',
    // When in paper context, filter by paper ID
    ...(paperContext && paperContext.paper ? { paper: paperContext.paper.id } : {}),
  });

  const includeUnvalidated = searchParams.get('include_unvalidated') === 'true';
  const buildUsagePath = (targetUsageId) => {
    if (isReadOnly) {
      const currentBibcode = bibcode || paperContext?.paper?.bibcode;
      const querySuffix = includeUnvalidated ? '?include_unvalidated=true' : '';
      return `/public/p/${encodeURIComponent(currentBibcode || '')}/evidence/${targetUsageId}${querySuffix}`;
    }
    // Preserve campaign/blind mode across in-page navigation (next/prev
    // claim) so a blind review session cannot accidentally unblind itself.
    // Campaign mode has its own route that bypasses the PaperValidationDetail
    // wrapper (whose paper/analysis context fetches would unblind the review).
    if (isCampaign && paperId) {
      const phaseSuffix = campaignPhase ? `&phase=${encodeURIComponent(campaignPhase)}` : '';
      return `/campaign/papers/${paperId}/claims/${targetUsageId}?campaign=${encodeURIComponent(campaignSlug)}${phaseSuffix}`;
    }
    const blindSuffix = isBlind ? '?blind=1' : '';
    if (paperId) return `/papers/${paperId}/validate/${targetUsageId}${blindSuffix}`;
    return `/validate/${targetUsageId}${blindSuffix}`;
  };

  // PDF loading for current usage
  const authPdfState = usePaperPDF(isReadOnly ? null : currentUsage?.paper?.bibcode);
  const publicPdfState = usePublicPaperPDF(isReadOnly ? currentUsage?.paper?.bibcode : null);
  const {
    pdfUrl,
    hasPdf,
    isLoading: pdfUrlLoading,
    error: pdfUrlError,
  } = isReadOnly ? publicPdfState : authPdfState;
  const { pdf, numPages, isLoading: pdfLoading, error: pdfError } = usePDF(
    pdfUrlLoading ? null : pdfUrl
  );

  // PDF Search functionality
  const {
    searchQuery,
    setSearchQuery,
    searchResults,
    currentMatchIndex,
    currentMatch,
    isSearching,
    isSearchVisible,
    showSearch,
    clearSearch,
    goToNextMatch,
    goToPreviousMatch,
    getMatchesForPage,
    totalMatches
  } = usePDFSearch(pdf, numPages);

  // Preload next item's PDF for smoother transitions
  const nextUsage = currentIndex < validationQueue.length - 1 ? validationQueue[currentIndex + 1] : null;
  const { pdfUrl: nextAuthPdfUrl } = usePaperPDF(isReadOnly ? null : nextUsage?.paper?.bibcode);
  const { pdfUrl: nextPublicPdfUrl } = usePublicPaperPDF(isReadOnly ? nextUsage?.paper?.bibcode : null);
  const nextPdfUrl = isReadOnly ? nextPublicPdfUrl : nextAuthPdfUrl;
  const { pdf: nextPdf } = usePDF(nextPdfUrl); // Preload next PDF

  // Load validation data (fetch queue/stats once per paper/context change, not on usage change)
  useEffect(() => {
    const loadValidationData = async () => {
      try {
        setIsLoading(true);
        
        let queue;
        
        // Public readonly mode always uses provided queue context
        if (isReadOnly && paperContext && paperContext.datasetUsages) {
          queue = paperContext.datasetUsages;
          setValidationQueue(queue);
        // Campaign mode: blinded, deduplicated claim list from the campaign API.
        // Claims arrive complete (paper, quotes, my_* fields) — no detail fetches.
        } else if (isCampaign && paperId) {
          // Cross-paper jump: drop the stale claim immediately so the skeleton
          // shows instead of the previous paper's claim lingering on screen.
          if (currentUsage && String(currentUsage.paper?.id) !== String(paperId)) {
            setCurrentUsage(null);
            setValidationQueue([]);
          }
          queue = await fetchCampaignPaperClaims(campaignSlug, paperId);
          if (campaignPhase === 'calibration') {
            // Calibration phase: only this paper's calibration claims are in
            // the queue — bulk claims stay untouchable until the rubric freeze.
            const overview = await fetchCampaignOverview(campaignSlug);
            const calibrationIds = new Set(
              (overview.calibration?.claims || []).map(c => c.usage_id)
            );
            queue = (queue || []).filter(c => calibrationIds.has(c.id));
          }
          setValidationQueue(queue || []);
        // Prefer backend-ordered list when scoping to a single paper, even if paperContext is present
        } else if (paperId) {
          // Scoped to a single paper: include usages even without supporting quotes
          const options = { has_quotes: 'false', ordering: 'instrument__observatory__datasource__slug,instrument__observatory__short_name,instrument__short_name,start_lower,end_upper,id' };
          if (filters.validation_status && filters.validation_status !== 'all') {
            options.validation_status = filters.validation_status;
          }
          const usages = await fetchPaperDatasetUsages(paperId, options);

          queue = usages.results || usages || [];
          setValidationQueue(queue);
          // Stats not needed on detail page - only shown on queue page
        } else if (paperContext && paperContext.datasetUsages) {
          // Fallback: use provided context data (not ordered by backend)
          queue = paperContext.datasetUsages;
          setValidationQueue(queue);
          // Stats not needed on detail page - only shown on queue page
        } else {
          // Fallback to the API for standalone mode (all papers)
          const queueData = await fetchValidationQueue(filters);
          queue = queueData.results || queueData;
          setValidationQueue(queue);
          // Stats not needed on detail page - only shown on queue page
        }
        
        // Ensure queue is an array
        if (!Array.isArray(queue)) {
          console.error('Queue is not an array:', queue);
          setError('Invalid queue data received');
          return;
        }
        
        // Calculate paper progress
        if (queue.length > 0) {
          let currentBibcode = queue[0]?.paper?.bibcode;
          let totalForPaper = queue.length;
          if (!paperId) {
            // When we loaded the global queue, limit to the current paper
            currentBibcode = queue[0]?.paper?.bibcode;
            totalForPaper = queue.filter(item => item.paper?.bibcode === currentBibcode).length;
          }
          setPaperProgress({
            current: 1,
            total: totalForPaper,
            bibcode: currentBibcode
          });
        }
        
        // Set current usage
        if (usageId) {
          const targetIndex = queue.findIndex(item => item.id === usageId);
          if (targetIndex >= 0) {
            setCurrentIndex(targetIndex);
            const usage = queue[targetIndex];
            
            // Show immediately; fetch full data in background if needed
            setCurrentUsage(usage);
            if (isLightweightData(usage)) {
              fetchFullUsageData(usage.id).then(full => {
                if (full) { usageCacheRef.current[usage.id] = full; setCurrentUsage(full); }
              });
            }
            
            setShowScriptModal(false);
    setShowContextModal(false);
    setShowFullTextModal(false);
            updatePaperProgress(queue[targetIndex], targetIndex);
          } else {
            // If specific UUID not found, try expanding search to all statuses
            console.warn(`Dataset usage ${usageId} not found in current queue. This may be because it doesn't match the current filters.`);
            if (queue.length > 0) {
              setCurrentIndex(0);
              const usage = queue[0];
              
              // Check if we have lightweight data and need to fetch full data
              if (isLightweightData(usage)) {
                // Fetch full data for this usage
                const fullData = await fetchFullUsageData(usage.id);
                if (fullData) {
                  setCurrentUsage(fullData);
                } else {
                  setCurrentUsage(usage); // Fallback to lightweight data
                }
              } else {
                setCurrentUsage(usage);
              }
              
              setShowScriptModal(false);
    setShowContextModal(false);
    setShowFullTextModal(false);
              updatePaperProgress(queue[0], 0);
              navigate(buildUsagePath(queue[0].id), { replace: true });
            }
          }
        } else if (queue.length > 0) {
          setCurrentIndex(0);
          const usage = queue[0];
          
          // Check if we have lightweight data and need to fetch full data
          if (isLightweightData(usage)) {
            // Fetch full data for this usage
            const fullData = await fetchFullUsageData(usage.id);
            if (fullData) {
              setCurrentUsage(fullData);
            } else {
              setCurrentUsage(usage); // Fallback to lightweight data
            }
          } else {
            setCurrentUsage(usage);
          }
          
          setShowScriptModal(false);
    setShowContextModal(false);
    setShowFullTextModal(false);
          updatePaperProgress(queue[0], 0);
          
          navigate(buildUsagePath(queue[0].id), { replace: true });
        }
      } catch (err) {
        console.error('Error loading validation data:', err);
        setError(err.message);
      } finally {
        setIsLoading(false);
      }
    };

    loadValidationData();
  }, [filters, isReadOnly, paperId, paperContext?.paper?.id, paperContext?.paper?.bibcode, paperContext?.datasetUsages?.length, includeUnvalidated, bibcode, isCampaign, campaignSlug, campaignPhase]);

  // Sync current usage with URL without refetching the whole queue
  useEffect(() => {
    if (!usageId || !Array.isArray(validationQueue) || validationQueue.length === 0) return;
    const idx = validationQueue.findIndex(u => u.id === usageId);
    if (idx >= 0) {
      setCurrentIndex(idx);
      const usage = validationQueue[idx];
      setShowScriptModal(false);
      setShowContextModal(false);
      setShowFullTextModal(false);
      updatePaperProgress(usage, idx);
      if (!isLightweightData(usage)) {
        setCurrentUsage(usage);
        setIsNavigating(false);
      } else {
        const cached = usageCacheRef.current[usage.id];
        if (cached) {
          setCurrentUsage(cached);
          setIsNavigating(false);
        } else {
          fetchFullUsageData(usage.id).then(full => {
            if (full) usageCacheRef.current[usage.id] = full;
            setCurrentUsage(full || usage);
            setIsNavigating(false);
          });
        }
      }
    }
  }, [usageId, validationQueue]);

  // Prefetch adjacent items so navigation feels instant
  useEffect(() => {
    const adjacent = [
      currentIndex > 0 ? validationQueue[currentIndex - 1] : null,
      currentIndex < validationQueue.length - 1 ? validationQueue[currentIndex + 1] : null,
    ];
    adjacent.forEach(usage => {
      if (!usage || !isLightweightData(usage) || usageCacheRef.current[usage.id]) return;
      fetchFullUsageData(usage.id).then(full => {
        if (full) usageCacheRef.current[usage.id] = full;
      });
    });
  }, [currentIndex, validationQueue]);

  // Clear cached full text when paper changes
  useEffect(() => {
    setPaperFullText(null);
  }, [currentUsage?.paper?.id]);

  // Campaign mode: initialize checkmarks per claim — from my previous verdict
  // when one exists, otherwise default all checked.
  useEffect(() => {
    if (!isCampaign || !currentUsage) return;
    setClaimChecks({
      mission: currentUsage.my_mission_correct !== false,
      instrument: currentUsage.my_instrument_correct !== false,
      window: currentUsage.my_window_correct !== false,
    });
    setValidationNotes(currentUsage.my_validation_notes || '');
    setRejectReason(currentUsage.my_reject_reason || null);
    setShowRejectPanel(false);
  }, [isCampaign, currentUsage?.id]);

  // Fetch per-usage validation counts when current usage changes (auth mode only).
  // Skipped entirely in campaign mode: the validations list exposes the other
  // reviewer's verdicts, which would break blinding on overlap papers.
  useEffect(() => {
    setShowPreviousValidations(false);
    setWantsToRevalidate(false);
    if (isReadOnly || isCampaign || !currentUsage?.id) {
      setValidationCounts(null);
      return;
    }
    let cancelled = false;
    fetchDatasetUsageValidations(currentUsage.id)
      .then(data => { if (!cancelled) setValidationCounts(data); })
      .catch(() => { if (!cancelled) setValidationCounts(null); });
    return () => { cancelled = true; };
  }, [currentUsage?.id, isReadOnly, isCampaign]);

  // Load paper analysis data when current usage changes
  useEffect(() => {
    const loadPaperAnalysis = async () => {
      // Campaign mode: the analysis carries configuration/model info — never
      // load it (blinding).
      if (isReadOnly || isCampaign) {
        setPaperAnalysis(null);
        setPaperAnalysisLoading(false);
        return;
      }

      // If we have analysis from paper context, use that instead
      if (paperContext?.analysis) {
        setPaperAnalysis(paperContext.analysis);
        setPaperAnalysisLoading(false);
        return;
      }
      
      if (!currentUsage?.paper?.id) return;
      
      // Only load if we don't already have it for this paper
      if (paperAnalysis?.paper?.id === currentUsage.paper.id) return;
      
      try {
        setPaperAnalysisLoading(true);
        const analysisData = await fetchPaperAnalysis(currentUsage.paper.id);
        
        // fetchPaperAnalysis now returns an array, so we need to select the appropriate analysis
        if (Array.isArray(analysisData) && analysisData.length > 0) {
          // Prefer standard configuration, fallback to first available
          const standardAnalysis = analysisData.find(a => a.configuration_name === 'standard');
          const selectedAnalysis = standardAnalysis || analysisData[0];
          setPaperAnalysis(selectedAnalysis);
        } else {
          setPaperAnalysis(null);
        }
      } catch (error) {
        console.error('Error loading paper analysis:', error);
        setPaperAnalysis(null);
      } finally {
        setPaperAnalysisLoading(false);
      }
    };

    loadPaperAnalysis();
  }, [isReadOnly, isCampaign, currentUsage?.paper?.id, paperAnalysis?.paper?.id, paperContext?.analysis]);

  // Keyboard shortcuts
  useEffect(() => {
    const handleKeyDown = (event) => {
      // Only handle shortcuts when no input is focused and search is not visible
      if (event.target.tagName === 'INPUT' || event.target.tagName === 'TEXTAREA') {
        return;
      }

      // Ctrl+F or Cmd+F to open PDF search
      if ((event.ctrlKey || event.metaKey) && event.key === 'f') {
        event.preventDefault();
        showSearch();
      }
    };

    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [showSearch]);

  // Campaign: advance across papers when the in-paper queue is exhausted.
  // Calibration phase walks the calibration list wherever its claims live;
  // bulk/overlap follows the server's resume pointer to the next unfinished
  // paper. Lands on /campaign when everything is judged.
  const advanceCampaign = async () => {
    try {
      const prefetched = campaignAdvancePrefetchRef.current;
      campaignAdvancePrefetchRef.current = null;
      const overview = (prefetched && await prefetched) || await fetchCampaignOverview(campaignSlug);
      const slugParam = encodeURIComponent(campaignSlug);
      if (campaignPhase === 'calibration') {
        const next = (overview.calibration?.claims || []).find(
          c => !c.judged && c.usage_id !== currentUsage?.id
        );
        if (next) {
          navigate(`/campaign/papers/${next.paper_id}/claims/${next.usage_id}?campaign=${slugParam}&phase=calibration`);
          return;
        }
        toast.success('Calibration complete — your papers are now unlocked!');
        navigate('/campaign');
        return;
      }
      if (overview.resume) {
        navigate(`/campaign/papers/${overview.resume.paper_id}/claims/${overview.resume.usage_id}?campaign=${slugParam}`);
        return;
      }
      toast.success('All of your campaign claims are judged!');
      navigate('/campaign');
    } catch (error) {
      console.error('Campaign advance failed:', error);
      navigate('/campaign');
    }
  };

  // Navigation functions
  const goToNext = async () => {
    if (isNavigating) return;
    setIsNavigating(true);
    // Always clear validation notes and revalidate prompt when navigating
    setValidationNotes('');
    setShowValidationNotes(false);

    setCurrentQuoteIndex(0);
    setShowScriptModal(false);
    setShowContextModal(false);
    setShowFullTextModal(false);

    if (paperContext && paperContext.onNavigateNext) {
      // Use paper context navigation
      paperContext.onNavigateNext();
    } else if (currentIndex < validationQueue.length - 1) {
      const nextUsage = validationQueue[currentIndex + 1];
      // URL change drives the rest (URL sync effect handles data + setIsNavigating(false))
      navigate(buildUsagePath(nextUsage.id));
    } else if (isCampaign) {
      // End of this paper's queue: jump to the next calibration claim /
      // unfinished paper instead of stalling.
      await advanceCampaign();
      setIsNavigating(false);
    } else {
      setIsNavigating(false);
    }
  };

  const goToPrevious = async () => {
    if (isNavigating) return;
    setIsNavigating(true);
    // Always clear validation notes and revalidate prompt when navigating
    setValidationNotes('');
    setShowValidationNotes(false);

    setCurrentQuoteIndex(0);
    setShowScriptModal(false);
    setShowContextModal(false);
    setShowFullTextModal(false);

    if (paperContext && paperContext.onNavigatePrevious) {
      // Use paper context navigation
      paperContext.onNavigatePrevious();
    } else if (currentIndex > 0) {
      const prevUsage = validationQueue[currentIndex - 1];
      // URL change drives the rest (URL sync effect handles data + setIsNavigating(false))
      navigate(buildUsagePath(prevUsage.id));
    }
  };

  // Fetch fresh statuses for all claims in the current paper to color the progress bar
  useEffect(() => {
    const loadPaperStatuses = async () => {
      // Campaign mode: progress coloring comes from my_validation_status on
      // the claims themselves — never fetch (or show) consensus statuses,
      // which would leak the co-reviewer's activity on overlap papers.
      if (isReadOnly || isCampaign) {
        setPaperStatusMap({});
        return;
      }
      try {
        const paperId = paperContext?.paper?.id || currentUsage?.paper?.id;
        if (!paperId) return;
        const usages = await fetchPaperDatasetUsages(paperId, { ordering: 'instrument__observatory__datasource__slug,instrument__observatory__short_name,instrument__short_name,start_lower,end_upper,id' });
        const map = {};
        (usages || []).forEach(u => { map[u.id] = u.validation_status || 'pending'; });
        setPaperStatusMap(map);
      } catch (e) {
        // Non-fatal; keep existing coloring
        console.warn('Could not refresh paper statuses for progress bar:', e);
      }
    };
    loadPaperStatuses();
    // also refresh when you perform a local validation
  }, [isReadOnly, isCampaign, paperContext?.paper?.id, currentUsage?.paper?.id]);
  
  // Claims list for current paper (for progress bar)
  const paperClaims = useMemo(() => {
    if (paperContext?.datasetUsages && Array.isArray(paperContext.datasetUsages)) {
      return paperContext.datasetUsages;
    }
    const bib = currentUsage?.paper?.bibcode;
    if (!bib) return [];
    return validationQueue.filter(u => u.paper?.bibcode === bib);
  }, [paperContext?.datasetUsages, currentUsage?.paper?.bibcode, validationQueue]);

  const currentPaperClaimIndex = useMemo(() => {
    if (!currentUsage) return -1;
    return paperClaims.findIndex(u => u.id === currentUsage.id);
  }, [paperClaims, currentUsage]);

  const statusToClass = (status) => {
    if (status === 'approved') return 'status-approved';
    if (status === 'rejected') return 'status-rejected';
    if (status === 'needs_review') return 'status-needs_review';
    return 'status-pending';
  };

  const getUsageStatus = (u) => {
    // 1) Local overrides from this session
    if (statusOverrides[u.id]) return statusOverrides[u.id];
    // 2) Current usage state (live)
    if (currentUsage && u.id === currentUsage.id && currentUsage.validation_status) return currentUsage.validation_status;
    // 3) Map from fresh paper-level fetch
    if (paperStatusMap[u.id]) return paperStatusMap[u.id];
    // 4) Validation queue copy (may be fresher than paperContext)
    const q = validationQueue.find(it => it.id === u.id);
    if (q && q.validation_status) return q.validation_status;
    // 5) Fallback to the item itself
    return u.validation_status || 'pending';
  };

  // Returns CSS class for progress bar segments:
  //   - "status-<vote>" if YOU validated (solid color of your vote)
  //   - "validated-by-others" if someone else validated but not you (neutral, no vote color)
  //   - "status-pending" if no validations
  const getSegmentClass = (u) => {
    // Check optimistic override first (from validationQueue update after voting)
    const queueItem = validationQueue.find(it => it.id === u.id);
    const myStatus = queueItem?.my_validation_status || u.my_validation_status || null;
    const consensus = getUsageStatus(u);
    if (myStatus) return statusToClass(myStatus);
    if (consensus !== 'pending') return 'validated-by-others';
    return 'status-pending';
  };

  // Helper function to update paper progress
  const updatePaperProgress = (usage, index) => {
    if (!usage?.paper?.bibcode) return;
    
    const currentBibcode = usage.paper.bibcode;
    const paperUsages = validationQueue.filter(item => item.paper?.bibcode === currentBibcode);
    const currentPaperIndex = paperUsages.findIndex(item => item.id === usage.id);
    
    setPaperProgress({
      current: currentPaperIndex + 1,
      total: paperUsages.length,
      bibcode: currentBibcode,
      overallIndex: index + 1,
      overallTotal: validationQueue.length
    });
  };

  // Navigation to next paper (skip remaining dataset usages from current paper)
  const goToNextPaper = () => {
    if (paperContext && paperContext.onReturnToPaperOverview) {
      // In paper context, go to paper overview instead
      paperContext.onReturnToPaperOverview();
    } else if (!currentUsage?.paper?.bibcode) {
      return;
    } else {
      // Legacy navigation
      const currentBibcode = currentUsage.paper.bibcode;
      
      // Find the next usage that belongs to a different paper
      const nextPaperIndex = validationQueue.findIndex((item, index) => 
        index > currentIndex && item.paper?.bibcode !== currentBibcode
      );
      
      if (nextPaperIndex >= 0) {
        const nextUsage = validationQueue[nextPaperIndex];
        setCurrentIndex(nextPaperIndex);
        setCurrentUsage(nextUsage);
        setCurrentQuoteIndex(0);
        setValidationNotes('');
        setShowValidationNotes(false);
    
        setShowScriptModal(false);
    setShowContextModal(false);
    setShowFullTextModal(false);
        updatePaperProgress(nextUsage, nextPaperIndex);
        
        navigate(buildUsagePath(nextUsage.id));
      }
    }
  };
  
  // Handle quote click to scroll to PDF location
  const handleQuoteClick = (quoteIndex) => {
    setCurrentQuoteIndex(quoteIndex);
    // Increment scroll trigger to force re-scroll even for the same quote
    setScrollTrigger(prev => prev + 1);
  };

  // Validation handler
  const handleValidation = async (status) => {
    if (isReadOnly || !currentUsage || isValidating) return;

    // Campaign consistency rules (mirrored server-side): approve asserts all
    // three components correct; reject requires a note (the rejection reason).
    // An approve always sends all-true checks — the checkboxes only carry
    // information on the reject path.
    const effectiveChecks = status === 'approved'
      ? { mission: true, instrument: true, window: true }
      : claimChecks;
    const effectiveReason = status === 'rejected' ? rejectReason : null;
    if (isCampaign && status === 'rejected'
        && effectiveChecks.mission && effectiveChecks.instrument && effectiveChecks.window
        && !effectiveReason) {
      toast.error('Pick a reason category, or uncheck the incorrect component.');
      return;
    }
    if (isCampaign && effectiveReason === 'other' && !validationNotes.trim()) {
      toast.error("'Other' requires a note.");
      setShowValidationNotes(true);
      return;
    }

    try {
      setIsValidating(true);

      let result;
      if (isCampaign) {
        result = await validateCampaignClaim(campaignSlug, currentUsage.id, {
          validation_status: status,
          mission_correct: effectiveChecks.mission,
          instrument_correct: effectiveChecks.instrument,
          window_correct: effectiveChecks.window,
          reject_reason: effectiveReason,
          validation_notes: validationNotes,
        });
      } else {
        result = await validateDatasetUsage(
          currentUsage.id,
          status,
          validationNotes
        );
      }

      // Update current usage status (campaign mode: my_* fields only — there
      // is no consensus in a campaign response)
      setCurrentUsage(prev => ({
        ...prev,
        ...(isCampaign ? {} : { validation_status: status }),
        my_validation_status: status,
        ...(isCampaign ? {
          my_mission_correct: effectiveChecks.mission,
          my_instrument_correct: effectiveChecks.instrument,
          my_window_correct: effectiveChecks.window,
          my_reject_reason: effectiveReason,
          my_validation_notes: validationNotes,
        } : {
          validated_by_username: result.validated_by,
          validated_at: result.validated_at,
          validation_notes: validationNotes,
        }),
      }));

      // Reflect status in progress bar and local queue
      setStatusOverrides(prev => ({ ...prev, [currentUsage.id]: status }));
      setValidationQueue(prev => prev.map(u => (
        u.id === currentUsage.id
          ? { ...u, ...(isCampaign ? {} : { validation_status: status }), my_validation_status: status }
          : u
      )));

      // Add to validation history
      setValidationHistory(prev => [
        ...prev.slice(-4), // Keep last 4 items
        {
          id: currentUsage.id,
          status: status,
          timestamp: new Date(),
          instrument: currentUsage.instrument?.short_name,
          bibcode: currentUsage.paper?.bibcode
        }
      ]);
      
      // Optimistically update validationCounts so the "your vote" indicator
      // reflects the new vote immediately without waiting for a re-fetch.
      // (validationCounts is always null in campaign mode, so this is a no-op there.)
      const currentUsername = localStorage.getItem('username');
      const anonId = localStorage.getItem('pdl_anonymous_id');
      setValidationCounts(prev => {
        if (!prev) return prev;
        const updatedValidations = prev.validations ? prev.validations.map(v => {
          const isMe = currentUsername ? v.username === currentUsername : v.anonymous_id === anonId;
          return isMe ? { ...v, validation_status: status } : v;
        }) : [];
        const alreadyVoted = prev.validations?.some(v =>
          currentUsername ? v.username === currentUsername : v.anonymous_id === anonId
        );
        const newValidations = alreadyVoted ? updatedValidations : [
          ...updatedValidations,
          { username: currentUsername, anonymous_id: anonId, validation_status: status }
        ];
        const counts = newValidations.reduce((acc, v) => {
          acc[v.validation_status] = (acc[v.validation_status] || 0) + 1;
          return acc;
        }, {});
        return {
          ...prev,
          validations: newValidations,
          total: newValidations.length,
          approved: counts.approved || 0,
          rejected: counts.rejected || 0,
          needs_review: counts.needs_review || 0,
        };
      });

      // Show success toast
      toast.success('Validation submitted!');

      // Campaign: if this vote finished the paper's queue, start fetching the
      // overview NOW so the where-to-next decision overlaps the flash.
      if (isCampaign && currentIndex >= validationQueue.length - 1) {
        campaignAdvancePrefetchRef.current =
          fetchCampaignOverview(campaignSlug).catch(() => null);
      }

      // Flash the claim card briefly, then navigate
      setValidationAnimation(status);
      setTimeout(() => {
        setValidationAnimation(null);
        goToNext();
      }, isCampaign ? 300 : 600);
      
    } catch (error) {
      console.error('Validation failed:', error);
      toast.error(`Failed to validate: ${error.message}`);
      setValidationAnimation(null);
    } finally {
      setIsValidating(false);
    }
  };

  // Prepare PDF annotations and quote-to-annotation mapping
  const { annotations, quoteToAnnotationMap } = useMemo(() => {
    return mapQuotesToAnnotations(
      currentUsage?.supporting_quotes || [],
      currentUsage?.instrument?.short_name
    );
  }, [currentUsage?.supporting_quotes, currentUsage?.instrument?.short_name]);

  // Just use the real data - no special loading data
  const displayUsage = currentUsage;
  const displayProgress = paperProgress;
  const displayStats = stats;

  // Calculate focused annotations for PDF viewer (all regions of the current quote)
  const focusedAnnotationIndex = quoteToAnnotationMap.get(currentQuoteIndex);
  const focusedQuoteIds = useMemo(() => {
    if (focusedAnnotationIndex === undefined) return [];
    
    // Find all annotations that belong to the current quote
    const currentQuote = displayUsage?.supporting_quotes?.[currentQuoteIndex];
    if (!currentQuote) return [];
    
    // Get all annotations that have the same originalQuoteIndex as the current quote
    return annotations
      .filter(annotation => annotation.originalQuoteIndex === currentQuoteIndex)
      .map(annotation => annotation.id);
  }, [focusedAnnotationIndex, currentQuoteIndex, annotations, displayUsage?.supporting_quotes]);
  
  const targetPage = focusedAnnotationIndex !== undefined ? annotations[focusedAnnotationIndex]?.pageNumber : null;

  if (error) {
    return (
      <div className="streamlined-validation error">
        <div className="error-message">Error: {error}</div>
        <button onClick={() => window.location.reload()}>Retry</button>
      </div>
    );
  }

  if (!isLoading && (!validationQueue.length || !currentUsage)) {
    return (
      <div className="streamlined-validation empty">
        <div className="empty-message">
          <h3>{isReadOnly ? 'No public evidence found' : 'No items to validate'}</h3>
          <p>Queue length: {validationQueue.length}</p>
        </div>
      </div>
    );
  }

  // Don't render anything if we're loading and have no data yet
  if (isLoading && !currentUsage) {
    return (
      <div className="streamlined-validation">
        <div className="validation-main">
          <div className="claim-sidebar">
            <div className="paper-header">
              <div className="paper-info">
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <h2 className="paper-title" style={{ margin: 0 }}>
                    <div className="skeleton-box skeleton-w-60" style={{ height: '1rem', display: 'inline-block' }} />
                  </h2>
                </div>
              </div>
            </div>
            <div className="claim-card">
              <div className="claim-content">
                <div className="claim-details">
                  <div className="detail-item compact-mission"><div className="skeleton-box skeleton-w-80" /></div>
                  <div className="detail-item compact-time-range"><div className="skeleton-box skeleton-w-60" /></div>
                </div>
                <div className="supporting-quotes">
                  <div className="skeleton-box skeleton-w-40" style={{ height: '0.75rem', marginBottom: '0.6rem' }} />
                  <div className="quotes-list">
                    {[80, 60, 90, 50, 70].map((w, i) => (
                      <div key={i} className="quote-item quote-item--default">
                        <div className={`skeleton-box skeleton-w-${w}`} style={{ height: '0.7rem' }} />
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="streamlined-validation">
      {/* Main Content: Claim Sidebar + PDF */}
      <div className="validation-main">
        {/* Left: Claim Card Sidebar */}
        <div className="claim-sidebar">
          {/* Paper Header with Navigation */}
          <div className="paper-header">
            <div className="paper-info">
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <h2 className="paper-title" style={{ margin: 0 }}>
                  <button
                    className="btn btn-link p-0"
                    onClick={() => {
                      if (isCampaign) {
                        // Campaign mode: back to the campaign dashboard (the
                        // paper overview would show config/consensus data)
                        navigate('/campaign');
                      } else if (paperContext && paperContext.onReturnToPaperOverview) {
                        paperContext.onReturnToPaperOverview();
                      } else if (isReadOnly && displayUsage?.paper?.bibcode) {
                        navigate(`/public/p/${encodeURIComponent(displayUsage.paper.bibcode)}`);
                      } else if (displayUsage?.paper?.id) {
                        navigate(`/papers/${displayUsage.paper.id}/validate`);
                      }
                    }}
                    title={isCampaign ? 'Return to campaign dashboard' : (isReadOnly ? 'Return to public paper page' : 'Return to paper overview')}
                    style={{ 
                      color: '#0969da',
                      fontSize: 'inherit',
                      fontWeight: 'inherit',
                      textAlign: 'left',
                      textDecoration: 'underline',
                      cursor: 'pointer'
                    }}
                    onMouseEnter={(e) => {
                      e.target.style.color = '#0550ae';
                      e.target.style.textDecoration = 'underline';
                    }}
                    onMouseLeave={(e) => {
                      e.target.style.color = '#0969da';
                      e.target.style.textDecoration = 'underline';
                    }}
                  >
                    {displayUsage?.paper?.bibcode || 'Loading...'}
                  </button>
                  {/* Blind-review indicator (config deliberately hidden) */}
                  {isBlind && (
                    <span
                      style={{
                        display: 'inline-block',
                        marginLeft: '0.5rem',
                        padding: '0.1rem 0.4rem',
                        borderRadius: '0.4rem',
                        background: '#f0f0f0',
                        color: '#57606a',
                        fontSize: '0.8rem',
                        fontWeight: 600
                      }}
                      title="Blind review: the producing configuration is hidden"
                    >
                      {isCampaign && campaignPhase === 'calibration' ? 'calibration' : 'blind review'}
                    </span>
                  )}
                  {/* Configuration badge when available */}
                  {!isBlind && paperContext?.analysis?.configuration_name && (
                    <span
                      style={{
                        display: 'inline-block',
                        marginLeft: '0.5rem',
                        padding: '0.1rem 0.4rem',
                        borderRadius: '0.4rem',
                        background: '#ddf4ff',
                        color: '#0550ae',
                        fontSize: '0.8rem',
                        fontWeight: 600
                      }}
                      title="Configuration"
                    >
                      {getConfigurationDisplayName(paperContext.analysis.configuration_name)}
                    </span>
                  )}
                </h2>
                {(() => {
                  const hasContextIndex = !!paperContext && paperContext.currentUsageIndex !== undefined;
                  const navLock = isNavigating && currentUsage?.id !== usageId;
                  const prevDisabled = isLoading || navLock || (hasContextIndex ? (paperContext.currentUsageIndex <= 0) : (currentIndex === 0));
                  const nextDisabled = isLoading || navLock || (hasContextIndex ? (
                    !paperContext.datasetUsages || paperContext.currentUsageIndex >= paperContext.datasetUsages.length - 1
                  ) : (
                    currentIndex >= validationQueue.length - 1
                  ));
                  const claimNum = hasContextIndex ? paperContext.currentUsageIndex + 1 : displayProgress?.current;
                  const claimTotal = hasContextIndex ? paperContext.datasetUsages.length : displayProgress?.total;
                  return (claimNum != null && claimTotal != null) ? (
                    <div className="claim-nav-inline">
                      <button onClick={goToPrevious} disabled={prevDisabled} className="claim-nav-arrow" title="Previous (P)">‹</button>
                      <span className="claim-nav-counter">{claimNum}/{claimTotal}</span>
                      <button onClick={goToNext} disabled={nextDisabled} className="claim-nav-arrow" title="Next (N)">›</button>
                    </div>
                  ) : null;
                })()}
              </div>
            </div>
          </div>

          {/* Navigation Controls */}
          <div className="navigation-section">
            {/* Compact claim progress bar: shows each claim for this paper */}
            {paperClaims.length > 0 && (
              <div className="claim-progress-bar" role="progressbar" aria-valuemin={0} aria-valuemax={paperClaims.length} aria-valuenow={currentPaperClaimIndex + 1}>
                {paperClaims.map((u, idx) => (
                  <div
                    key={u.id}
                    className={`claim-progress-segment ${getSegmentClass(u)} ${idx === currentPaperClaimIndex ? 'is-current' : ''}`}
                    title={`Claim ${idx + 1}/${paperClaims.length} - ${u.my_validation_status ? 'you: ' + u.my_validation_status.replace('_', ' ') : getUsageStatus(u).replace('_', ' ')}`}
                  />
                ))}
              </div>
            )}
          </div>

          {/* Dataset Usage Claim Details */}
          <div className={`claim-card ${(() => {
            const myStatus = displayUsage.my_validation_status;
            const consensus = displayUsage.validation_status;
            if (myStatus) return `status-${myStatus}`;
            if (consensus && consensus !== 'pending') return 'validated-by-others';
            return '';
          })()} ${validationAnimation ? `flash-${validationAnimation}` : ''}`}>
            
            {/* Claim Content */}
            <div className="claim-content">
                  {/* Claim Details */}
                  <div className="claim-details">
                    {isNavigating ? (
                      <>
                        <div className="detail-item compact-mission"><div className="skeleton-box skeleton-w-80"></div></div>
                        <div className="detail-item compact-time start-time"><div className="skeleton-box skeleton-w-60"></div></div>
                        <div className="detail-item compact-time end-time"><div className="skeleton-box skeleton-w-60"></div></div>
                      </>
                    ) : (
                      <>
                    {/* Instrument on Mission */}
                    <div className="detail-item compact-mission">
                      <span
                        className="instrument-mission-display"
                        onMouseEnter={(e) => {
                          const rect = e.currentTarget.getBoundingClientRect();
                          const position = {
                            x: rect.left,
                            y: rect.top - 10
                          };
                          setTooltipPosition(position);
                          requestAnimationFrame(() => {
                            setShowInstrumentTooltip(true);
                          });
                        }}
                        onMouseLeave={() => {
                          setShowInstrumentTooltip(false);
                          setTooltipPosition(null);
                        }}
                      >
                        <span className="instrument-name">{displayUsage?.instrument?.display_name || displayUsage?.instrument?.full_name || 'Loading...'}</span>
                        <span className="on-connector"> on </span>
                        <span className="mission-name">{displayUsage?.observatory?.display_name || displayUsage?.observatory?.name || 'Loading...'}</span>
                      </span>
                      {displayUsage.validation_status && displayUsage.validation_status !== 'pending' && (
                        <span className={`validation-status-badge status-${displayUsage.validation_status}`}>
                          {displayUsage.validation_status === 'approved' && 'Approved'}
                          {displayUsage.validation_status === 'rejected' && 'Incorrect'}
                          {displayUsage.validation_status === 'needs_review' && 'Review'}
                        </span>
                      )}
                    </div>

                    {/* Time range + action buttons on same line */}
                    <div className="detail-item compact-time-range">
                      <span className="time-connector">from</span>
                      <span className="time-display">
                        <span className="date-part">{formatColoredDateTime(displayUsage?.start_time).date}</span>
                        <span className="time-part">{formatColoredDateTime(displayUsage?.start_time).time}</span>
                      </span>
                      <span className="time-connector">to</span>
                      <span className="time-display">
                        <span className="date-part">{formatColoredDateTime(displayUsage?.end_time).date}</span>
                        <span className="time-part">{formatColoredDateTime(displayUsage?.end_time).time}</span>
                      </span>
                      <div className="claim-more-menu-wrap">
                        <button
                          className="claim-more-btn"
                          title="More info"
                          onClick={() => setShowMoreMenu(m => !m)}
                        >
                          ···
                        </button>
                        {showMoreMenu && (
                          <>
                            <div className="claim-more-backdrop" onClick={() => setShowMoreMenu(false)} />
                            <div className="claim-more-dropdown">
                              {displayUsage?.extra_params && Object.keys(displayUsage.extra_params).length > 0 && (
                                <button className="claim-more-item" onClick={() => { setShowParamsModal(true); setShowMoreMenu(false); }}>
                                  Parameters <span className="claim-more-count">{Object.keys(displayUsage.extra_params).length}</span>
                                </button>
                              )}
                              {displayUsage?.analysis?.python_snippet && (
                                <button className="claim-more-item" onClick={() => { setShowScriptModal(true); setShowMoreMenu(false); }}>
                                  Script
                                  <span className={`script-status-dot ${displayUsage.analysis.is_valid_syntax && displayUsage.analysis.execution_successful ? 'success' : 'error'}`} />
                                </button>
                              )}
                              {/* Context modal exposes configuration_name + per-call
                                  model names — hidden entirely in blind mode */}
                              {!isBlind && paperAnalysis && (
                                <button className="claim-more-item" onClick={() => { setShowContextModal(true); setShowMoreMenu(false); }}>
                                  Context
                                </button>
                              )}
                              {displayUsage?.paper?.id && (
                                <button className="claim-more-item" onClick={async () => {
                                  setShowMoreMenu(false);
                                  if (paperFullText !== null) { setShowFullTextModal(true); return; }
                                  setFullTextLoading(true);
                                  setShowFullTextModal(true);
                                  try {
                                    const details = await fetchPaperDetails(displayUsage.paper.id);
                                    setPaperFullText(details.full_text || '');
                                  } catch {
                                    setPaperFullText('Failed to load full text.');
                                  } finally {
                                    setFullTextLoading(false);
                                  }
                                }}>
                                  Full Text
                                </button>
                              )}
                            </div>
                          </>
                        )}
                      </div>
                    </div>
                      </>
                    )}
                  </div>

                  {/* Supporting Quotes */}
                  <div className="supporting-quotes">
                    <h4>Supporting Evidence ({displayUsage.supporting_quotes?.length || 0} quotes)</h4>
                    <div className="quotes-list">
                      {displayUsage.supporting_quotes?.map((quote, index) => {
                        // Find category for this quote from categorized_quotes
                        const categorizedQuote = displayUsage.categorized_quotes?.find(cq => cq.id === quote.id);
                        const category = categorizedQuote?.category || quote.support_category;
                        
                        return (
                          <div 
                            key={quote.id || index}
                            className={`quote-item quote-item--${category || 'default'} ${index === currentQuoteIndex ? 'active' : ''}`}
                            onClick={() => handleQuoteClick(index)}
                            title="Click to scroll to this quote in the PDF"
                          >
                            <div className="quote-meta">
                              {category && (
                                <span className={`category-badge category-${category}`}>
                                  {category.replace('_', ' ')}
                                </span>
                              )}
                              {quote.page_number && (
                                <span className="page-number">Page {quote.page_number}</span>
                              )}
                            </div>
                            <div className="quote-text">"{quote.quote}"</div>
                          </div>
                        );
                      })}
                    </div>
                  </div>
            </div>
          </div>

          {/* Validation Controls */}
          {!isReadOnly && (() => {
            const myVote = displayUsage.my_validation_status || null;
            const hasVoted = myVote !== null;

            return (
            <div className="validation-section">
              {validationCounts && validationCounts.total > 0 && (
                <button
                  className="toggle-validations-btn"
                  onClick={() => setShowPreviousValidations(true)}
                  title="View previous validations (may bias your judgment)"
                >
                  View previous validations ({validationCounts.total})
                </button>
              )}

              {hasVoted && !wantsToRevalidate ? (
                <div className="my-vote-block">
                  <div className="my-vote-indicator">
                    Your vote: <span className={`my-vote-status ${myVote}`}>
                      {myVote === 'approved' ? 'Correct' : myVote === 'rejected' ? 'Incorrect' : (isCampaign ? 'Unsure' : 'Review')}
                    </span>
                  </div>
                  <button
                    className="toggle-validations-btn"
                    onClick={() => setWantsToRevalidate(true)}
                  >
                    Change your vote
                  </button>
                </div>
              ) : (isCampaign && showRejectPanel) ? (() => {
                const allChecked = claimChecks.mission && claimChecks.instrument && claimChecks.window;
                const needsReason = allChecked && !rejectReason;
                const needsNotes = rejectReason === 'other' && !validationNotes.trim();
                const rejectBlocked = needsReason || needsNotes;
                return (
                <>
                  {/* Reject panel. Rule: "uncheck what's false, or pick why it
                      doesn't count." Unchecked box = misattribution (the box is
                      the reason); all boxes intact = misclassification and a
                      usage-type category is required. */}
                  <div className="claim-reject-panel">
                    <div className="claim-checks-prompt">
                      Uncheck anything that is factually wrong:
                    </div>
                    <div className="claim-checks">
                      {[
                        { key: 'mission', label: 'Mission' },
                        { key: 'instrument', label: 'Instrument' },
                        { key: 'window', label: 'Time window' },
                      ].map(({ key, label }) => (
                        <label key={key} className="claim-check" title={`Is the ${label.toLowerCase()} of this claim correct?`}>
                          <input
                            type="checkbox"
                            checked={claimChecks[key]}
                            onChange={(e) => setClaimChecks(prev => ({ ...prev, [key]: e.target.checked }))}
                            disabled={isLoading || isValidating}
                          />
                          <span>{label}</span>
                        </label>
                      ))}
                    </div>
                    <div className="claim-checks-prompt" style={{ marginTop: '0.45rem' }}>
                      {allChecked
                        ? 'All three are right — so why doesn’t this count as data usage?'
                        : 'Optionally, also pick a reason category:'}
                      <button
                        type="button"
                        className="reject-help-btn"
                        onClick={() => setShowRejectHelp(true)}
                        title="What do these categories mean?"
                      >
                        ?
                      </button>
                    </div>
                    <div className="reject-reason-groups">
                      <div className="reject-reason-group">
                        <span className="reject-reason-group-label">Doesn't use this data</span>
                        <div className="reject-reason-chips">
                          {[
                            { key: 'mention_only', label: 'Mention only' },
                            { key: 'external_summary', label: "Cites others' work" },
                            { key: 'review_reproduction', label: 'Reproduced figure' },
                          ].map(({ key, label }) => (
                            <button key={key} type="button"
                              className={`reject-reason-chip ${rejectReason === key ? 'is-selected' : ''}`}
                              onClick={() => setRejectReason(prev => (prev === key ? null : key))}
                              disabled={isLoading || isValidating}>
                              {label}
                            </button>
                          ))}
                        </div>
                      </div>
                      <div className="reject-reason-group">
                        <span className="reject-reason-group-label">Analyzes no data at all</span>
                        <div className="reject-reason-chips">
                          {[
                            { key: 'infrastructure', label: 'Instrument/design paper' },
                            { key: 'theory_context', label: 'Theory only' },
                          ].map(({ key, label }) => (
                            <button key={key} type="button"
                              className={`reject-reason-chip ${rejectReason === key ? 'is-selected' : ''}`}
                              onClick={() => setRejectReason(prev => (prev === key ? null : key))}
                              disabled={isLoading || isValidating}>
                              {label}
                            </button>
                          ))}
                          <button type="button"
                            className={`reject-reason-chip reject-reason-chip--other ${rejectReason === 'other' ? 'is-selected' : ''}`}
                            onClick={() => setRejectReason(prev => (prev === 'other' ? null : 'other'))}
                            disabled={isLoading || isValidating}>
                            Other…
                          </button>
                        </div>
                      </div>
                    </div>
                  </div>
                  <div className="validation-notes">
                    <textarea
                      id="validation-notes"
                      value={validationNotes}
                      onChange={(e) => setValidationNotes(e.target.value)}
                      placeholder={rejectReason === 'other'
                        ? 'Explain the reason (required for Other)...'
                        : 'Notes (optional — detail always helps the census)...'}
                      rows={2}
                      disabled={isLoading}
                      autoFocus
                    />
                  </div>
                  <div className="validation-controls">
                    <button
                      className="validation-btn reject"
                      onClick={() => handleValidation('rejected')}
                      disabled={isLoading || isValidating || rejectBlocked}
                      title={needsReason
                        ? 'Pick a reason category (or uncheck the incorrect component)'
                        : needsNotes ? "'Other' requires a note" : 'Submit rejection'}
                    >
                      Confirm Incorrect
                    </button>
                    <button
                      className="validation-btn"
                      onClick={() => {
                        setShowRejectPanel(false);
                        setClaimChecks({ mission: true, instrument: true, window: true });
                        setRejectReason(null);
                      }}
                      disabled={isValidating}
                    >
                      Cancel
                    </button>
                  </div>
                </>
                );
              })() : (
                <>
                  <div className="validation-notes">
                    {(showValidationNotes || validationNotes) ? (
                      <textarea
                        id="validation-notes"
                        value={validationNotes}
                        onChange={(e) => setValidationNotes(e.target.value)}
                        placeholder="Add a note about this decision..."
                        rows={2}
                        disabled={isLoading}
                        autoFocus
                      />
                    ) : (
                      <button
                        className="add-note-btn"
                        onClick={() => setShowValidationNotes(true)}
                        disabled={isLoading}
                      >
                        + Add note
                      </button>
                    )}
                  </div>
                  <div className="validation-controls">
                    <button
                      className="validation-btn approve"
                      onClick={() => handleValidation('approved')}
                      disabled={isLoading || isValidating}
                      title={isCampaign ? 'Correct — mission, instrument, and time window all check out' : 'Approve'}
                    >
                      Correct
                    </button>
                    <button
                      className="validation-btn reject"
                      onClick={() => {
                        if (isCampaign) {
                          // Two-step in campaign mode: open the what's-wrong
                          // panel instead of submitting immediately.
                          setShowRejectPanel(true);
                        } else {
                          handleValidation('rejected');
                        }
                      }}
                      disabled={isLoading || isValidating}
                      title={isCampaign ? 'Incorrect — you will be asked what is wrong' : 'Reject'}
                    >
                      Incorrect
                    </button>
                    <button
                      className="validation-btn review"
                      onClick={() => handleValidation('needs_review')}
                      disabled={isLoading || isValidating}
                      title={isCampaign ? "Unsure — can't verify from the paper" : 'Needs Review'}
                    >
                      {isCampaign ? 'Unsure' : 'Review'}
                    </button>
                  </div>
                </>
              )}
            </div>
            );
          })()}

        </div>



        {/* Right: PDF Viewer */}
        <div className="pdf-section">
          {pdf ? (
            <ValidationProvider bibcode={currentUsage.paper.bibcode}>
              <div className="pdf-content">
                {/* PDF Search Bar */}
                {isSearchVisible && (
                  <PDFSearch
                    searchQuery={searchQuery}
                    setSearchQuery={setSearchQuery}
                    totalMatches={totalMatches}
                    currentMatchIndex={currentMatchIndex}
                    isSearching={isSearching}
                    onNextMatch={goToNextMatch}
                    onPreviousMatch={goToPreviousMatch}
                    onClose={clearSearch}
                  />
                )}
                
                <PDFDocument
                  pdf={pdf}
                  numPages={numPages}
                  annotations={annotations}
                  focusedQuoteIds={focusedQuoteIds}
                  targetPage={targetPage}
                  scrollTrigger={scrollTrigger}
                  searchMatches={searchResults}
                  currentMatchIndex={currentMatchIndex}
                  getMatchesForPage={getMatchesForPage}
                />
              </div>
            </ValidationProvider>
          ) : (
            <div className="pdf-loading">
              {pdfLoading ? 'Loading PDF...' : 'No PDF available'}
            </div>
          )}
        </div>

      </div>

      {/* Custom Tooltip - Positioned outside main content */}
      {showInstrumentTooltip && tooltipPosition && (
        <div 
          className="instrument-tooltip"
          style={{
            left: `${tooltipPosition.x}px`,
            top: `${tooltipPosition.y}px`,
            transform: 'translateY(-100%)'
          }}
        >
          <div className="tooltip-line">
            <strong>Instrument:</strong> {displayUsage?.instrument?.full_name || displayUsage?.instrument?.short_name}
          </div>
          <div className="tooltip-line">
            <strong>Mission:</strong> {displayUsage?.observatory?.name || displayUsage?.observatory?.short_name}
          </div>
          {displayUsage?.instrument?.data_source && (
            <div className="tooltip-line">
              <strong>Data Source:</strong> {displayUsage.instrument.data_source.name}
            </div>
          )}
        </div>
      )}

      {/* Parameters Modal - Positioned outside main content */}
      {showParamsModal && displayUsage?.extra_params && (
        <div className="modal-overlay" onClick={(e) => e.target === e.currentTarget && setShowParamsModal(false)}>
          <div className="context-modal" style={{ width: '480px' }}>
            <div className="context-modal-header">
              <h2>Parameters</h2>
              <button className="modal-close" onClick={() => setShowParamsModal(false)}>&times;</button>
            </div>
            <div className="context-modal-body">
            <div className="params-modal-content">
              {Object.entries(displayUsage?.extra_params || {}).map(([key, value]) => {
                // Smart formatting based on value type and length
                let formattedValue;
                let valueClass = 'param-value';
                
                if (value === null || value === undefined) {
                  formattedValue = 'null';
                  valueClass += ' param-null';
                } else if (typeof value === 'boolean') {
                  formattedValue = value.toString();
                  valueClass += ' param-boolean';
                } else if (typeof value === 'number') {
                  formattedValue = value.toString();
                  valueClass += ' param-number';
                } else if (typeof value === 'string') {
                  formattedValue = value;
                  valueClass += ' param-string';
                } else if (Array.isArray(value)) {
                  formattedValue = JSON.stringify(value, null, 2);
                  valueClass += ' param-array';
                } else if (typeof value === 'object') {
                  formattedValue = JSON.stringify(value, null, 2);
                  valueClass += ' param-object';
                } else {
                  formattedValue = JSON.stringify(value);
                  valueClass += ' param-unknown';
                }
                
                return (
                  <div key={key} className="param-line">
                    <span className="param-key">{key}:</span>
                    <span className={valueClass}>
                      {formattedValue}
                    </span>
                  </div>
                );
              })}
            </div>
            </div>
          </div>
        </div>
      )}

      {/* Script Modal */}
      {showScriptModal && displayUsage?.analysis && (
        <ScriptModal
          usage={{
            python_snippet: displayUsage.analysis.python_snippet,
            script_analysis: displayUsage.analysis,
            observatory: {
              display_name: displayUsage.observatory?.display_name || displayUsage.observatory?.name || displayUsage.observatory?.short_name,
              name: displayUsage.observatory?.name || displayUsage.observatory?.short_name,
            },
            instrument: {
              display_name: displayUsage.instrument?.display_name || displayUsage.instrument?.full_name || displayUsage.instrument?.short_name,
              full_name: displayUsage.instrument?.full_name || displayUsage.instrument?.short_name,
            },
            start_time: displayUsage.start_time,
            end_time: displayUsage.end_time,
          }}
          onClose={() => setShowScriptModal(false)}
        />
      )}

      {/* Full Text Modal */}
      {showFullTextModal && (
        <div className="modal-overlay" onClick={(e) => e.target === e.currentTarget && setShowFullTextModal(false)}>
          <div className="context-modal" style={{ width: '800px' }}>
            <div className="context-modal-header">
              <h2>Full Text</h2>
              <span style={{ fontSize: '0.8rem', color: '#656d76' }}>{displayUsage?.paper?.bibcode}</span>
              <button className="modal-close" onClick={() => setShowFullTextModal(false)}>&times;</button>
            </div>
            <div className="context-modal-body">
              {fullTextLoading ? (
                <p style={{ color: '#656d76', textAlign: 'center', padding: '1.5rem' }}>Loading full text...</p>
              ) : paperFullText ? (
                <pre className="structured-data" style={{ maxHeight: 'none', whiteSpace: 'pre-wrap', wordBreak: 'break-word', fontSize: '0.85rem', lineHeight: '1.5' }}>
                  {paperFullText}
                </pre>
              ) : (
                <p style={{ color: '#656d76', textAlign: 'center', padding: '1.5rem' }}>No full text available for this paper.</p>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Previous Validations Modal */}
      {showPreviousValidations && validationCounts && (
        <div className="modal-overlay" onClick={(e) => e.target === e.currentTarget && setShowPreviousValidations(false)}>
          <div className="context-modal" style={{ width: '420px' }}>
            <div className="context-modal-header">
              <h2>Previous Validations</h2>
              <button className="modal-close" onClick={() => setShowPreviousValidations(false)}>&times;</button>
            </div>
            <div className="context-modal-body">
              <div className="validation-counts-badge" title="Total validations submitted by all reviewers">
                <span className="validation-counts-label">
                  {validationCounts.total} validation{validationCounts.total !== 1 ? 's' : ''}:
                </span>
                {validationCounts.approved > 0 && (
                  <span className="validation-count approved">{validationCounts.approved} correct</span>
                )}
                {validationCounts.rejected > 0 && (
                  <span className="validation-count rejected">{validationCounts.rejected} incorrect</span>
                )}
                {validationCounts.needs_review > 0 && (
                  <span className="validation-count needs-review">{validationCounts.needs_review} review</span>
                )}
              </div>
              {validationCounts.validations && validationCounts.validations.length > 0 && (
                <div className="validations-list">
                  {validationCounts.validations.map((v, i) => (
                    <div key={i} className={`validation-list-item status-${v.validation_status}`}>
                      <span className="validation-list-user">{v.username || 'Anonymous'}</span>
                      <span className={`validation-status-badge status-${v.validation_status}`}>
                        {v.validation_status === 'approved' ? 'Correct' : v.validation_status === 'rejected' ? 'Incorrect' : 'Review'}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Reject-category help modal (campaign mode) */}
      {showRejectHelp && (
        <div className="modal-overlay" onClick={(e) => e.target === e.currentTarget && setShowRejectHelp(false)}>
          <div className="context-modal" style={{ width: '560px' }}>
            <div className="context-modal-header">
              <h2>Rejecting a claim</h2>
              <button className="modal-close" onClick={() => setShowRejectHelp(false)}>&times;</button>
            </div>
            <div className="context-modal-body reject-help-body">
              <p><strong>The rule: uncheck what's false, or pick why it doesn't count.</strong></p>
              <p>
                If the mission, instrument, or time window is <em>factually wrong</em>
                (wrong spacecraft member, wrong sibling instrument, a time span the
                paper never asserts), uncheck that box — no category needed, the box
                is the reason.
              </p>
              <p>
                If all three are correctly identified but the paper doesn't actually
                <em> use</em> the data, pick a category:
              </p>
              <h4>Doesn't use this data</h4>
              <ul>
                <li><strong>Mention only</strong> — the data appears as background or
                  context, never analyzed. <em>Ex: "CMEs were observed by LASCO during
                  this period" in an introduction.</em></li>
                <li><strong>Cites others' work</strong> — the paper discusses another
                  work's analysis of this data without doing its own. <em>Ex: a meeting
                  abstract summarizing external SOHO/CDS results.</em></li>
                <li><strong>Reproduced figure</strong> — a figure from a cited paper is
                  reprinted; the analysis happened there. <em>Ex: a review reprinting an
                  AIA figure from Downs et al. 2013.</em></li>
              </ul>
              <h4>Analyzes no data at all</h4>
              <ul>
                <li><strong>Instrument/design paper</strong> — describes an instrument
                  or data system rather than analyzing observations. <em>Ex: the 1995
                  ISTP data-systems paper. (A commissioning-data analysis section DOES
                  count as usage.)</em></li>
                <li><strong>Theory only</strong> — purely theoretical; datasets referenced
                  generically, none analyzed.</li>
              </ul>
              <p className="reject-help-note">
                Composite products (OMNI-style): if the paper names only the composite,
                a component claim is factually wrong — uncheck <strong>Mission</strong>.
                If the component is mentioned but only the merged product is analyzed —
                <strong> Mention only</strong> + a note.
              </p>
              <p className="reject-help-note">
                <strong>Other…</strong> requires a note. Notes are welcome on every
                verdict — they feed the usage-type census.
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Paper Context Modal */}
      {!isBlind && showContextModal && paperAnalysis && (
        <div className="modal-overlay" onClick={(e) => e.target === e.currentTarget && setShowContextModal(false)}>
          <div className="context-modal">
            <div className="context-modal-header">
              <h2>Context</h2>
              {paperAnalysis.configuration_name && (
                <span className="config-badge">
                  {paperAnalysis.configuration_name.charAt(0).toUpperCase() + paperAnalysis.configuration_name.slice(1)}
                </span>
              )}
              <button className="modal-close" onClick={() => setShowContextModal(false)}>&times;</button>
            </div>
            <div className="context-modal-body">
              {paperAnalysis.instruments_details && (
                <div className="context-modal-section">
                  <h4>Instrument Details from Paper Analysis</h4>
                  <div className="markdown-content"
                       dangerouslySetInnerHTML={{
                         __html: paperAnalysis.instruments_details
                           .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
                           .replace(/\*(.*?)\*/g, '<em>$1</em>')
                           .replace(/^### (.+)$/gm, '<h3>$1</h3>')
                           .replace(/^## (.+)$/gm, '<h2>$1</h2>')
                           .replace(/^# (.+)$/gm, '<h1>$1</h1>')
                           .replace(/\n/g, '<br>')
                       }}
                  />
                </div>
              )}
              {paperAnalysis.structured_instruments_details && (
                <div className="context-modal-section">
                  <h4>Structured Instrument Data</h4>
                  <pre className="structured-data">{JSON.stringify(paperAnalysis.structured_instruments_details, null, 2)}</pre>
                </div>
              )}
              {!paperAnalysis.instruments_details && !paperAnalysis.structured_instruments_details && (
                <p style={{ color: '#656d76', textAlign: 'center', padding: '1.5rem' }}>No paper analysis data available.</p>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
