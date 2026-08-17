import axios from 'axios';
import { API_ENDPOINTS, BASE_URL } from './apiEndpoints';
import { toast } from 'react-toastify';


const authAxios = axios.create({
  baseURL: BASE_URL,
});

authAxios.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('access_token');
    if (token) {
      config.headers['Authorization'] = `Bearer ${token}`;
    }
    return config;
  },
  (error) => {
    return Promise.reject(error);
  }
);

authAxios.interceptors.response.use(
  response => response,
  async error => {
    const originalRequest = error.config;

    // If we get a 401 and we haven't already tried a refresh, attempt to refresh the token
    if (error.response && error.response.status === 401 && !originalRequest._retry) {
      originalRequest._retry = true;
      try {
        const refreshToken = localStorage.getItem('refresh_token');
        const refreshResponse = await axios.post(API_ENDPOINTS.REFRESH_TOKEN, {
          refresh: refreshToken,
        });
        const { access } = refreshResponse.data;
        localStorage.setItem('access_token', access);
        // Retry the original request with new token
        return authAxios(originalRequest);
      } catch (refreshError) {
        // Refresh failed: fall through to logout handling below
      }
    }

    // For any 401 (including after retry), clear session and redirect
    if (error.response && error.response.status === 401) {
      // Clear stored credentials
      localStorage.removeItem('access_token');
      localStorage.removeItem('refresh_token');
      localStorage.removeItem('username');

      // Redirect to public page and signal that the login modal should open
      window.location.href = '/public/papers?login=1';
    }

    return Promise.reject(error);
  }
);



export const fetchPaperDetails = async (paperId) => {
    const response = await fetch(API_ENDPOINTS.generate.PAPER_DETAIL(paperId)); // Use LIST_PAPERS and append the paper ID
    if (!response.ok) {
        throw new Error('Failed to fetch paper details');
    }
    return await response.json();
};

export const loginUser = async (username, password) => {
  try {
    const response = await axios.post(API_ENDPOINTS.LOGIN, {
      username,
      password,
    });
    localStorage.setItem('username', username); // Store the username in local storage
    return response;
  } catch (error) {
    throw error;
  }
};

export const logoutUser = () => {
  localStorage.removeItem('access_token');
  localStorage.removeItem('refresh_token');
  localStorage.removeItem('username');
};

/**
 * Fetches details for a specific dataset usage
 * @param {string} usageId - UUID of the dataset usage
 * @returns {Promise<Object>} - Dataset usage details with supporting quotes
 */
export const fetchDatasetUsageDetail = async (usageId) => {
  try {
    const response = await authAxios.get(API_ENDPOINTS.generate.DATASET_USAGE_DETAIL(usageId));
    return response.data;
  } catch (error) {
    console.error(`Failed to fetch dataset usage details for usage ${usageId}:`, error);
    throw error;
  }
};

/**
 * Fetches all paper analyses for a given paper ID
 * @param {string} paperId - The UUID of the paper
 * @returns {Promise<Array>} Array of paper analysis objects
 */
export const fetchPaperAnalysis = async (paperId, { configuration_name, view } = {}) => {
  try {
    const params = {};
    if (configuration_name) params.configuration_name = configuration_name;
    if (view) params.view = view;
    const response = await authAxios.get(API_ENDPOINTS.generate.PAPER_ANALYSIS(paperId), { params });
    return response.data; // Now returns array
  } catch (error) {
    console.error('Failed to fetch paper analysis:', error);
    throw error;
  }
};

/**
 * Fetch a specific analysis by analysis ID
 * @param {string} analysisId - The UUID of the analysis
 * @returns {Promise<Object>} The analysis object
 */
export const fetchAnalysisById = async (analysisId) => {
  try {
    const response = await authAxios.get(`${API_ENDPOINTS.BUILDER_BASE}/analyses/${analysisId}/`);
    return response.data;
  } catch (error) {
    console.error('Failed to fetch analysis by ID:', error);
    throw error;
  }
};

/**
 * Fetch the pipeline execution tree for an analysis
 * @param {string|number} analysisId - The ID of the analysis
 * @returns {Promise<Array>} Array of root PipelineNode objects (tree structure)
 */
export const fetchAnalysisPipelineTree = async (analysisId) => {
  const response = await authAxios.get(`${API_ENDPOINTS.BUILDER_BASE}/analyses/${analysisId}/pipeline-tree/`);
  return response.data;
};

/**
 * Fetch hierarchical validation overview for a paper
 * @param {string} paperId - The UUID of the paper
 * @returns {Promise<Array>} Array of analysis objects with their dataset usages and validation stats
 */
export const fetchPaperValidationOverview = async (paperId) => {
  try {
    const response = await authAxios.get(`${API_ENDPOINTS.BUILDER_BASE}/papers/${paperId}/validation-overview/`);
    return response.data;
  } catch (error) {
    console.error('Failed to fetch paper validation overview:', error);
    throw error;
  }
};

export const fetchUsageByMission = async () => {
  const resp = await axios.get(API_ENDPOINTS.USAGE_BY_MISSION);
  return resp.data;
};


/**
 * Fetches mission launch data
 * @returns {Promise<Array>} Array of mission launch objects
 */
export const fetchMissionLaunches = async () => {
  try {
    const response = await axios.get(API_ENDPOINTS.MISSION_LAUNCHES);
    return response.data;
  } catch (error) {
    console.error('Failed to fetch mission launches:', error);
    throw error;
  }
};

/**
 * Fetches solar event data
 * @returns {Promise<Array>} Array of solar event objects
 */
export const fetchSolarEvents = async () => {
  try {
    const response = await axios.get(API_ENDPOINTS.SOLAR_EVENTS);
    return response.data;
  } catch (error) {
    console.error('Failed to fetch solar events:', error);
    throw error;
  }
};

/**
 * Fetches PDF URL for a given bibcode
 * @param {string} bibcode - The bibcode of the paper
 * @returns {Promise<Object>} - Object containing PDF URL and metadata
 */
export const fetchPaperPDF = async (bibcode) => {
  try {
    const response = await authAxios.get(API_ENDPOINTS.generate.PAPER_PDF(bibcode));
    return response.data;
  } catch (error) {
    console.error(`Failed to fetch PDF URL for bibcode ${bibcode}:`, error);
    throw error;
  }
};

/**
 * Fetches PDF annotations for a given bibcode from database
 * @param {string} bibcode - The bibcode of the paper
 * @returns {Promise<Object>} - Object containing PDF annotations data
 */
export const fetchPaperPDFAnnotations = async (bibcode) => {
  try {
    const response = await authAxios.get(API_ENDPOINTS.generate.PAPER_PDF_ANNOTATIONS(bibcode));
    return response.data;
  } catch (error) {
    console.error(`Failed to fetch PDF annotations for bibcode ${bibcode}:`, error);
    throw error;
  }
};

/**
 * Fetches validation queue (dataset usages needing validation)
 * @param {Object} filters - Filter options
 * @returns {Promise<Array>} - List of dataset usages pending validation
 */
export const fetchValidationQueue = async (filters = {}) => {
  const { validation_status, instrument, observatory, has_quotes, ordering } = filters;

  const params = new URLSearchParams();

  if (validation_status) params.append('validation_status', validation_status);
  if (instrument) params.append('instrument', instrument);
  if (observatory) params.append('observatory', observatory);
  if (has_quotes) params.append('has_quotes', has_quotes);
  if (ordering) params.append('ordering', ordering);

  try {
    const response = await authAxios.get(API_ENDPOINTS.VALIDATION_QUEUE, { params });
    // Handle paginated response - ValidationQueueView uses default pagination
    return response.data.results || response.data || [];
  } catch (error) {
    console.error('Failed to fetch validation queue:', error);
    throw error;
  }
};

/**
 * Returns the anonymous tracking UUID stored in localStorage,
 * creating and persisting one if it doesn't exist yet.
 */
function getOrCreateAnonymousId() {
  const key = 'pdl_anonymous_id';
  let id = localStorage.getItem(key);
  if (!id) {
    id = 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
      const r = (Math.random() * 16) | 0;
      const v = c === 'x' ? r : (r & 0x3) | 0x8;
      return v.toString(16);
    });
    localStorage.setItem(key, id);
  }
  return id;
}

/**
 * Updates validation status for a dataset usage
 * @param {string} usageId - UUID of the dataset usage
 * @param {string} validationStatus - New validation status
 * @param {string} validationNotes - Optional notes
 * @returns {Promise<Object>} - Result of the validation update
 */
export const validateDatasetUsage = async (usageId, validationStatus, validationNotes = '') => {
  try {
    const response = await authAxios.post(
      API_ENDPOINTS.generate.DATASET_USAGE_VALIDATE(usageId),
      {
        validation_status: validationStatus,
        validation_notes: validationNotes,
      },
      {
        headers: { 'X-Anonymous-ID': getOrCreateAnonymousId() },
      }
    );
    return response.data;
  } catch (error) {
    console.error(`Failed to validate dataset usage ${usageId}:`, error);
    throw error;
  }
};

/**
 * Fetches the list of individual validations for a dataset usage
 * @param {string} usageId - UUID of the dataset usage
 * @returns {Promise<Object>} - Validation list and summary counts
 */
export const fetchDatasetUsageValidations = async (usageId) => {
  try {
    const response = await authAxios.get(
      `${API_ENDPOINTS.BUILDER_BASE}/dataset-usages/${usageId}/validations/`
    );
    return response.data;
  } catch (error) {
    console.error(`Failed to fetch validations for usage ${usageId}:`, error);
    throw error;
  }
};

/**
 * Fetches inter-rater kappa for a given scope
 * @param {Object} params - Optional { paper, configuration }
 * @returns {Promise<Object>} - Fleiss kappa and pairwise Cohen kappas
 */
export const fetchValidationKappa = async ({ paper, configuration } = {}) => {
  try {
    const queryParams = new URLSearchParams();
    if (paper) queryParams.append('paper', paper);
    if (configuration) queryParams.append('configuration', configuration);
    const url = `${API_ENDPOINTS.BUILDER_BASE}/validation/kappa/${queryParams.toString() ? '?' + queryParams.toString() : ''}`;
    const response = await authAxios.get(url);
    return response.data;
  } catch (error) {
    console.error('Failed to fetch validation kappa:', error);
    throw error;
  }
};

/**
 * Fetches validation statistics
 * @returns {Promise<Object>} - Validation progress and statistics
 */
export const fetchValidationStats = async () => {
  try {
    const response = await authAxios.get(API_ENDPOINTS.VALIDATION_STATS);
    return response.data;
  } catch (error) {
    console.error('Failed to fetch validation stats:', error);
    throw error;
  }
};

/**
 * Fetches paper validation queue (papers needing validation)
 * @param {Object} filters - Filter options
 * @returns {Promise<Object>} - Paginated response with papers and validation statistics
 */
export const fetchPaperValidationQueue = async (filters = {}) => {
  const { validation_status, configuration_name, ordering, page, page_size, tags, search } = filters;

  const params = new URLSearchParams();

  if (validation_status) params.append('validation_status', validation_status);
  if (configuration_name) params.append('configuration_name', configuration_name);
  if (ordering) params.append('ordering', ordering);
  if (page) params.append('page', page);
  if (page_size) params.append('page_size', page_size);
  if (search) params.append('search', search);
  // Tags can be a string (comma-separated) or an array of strings
  if (tags) {
    if (Array.isArray(tags)) {
      tags.filter(Boolean).forEach(t => params.append('tags', t));
    } else if (typeof tags === 'string') {
      // Support comma-separated in one param as well
      tags.split(',').map(s => s.trim()).filter(Boolean).forEach(t => params.append('tags', t));
    }
  }

  try {
    const response = await authAxios.get(API_ENDPOINTS.PAPER_VALIDATION_QUEUE, { params, timeout: 30000 });
    return response.data;
  } catch (error) {
    console.error('Failed to fetch paper validation queue:', error);
    throw error;
  }
};

/**
 * Fetch counts for pending and complete papers given filters.
 * Only configuration_name and tags are considered for counts.
 * @param {Object} filters
 * @returns {Promise<{pending:number, complete:number}>}
 */
export const fetchPaperValidationQueueCounts = async (filters = {}) => {
  const { configuration_name, tags } = filters;
  const params = new URLSearchParams();
  if (configuration_name) params.append('configuration_name', configuration_name);
  if (tags) {
    if (Array.isArray(tags)) {
      tags.filter(Boolean).forEach(t => params.append('tags', t));
    } else if (typeof tags === 'string') {
      tags.split(',').map(s => s.trim()).filter(Boolean).forEach(t => params.append('tags', t));
    }
  }
  try {
    const response = await authAxios.get(API_ENDPOINTS.PAPER_VALIDATION_QUEUE_STATS, { params, timeout: 15000 });
    return response.data || { pending: 0, complete: 0 };
  } catch (error) {
    console.error('Failed to fetch paper validation queue counts:', error);
    return { pending: 0, complete: 0 };
  }
};

/**
 * Fetches distinct paper tags
 * @returns {Promise<Array<string>>}
 */
export const fetchPaperTags = async () => {
  try {
    const response = await authAxios.get(API_ENDPOINTS.PAPER_TAGS);
    return response.data || [];
  } catch (error) {
    console.error('Failed to fetch paper tags:', error);
    throw error;
  }
};

/**
 * Fetches available LLM configuration names
 * @returns {Promise<Array<string>>}
 */
export const fetchAvailableConfigurations = async () => {
  try {
    const response = await authAxios.get(API_ENDPOINTS.CONFIGURATIONS);
    return response.data || [];
  } catch (error) {
    console.error('Failed to fetch available configurations:', error);
    throw error;
  }
};

/**
 * Fetches all dataset usages for a specific paper
 * @param {string} paperId - UUID of the paper
 * @param {Object} filters - Filter options
 * @returns {Promise<Array>} - List of dataset usages for the paper
 */
export const fetchPaperDatasetUsages = async (paperId, filters = {}) => {
  const { validation_status, has_quotes, ordering } = filters;

  const params = new URLSearchParams();

  if (validation_status) params.append('validation_status', validation_status);
  if (has_quotes) params.append('has_quotes', has_quotes);
  if (ordering) params.append('ordering', ordering);

  try {
    const response = await authAxios.get(API_ENDPOINTS.generate.PAPER_DATASET_USAGES(paperId), { params });
    return response.data;
  } catch (error) {
    console.error(`Failed to fetch dataset usages for paper ${paperId}:`, error);
    throw error;
  }
};

/**
 * Fetches the reviewer's campaign overview (sections, per-user progress, resume pointer)
 * @param {string} slug - Campaign slug (e.g. "val2026")
 * @returns {Promise<Object>} - Campaign overview
 */
export const fetchCampaignOverview = async (slug) => {
  try {
    const response = await authAxios.get(API_ENDPOINTS.generate.CAMPAIGN_OVERVIEW(slug));
    return response.data;
  } catch (error) {
    console.error(`Failed to fetch campaign overview for ${slug}:`, error);
    throw error;
  }
};

/**
 * Fetches the blinded, deduplicated claim list for a paper in a campaign
 * @param {string} slug - Campaign slug
 * @param {string} paperId - UUID of the paper
 * @returns {Promise<Array>} - Claim list
 */
export const fetchCampaignPaperClaims = async (slug, paperId) => {
  try {
    const response = await authAxios.get(API_ENDPOINTS.generate.CAMPAIGN_PAPER_CLAIMS(slug, paperId));
    return response.data;
  } catch (error) {
    console.error(`Failed to fetch campaign claims for paper ${paperId}:`, error);
    throw error;
  }
};

/**
 * Submits a campaign verdict for a claim (propagates to all member usages server-side)
 * @param {string} slug - Campaign slug
 * @param {string} usageId - Representative usage UUID of the claim
 * @param {Object} payload - {validation_status, mission_correct, instrument_correct, window_correct, validation_notes}
 * @returns {Promise<Object>} - {claim_usage_id, propagated_to, my_validation_status}
 */
export const validateCampaignClaim = async (slug, usageId, payload) => {
  try {
    const response = await authAxios.post(
      API_ENDPOINTS.generate.CAMPAIGN_CLAIM_VALIDATE(slug, usageId),
      payload
    );
    return response.data;
  } catch (error) {
    console.error(`Failed to validate campaign claim ${usageId}:`, error);
    throw error;
  }
};

/**
 * Fetches validation statistics for a specific paper
 * @param {string} paperId - UUID of the paper
 * @returns {Promise<Object>} - Paper validation statistics
 */
export const fetchPaperValidationStats = async (paperId) => {
  try {
    const response = await authAxios.get(API_ENDPOINTS.generate.PAPER_VALIDATION_STATS(paperId));
    return response.data;
  } catch (error) {
    console.error(`Failed to fetch paper validation stats for paper ${paperId}:`, error);
    throw error;
  }
};

/**
 * Fetches the next paper in the validation queue
 * @param {string} paperId - UUID of the current paper
 * @param {Object} filters - Filter options
 * @returns {Promise<Object>} - Next paper in queue
 */
export const fetchNextPaperInQueue = async (paperId, filters = {}) => {
  const { validation_status, configuration_name, direction, queue } = filters;

  const params = new URLSearchParams();

  if (validation_status) params.append('validation_status', validation_status);
  if (configuration_name) params.append('configuration_name', configuration_name);
  if (direction) params.append('direction', direction);
  if (queue) params.append('queue', queue);

  try {
    const response = await authAxios.get(API_ENDPOINTS.generate.NEXT_PAPER_IN_QUEUE(paperId), { params });
    return response.data;
  } catch (error) {
    console.error(`Failed to fetch next paper in queue for paper ${paperId}:`, error);
    throw error;
  }
};

export const fetchMonitoringDashboard = async ({ needsReview = 'exclude', configuration = null } = {}) => {
  try {
    const params = { needs_review: needsReview };
    if (configuration) params.configuration = configuration;
    const response = await authAxios.get(API_ENDPOINTS.MONITORING_DASHBOARD, { params });
    return response.data;
  } catch (error) {
    console.error('Failed to fetch monitoring dashboard:', error);
    throw error;
  }
};

export const fetchUserProfile = async () => {
  const response = await authAxios.get(API_ENDPOINTS.ME);
  return response.data;
};

export const fetchCostMonitoring = async ({ startDate, endDate } = {}) => {
  try {
    const params = {};
    if (startDate) params.start_date = startDate;
    if (endDate) params.end_date = endDate;
    const response = await authAxios.get(API_ENDPOINTS.MONITORING_COSTS, { params });
    return response.data;
  } catch (error) {
    console.error('Failed to fetch cost monitoring:', error);
    throw error;
  }
};

const BUILDER_URL = API_ENDPOINTS.BUILDER_BASE;

export const fetchBatchJobs = async ({ status, page = 1, page_size = 25 } = {}) => {
  const params = { page, page_size };
  if (status) params.status = status;
  return (await authAxios.get(`${BUILDER_URL}/batch-jobs/`, { params })).data;
};

export const fetchBatchPapers = async (batchId, { page = 1, page_size = 50 } = {}) =>
  (await authAxios.get(`${BUILDER_URL}/batch-jobs/${batchId}/papers/`, { params: { page, page_size } })).data;


// ---------------------------------------------------------------------------
// Phenomenon validation services
// ---------------------------------------------------------------------------

/**
 * Fetch the phenomenon validation queue (pending mentions).
 */
export const fetchPhenomenonValidationQueue = async (filters = {}) => {
  const params = new URLSearchParams();
  const { validation_status, bibcode, instrument, phenomenon, page, page_size } = filters;
  if (validation_status) params.append('validation_status', validation_status);
  if (bibcode) params.append('bibcode', bibcode);
  if (instrument) params.append('instrument', instrument);
  if (phenomenon) params.append('phenomenon', phenomenon);
  if (page) params.append('page', page);
  if (page_size) params.append('page_size', page_size);
  try {
    const response = await authAxios.get(API_ENDPOINTS.PHENOMENON_VALIDATION_QUEUE, { params });
    return response.data;
  } catch (error) {
    console.error('Failed to fetch phenomenon validation queue:', error);
    throw error;
  }
};

/**
 * Submit a validation judgment for a PhenomenonMention.
 */
export const validatePhenomenonMention = async (mentionId, validationStatus, validationNotes = '') => {
  try {
    const response = await authAxios.post(
      API_ENDPOINTS.generate.PHENOMENON_VALIDATE(mentionId),
      {
        validation_status: validationStatus,
        validation_notes: validationNotes,
      },
      {
        headers: { 'X-Anonymous-ID': getOrCreateAnonymousId() },
      }
    );
    return response.data;
  } catch (error) {
    console.error('Failed to validate phenomenon mention:', error);
    throw error;
  }
};

/**
 * Fetch all phenomenon mentions for a paper.
 */
export const fetchPaperPhenomena = async (paperId, { configuration_name } = {}) => {
  try {
    const params = {};
    if (configuration_name) params.configuration_name = configuration_name;
    const response = await authAxios.get(API_ENDPOINTS.generate.PAPER_PHENOMENA(paperId), { params });
    return response.data;
  } catch (error) {
    console.error('Failed to fetch paper phenomena:', error);
    throw error;
  }
};

/**
 * Fetch the paper-level phenomena queue (papers with pending mentions).
 */
export const fetchPhenomenaQueuePapers = async ({ validation_status = 'pending', search = '', page = 1, page_size = 25 } = {}) => {
  try {
    const params = new URLSearchParams();
    if (validation_status) params.append('validation_status', validation_status);
    if (search) params.append('search', search);
    params.append('page', page);
    params.append('page_size', page_size);
    const response = await authAxios.get(API_ENDPOINTS.PHENOMENON_PAPERS_QUEUE, { params });
    return response.data;
  } catch (error) {
    console.error('Failed to fetch phenomena queue papers:', error);
    throw error;
  }
};
