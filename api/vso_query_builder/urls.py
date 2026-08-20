from django.urls import path

from .campaign_views import (
    CampaignOverviewView,
    CampaignPaperClaimsView,
    CampaignClaimValidationView,
    CampaignRubricView,
)
from .views import (
    PaperUploadView,
    ListPapersView,
    MyPapersView,
    PaperDetailView,
    SearchQuotesView,
    OnePaperAnalysisView,
    AnalysisDetailView,
    PaperAnalysisView,
    PaperScriptParamSearchView,
    UsageByMissionAPIView,
    MissionLaunchesView,
    SolarEventsView,
    DatasetUsageListView,
    DatasetUsageDetailView,
    DatasetUsageStatsView,
    DatasetUsageValidationView,
    DatasetUsageValidationsListView,
    ValidationKappaView,
    ValidationQueueView,
    ValidationStatsView,
    PaperPDFAnnotationsView,
    PaperPDFView,
    PublicPaperPDFView,
    PaperValidationQueueView,
    PaperValidationQueueStatsView,
    PaperValidationOverviewView,
    PaperDatasetUsagesView,
    PaperValidationStatsView,
    NextPaperInQueueView,
    PaperConfigurationComparisonView,
    AggregateConfigurationComparisonView,
    PublicPaperValidatedUsagesView,
    PublicValidatedPapersListView,
    PublicValidatedPapersCSVView,
    PublicPapersFilterOptionsView,
    SimilarPapersView,
    PaperTagsListView,
    AvailableConfigurationsView,
    MonitoringDashboardView,
    CostMonitoringView,
    UserProfileView,
    PipelineTreeView,
    BatchJobListView,
    BatchJobPapersView,
    PublicPaperInstrumentMentionsView,
    PhenomenonMentionValidationView,
    PhenomenonValidationQueueView,
    PaperPhenomenaView,
    PhenomenaQueuePapersView,
)

urlpatterns = [
    path('upload/', PaperUploadView.as_view(), name='paper_upload'),
    path('papers/', ListPapersView.as_view(), name='list_papers'),  # New URL for listing papers
    path('my_papers/', MyPapersView.as_view(), name='my_papers'),  # New URL for listing papers
    path('papers/<uuid:pk>/', PaperDetailView.as_view(), name='paper_detail'),  # New URL for fetching paper details
    path('papers/<uuid:paper_id>/analysis/', OnePaperAnalysisView.as_view(), name='paper-analysis'),
    path('papers/<str:bibcode>/pdf-annotations/', PaperPDFAnnotationsView.as_view(), name='paper-pdf-annotations'),
    path('papers/<str:bibcode>/pdf/', PaperPDFView.as_view(), name='paper-pdf'),
    path('papers/search_by_script_params/', PaperScriptParamSearchView.as_view(), name='paper-script-param-search'), # Add this line
    path('search/', SearchQuotesView.as_view(), name='search_quotes'),
    path('paper-analyses/', PaperAnalysisView.as_view(), name='paper-analyses'),
    
    # Analysis-centric endpoints
    path('analyses/<int:analysisId>/', AnalysisDetailView.as_view(), name='analysis-detail'),
    path('analyses/<int:analysisId>/pipeline-tree/', PipelineTreeView.as_view(), name='analysis-pipeline-tree'),
    
    path("usage_by_mission/", UsageByMissionAPIView.as_view(), name="usage-by-mission"),
    path('mission-launches/', MissionLaunchesView.as_view(), name='mission-launches'),
    path('solar-events/', SolarEventsView.as_view(), name='solar-events'),

    # Dataset Usage endpoints
    path('dataset-usages/', DatasetUsageListView.as_view(), name='dataset-usage-list'),
    path('dataset-usages/<uuid:id>/', DatasetUsageDetailView.as_view(), name='dataset-usage-detail'),
    path('dataset-usages/stats/', DatasetUsageStatsView.as_view(), name='dataset-usage-stats'),
    
    # Validation endpoints
    path('dataset-usages/<uuid:usage_id>/validate/', DatasetUsageValidationView.as_view(), name='dataset-usage-validate'),
    path('dataset-usages/<uuid:usage_id>/validations/', DatasetUsageValidationsListView.as_view(), name='dataset-usage-validations-list'),
    path('validation/queue/', ValidationQueueView.as_view(), name='validation-queue'),
    path('validation/stats/', ValidationStatsView.as_view(), name='validation-stats'),
    path('validation/kappa/', ValidationKappaView.as_view(), name='validation-kappa'),
    
    # Paper-centric validation endpoints
    path('papers/validation-queue/', PaperValidationQueueView.as_view(), name='paper-validation-queue'),
    path('papers/validation-queue/stats/', PaperValidationQueueStatsView.as_view(), name='paper-validation-queue-stats'),
    path('papers/<uuid:paper_id>/validation-overview/', PaperValidationOverviewView.as_view(), name='paper-validation-overview'),
    path('papers/<uuid:paper_id>/dataset-usages/', PaperDatasetUsagesView.as_view(), name='paper-dataset-usages'),
    path('papers/<uuid:paper_id>/validation-stats/', PaperValidationStatsView.as_view(), name='paper-validation-stats'),
    path('papers/<uuid:paper_id>/next-paper/', NextPaperInQueueView.as_view(), name='next-paper-in-queue'),
    path('papers/<uuid:paper_id>/compare-configurations/', PaperConfigurationComparisonView.as_view(), name='paper-configuration-comparison'),
    path('papers/aggregate-configuration-comparison/', AggregateConfigurationComparisonView.as_view(), name='aggregate-configuration-comparison'),
    path('papers/tags/', PaperTagsListView.as_view(), name='paper-tags-list'),
    path('configurations/', AvailableConfigurationsView.as_view(), name='available-configurations'),

    # Validation campaign endpoints (blinded claim-level review)
    path('validation-campaigns/<slug:slug>/overview/',
         CampaignOverviewView.as_view(), name='campaign-overview'),
    path('validation-campaigns/<slug:slug>/rubric/',
         CampaignRubricView.as_view(), name='campaign-rubric'),
    path('validation-campaigns/<slug:slug>/papers/<uuid:paper_id>/claims/',
         CampaignPaperClaimsView.as_view(), name='campaign-paper-claims'),
    path('validation-campaigns/<slug:slug>/claims/<uuid:usage_id>/validate/',
         CampaignClaimValidationView.as_view(), name='campaign-claim-validate'),

    # User profile
    path('me/', UserProfileView.as_view(), name='user-profile'),

    # Monitoring
    path('monitoring/dashboard/', MonitoringDashboardView.as_view(), name='monitoring-dashboard'),
    path('monitoring/costs/', CostMonitoringView.as_view(), name='monitoring-costs'),

    # Batch job monitoring
    path('batch-jobs/', BatchJobListView.as_view(), name='batch-job-list'),
    path('batch-jobs/<int:batch_id>/papers/', BatchJobPapersView.as_view(), name='batch-job-papers'),

    # Phenomenon validation endpoints
    path('phenomenon-mentions/<uuid:mention_id>/validate/', PhenomenonMentionValidationView.as_view(), name='phenomenon-mention-validate'),
    path('phenomenon-mentions/validation-queue/', PhenomenonValidationQueueView.as_view(), name='phenomenon-validation-queue'),
    path('phenomenon-mentions/papers-queue/', PhenomenaQueuePapersView.as_view(), name='phenomenon-papers-queue'),
    path('papers/<uuid:paper_id>/phenomena/', PaperPhenomenaView.as_view(), name='paper-phenomena'),

    # Public endpoint (no auth)
    path('public/papers/<str:bibcode>/validated-usages/', PublicPaperValidatedUsagesView.as_view(), name='public-paper-validated-usages'),
    path('public/papers/<str:bibcode>/pdf/', PublicPaperPDFView.as_view(), name='public-paper-pdf'),
    path('public/papers/<str:bibcode>/instrument-mentions/', PublicPaperInstrumentMentionsView.as_view(), name='public-paper-instrument-mentions'),
    path('public/papers/validated/', PublicValidatedPapersListView.as_view(), name='public-validated-papers'),
    path('public/papers/csv/', PublicValidatedPapersCSVView.as_view(), name='public-validated-papers-csv'),
    path('public/papers/filter-options/', PublicPapersFilterOptionsView.as_view(), name='public-papers-filter-options'),
    path('public/papers/<str:bibcode>/similar/', SimilarPapersView.as_view(), name='public-similar-papers'),
]
