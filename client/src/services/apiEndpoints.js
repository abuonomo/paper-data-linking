// Base URL is configured at build time via Vite env (VITE_BASE_PROTOCOL/VITE_BASE_URL).
export const BASE_URL = `${import.meta.env.VITE_BASE_PROTOCOL}://${import.meta.env.VITE_BASE_URL}`;
const BUILDER_URL = `${BASE_URL}/builder`;

export const API_ENDPOINTS = {
    BUILDER_BASE: BUILDER_URL,
    LOGIN: `${BASE_URL}/token/`,
    REFRESH_TOKEN: `${BASE_URL}/token/refresh/`,

    // Validation endpoints
    VALIDATION_QUEUE: `${BUILDER_URL}/validation/queue/`,
    VALIDATION_STATS: `${BUILDER_URL}/validation/stats/`,
    VALIDATION_KAPPA: `${BUILDER_URL}/validation/kappa/`,

    // Paper-centric validation endpoints
    PAPER_VALIDATION_QUEUE: `${BUILDER_URL}/papers/validation-queue/`,
    PAPER_VALIDATION_QUEUE_STATS: `${BUILDER_URL}/papers/validation-queue/stats/`,
    PAPER_TAGS: `${BUILDER_URL}/papers/tags/`,
    CONFIGURATIONS: `${BUILDER_URL}/configurations/`,

    // User profile
    ME: `${BUILDER_URL}/me/`,

    // Monitoring
    MONITORING_DASHBOARD: `${BUILDER_URL}/monitoring/dashboard/`,
    MONITORING_COSTS: `${BUILDER_URL}/monitoring/costs/`,

    // Usage explorer endpoints
    USAGE_BY_MISSION: `${BUILDER_URL}/usage_by_mission/`,
    MISSION_LAUNCHES: `${BUILDER_URL}/mission-launches/`,
    SOLAR_EVENTS: `${BUILDER_URL}/solar-events/`,

    // Define an object for generating dynamic endpoints
    generate: {
        PAPER_DETAIL: (uuid) => `${BUILDER_URL}/papers/${uuid}/`,
        PAPER_ANALYSIS: (paperId) => `${BUILDER_URL}/papers/${paperId}/analysis/`,

        // Dataset Usage generate endpoints
        DATASET_USAGE_DETAIL: (usageId) => `${BUILDER_URL}/dataset-usages/${usageId}/`,
        DATASET_USAGE_VALIDATE: (usageId) => `${BUILDER_URL}/dataset-usages/${usageId}/validate/`,

        // PDF endpoints
        PAPER_PDF: (bibcode) => `${BUILDER_URL}/papers/${bibcode}/pdf/`,
        PAPER_PDF_ANNOTATIONS: (bibcode) => `${BUILDER_URL}/papers/${bibcode}/pdf-annotations/`,

        // Paper-centric validation endpoints
        PAPER_DATASET_USAGES: (paperId) => `${BUILDER_URL}/papers/${paperId}/dataset-usages/`,
        PAPER_VALIDATION_STATS: (paperId) => `${BUILDER_URL}/papers/${paperId}/validation-stats/`,
        NEXT_PAPER_IN_QUEUE: (paperId) => `${BUILDER_URL}/papers/${paperId}/next-paper/`,
        PAPER_VALIDATION_OVERVIEW: (paperId) => `${BUILDER_URL}/papers/${paperId}/validation-overview/`,

        // Analysis-centric endpoints
        ANALYSIS_DETAIL: (analysisId) => `${BUILDER_URL}/analyses/${analysisId}/`,

        // Phenomena endpoints
        PHENOMENON_VALIDATE: (mentionId) => `${BUILDER_URL}/phenomenon-mentions/${mentionId}/validate/`,
        PAPER_PHENOMENA: (paperId) => `${BUILDER_URL}/papers/${paperId}/phenomena/`,

        // Validation campaign endpoints (blinded claim-level review)
        CAMPAIGN_OVERVIEW: (slug) => `${BUILDER_URL}/validation-campaigns/${slug}/overview/`,
        CAMPAIGN_PAPER_CLAIMS: (slug, paperId) => `${BUILDER_URL}/validation-campaigns/${slug}/papers/${paperId}/claims/`,
        CAMPAIGN_CLAIM_VALIDATE: (slug, usageId) => `${BUILDER_URL}/validation-campaigns/${slug}/claims/${usageId}/validate/`,
    },

    // Phenomena validation queue
    PHENOMENON_VALIDATION_QUEUE: `${BUILDER_URL}/phenomenon-mentions/validation-queue/`,
    PHENOMENON_PAPERS_QUEUE: `${BUILDER_URL}/phenomenon-mentions/papers-queue/`,
};
