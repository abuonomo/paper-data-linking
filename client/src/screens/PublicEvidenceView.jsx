import React, { useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { fetchPublicValidatedUsages } from '../services/apiPublic';
import { StreamlinedValidationInterface } from '../components/StreamlinedValidationInterface';
import { useAuth } from '../hooks/useAuth';

function mapUsageForEvidence(usage, paper) {
  return {
    ...usage,
    paper: {
      id: paper?.id,
      bibcode: paper?.bibcode,
      title: paper?.title,
      journal: paper?.journal,
    },
    analysis: usage?.python_snippet
      ? {
          python_snippet: usage.python_snippet,
          is_valid_syntax: usage?.script_analysis?.is_valid_syntax,
          execution_successful: usage?.script_analysis?.execution_successful,
        }
      : null,
    categorized_quotes: (usage.supporting_quotes || []).map((quote) => ({
      id: quote.id,
      category: quote.support_category,
    })),
  };
}

export default function PublicEvidenceView() {
  const { bibcode, usageId } = useParams();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const { isAuthenticated } = useAuth();

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [paper, setPaper] = useState(null);
  const [datasetUsages, setDatasetUsages] = useState([]);

  const includeUnvalidated = searchParams.get('include_unvalidated') === 'true';
  const querySuffix = includeUnvalidated ? '?include_unvalidated=true' : '';

  useEffect(() => {
    let mounted = true;

    async function loadPublicEvidence() {
      try {
        setLoading(true);
        setError(null);

        const data = await fetchPublicValidatedUsages(bibcode, includeUnvalidated);
        if (!mounted) return;

        // Logged-in users should use the standard validation workflow.
        if (isAuthenticated) {
          const targetUsage = (data.usages || []).find((usage) => String(usage.id) === String(usageId))
            || (data.usages || [])[0];
          if (data.paper?.id && targetUsage?.id) {
            navigate(`/papers/${data.paper.id}/validate/${targetUsage.id}`, { replace: true });
            return;
          }
        }

        const mapped = (data.usages || []).map((usage) => mapUsageForEvidence(usage, data.paper));
        setPaper(data.paper || null);
        setDatasetUsages(mapped);

        if (mapped.length > 0 && !mapped.some((u) => String(u.id) === String(usageId))) {
          navigate(
            `/public/p/${encodeURIComponent(bibcode)}/evidence/${mapped[0].id}${querySuffix}`,
            { replace: true }
          );
        }
      } catch (err) {
        if (!mounted) return;
        setError(err?.message || String(err));
      } finally {
        if (mounted) setLoading(false);
      }
    }

    loadPublicEvidence();
    return () => {
      mounted = false;
    };
  }, [bibcode, usageId, includeUnvalidated, isAuthenticated, navigate, querySuffix]);

  const currentUsageIndex = useMemo(
    () => datasetUsages.findIndex((usage) => String(usage.id) === String(usageId)),
    [datasetUsages, usageId]
  );

  const paperContext = useMemo(() => {
    if (!paper) return null;
    return {
      paper,
      datasetUsages,
      currentUsageIndex,
      onReturnToPaperOverview: () => {
        navigate(`/public/p/${encodeURIComponent(bibcode)}${querySuffix}`);
      },
      onNavigateNext: () => {
        if (currentUsageIndex < 0 || currentUsageIndex >= datasetUsages.length - 1) return;
        const nextUsage = datasetUsages[currentUsageIndex + 1];
        navigate(`/public/p/${encodeURIComponent(bibcode)}/evidence/${nextUsage.id}${querySuffix}`);
      },
      onNavigatePrevious: () => {
        if (currentUsageIndex <= 0) return;
        const prevUsage = datasetUsages[currentUsageIndex - 1];
        navigate(`/public/p/${encodeURIComponent(bibcode)}/evidence/${prevUsage.id}${querySuffix}`);
      },
    };
  }, [paper, datasetUsages, currentUsageIndex, navigate, bibcode, querySuffix]);

  if (loading) {
    return <p style={{ color: '#666', fontStyle: 'italic' }}>Loading evidence view...</p>;
  }

  if (error) {
    return <p style={{ color: '#c53030' }}>Error loading evidence view: {error}</p>;
  }

  if (!paperContext || datasetUsages.length === 0) {
    return <p style={{ color: '#666' }}>No public evidence available for this paper.</p>;
  }

  return <StreamlinedValidationInterface paperContext={paperContext} mode="readonly" />;
}
