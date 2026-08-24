import csv
import hashlib
import json
import logging
import math
import numpy as np
import pandas as pd
import pytz
from dateutil import parser as date_parser
from urllib.parse import quote
from django.conf import settings
from django.contrib.postgres.fields.ranges import DateTimeTZRange
from django.core.cache import cache
from django.db.models import F, Count
from django.http import Http404, StreamingHttpResponse
from openai import OpenAI
from pathlib import Path
from pgvector.django import CosineDistance
from rest_framework import filters
from rest_framework import status
from rest_framework.generics import ListAPIView
from rest_framework.generics import RetrieveAPIView
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.permissions import IsAuthenticated, AllowAny
from django.db.models import Count, Exists, Max, Min, OuterRef, Q, F, Func, Subquery, Sum, DateTimeField, IntegerField, Value
from django.db.models.functions import Coalesce
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.pagination import PageNumberPagination
from rest_framework_simplejwt.authentication import JWTAuthentication

from .models import DatasetUsage, DatasetUsageValidation, recompute_consensus
from .models import Instrument, Observatory
from .models import InstrumentMention
from .models import LLMCall
from .models import Paper, PaperAnalysis, PipelineNode
from .models import SupportQuote, BatchJob
from .models import Phenomenon, PhenomenonMention, PhenomenonMentionValidation, recompute_phenomenon_consensus
from .serializers import MinimalPaperSerializer, DatasetUsageThinSerializer, DatasetUsageListSerializer, \
    DatasetUsageDetailSerializer
from .serializers import DatasetUsageValidationSerializer
from .serializers import PublicDatasetUsageSerializer, PublicValidatedPaperSerializer, PublicInstrumentMentionSerializer
from .serializers import PhenomenonSerializer, PhenomenonMentionSerializer, PhenomenonMentionValidationSerializer
from .ads_service import ADSService
from django.core.cache import cache
from .serializers import PaperDatasetUsageListSerializer
from .serializers import (
    PaperSerializer,
    SupportQuoteSearchSerializer,
    PaperAnalysisSerializer,
    PaperAnalysisPhenomenaSerializer,
    PDFAnnotationsSerializer,
)
from .serializers import PipelineNodeSerializer
from .serializers import BatchJobSerializer, BatchPaperStatusSerializer
from .kappa_utils import compute_kappa_for_validations

# Optional: Get a logger instance
logger = logging.getLogger(__name__)


def annotate_my_validation(queryset, user):
    """Annotate a DatasetUsage queryset with the requesting user's validation status."""
    if user and user.is_authenticated:
        return queryset.annotate(
            _my_validation_status=Subquery(
                DatasetUsageValidation.objects.filter(
                    dataset_usage=OuterRef('pk'),
                    user=user,
                ).values('validation_status')[:1]
            )
        )
    return queryset


class PublicPapersPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


class PaperUploadView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]
    parser_classes = (MultiPartParser, FormParser)

    def post(self, request, *args, **kwargs):
        paper_serializer = PaperSerializer(data=request.data)
        if paper_serializer.is_valid():
            paper_serializer.save(user=request.user)
            return Response(paper_serializer.data, status=status.HTTP_201_CREATED)
        else:
            return Response(paper_serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class ListPapersView(ListAPIView):
    serializer_class = PaperSerializer
    pagination_class = None
    filter_backends = [filters.SearchFilter]
    search_fields = ['bibcode', 'full_text']

    def get_queryset(self):
        queryset = Paper.objects.all()
        tags = self.request.query_params.getlist('tags', [])
        exclude_tags = self.request.query_params.getlist('exclude_tags', [])

        if tags:
            queryset = queryset.filter(tags__contains=tags)
        if exclude_tags:
            queryset = queryset.exclude(tags__contains=exclude_tags)

        return queryset


class MyPapersView(ListAPIView):
    serializer_class = PaperSerializer
    pagination_class = None
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.SearchFilter]
    search_fields = ['bibcode', 'full_text']

    def get_queryset(self):
        queryset = Paper.objects.filter(user=self.request.user)
        tags = self.request.query_params.getlist('tags', [])
        exclude_tags = self.request.query_params.getlist('exclude_tags', [])

        if tags:
            queryset = queryset.filter(tags__contains=tags)
        if exclude_tags:
            queryset = queryset.exclude(tags__contains=exclude_tags)

        return queryset


class PaperDetailView(RetrieveAPIView):
    queryset = Paper.objects.all()
    serializer_class = PaperSerializer



class OnePaperAnalysisView(APIView):
    """
    API endpoint to retrieve all paper analysis data for a paper
    Returns array of analyses (one per configuration)
    """
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, paper_id):
        try:
            paper = Paper.objects.get(id=paper_id)
            # Get all paper analyses for this paper, ordered by configuration name for consistency
            paper_analyses = PaperAnalysis.objects.filter(paper=paper).order_by('configuration_name', '-created_at')

            configuration_name = request.query_params.get('configuration_name')
            if configuration_name:
                paper_analyses = paper_analyses.filter(configuration_name=configuration_name)
            
            if not paper_analyses.exists():
                return Response(
                    {"error": "No analyses found for this paper"},
                    status=status.HTTP_404_NOT_FOUND
                )
            
            serializer_class = (
                PaperAnalysisPhenomenaSerializer
                if request.query_params.get('view') == 'phenomena'
                else PaperAnalysisSerializer
            )
            serializer = serializer_class(paper_analyses, many=True, context={'request': request})
            return Response(serializer.data, status=status.HTTP_200_OK)
            
        except Paper.DoesNotExist:
            return Response(
                {"error": "Paper not found"},
                status=status.HTTP_404_NOT_FOUND
            )


class AnalysisDetailView(RetrieveAPIView):
    """
    API endpoint to retrieve a specific paper analysis by analysis ID
    """
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]
    queryset = PaperAnalysis.objects.all()
    serializer_class = PaperAnalysisSerializer
    lookup_field = 'id'
    lookup_url_kwarg = 'analysisId'


class PaperValidationOverviewView(APIView):
    """
    API endpoint to get hierarchical validation data for a paper
    Returns analyses with their associated dataset usages for the paper-centric validation workflow
    """
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, paper_id):
        from django.db.models import Count, Q, Case, When, Value, FloatField, ExpressionWrapper
        from django.db.models import Prefetch

        try:
            # OPTIMIZATION: Check if paper exists with a lightweight query
            if not Paper.objects.filter(id=paper_id).exists():
                return Response(
                    {"error": "Paper not found"},
                    status=status.HTTP_404_NOT_FOUND
                )

            # OPTIMIZATION: Compute validation stats in the database, not Python
            # Use aggregation to calculate stats per analysis
            analyses = (
                PaperAnalysis.objects
                .filter(paper_id=paper_id)
                .annotate(
                    total_usages=Count('dataset_usages', distinct=True),
                    pending_count=Count(
                        'dataset_usages',
                        distinct=True,
                        filter=Q(dataset_usages__validation_status='pending')
                    ),
                    approved_count=Count(
                        'dataset_usages',
                        distinct=True,
                        filter=Q(dataset_usages__validation_status='approved')
                    ),
                    rejected_count=Count(
                        'dataset_usages',
                        distinct=True,
                        filter=Q(dataset_usages__validation_status='rejected')
                    ),
                    needs_review_count=Count(
                        'dataset_usages',
                        distinct=True,
                        filter=Q(dataset_usages__validation_status='needs_review')
                    ),
                    validated_count=Count(
                        'dataset_usages',
                        distinct=True,
                        filter=Q(dataset_usages__validation_status__in=['approved', 'rejected'])
                    ),
                )
                .annotate(
                    validation_progress=Case(
                        When(total_usages__gt=0,
                             then=ExpressionWrapper(100.0 * F('validated_count') / F('total_usages'), output_field=FloatField())),
                        default=Value(0.0),
                        output_field=FloatField(),
                    )
                )
                .prefetch_related(
                    Prefetch(
                        'dataset_usages',
                        queryset=(
                            DatasetUsage.objects
                            .select_related('instrument', 'instrument__observatory')
                            .annotate(start_lower=Func(F('observation_window'), function='lower', output_field=DateTimeField()))
                            .order_by('instrument__observatory__short_name', 'instrument__short_name', 'start_lower')
                        )
                    )
                )
                .order_by('configuration_name', '-created_at')
            )

            if not analyses.exists():
                return Response(
                    {"error": "No analyses found for this paper"},
                    status=status.HTTP_404_NOT_FOUND
                )

            # Build hierarchical structure using pre-computed stats
            result = []
            for analysis in analyses:
                analysis_data = {
                    'analysis': PaperAnalysisSerializer(analysis).data,
                    'dataset_usages': PaperDatasetUsageListSerializer(analysis.dataset_usages.all(), many=True).data,
                    'validation_stats': {
                        'total_usages': analysis.total_usages,
                        'pending': analysis.pending_count,
                        'approved': analysis.approved_count,
                        'rejected': analysis.rejected_count,
                        'needs_review': analysis.needs_review_count,
                        'validation_progress': round(float(analysis.validation_progress or 0.0), 1)
                    }
                }
                result.append(analysis_data)

            return Response(result, status=status.HTTP_200_OK)

        except Exception as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class SearchQuotesView(APIView):
    def post(self, request):
        query = request.data.get('query')
        client = OpenAI(api_key=settings.OPENAI_API_KEY)

        # Create a cache key based on the query text
        cache_key = 'search_embedding_' + hashlib.md5(query.encode('utf-8')).hexdigest()

        # Check if embedding exists in cache
        query_embedding = cache.get(cache_key)
        if query_embedding is None:
            client = OpenAI(api_key=settings.OPENAI_API_KEY)
            response = client.embeddings.create(
                input=[query],
                model='text-embedding-3-small'
            )
            query_embedding = response.data[0].embedding
            # Cache the embedding for 1 hour (3600 seconds)
            cache.set(cache_key, query_embedding, timeout=3600)

        # Search using cosine similarity
        results = SupportQuote.objects.annotate(
            distance=CosineDistance('embedding', query_embedding)
        ).order_by('distance')[:10]
        data = SupportQuoteSearchSerializer(results, many=True, context={'request': request}).data
        return Response(data)


class PaperAnalysisView(ListAPIView):
    serializer_class = PaperAnalysisSerializer
    pagination_class = None
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        queryset = PaperAnalysis.objects.all()
        tags = self.request.query_params.getlist('tags', [])
        exclude_tags = self.request.query_params.getlist('exclude_tags', [])

        if tags:
            queryset = queryset.filter(paper__tags__contains=tags)
        if exclude_tags:
            queryset = queryset.exclude(paper__tags__contains=exclude_tags)

        return queryset


class PaperScriptParamSearchView(ListAPIView):
    """
    Returns JSON with *papers* and matching *dataset usages*.
    """
    # we override `list()`, so no serializer_class needed
    pagination_class = None

    def list(self, request, *args, **kwargs):
        qp        = request.query_params
        # use_raw   = qp.get("raw", "").lower() in ("1", "true", "yes")
        use_raw = True
        rel_model = DatasetUsage

        instr_txt = qp.get("instrument")
        obs_txt   = qp.get("observatory")
        start_str = qp.get("start_date")
        end_str   = qp.get("end_date")

        # --- build filters shared by paper‑query *and* usage‑query -----------
        usage_filter = {}

        if instr_txt:
            usage_filter["instrument__short_name__icontains"] = instr_txt
        if obs_txt:
            usage_filter["instrument__observatory__short_name__icontains"] = obs_txt
        if start_str:
            start_dt = date_parser.parse(start_str).astimezone(pytz.UTC)
            if end_str:
                end_dt = date_parser.parse(end_str).replace(
                    hour=23, minute=59, second=59, microsecond=999999,
                    tzinfo=pytz.UTC,
                )
            else:
                end_dt = start_dt.replace(
                    hour=23, minute=59, second=59, microsecond=999999
                )
            window = DateTimeTZRange(start_dt, end_dt)
            usage_filter["observation_window__overlap"] = window

        if not usage_filter:
            return Response({"papers": [], "usages": []})

        # --- pull usages first ------------------------------------------------
        usages_qs = rel_model.objects.filter(**usage_filter).select_related(
            "paper", "instrument", "instrument__observatory"
        )

        # ids for the paper query
        paper_ids = usages_qs.values_list("paper_id", flat=True).distinct()

        papers_qs = (
            Paper.objects.filter(id__in=paper_ids)
            .select_related("user")
        )

        papers_data  = MinimalPaperSerializer(papers_qs, many=True).data
        usages_data  = DatasetUsageThinSerializer(usages_qs, many=True).data
        return Response({"papers": papers_data, "usages": usages_data})


class UsageByMissionAPIView(APIView):
    """
    Returns JSON like:
      {
        "dates": ["2020-01-01", "2020-01-02", …],
        "missions": ["SOHO", "SDO", …],
        "data": [
          [10, 15, …],  # counts for SOHO, SDO, … on 2020-01-01
          [11, 13, …],  # counts on 2020-01-02
           …
        ]
      }
    """

    def get(self, request):
        usages_query = DatasetUsage.objects \
            .exclude(observation_window__isnull=True) \
            .exclude(observation_window__isempty=True) \
            .select_related("instrument__observatory")

        usages = list(usages_query)

        # If no usages found, return empty data
        if not usages:
            return Response({
                "dates": [],
                "missions": [],
                "data": []
            })

        # build date index
        starts = [u.observation_window.lower.date() for u in usages]
        ends = [u.observation_window.upper.date() for u in usages]
        dates = pd.date_range(min(starts), max(ends), freq="D")
        missions = sorted({u.instrument.observatory.short_name.upper()
                           for u in usages if u.instrument.observatory})

        # zero table
        df = pd.DataFrame(0, index=dates, columns=missions)

        # fill
        for u in usages:
            obs = u.instrument.observatory
            if not obs: continue
            span = pd.date_range(u.observation_window.lower.date(),
                                 u.observation_window.upper.date(), freq="D")
            df.loc[span, obs.short_name.upper()] += 1

        return Response({
            "dates": [d.strftime("%Y-%m-%d") for d in df.index],
            "missions": missions,
            "data": df.values.tolist()
        })


class MissionLaunchesView(APIView):
    def get(self, request):
        # Get the path to your JSON file
        data_path = Path(__file__).parent / 'data' / 'mission_launches.json'

        # Read and return the JSON data
        with open(data_path, 'r') as f:
            data = json.load(f)

        return Response(data)


class SolarEventsView(APIView):
    def get(self, request):
        # Get the path to your JSON file
        data_path = Path(__file__).parent / 'data' / 'solar_events.json'

        # Read and return the JSON data
        with open(data_path, 'r') as f:
            data = json.load(f)

        return Response(data)


class DatasetUsageListView(ListAPIView):
    """
    List dataset usages with filtering capabilities
    Supports filtering by:
    - instrument: instrument short name
    - observatory: observatory slug
    - paper: paper bibcode
    - start_date/end_date: filter by observation time window
    """
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]
    serializer_class = DatasetUsageListSerializer
    filter_backends = [filters.OrderingFilter]
    ordering_fields = [
        'observation_window', 'paper__bibcode', 'instrument__short_name', 
        'instrument__observatory__name', 'supporting_quotes_count'
    ]
    ordering = ['-observation_window']

    def get_queryset(self):
        queryset = DatasetUsage.objects.select_related(
            'paper', 'instrument', 'instrument__observatory'
        ).prefetch_related('supporting_quotes', 'analysis').annotate(
            supporting_quotes_count=Count('supporting_quotes')
        )

        # Apply filters from query parameters
        instrument = self.request.query_params.get('instrument')
        if instrument:
            queryset = queryset.filter(instrument__short_name__icontains=instrument)

        observatory = self.request.query_params.get('observatory')
        if observatory:
            queryset = queryset.filter(instrument__observatory__short_name__icontains=observatory)

        paper = self.request.query_params.get('paper')
        if paper:
            queryset = queryset.filter(paper__bibcode__icontains=paper)

        # Filter by analysis presence
        has_analysis = self.request.query_params.get('has_analysis')
        if has_analysis == 'true':
            queryset = queryset.filter(analysis__isnull=False)
        elif has_analysis == 'false':
            queryset = queryset.filter(analysis__isnull=True)

        # Filter by quotes presence
        has_quotes = self.request.query_params.get('has_quotes')
        if has_quotes == 'true':
            queryset = queryset.filter(supporting_quotes__isnull=False).distinct()
        elif has_quotes == 'false':
            queryset = queryset.filter(supporting_quotes__isnull=True)

        start_date = self.request.query_params.get('start_date')
        end_date = self.request.query_params.get('end_date')
        if start_date:
            start_dt = date_parser.parse(start_date).astimezone(pytz.UTC)
            if end_date:
                end_dt = date_parser.parse(end_date).replace(
                    hour=23, minute=59, second=59, microsecond=999999,
                    tzinfo=pytz.UTC,
                )
            else:
                end_dt = start_dt.replace(
                    hour=23, minute=59, second=59, microsecond=999999
                )
            window = DateTimeTZRange(start_dt, end_dt)
            queryset = queryset.filter(observation_window__overlap=window)

        return queryset


class DatasetUsageDetailView(RetrieveAPIView):
    """
    Retrieve detailed information for a specific dataset usage
    """
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]
    serializer_class = DatasetUsageDetailSerializer
    lookup_field = 'id'

    def get_queryset(self):
        qs = DatasetUsage.objects.select_related(
            'paper', 'instrument', 'instrument__observatory'
        ).prefetch_related('supporting_quotes', 'analysis')
        return annotate_my_validation(qs, self.request.user)


class DatasetUsageStatsView(APIView):
    """
    Get aggregated statistics for dataset usages
    Returns:
    - Instrument distribution
    - Observatory distribution
    - Time-based statistics
    """
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        # Base queryset with same filtering as list view
        queryset = DatasetUsage.objects.select_related(
            'instrument', 'instrument__observatory'
        )

        # Apply same filters as list view
        instrument = request.query_params.get('instrument')
        if instrument:
            queryset = queryset.filter(instrument__short_name__icontains=instrument)

        observatory = request.query_params.get('observatory')
        if observatory:
            queryset = queryset.filter(instrument__observatory__short_name__icontains=observatory)

        paper = request.query_params.get('paper')
        if paper:
            queryset = queryset.filter(paper__bibcode__icontains=paper)

        # Filter by analysis presence
        has_analysis = request.query_params.get('has_analysis')
        if has_analysis == 'true':
            queryset = queryset.filter(analysis__isnull=False)
        elif has_analysis == 'false':
            queryset = queryset.filter(analysis__isnull=True)

        # Filter by quotes presence
        has_quotes = request.query_params.get('has_quotes')
        if has_quotes == 'true':
            queryset = queryset.filter(supporting_quotes__isnull=False).distinct()
        elif has_quotes == 'false':
            queryset = queryset.filter(supporting_quotes__isnull=True)

        start_date = request.query_params.get('start_date')
        end_date = request.query_params.get('end_date')
        if start_date:
            start_dt = date_parser.parse(start_date).astimezone(pytz.UTC)
            if end_date:
                end_dt = date_parser.parse(end_date).replace(
                    hour=23, minute=59, second=59, microsecond=999999,
                    tzinfo=pytz.UTC,
                )
            else:
                end_dt = start_dt.replace(
                    hour=23, minute=59, second=59, microsecond=999999
                )
            window = DateTimeTZRange(start_dt, end_dt)
            queryset = queryset.filter(observation_window__overlap=window)

        # Calculate statistics
        total_count = queryset.count()

        # Instrument distribution (top 10)
        instrument_stats = (
            queryset.values('instrument__short_name')
            .annotate(count=Count('id'))
            .order_by('-count')[:10]
        )
        instrument_distribution = {
            item['instrument__short_name']: item['count']
            for item in instrument_stats
        }

        # Observatory distribution
        observatory_stats = (
            queryset.values('instrument__observatory__name')
            .annotate(count=Count('id'))
            .order_by('-count')[:10]
        )
        observatory_distribution = {
            item['instrument__observatory__name']: item['count']
            for item in observatory_stats
        }

        # Analysis statistics
        with_analysis = queryset.filter(analysis__isnull=False).count()
        successful_analysis = queryset.filter(
            analysis__isnull=False, 
            analysis__execution_successful=True
        ).count()

        # Supporting quotes statistics
        with_quotes = queryset.filter(supporting_quotes__isnull=False).distinct().count()

        return Response({
            'total_count': total_count,
            'instrument_distribution': instrument_distribution,
            'observatory_distribution': observatory_distribution,
            'analysis_stats': {
                'with_analysis': with_analysis,
                'successful_analysis': successful_analysis,
                'analysis_success_rate': round(successful_analysis / with_analysis * 100, 1) if with_analysis > 0 else 0
            },
            'quote_stats': {
                'with_quotes': with_quotes,
                'quote_coverage': round(with_quotes / total_count * 100, 1) if total_count > 0 else 0
            }
        })


def _build_observatory_filter_q(missions, short_name_field: str, datasource_slug_field: str) -> Q:
    """
    Build a mission filter Q that supports both plain mission names (SOHO)
    and datasource-qualified mission keys (cdaweb:SOHO).
    """
    composite = [m for m in missions if ':' in m]
    plain = [m for m in missions if ':' not in m]
    mission_q = Q()

    if plain:
        mission_q |= Q(**{f'{short_name_field}__in': plain})

    for key in composite:
        ds_slug, obs_name = key.split(':', 1)
        mission_q |= Q(**{
            datasource_slug_field: ds_slug,
            short_name_field: obs_name,
        })

    return mission_q


def _build_dataset_usage_filter_q(missions, instruments, start_date, end_date, validation_statuses, prefix='dataset_usages__') -> Q:
    """Build dataset-usage filter clauses for both Paper and DatasetUsage query contexts."""
    filters = Q()

    if missions:
        mission_q = _build_observatory_filter_q(
            missions,
            short_name_field=f'{prefix}instrument__observatory__short_name',
            datasource_slug_field=f'{prefix}instrument__observatory__datasource__slug',
        )
        if mission_q.children:
            filters &= mission_q

    if instruments:
        filters &= Q(**{f'{prefix}instrument__short_name__in': instruments})

    if validation_statuses:
        filters &= Q(**{f'{prefix}validation_status__in': validation_statuses})

    if start_date or end_date:
        from django.utils import timezone

        if start_date and end_date:
            start = timezone.datetime.fromisoformat(start_date.replace('Z', '+00:00'))
            end = timezone.datetime.fromisoformat(end_date.replace('Z', '+00:00'))
            filters &= Q(**{
                f'{prefix}observation_window__overlap': DateTimeTZRange(start, end)
            })
        elif start_date:
            start = timezone.datetime.fromisoformat(start_date.replace('Z', '+00:00'))
            filters &= Q(**{f'{prefix}observation_window__endswith__gte': start})
        elif end_date:
            end = timezone.datetime.fromisoformat(end_date.replace('Z', '+00:00'))
            filters &= Q(**{f'{prefix}observation_window__startswith__lte': end})

    return filters


def _build_public_papers_query_parts(include_unvalidated, missions, instruments, start_date, end_date, validation_statuses, text_query):
    """Build list/CSV paper query parts with mission_only inclusion semantics."""
    if include_unvalidated:
        allowed_statuses = ['approved', 'pending']
    else:
        allowed_statuses = ['approved']

    papers_with_usages = Paper.objects.filter(dataset_usages__validation_status__in=allowed_statuses)
    usage_filters = _build_dataset_usage_filter_q(
        missions=missions,
        instruments=instruments,
        start_date=start_date,
        end_date=end_date,
        validation_statuses=validation_statuses,
        prefix='dataset_usages__',
    )
    usage_papers = papers_with_usages.filter(usage_filters) if usage_filters.children else papers_with_usages
    if text_query:
        usage_papers = usage_papers.filter(Q(bibcode__icontains=text_query) | Q(title__icontains=text_query))

    # mission_only papers are only surfaced when filtering by mission,
    # and only when filters requiring DatasetUsage semantics are absent.
    allow_mission_only = bool(missions) and not validation_statuses and not instruments and not (start_date or end_date)
    mission_only_papers = Paper.objects.none()
    if allow_mission_only:
        mission_only_mission_q = _build_observatory_filter_q(
            missions,
            short_name_field='paperanalysis__instrument_mentions__matched_observatory__short_name',
            datasource_slug_field='paperanalysis__instrument_mentions__matched_observatory__datasource__slug',
        )
        if mission_only_mission_q.children:
            mission_only_papers = (
                Paper.objects
                .filter(paperanalysis__instrument_mentions__match_level=InstrumentMention.MATCH_LEVEL_MISSION_ONLY)
                .filter(mission_only_mission_q)
            )
            if text_query:
                mission_only_papers = mission_only_papers.filter(
                    Q(bibcode__icontains=text_query) | Q(title__icontains=text_query)
                )

    # Always wrap in an id__in subquery so the returned queryset never carries
    # the dataset_usages join: joined duplicates would force DISTINCT over the
    # caller's annotated select list, which makes the database evaluate every
    # per-paper subquery for the full result set before LIMIT can apply (#11).
    combined_papers = Paper.objects.filter(id__in=usage_papers.values('id'))
    if allow_mission_only:
        combined_papers = Paper.objects.filter(
            Q(id__in=usage_papers.values('id')) | Q(id__in=mission_only_papers.values('id'))
        )

    matching_usage_exists = DatasetUsage.objects.filter(
        paper=OuterRef('pk'),
        validation_status__in=allowed_statuses,
    )
    usage_filters_for_exists = _build_dataset_usage_filter_q(
        missions=missions,
        instruments=instruments,
        start_date=start_date,
        end_date=end_date,
        validation_statuses=validation_statuses,
        prefix='',
    )
    if usage_filters_for_exists.children:
        matching_usage_exists = matching_usage_exists.filter(usage_filters_for_exists)

    mission_only_count_filter = Q(pk__isnull=True)
    if missions:
        mission_only_mission_q = _build_observatory_filter_q(
            missions,
            short_name_field='paperanalysis__instrument_mentions__matched_observatory__short_name',
            datasource_slug_field='paperanalysis__instrument_mentions__matched_observatory__datasource__slug',
        )
        if mission_only_mission_q.children:
            mission_only_count_filter = (
                Q(paperanalysis__instrument_mentions__match_level=InstrumentMention.MATCH_LEVEL_MISSION_ONLY)
                & mission_only_mission_q
            )

    return {
        'allowed_statuses': allowed_statuses,
        'papers': combined_papers,
        'matching_usage_exists': matching_usage_exists,
        'mission_only_count_filter': mission_only_count_filter,
        'total_count_filter': Q(dataset_usages__validation_status__in=allowed_statuses),
    }


class PublicPaperValidatedUsagesView(APIView):
    """Public, read-only view of dataset usages by paper bibcode (validated or all)."""
    permission_classes = [AllowAny]

    def get(self, request, bibcode: str):
        try:
            paper = Paper.objects.get(bibcode=bibcode)
        except Paper.DoesNotExist:
            raise Http404("Paper not found")

        include_unvalidated = request.query_params.get('include_unvalidated', '').lower() == 'true'
        
        if include_unvalidated:
            # Show Approved + Pending usages for this paper
            usages = (
                DatasetUsage.objects.filter(paper=paper, validation_status__in=['approved', 'pending'])
                .select_related('instrument', 'instrument__observatory', 'instrument__observatory__datasource', 'analysis')
                .prefetch_related('quote_links__quote')
                .annotate(
                    start_lower=Func(F('observation_window'), function='lower', output_field=DateTimeField()),
                    end_upper=Func(F('observation_window'), function='upper', output_field=DateTimeField()),
                )
                .order_by('instrument__observatory__datasource__slug', 'instrument__observatory__short_name', 'instrument__short_name', 'start_lower', 'end_upper', 'id')
            )
        else:
            # Show only approved dataset usages (original behavior)
            usages = (
                DatasetUsage.objects.filter(paper=paper, validation_status='approved')
                .select_related('instrument', 'instrument__observatory', 'instrument__observatory__datasource', 'analysis')
                .prefetch_related('quote_links__quote')
                .annotate(
                    start_lower=Func(F('observation_window'), function='lower', output_field=DateTimeField()),
                    end_upper=Func(F('observation_window'), function='upper', output_field=DateTimeField()),
                )
                .order_by('instrument__observatory__datasource__slug', 'instrument__observatory__short_name', 'instrument__short_name', 'start_lower', 'end_upper', 'id')
            )
        serializer = PublicDatasetUsageSerializer(usages, many=True)
        mention_levels = [
            InstrumentMention.MATCH_LEVEL_MISSION_ONLY,
            InstrumentMention.MATCH_LEVEL_INSTRUMENT_NO_TIME,
            InstrumentMention.MATCH_LEVEL_PARTIAL,
        ]
        level_order = {
            InstrumentMention.MATCH_LEVEL_MISSION_ONLY: 0,
            InstrumentMention.MATCH_LEVEL_INSTRUMENT_NO_TIME: 1,
            InstrumentMention.MATCH_LEVEL_PARTIAL: 2,
        }
        mission_mentions = (
            InstrumentMention.objects
            .filter(
                paper_analysis__paper=paper,
                match_level__in=mention_levels,
            )
            .select_related(
                'matched_observatory__datasource',
                'matched_instrument__observatory__datasource',
            )
            .order_by(
                'matched_observatory__datasource__slug',
                'matched_instrument__observatory__datasource__slug',
                'matched_observatory__short_name',
                'matched_instrument__observatory__short_name',
                'id',
            )
        )
        mission_mentions = sorted(
            mission_mentions,
            key=lambda m: (
                (m.matched_observatory.datasource.slug if m.matched_observatory and m.matched_observatory.datasource else
                 m.matched_instrument.observatory.datasource.slug if m.matched_instrument and m.matched_instrument.observatory and m.matched_instrument.observatory.datasource else
                 'unknown'),
                (m.matched_observatory.short_name if m.matched_observatory else
                 m.matched_instrument.observatory.short_name if m.matched_instrument and m.matched_instrument.observatory else
                 'unknown'),
                level_order.get(m.match_level, 99),
                str(m.id),
            ),
        )
        mission_mentions_data = PublicInstrumentMentionSerializer(mission_mentions, many=True).data

        include = (self.request.query_params.get('include') or '').split(',')
        include = [s.strip().lower() for s in include if s]
        # Use database ADS metadata (much faster than API calls)
        if paper.ads_metadata_fetched and paper.title:
            # Use stored database values
            paper_data = {
                'id': paper.id,
                'bibcode': paper.bibcode,
                'title': paper.title,
                'authors': paper.authors or [],
                'year': paper.year,
                'journal': paper.journal,
                'journal_abbrev': paper.journal_abbrev,
            }
            if 'abstract' in include and paper.abstract:
                paper_data['abstract'] = paper.abstract
        else:
            # Fallback for papers without cached metadata
            paper_data = {
                'id': paper.id,
                'bibcode': paper.bibcode,
                'title': paper.bibcode,  # Use bibcode as fallback title
                'authors': [],
                'year': None,
                'journal': None,
                'journal_abbrev': None,
            }
            if 'abstract' in include:
                paper_data['abstract'] = None

        response = {
            'paper': paper_data,
            'usages': serializer.data,
            'mission_mentions': mission_mentions_data,
            'mission_mentions_count': len(mission_mentions_data),
        }
        return Response(response)


class PublicValidatedPapersListView(APIView):
    """Public list of papers that have dataset usages (validated or all)."""
    permission_classes = [AllowAny]
    pagination_class = PublicPapersPagination

    def get(self, request):
        include_unvalidated = request.query_params.get('include_unvalidated', '').lower() == 'true'

        # Extract filter parameters
        missions = request.query_params.getlist('missions')
        instruments = request.query_params.getlist('instruments')
        start_date = request.query_params.get('start_date')
        end_date = request.query_params.get('end_date')
        validation_statuses = request.query_params.getlist('validation_status')

        # Text search by bibcode or title (param: q)
        q = (request.query_params.get('q') or '').strip()

        # Fast path: the default public listing (optionally text-searched) does
        # not depend on any per-request usage filter, so it can read the
        # denormalized rollups on Paper (refreshed by refresh_paper_usage_stats)
        # instead of aggregating over DatasetUsage on every request. Any
        # mission/instrument/date/validation-status filter changes the counting
        # or membership semantics, so those requests fall through to the live
        # aggregation path below.
        if not (missions or instruments or start_date or end_date or validation_statuses):
            return self._get_precomputed(request, include_unvalidated, q)

        query_parts = _build_public_papers_query_parts(
            include_unvalidated=include_unvalidated,
            missions=missions,
            instruments=instruments,
            start_date=start_date,
            end_date=end_date,
            validation_statuses=validation_statuses,
            text_query=q,
        )

        # Per-paper aggregates as correlated subqueries. As JOIN-based annotations
        # these forced dataset_usages AND paperanalysis__instrument_mentions into a
        # single GROUP BY, whose cartesian product exploded (e.g. 113 ACE papers ->
        # ~435k intermediate rows -> ~9s). Subqueries are small indexed per-paper
        # lookups, so nothing fans out and .distinct() is no longer needed.
        allowed_statuses = query_parts['allowed_statuses']
        validated_sq = Coalesce(Subquery(
            DatasetUsage.objects.filter(paper=OuterRef('pk'), validation_status='approved')
            .order_by().values('paper').annotate(c=Count('*')).values('c'),
            output_field=IntegerField()), 0)
        total_sq = Coalesce(Subquery(
            DatasetUsage.objects.filter(paper=OuterRef('pk'), validation_status__in=allowed_statuses)
            .order_by().values('paper').annotate(c=Count('*')).values('c'),
            output_field=IntegerField()), 0)
        if missions:
            mission_only_mentions = (
                InstrumentMention.objects
                .filter(paper_analysis__paper=OuterRef('pk'),
                        match_level=InstrumentMention.MATCH_LEVEL_MISSION_ONLY)
                .filter(_build_observatory_filter_q(
                    missions,
                    short_name_field='matched_observatory__short_name',
                    datasource_slug_field='matched_observatory__datasource__slug'))
            )
            mission_only_sq = Coalesce(Subquery(
                mission_only_mentions.order_by().values('paper_analysis__paper')
                .annotate(c=Count('*')).values('c'),
                output_field=IntegerField()), 0)
        else:
            mission_only_sq = Value(0, output_field=IntegerField())

        # Order by the denormalized rollup column instead of a live Max()
        # subquery: sorting by a correlated subquery makes the database
        # evaluate it for every matching row even under LIMIT. The rollup is
        # equivalent (max observation end over ALL of the paper's usages,
        # matching the old annotation's semantics) and is what the unfiltered
        # fast path already serves. Pagination happens on the queryset, so the
        # per-paper count subqueries run only for the requested page (#11).
        papers = (
            query_parts['papers']
            .annotate(
                validated_count=validated_sq,
                total_count=total_sq,
                mission_only_match_count=mission_only_sq,
                has_matching_dataset_usage=Exists(query_parts['matching_usage_exists']),
            )
            .order_by('-latest_observation_end_all', 'bibcode')
        )

        include_ads = (request.query_params.get('include') or '').lower()
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(papers, request, view=self)
        page_papers = page if page is not None else list(papers)

        # Build rows using database ADS metadata (much faster than API calls)
        rows = []
        for p in page_papers:
            row_data = {
                'id': p.id,
                'bibcode': p.bibcode,
                'validated_count': p.validated_count or 0,
                'total_count': getattr(p, 'total_count', None) or p.validated_count or 0,
                'mission_only_match_count': getattr(p, 'mission_only_match_count', 0) or 0,
                'has_matching_dataset_usage': bool(getattr(p, 'has_matching_dataset_usage', False)),
                'latest_end': p.latest_observation_end_all,
            }

            # Add ADS metadata from database if available, or fallback
            if include_ads:
                if p.ads_metadata_fetched and p.title:
                    # Use stored database values
                    row_data.update({
                        'title': p.title,
                        'authors': p.authors or [],
                        'year': p.year,
                        'journal': p.journal,
                    })
                else:
                    # Fallback for papers without cached metadata
                    row_data.update({
                        'title': p.bibcode,  # Use bibcode as fallback title
                        'authors': [],
                        'year': None,
                        'journal': None,
                    })

            rows.append(row_data)

        serializer = PublicValidatedPaperSerializer(rows, many=True)
        if page is not None:
            return paginator.get_paginated_response(serializer.data)
        return Response({'results': serializer.data})

    def _get_precomputed(self, request, include_unvalidated, q):
        """Serve the unfiltered public listing from denormalized Paper rollups.

        Reads the columns maintained by ``refresh_paper_usage_stats`` and lets
        the database apply ORDER BY + LIMIT, so the response cost is bounded by
        the page size rather than the total number of DatasetUsage rows. Only
        reachable when no per-request usage filter is active (see ``get``), so
        the mission-only count is 0 and every listed paper has a matching usage
        by construction — mirroring the live query's values for this case.
        """
        if include_unvalidated:
            papers_qs = (
                Paper.objects
                .filter(Q(approved_usage_count__gt=0) | Q(pending_usage_count__gt=0))
                .order_by('-latest_observation_end_all', 'bibcode')
            )
        else:
            papers_qs = (
                Paper.objects
                .filter(approved_usage_count__gt=0)
                .order_by('-latest_observation_end_approved', 'bibcode')
            )

        if q:
            papers_qs = papers_qs.filter(Q(bibcode__icontains=q) | Q(title__icontains=q))

        include_ads = (request.query_params.get('include') or '').lower()

        paginator = self.pagination_class()
        page = paginator.paginate_queryset(papers_qs, request, view=self)
        page_papers = page if page is not None else list(papers_qs)

        rows = []
        for p in page_papers:
            total = p.approved_usage_count + (p.pending_usage_count if include_unvalidated else 0)
            latest_end = (
                p.latest_observation_end_all if include_unvalidated
                else p.latest_observation_end_approved
            )
            row_data = {
                'id': p.id,
                'bibcode': p.bibcode,
                'validated_count': p.approved_usage_count,
                'total_count': total,
                'mission_only_match_count': 0,
                'has_matching_dataset_usage': True,
                'latest_end': latest_end,
            }
            if include_ads:
                if p.ads_metadata_fetched and p.title:
                    row_data.update({
                        'title': p.title,
                        'authors': p.authors or [],
                        'year': p.year,
                        'journal': p.journal,
                    })
                else:
                    row_data.update({
                        'title': p.bibcode,
                        'authors': [],
                        'year': None,
                        'journal': None,
                    })
            rows.append(row_data)

        serializer = PublicValidatedPaperSerializer(rows, many=True)
        if page is not None:
            return paginator.get_paginated_response(serializer.data)
        return Response({'results': serializer.data})


class Echo:
    """Helper class that returns what it writes for streaming CSV."""
    def write(self, value):
        return value


class PublicValidatedPapersCSVView(APIView):
    """
    Public CSV export of validated papers.
    Returns CSV with columns: Bibcode, URL
    URL format: https://<your-domain>/public/p/{encoded_bibcode}
    """
    permission_classes = [AllowAny]

    def get(self, request):
        include_unvalidated = request.query_params.get('include_unvalidated', '').lower() == 'true'

        # Extract filter parameters
        missions = request.query_params.getlist('missions')
        instruments = request.query_params.getlist('instruments')
        start_date = request.query_params.get('start_date')
        end_date = request.query_params.get('end_date')
        validation_statuses = request.query_params.getlist('validation_status')

        # Text search by bibcode or title (param: q)
        q = (request.query_params.get('q') or '').strip()

        query_parts = _build_public_papers_query_parts(
            include_unvalidated=include_unvalidated,
            missions=missions,
            instruments=instruments,
            start_date=start_date,
            end_date=end_date,
            validation_statuses=validation_statuses,
            text_query=q,
        )

        # Optimize query - only need bibcode, use distinct
        papers = query_parts['papers'].values_list('bibcode', flat=True).distinct().order_by('bibcode')

        # Get base URL from settings (configured via BASE_URL environment variable)
        # This handles nginx reverse proxy and Docker networking properly
        # Strip trailing slash to avoid double slashes in URLs
        base_url = settings.BASE_URL.rstrip('/')

        # Generate CSV response using streaming
        def generate_rows():
            buffer = Echo()
            writer = csv.writer(buffer)

            # Header
            yield writer.writerow(['Bibcode', 'URL'])

            # Data rows
            for bibcode in papers.iterator(chunk_size=500):
                encoded_bibcode = quote(bibcode, safe='')
                url = f'{base_url}/public/p/{encoded_bibcode}'
                yield writer.writerow([bibcode, url])

        response = StreamingHttpResponse(
            generate_rows(),
            content_type='text/csv'
        )
        response['Content-Disposition'] = 'attachment; filename="validated_papers.csv"'
        return response


class PublicPapersFilterOptionsView(APIView):
    """Public endpoint for getting filter options (missions, instruments, date ranges, etc.)"""
    permission_classes = [AllowAny]
    
    def get(self, request):
        include_unvalidated = request.query_params.get('include_unvalidated', '').lower() == 'true'
        
        # Base dataset usage query
        # include_unvalidated=True means include Approved + Pending
        if include_unvalidated:
            usages = DatasetUsage.objects.filter(validation_status__in=['approved', 'pending']).select_related('instrument__observatory')
        else:
            usages = DatasetUsage.objects.filter(validation_status='approved').select_related('instrument__observatory')
        
        # Usage-backed mission counts (including datasource metadata)
        missions = (
            usages
            .values(
                'instrument__observatory__short_name',
                'instrument__observatory__display_name',
                'instrument__observatory__name',
                'instrument__observatory__datasource__slug',
                'instrument__observatory__datasource__name',
            )
            .annotate(
                count=Count('paper', distinct=True),
                usage_count=Count('id')
            )
            .filter(count__gt=0)
            .order_by('instrument__observatory__datasource__slug', 'instrument__observatory__short_name')
        )

        # Get instruments grouped by mission with counts (now including datasource)
        instruments = (
            usages
            .values(
                'instrument__short_name',
                'instrument__display_name',
                'instrument__full_name',
                'instrument__observatory__short_name',
                'instrument__observatory__datasource__slug',
            )
            .annotate(
                count=Count('paper', distinct=True),
                usage_count=Count('id')
            )
            .filter(count__gt=0)
            .order_by('instrument__observatory__datasource__slug', 'instrument__observatory__short_name', 'instrument__short_name')
        )

        # Mission-only mentions are independent of DatasetUsage validation state.
        mission_only_mentions = (
            InstrumentMention.objects
            .filter(
                match_level=InstrumentMention.MATCH_LEVEL_MISSION_ONLY,
                matched_observatory__isnull=False,
            )
            .values(
                'matched_observatory__short_name',
                'matched_observatory__display_name',
                'matched_observatory__name',
                'matched_observatory__datasource__slug',
                'matched_observatory__datasource__name',
            )
            .annotate(
                mission_only_paper_count=Count('paper_analysis__paper', distinct=True),
                mission_only_usage_count=Count('id'),
            )
            .filter(mission_only_paper_count__gt=0)
            .order_by('matched_observatory__datasource__slug', 'matched_observatory__short_name')
        )
        
        # Get date ranges
        date_stats = usages.aggregate(
            earliest=Min(Func(F('observation_window'), function='lower', output_field=DateTimeField())),
            latest=Max(Func(F('observation_window'), function='upper', output_field=DateTimeField()))
        )
        
        # Get validation status counts
        validation_counts = (
            DatasetUsage.objects
            .values('validation_status')
            .annotate(
                count=Count('paper', distinct=True),
                usage_count=Count('id')
            )
            .order_by('validation_status')
        )
        
        # Mission metadata map + combined distinct paper counts (usage OR mission_only).
        mission_meta = {}
        usage_count_by_key = {}
        for mission in missions:
            ds_slug = mission['instrument__observatory__datasource__slug'] or 'unknown'
            ds_name = mission['instrument__observatory__datasource__name'] or ds_slug
            short_name = mission['instrument__observatory__short_name']
            key = (ds_slug, short_name)
            mission_meta[key] = {
                'datasource_slug': ds_slug,
                'datasource_name': ds_name,
                'short_name': short_name,
                'display_name': mission['instrument__observatory__display_name'] or short_name,
                'name': mission['instrument__observatory__name'],
            }
            usage_count_by_key[key] = mission['usage_count']

        mission_only_count_by_key = {}
        for mention in mission_only_mentions:
            ds_slug = mention['matched_observatory__datasource__slug'] or 'unknown'
            ds_name = mention['matched_observatory__datasource__name'] or ds_slug
            short_name = mention['matched_observatory__short_name']
            key = (ds_slug, short_name)
            mission_only_count_by_key[key] = mention['mission_only_usage_count']
            if key not in mission_meta:
                mission_meta[key] = {
                    'datasource_slug': ds_slug,
                    'datasource_name': ds_name,
                    'short_name': short_name,
                    'display_name': mention['matched_observatory__display_name'] or short_name,
                    'name': mention['matched_observatory__name'],
                }

        usage_paper_sets = {}
        for paper_id, ds_slug, short_name in (
            usages
            .values_list(
                'paper_id',
                'instrument__observatory__datasource__slug',
                'instrument__observatory__short_name',
            )
            .distinct()
        ):
            key = (ds_slug or 'unknown', short_name)
            usage_paper_sets.setdefault(key, set()).add(paper_id)

        mission_only_paper_sets = {}
        for paper_id, ds_slug, short_name in (
            InstrumentMention.objects
            .filter(
                match_level=InstrumentMention.MATCH_LEVEL_MISSION_ONLY,
                matched_observatory__isnull=False,
            )
            .values_list(
                'paper_analysis__paper_id',
                'matched_observatory__datasource__slug',
                'matched_observatory__short_name',
            )
            .distinct()
        ):
            key = (ds_slug or 'unknown', short_name)
            mission_only_paper_sets.setdefault(key, set()).add(paper_id)

        missions_by_datasource = {}
        missions_data = []  # backward compat flat list
        all_mission_keys = sorted(set(mission_meta.keys()) | set(usage_paper_sets.keys()) | set(mission_only_paper_sets.keys()))
        for key in all_mission_keys:
            ds_slug, short_name = key
            meta = mission_meta.get(key, {
                'datasource_slug': ds_slug,
                'datasource_name': ds_slug,
                'short_name': short_name,
                'display_name': short_name,
                'name': short_name,
            })
            usage_papers = usage_paper_sets.get(key, set())
            mission_only_papers = mission_only_paper_sets.get(key, set())

            mission_entry = {
                'key': f'{ds_slug}:{short_name}',
                'short_name': short_name,
                'display_name': meta['display_name'] or short_name,
                'name': meta['name'],
                'paper_count': len(usage_papers | mission_only_papers),
                'usage_count': usage_count_by_key.get(key, 0),
                'mission_only_paper_count': len(mission_only_papers),
                'mission_only_usage_count': mission_only_count_by_key.get(key, 0),
            }

            if ds_slug not in missions_by_datasource:
                missions_by_datasource[ds_slug] = {
                    'datasource_name': meta['datasource_name'],
                    'missions': [],
                }
            missions_by_datasource[ds_slug]['missions'].append(mission_entry)

            missions_data.append({
                'short_name': short_name,
                'name': meta['name'],
                'paper_count': len(usage_papers | mission_only_papers),
                'usage_count': usage_count_by_key.get(key, 0),
                'mission_only_paper_count': len(mission_only_papers),
            })

        # Format instruments data grouped by datasource:mission composite key
        instruments_by_datasource_and_mission = {}
        instruments_by_mission = {}  # backward compat
        for instrument in instruments:
            ds_slug = instrument['instrument__observatory__datasource__slug'] or 'unknown'
            obs_short = instrument['instrument__observatory__short_name']
            composite_key = f"{ds_slug}:{obs_short}"

            inst_display = instrument['instrument__display_name']
            inst_entry = {
                'short_name': instrument['instrument__short_name'],
                'display_name': inst_display or instrument['instrument__short_name'],
                'full_name': instrument['instrument__full_name'] or instrument['instrument__short_name'],
                'paper_count': instrument['count'],
                'usage_count': instrument['usage_count'],
            }

            # New structure keyed by composite key
            if composite_key not in instruments_by_datasource_and_mission:
                instruments_by_datasource_and_mission[composite_key] = []
            instruments_by_datasource_and_mission[composite_key].append(inst_entry)

            # backward compat keyed by mission short_name only
            if obs_short not in instruments_by_mission:
                instruments_by_mission[obs_short] = []
            instruments_by_mission[obs_short].append(inst_entry)
        
        # Format validation status data
        validation_data = []
        for status_info in validation_counts:
            validation_data.append({
                'status': status_info['validation_status'],
                'paper_count': status_info['count'],
                'usage_count': status_info['usage_count']
            })
        
        return Response({
            'missions_by_datasource': missions_by_datasource,
            'instruments_by_datasource_and_mission': instruments_by_datasource_and_mission,
            # backward compat
            'missions': missions_data,
            'instruments_by_mission': instruments_by_mission,
            'date_range': {
                'earliest': date_stats['earliest'],
                'latest': date_stats['latest']
            },
            'validation_statuses': validation_data
        })


class SimilarPapersView(APIView):
    """Return up to 10 papers most similar to the given paper, based on
    cosine similarity of averaged support-quote embeddings."""
    permission_classes = [AllowAny]

    def get(self, request, bibcode: str):
        include_unvalidated = request.query_params.get(
            'include_unvalidated', ''
        ).lower() == 'true'

        cache_key = f'similar_papers_{bibcode}_{"all" if include_unvalidated else "approved"}'
        cached = cache.get(cache_key)
        if cached is not None:
            return Response(cached)

        try:
            paper = Paper.objects.get(bibcode=bibcode)
        except Paper.DoesNotExist:
            raise Http404("Paper not found")

        quotes = SupportQuote.objects.filter(
            paper_analysis__paper=paper,
            embedding__isnull=False,
        ).only('embedding')

        if not quotes.exists():
            result = []
            cache.set(cache_key, result, timeout=86400)
            return Response(result)

        embeddings = [q.embedding for q in quotes]
        avg_embedding = np.mean(embeddings, axis=0).tolist()

        # Only return papers that have usages matching the validation filter
        if include_unvalidated:
            valid_statuses = ['approved', 'pending']
        else:
            valid_statuses = ['approved']
        valid_paper_ids = (
            DatasetUsage.objects
            .filter(validation_status__in=valid_statuses)
            .values_list('paper_id', flat=True)
            .distinct()
        )

        similar_quotes = (
            SupportQuote.objects
            .filter(
                embedding__isnull=False,
                paper_analysis__paper__in=valid_paper_ids,
            )
            .exclude(paper_analysis__paper=paper)
            .annotate(distance=CosineDistance('embedding', avg_embedding))
            .select_related('paper_analysis__paper')
            .order_by('distance')[:200]
        )

        seen = {}
        for sq in similar_quotes:
            p = sq.paper_analysis.paper
            if p.bibcode not in seen:
                seen[p.bibcode] = {
                    'bibcode': p.bibcode,
                    'title': p.title or p.bibcode,
                    'authors': (p.authors or [])[:3],
                    'year': p.year,
                    'score': round(1 - sq.distance, 3),
                }
            if len(seen) >= 10:
                break

        # Fetch missions (observatories) for each similar paper
        if seen:
            paper_missions = (
                DatasetUsage.objects
                .filter(
                    paper__bibcode__in=seen.keys(),
                    validation_status__in=valid_statuses,
                )
                .select_related('instrument__observatory')
                .values_list(
                    'paper__bibcode',
                    'instrument__observatory__display_name',
                    'instrument__observatory__short_name',
                )
                .distinct()
            )
            missions_by_bibcode = {}
            for bib, obs_display, obs_short in paper_missions:
                name = obs_display or obs_short
                if name:
                    missions_by_bibcode.setdefault(bib, set()).add(name)
            for bib, entry in seen.items():
                entry['missions'] = sorted(missions_by_bibcode.get(bib, set()))

        result = list(seen.values())
        cache.set(cache_key, result, timeout=86400)
        return Response(result)


class DatasetUsageValidationView(APIView):
    """
    Handle validation actions for dataset usages.
    POST: Submit a validation judgment (authenticated or anonymous).
    Authenticated users are identified by their user account (one vote per user).
    Anonymous users are identified by the X-Anonymous-ID header (one vote per UUID).
    After each submission the consensus status on DatasetUsage is recomputed.
    """
    # Allow both authenticated and unauthenticated requests
    authentication_classes = [JWTAuthentication]
    permission_classes = []

    def post(self, request, usage_id):
        try:
            usage = DatasetUsage.objects.get(id=usage_id)
        except DatasetUsage.DoesNotExist:
            return Response(
                {"error": "Dataset usage not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        validation_status_value = request.data.get('validation_status')
        validation_notes = request.data.get('validation_notes', '') or ''

        valid_statuses = ['approved', 'rejected', 'needs_review']
        if validation_status_value not in valid_statuses:
            return Response(
                {"error": f"Invalid status. Must be one of: {valid_statuses}"},
                status=status.HTTP_400_BAD_REQUEST
            )

        is_authenticated = bool(request.user and request.user.is_authenticated)

        if is_authenticated:
            # Upsert: one record per (dataset_usage, user)
            validation_obj, created = DatasetUsageValidation.objects.update_or_create(
                dataset_usage=usage,
                user=request.user,
                defaults={
                    'validation_status': validation_status_value,
                    'validation_notes': validation_notes,
                },
            )
            rater_label = request.user.username
        else:
            # Anonymous path: require X-Anonymous-ID header
            anon_id_str = request.headers.get('X-Anonymous-ID')
            if not anon_id_str:
                return Response(
                    {"error": "X-Anonymous-ID header is required for unauthenticated validation"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            import uuid as uuid_mod
            try:
                anon_uuid = uuid_mod.UUID(anon_id_str)
            except ValueError:
                return Response(
                    {"error": "X-Anonymous-ID must be a valid UUID"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            # Upsert: one record per (dataset_usage, anonymous_id) when user is null
            try:
                validation_obj = DatasetUsageValidation.objects.get(
                    dataset_usage=usage,
                    user__isnull=True,
                    anonymous_id=anon_uuid,
                )
                validation_obj.validation_status = validation_status_value
                validation_obj.validation_notes = validation_notes
                validation_obj.save(update_fields=['validation_status', 'validation_notes'])
                created = False
            except DatasetUsageValidation.DoesNotExist:
                validation_obj = DatasetUsageValidation.objects.create(
                    dataset_usage=usage,
                    user=None,
                    anonymous_id=anon_uuid,
                    validation_status=validation_status_value,
                    validation_notes=validation_notes,
                )
                created = True
            rater_label = f'anonymous:{anon_uuid}'

        # Also keep legacy fields up to date (validated_by = last authenticated validator)
        if is_authenticated:
            from django.utils import timezone
            usage.validated_by = request.user
            usage.save(update_fields=['validated_by'])

        # Recompute consensus across all validations
        recompute_consensus(usage)
        # Refresh to get updated consensus status
        usage.refresh_from_db(fields=['validation_status', 'validated_at'])

        return Response({
            "message": "Validation submitted successfully",
            "usage_id": str(usage.id),
            "validation_id": validation_obj.id,
            "created": created,
            "validation_status": validation_status_value,
            "consensus_status": usage.validation_status,
            "validated_by": rater_label,
            "validated_at": usage.validated_at.isoformat() if usage.validated_at else None,
        })


class DatasetUsageValidationsListView(APIView):
    """
    GET /api/dataset-usages/<id>/validations/
    Returns the list of individual DatasetUsageValidation records for a usage
    plus a summary (total, approved, rejected, needs_review counts).
    Accessible to authenticated users only.
    """
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, usage_id):
        try:
            usage = DatasetUsage.objects.get(id=usage_id)
        except DatasetUsage.DoesNotExist:
            return Response({"error": "Dataset usage not found"}, status=status.HTTP_404_NOT_FOUND)

        validations = usage.validations.select_related('user').order_by('created_at')
        serializer = DatasetUsageValidationSerializer(validations, many=True)

        from collections import Counter
        counts = Counter(v.validation_status for v in validations)

        return Response({
            "usage_id": str(usage.id),
            "consensus_status": usage.validation_status,
            "total": validations.count(),
            "approved": counts.get('approved', 0),
            "rejected": counts.get('rejected', 0),
            "needs_review": counts.get('needs_review', 0),
            "validations": serializer.data,
        })


class ValidationKappaView(APIView):
    """
    GET /api/validation-kappa/
    Compute inter-rater agreement (Fleiss' kappa + pairwise Cohen's kappas)
    for a scope of DatasetUsageValidation records.

    Query params (all optional, scopes are ANDed):
      ?paper=<uuid>         — limit to a specific paper
      ?configuration=<name> — limit to usages from a specific analysis configuration
    If no params are supplied, all validations are used.
    """
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = DatasetUsageValidation.objects.select_related('user', 'dataset_usage')

        paper_id = request.query_params.get('paper')
        if paper_id:
            qs = qs.filter(dataset_usage__paper_id=paper_id)

        configuration = request.query_params.get('configuration')
        if configuration:
            qs = qs.filter(dataset_usage__paper_analysis__configuration_name=configuration)

        result = compute_kappa_for_validations(qs)
        return Response(result)


class ValidationQueueView(ListAPIView):
    """
    Get dataset usages that need validation, with filtering for validation workflow
    """
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]
    serializer_class = DatasetUsageDetailSerializer
    filter_backends = [filters.OrderingFilter]
    # Allow sorting by paper, observatory, instrument, start/end times, and id for tie-breaks
    ordering_fields = [
        'paper__bibcode',
        'instrument__observatory__datasource__slug',
        'instrument__observatory__short_name',
        'instrument__short_name',
        'start_lower',
        'end_upper',
        'observation_window',
        'validation_status',
        'id',
    ]
    # Default ordering aligns with desired claim order within papers, with deterministic tie-breakers
    ordering = [
        'paper__bibcode',
        'instrument__observatory__datasource__slug',
        'instrument__observatory__short_name',
        'instrument__short_name',
        'start_lower',
        'end_upper',
        'id',
    ]

    def get_queryset(self):
        queryset = DatasetUsage.objects.select_related(
            'paper', 'instrument', 'instrument__observatory',
            'validated_by'
        ).prefetch_related('supporting_quotes', 'analysis').annotate(
            supporting_quotes_count=Count('supporting_quotes')
        )

        # Filter by validation status (default to pending)
        validation_status = self.request.query_params.get('validation_status', 'pending')
        if validation_status != 'all':
            queryset = queryset.filter(validation_status=validation_status)

        # Only show items with supporting quotes for validation (they need PDF context)
        has_quotes_param = self.request.query_params.get('has_quotes', 'true')
        if has_quotes_param == 'true':
            queryset = queryset.filter(supporting_quotes__isnull=False).distinct()

        # Apply other filters similar to DatasetUsageListView
        instrument = self.request.query_params.get('instrument')
        if instrument:
            queryset = queryset.filter(instrument__short_name__icontains=instrument)

        observatory = self.request.query_params.get('observatory')
        if observatory:
            queryset = queryset.filter(instrument__observatory__short_name__icontains=observatory)

        # Always annotate bounds to enable ordering by lower/upper
        queryset = queryset.annotate(
            start_lower=Func(F('observation_window'), function='lower', output_field=DateTimeField()),
            end_upper=Func(F('observation_window'), function='upper', output_field=DateTimeField()),
        )

        return annotate_my_validation(queryset, self.request.user)


class UserProfileView(APIView):
    """Return basic profile info for the authenticated user."""
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        u = request.user
        return Response({
            'username': u.username,
            'email': u.email,
            'first_name': u.first_name,
            'last_name': u.last_name,
            'date_joined': u.date_joined.isoformat(),
            'is_staff': u.is_staff,
        })


class ValidationStatsView(APIView):
    """
    Get validation statistics for progress tracking
    """
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from django.utils import timezone
        from datetime import timedelta
        from django.db.models import Q, Count, F, Max, Case, When, IntegerField
        from django.db.models.functions import TruncDate
        from django.core.cache import cache
        import hashlib

        # Create cache key based on user ID
        cache_key = f"validation_stats:{request.user.id}"

        # Try to get from cache first (60 second TTL)
        cached_result = cache.get(cache_key)
        if cached_result is not None:
            return Response(cached_result)

        # Get total counts by validation status in a single query using conditional aggregation

        validation_stats_result = DatasetUsage.objects.aggregate(
            pending=Count('id', filter=Q(validation_status='pending')),
            approved=Count('id', filter=Q(validation_status='approved')),
            rejected=Count('id', filter=Q(validation_status='rejected')),
            needs_review=Count('id', filter=Q(validation_status='needs_review')),
        )
        validation_stats = {
            'pending': validation_stats_result['pending'],
            'approved': validation_stats_result['approved'],
            'rejected': validation_stats_result['rejected'],
            'needs_review': validation_stats_result['needs_review'],
        }

        # User-specific validation stats
        user_validated_count = DatasetUsage.objects.filter(validated_by=request.user).count()

        # Today's validation count for current user (claims)
        today = timezone.now().date()
        today_validated_count = DatasetUsage.objects.filter(
            validated_by=request.user,
            validated_at__date=today
        ).count()

        # Weekly validation count for current user (claims, last 7 days)
        week_ago = timezone.now() - timedelta(days=7)
        weekly_validated_count = DatasetUsage.objects.filter(
            validated_by=request.user,
            validated_at__gte=week_ago
        ).count()

        # Fully validated Paper Analyses by the user (count analyses where ALL usages are approved/rejected/needs_review)
        # This aligns with the "133" count derived from a more granular analysis concept.
        # It also explicitly includes 'needs_review' as a resolved state as per discussion.
        fully_validated_analyses = (
            PaperAnalysis.objects
            .filter(dataset_usages__isnull=False) # Ensure the analysis has some usages
            .annotate(
                total_usages=Count('dataset_usages'), # Total usages for this specific analysis
                # Usages are considered 'validated' if they are not 'pending'
                validated_usage_count=Count(
                    'dataset_usages',
                    filter=Q(dataset_usages__validation_status__in=['approved', 'rejected', 'needs_review'])
                ),
                # Check if the current user validated any usage within this analysis
                user_validated_any=Count(
                    'dataset_usages',
                    filter=Q(dataset_usages__validated_by=request.user)
                ),
                # The timestamp of the latest validation among usages for this analysis
                last_validated_at=Max('dataset_usages__validated_at')
            )
            .filter(
                total_usages__gt=0, # Must have at least one usage
                validated_usage_count=F('total_usages'), # All usages must be validated/resolved
                user_validated_any__gt=0 # The user must have contributed to this analysis
            )
        )

        # Update the 'papers_validated_*' variables with the new 'analyses' counts
        # This will immediately reflect the new "true count" on the frontend
        total_papers_validated = fully_validated_analyses.count()
        papers_validated_today = fully_validated_analyses.filter(last_validated_at__date=today).count()
        papers_validated_this_week = fully_validated_analyses.filter(last_validated_at__gte=week_ago).count()

        # Time-series for the last 7 days
        days_back = 7
        start_day = (timezone.now() - timedelta(days=days_back - 1)).date()
        # Claims per day
        claims_series_qs = (
            DatasetUsage.objects
            .filter(validated_by=request.user, validated_at__date__gte=start_day)
            .annotate(day=TruncDate('validated_at'))
            .values('day')
            .annotate(count=Count('id'))
        )
        claims_by_day = {row['day']: row['count'] for row in claims_series_qs}
        # Papers per day (distinct papers validated)
        papers_series_qs = (
            DatasetUsage.objects
            .filter(validated_by=request.user, validated_at__date__gte=start_day)
            .annotate(day=TruncDate('validated_at'))
            .values('day')
            .annotate(count=Count('paper_id', distinct=True))
        )
        papers_by_day = {row['day']: row['count'] for row in papers_series_qs}

        # Build ordered arrays for each day
        claims_per_day = []
        papers_per_day = []
        cur = start_day
        max_claims = 0
        max_papers = 0
        for i in range(days_back):
            c = int(claims_by_day.get(cur, 0))
            p = int(papers_by_day.get(cur, 0))
            claims_per_day.append(c)
            papers_per_day.append(p)
            if c > max_claims:
                max_claims = c
            if p > max_papers:
                max_papers = p
            cur = cur + timedelta(days=1)

        # Year heatmap (last 365 days) for profile page contribution graph
        year_days = 365
        year_start = (timezone.now() - timedelta(days=year_days - 1)).date()
        year_claims_qs = (
            DatasetUsage.objects
            .filter(validated_by=request.user, validated_at__date__gte=year_start)
            .annotate(day=TruncDate('validated_at'))
            .values('day')
            .annotate(count=Count('id'))
        )
        year_claims_by_day = {row['day']: row['count'] for row in year_claims_qs}
        year_heatmap = []
        cur_year = year_start
        for _ in range(year_days):
            year_heatmap.append({'date': cur_year.isoformat(), 'count': int(year_claims_by_day.get(cur_year, 0))})
            cur_year = cur_year + timedelta(days=1)

        response_data = {
            'total_stats': validation_stats,
            'user_stats': {
                'total_validated': user_validated_count,
                'validated_today': today_validated_count,
                'validated_this_week': weekly_validated_count,
                'papers_validated_total': total_papers_validated,
                'papers_validated_today': papers_validated_today,
                'papers_validated_this_week': papers_validated_this_week,
            },
            'series': {
                'start_date': start_day.isoformat(),
                'days': days_back,
                'claims_per_day': claims_per_day,
                'papers_per_day': papers_per_day,
                'max_claims': max_claims,
                'max_papers': max_papers,
                'year_heatmap': year_heatmap,
            },
            'progress': {
                'total_items': sum(validation_stats.values()),
                'completed_items': validation_stats['approved'] + validation_stats['rejected'],
                'completion_rate': round(
                    (validation_stats['approved'] + validation_stats['rejected']) /
                    sum(validation_stats.values()) * 100, 1
                ) if sum(validation_stats.values()) > 0 else 0
            }
        }

        # Cache for 60 seconds
        cache.set(cache_key, response_data, 60)

        return Response(response_data)


class PaperPDFAnnotationsView(RetrieveAPIView):
    """
    API endpoint that serves PDF annotations from the database instead of static JSON files.
    This replaces the hardcoded JSON file approach with proper database integration.
    """
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]
    serializer_class = PDFAnnotationsSerializer
    lookup_field = 'paper__bibcode'
    lookup_url_kwarg = 'bibcode'

    def get_queryset(self):
        return PaperAnalysis.objects.select_related('paper').prefetch_related('support_quotes')

    def get_object(self):
        """
        Get the PaperAnalysis for the given bibcode
        """
        bibcode = self.kwargs.get('bibcode')
        if not bibcode:
            raise Http404("Bibcode not provided")
        
        try:
            return self.get_queryset().get(paper__bibcode=bibcode)
        except PaperAnalysis.DoesNotExist:
            # If no analysis exists, return an empty structure
            try:
                paper = Paper.objects.get(bibcode=bibcode)
                # Create a minimal analysis structure for papers without analysis
                return type('EmptyAnalysis', (), {
                    'paper': paper,
                    'support_quotes': type('Manager', (), {'all': lambda: []})(),
                    'id': None,
                    'created_at': None
                })()
            except Paper.DoesNotExist:
                raise Http404(f"Paper with bibcode {bibcode} not found")

    def retrieve(self, request, *args, **kwargs):
        """
        Override retrieve to add custom response logic
        """
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return Response(serializer.data)


class PaperPDFView(APIView):
    """
    API endpoint that returns the PDF URL for a given bibcode.
    Used by the PDF viewer to get the correct database-backed PDF URL.
    """
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, bibcode):
        try:
            paper = Paper.objects.get(bibcode=bibcode)
            
            # Build the PDF URL if it exists
            if paper.pdf:
                pdf_url = paper.pdf.url
                # Only build absolute URI for relative URLs (local storage)
                # S3 storage returns absolute presigned URLs already
                if not pdf_url.startswith('http'):
                    pdf_url = request.build_absolute_uri(pdf_url)
                return Response({
                    'pdf_url': pdf_url,
                    'bibcode': paper.bibcode,
                    'has_pdf': True
                })
            else:
                return Response({
                    'pdf_url': None,
                    'bibcode': paper.bibcode,
                    'has_pdf': False,
                    'message': 'No PDF file found for this paper'
                })
                
        except Paper.DoesNotExist:
            return Response({
                'error': f'Paper with bibcode {bibcode} not found'
            }, status=status.HTTP_404_NOT_FOUND)


class PublicPaperPDFView(APIView):
    """
    Public API endpoint that returns the PDF URL for a given bibcode.
    """
    permission_classes = [AllowAny]

    def get(self, request, bibcode):
        try:
            paper = Paper.objects.get(bibcode=bibcode)

            if paper.pdf:
                pdf_url = paper.pdf.url
                if not pdf_url.startswith('http'):
                    pdf_url = request.build_absolute_uri(pdf_url)
                return Response({
                    'pdf_url': pdf_url,
                    'bibcode': paper.bibcode,
                    'has_pdf': True
                })

            return Response({
                'pdf_url': None,
                'bibcode': paper.bibcode,
                'has_pdf': False,
                'message': 'No PDF file found for this paper'
            })

        except Paper.DoesNotExist:
            return Response({
                'error': f'Paper with bibcode {bibcode} not found'
            }, status=status.HTTP_404_NOT_FOUND)


class PaperTagsListView(APIView):
    """
    Returns a sorted list of distinct Paper tags.
    """
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from django.db.models import Func, CharField
        tags = (
            Paper.objects
            .annotate(tag=Func('tags', function='unnest', output_field=CharField()))
            .values_list('tag', flat=True)
            .distinct()
            .order_by('tag')
        )
        return Response(list(tags))


class AvailableConfigurationsView(APIView):
    """
    Returns the list of available LLM configuration names.
    """
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        from paper_data_linking.config.settings import list_available_configurations
        return Response(list_available_configurations())


class PaperValidationQueueView(ListAPIView):
    """
    Get papers that have dataset usages needing validation
    Returns papers with aggregated validation statistics across all their analyses
    Shows one row per paper with combined statistics from all configurations
    """
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]
    # Use a lean serializer to avoid heavy relational counts per row
    from .serializers import PaperQueueSerializer as _PaperQueueSerializer
    serializer_class = _PaperQueueSerializer
    filter_backends = [filters.OrderingFilter, filters.SearchFilter]
    ordering_fields = [
        'bibcode',
        'created_at',
        'latest_analysis_date',
        'latest_validated_at',
        'validation_progress',
        'pending_count',
        'total_usages',
        'configuration_count',
        # allow pending percentage ordering explicitly
        'pending_percentage',
    ]
    ordering = ['bibcode']
    search_fields = ['bibcode', 'title']

    def get_queryset(self):
        from django.db.models import (
            F, Case, When, Value, FloatField, ExpressionWrapper,
            IntegerField, Q, Max, Count, Subquery, OuterRef
        )
        from .models import PaperAnalysis as _PA

        configuration_name = self.request.query_params.get('configuration_name')
        validation_status = self.request.query_params.get('validation_status', 'pending')

        # latest_analysis_date stays as a subquery to avoid a cross-join between
        # paperanalysis and dataset_usages that would inflate the COUNT aggregates.
        latest_analysis_sq = (
            _PA.objects
            .filter(paper=OuterRef('pk'))
            .order_by('-created_at')
            .values('created_at')[:1]
        )

        # Optional config filter applied inside each conditional aggregate via CASE/WHEN,
        # so it does not restrict the outer WHERE (which would exclude papers entirely).
        config_q = (
            Q(dataset_usages__paper_analysis__configuration_name=configuration_name)
            if configuration_name else Q()
        )

        # Single GROUP BY pass with conditional aggregation replaces 4 correlated subqueries.
        queryset = (
            Paper.objects
            .annotate(
                total_usages=Count('dataset_usages', filter=config_q, distinct=True),
                pending_count=Count(
                    'dataset_usages',
                    filter=config_q & Q(dataset_usages__validation_status='pending'),
                    distinct=True,
                ),
                validated_count=Count(
                    'dataset_usages',
                    filter=config_q & Q(dataset_usages__validation_status__in=['approved', 'rejected']),
                    distinct=True,
                ),
                latest_validated_at=Max('dataset_usages__validated_at', filter=config_q),
                latest_analysis_date=Subquery(latest_analysis_sq),
            )
        )

        # For "no_usages" show papers that were analyzed but produced no dataset usages.
        # For all other statuses keep the existing behaviour of only showing papers with usages.
        if validation_status == 'no_usages':
            queryset = queryset.filter(total_usages=0, latest_analysis_date__isnull=False)
        else:
            queryset = queryset.filter(total_usages__gt=0)

        # Filter by validation status
        if validation_status and validation_status not in ('all', 'no_usages'):
            if validation_status == 'pending':
                queryset = queryset.filter(pending_count__gt=0)
            elif validation_status == 'complete':
                queryset = queryset.filter(pending_count=0)
            else:
                queryset = queryset.filter(
                    dataset_usages__validation_status=validation_status,
                    dataset_usages__supporting_quotes__isnull=False,
                )

        # Filter by tags
        raw_tags = self.request.query_params.getlist('tags')
        if raw_tags:
            tags = []
            for t in raw_tags:
                if t is None:
                    continue
                parts = [p.strip() for p in str(t).split(',') if p.strip()]
                tags.extend(parts)
            if tags:
                queryset = queryset.filter(tags__contains=tags)

        # Computed fields for ordering (reference the annotated counts above)
        queryset = queryset.annotate(
            validation_progress=Case(
                When(total_usages__gt=0,
                     then=ExpressionWrapper(100.0 * F('validated_count') / F('total_usages'), output_field=FloatField())),
                default=Value(0.0),
                output_field=FloatField(),
            ),
            pending_percentage=Case(
                When(total_usages__gt=0,
                     then=ExpressionWrapper(100.0 * F('pending_count') / F('total_usages'), output_field=FloatField())),
                default=Value(0.0),
                output_field=FloatField(),
            ),
        )

        return queryset

    def _build_paper_data(self, paper):
        paper_data = self.get_serializer(paper).data
        paper_data['validation_stats'] = {
            'total_usages': paper.total_usages or 0,
            'pending': paper.pending_count or 0,
            'validation_progress': round(float(paper.validation_progress or 0.0), 1),
        }
        paper_data['latest_analysis_date'] = paper.latest_analysis_date.isoformat() if paper.latest_analysis_date else None
        paper_data['latest_validated_at'] = paper.latest_validated_at.isoformat() if paper.latest_validated_at else None
        return paper_data

    def list(self, request, *args, **kwargs):
        # Cache key from all query params that affect the result
        cache_params = {k: v for k, v in sorted(request.query_params.items())}
        cache_key = f"paper_validation_queue:{hashlib.md5(json.dumps(cache_params, sort_keys=True).encode()).hexdigest()}"
        cached = cache.get(cache_key)
        if cached is not None:
            return Response(cached)

        queryset = self.get_queryset()
        queryset = self.filter_queryset(queryset)

        page = self.paginate_queryset(queryset)
        if page is not None:
            result = [self._build_paper_data(p) for p in page]
            response = self.get_paginated_response(result)
            cache.set(cache_key, response.data, 120)
            return response

        result = [self._build_paper_data(p) for p in queryset]
        cache.set(cache_key, result, 120)
        return Response(result)


class PaperValidationQueueStatsView(APIView):
    """
    Return counts for pending and complete papers under current filters.
    - pending: papers with total_usages>0 and pending_count>0
    - complete: papers with total_usages>0 and pending_count=0
    Filters supported: configuration_name, tags

    OPTIMIZED: Uses a single aggregation query and caches results for 60 seconds
    """
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from django.db.models import Q, Count, Max, Case, When, IntegerField
        from django.core.cache import cache
        import hashlib
        import json

        configuration_name = request.query_params.get('configuration_name')
        raw_tags = request.query_params.getlist('tags')

        # Create cache key from filters
        cache_params = {
            'config': configuration_name or '',
            'tags': sorted(raw_tags) if raw_tags else []
        }
        cache_key = f"paper_validation_queue_stats:{hashlib.md5(json.dumps(cache_params, sort_keys=True).encode()).hexdigest()}"

        # Try to get from cache first
        cached_result = cache.get(cache_key)
        if cached_result is not None:
            return Response(cached_result)

        # Build config filter used inside annotations
        config_filter = Q()
        if configuration_name:
            config_filter = (
                Q(dataset_usages__paper_analysis__configuration_name=configuration_name)
            )

        # OPTIMIZATION: Use subqueries to count papers directly without annotating every paper
        # Build base filter for dataset usages
        dataset_filter = Q(dataset_usages__isnull=False)

        if configuration_name:
            dataset_filter &= (
                Q(dataset_usages__paper_analysis__configuration_name=configuration_name)
            )

        # Base queryset with filters
        base_qs = Paper.objects.filter(dataset_filter).distinct()

        if raw_tags:
            tags = []
            for t in raw_tags:
                if t is None:
                    continue
                parts = [p.strip() for p in str(t).split(',') if p.strip()]
                tags.extend(parts)
            if tags:
                base_qs = base_qs.filter(tags__contains=tags)

        # OPTIMIZATION: Use conditional aggregation to count papers directly
        # Count dataset usages grouped by validation status, then determine if paper has pending
        pending_filter = Q(dataset_usages__validation_status='pending')
        if configuration_name:
            pending_filter &= (
                Q(dataset_usages__paper_analysis__configuration_name=configuration_name)
            )
        # Annotate each paper with pending count, then aggregate. NOTE: named
        # live_* because Paper now has a precomputed `pending_usage_count`
        # FIELD (usage rollups) and Django forbids annotation names that
        # collide with model fields (this view 500'd on that ValueError). The
        # live computation stays: this endpoint filters by configuration_name,
        # which the global rollup column cannot express.
        annotated_qs = base_qs.annotate(
            live_pending_usage_count=Count(
                'dataset_usages',
                distinct=True,
                filter=pending_filter
            )
        )

        # Count papers with/without pending usages
        result = annotated_qs.aggregate(
            pending=Count('id', distinct=True, filter=Q(live_pending_usage_count__gt=0)),
            complete=Count('id', distinct=True, filter=Q(live_pending_usage_count=0))
        )

        response_data = {
            'pending': result['pending'] or 0,
            'complete': result['complete'] or 0,
        }

        # Cache for 60 seconds
        cache.set(cache_key, response_data, 60)

        return Response(response_data)


class PaperDatasetUsagesView(ListAPIView):
    """
    Get all dataset usages for a specific paper.
    This view is optimized for performance using a lightweight serializer
    and an efficient database query.
    """
    # --- Core View Setup ---
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]
    pagination_class = None

    # --- Key Change: Use the new, fast serializer ---
    serializer_class = PaperDatasetUsageListSerializer

    # --- Filtering and Ordering ---
    filter_backends = [filters.OrderingFilter]
    # Allow explicit ordering by observatory, instrument, start/end times, and id for tie-breaks
    ordering_fields = [
        'instrument__observatory__datasource__slug',
        'instrument__observatory__short_name',
        'instrument__short_name',
        'start_lower',
        'end_upper',
        'observation_window',
        'validation_status',
        'id',
    ]
    # Default within a paper: observatory > instrument > start > end > id
    ordering = [
        'instrument__observatory__datasource__slug',
        'instrument__observatory__short_name',
        'instrument__short_name',
        'start_lower',
        'end_upper',
        'id',
    ]

    def get_queryset(self):
        """
        Builds an optimized queryset that only fetches the data
        needed for the list view.
        """
        paper_id = self.kwargs.get('paper_id')

        # --- Key Change: Optimized Query ---
        # This query is much leaner. It only joins the instrument and observatory tables.
        queryset = DatasetUsage.objects.filter(
            paper__id=paper_id
        ).select_related(
            'instrument',
            'instrument__observatory',
            'instrument__observatory__datasource',
        ).annotate(
            start_lower=Func(F('observation_window'), function='lower', output_field=DateTimeField()),
            end_upper=Func(F('observation_window'), function='upper', output_field=DateTimeField()),
        )

        # --- Dynamic Filtering (remains the same) ---
        validation_status = self.request.query_params.get('validation_status')
        if validation_status and validation_status != 'all':
            queryset = queryset.filter(validation_status=validation_status)

        # Optional filter by producing configuration(s), comma-separable.
        configuration_name = self.request.query_params.get('configuration_name')
        if configuration_name:
            queryset = queryset.filter(
                paper_analysis__configuration_name__in=configuration_name.split(',')
            )

        has_quotes_param = self.request.query_params.get('has_quotes', 'true')
        if has_quotes_param == 'true':
            # We still filter by quotes, but now we add .distinct() to prevent duplicates
            # that can arise from the join on supporting_quotes.
            queryset = queryset.filter(supporting_quotes__isnull=False).distinct()

        # Apply default ordering within a paper if client didn't request a specific ordering
        if not self.request.query_params.get('ordering'):
            queryset = queryset.order_by(
                'instrument__observatory__datasource__slug',
                'instrument__observatory__short_name',
                'instrument__short_name',
                'start_lower',
                'end_upper',
                'id',
            )

        return annotate_my_validation(queryset, self.request.user)


class PaperValidationStatsView(APIView):
    """
    Get validation statistics for a specific paper
    """
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, paper_id):
        try:
            paper = Paper.objects.get(id=paper_id)
        except Paper.DoesNotExist:
            return Response(
                {"error": "Paper not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        # Get dataset usages for this paper
        usages = DatasetUsage.objects.filter(
            paper=paper,
            supporting_quotes__isnull=False
        ).distinct()

        # Calculate validation stats
        total_usages = usages.count()
        validation_stats = {}
        for status_choice in ['pending', 'approved', 'rejected', 'needs_review']:
            validation_stats[status_choice] = usages.filter(
                validation_status=status_choice
            ).count()

        # Calculate progress
        completed_items = validation_stats['approved'] + validation_stats['rejected']
        completion_rate = round(
            completed_items / total_usages * 100, 1
        ) if total_usages > 0 else 0

        return Response({
            'paper': {
                'id': str(paper.id),
                'bibcode': paper.bibcode
            },
            'validation_stats': validation_stats,
            'total_usages': total_usages,
            'completed_items': completed_items,
            'completion_rate': completion_rate
        })


class NextPaperInQueueView(APIView):
    """
    Get the next or previous paper in the validation queue.
    Accepts ?direction=next (default) or ?direction=prev.
    """
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, paper_id):
        try:
            current_paper = Paper.objects.get(id=paper_id)
        except Paper.DoesNotExist:
            return Response(
                {"error": "Current paper not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        validation_status = request.query_params.get('validation_status', 'pending')
        direction = request.query_params.get('direction', 'next')
        queue = request.query_params.get('queue', 'instruments')

        if queue == 'phenomena':
            mention_filter = PhenomenonMention.objects.filter(
                paper_analysis__paper=OuterRef('pk'),
            )
            if validation_status != 'all':
                mention_filter = mention_filter.filter(validation_status=validation_status)
            queryset = Paper.objects.filter(Exists(mention_filter))
        else:
            usage_filter = DatasetUsage.objects.filter(
                paper=OuterRef('pk'),
                supporting_quotes__isnull=False,
            )
            if validation_status != 'all':
                usage_filter = usage_filter.filter(validation_status=validation_status)
            queryset = Paper.objects.filter(Exists(usage_filter))

        if direction == 'prev':
            target = queryset.filter(
                bibcode__lt=current_paper.bibcode
            ).order_by('-bibcode').first()
            if not target:
                target = queryset.order_by('-bibcode').first()
        else:
            target = queryset.filter(
                bibcode__gt=current_paper.bibcode
            ).order_by('bibcode').first()
            if not target:
                target = queryset.order_by('bibcode').first()

        if target:
            return Response({
                'next_paper': {
                    'id': str(target.id),
                    'bibcode': target.bibcode
                }
            })
        else:
            return Response({
                'next_paper': None,
                'message': 'No more papers in validation queue'
            })


class PaperConfigurationComparisonView(APIView):
    """
    Compare dataset usages between different configurations for the same paper.
    Provides overlap analysis, statistics, and detailed comparisons.
    """
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, paper_id):
        """
        Compare two configurations for a paper
        Query params: config1, config2 (configuration names to compare)
        """
        config1 = request.query_params.get('config1')
        config2 = request.query_params.get('config2')
        
        if not config1 or not config2:
            return Response({
                'error': 'Both config1 and config2 parameters are required'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        if config1 == config2:
            return Response({
                'error': 'config1 and config2 must be different'
            }, status=status.HTTP_400_BAD_REQUEST)

        try:
            paper = Paper.objects.get(id=paper_id)
        except Paper.DoesNotExist:
            return Response({
                'error': 'Paper not found'
            }, status=status.HTTP_404_NOT_FOUND)

        # Get analyses for both configurations
        # Handle legacy configuration (configuration_name=None)
        config1_filter = None if config1.lower() == 'legacy' else config1
        config2_filter = None if config2.lower() == 'legacy' else config2
        
        try:
            analysis1 = PaperAnalysis.objects.get(paper=paper, configuration_name=config1_filter)
        except PaperAnalysis.DoesNotExist:
            return Response({
                'error': f'Analysis not found for configuration: {config1}'
            }, status=status.HTTP_404_NOT_FOUND)

        try:
            analysis2 = PaperAnalysis.objects.get(paper=paper, configuration_name=config2_filter)
        except PaperAnalysis.DoesNotExist:
            return Response({
                'error': f'Analysis not found for configuration: {config2}'
            }, status=status.HTTP_404_NOT_FOUND)

        # Get dataset usages for each configuration using paper_analysis FK
        usages1 = DatasetUsage.objects.filter(
            paper_analysis=analysis1
        ).select_related(
            'instrument',
            'instrument__observatory'
        ).prefetch_related(
            'supporting_quotes'
        )

        usages2 = DatasetUsage.objects.filter(
            paper_analysis=analysis2
        ).select_related(
            'instrument',
            'instrument__observatory'
        ).prefetch_related(
            'supporting_quotes'
        )

        # Perform simplified instrument set analysis
        overlap_analysis = self._analyze_instrument_sets(usages1, usages2)
        
        # Calculate statistics for each configuration
        stats1 = self._calculate_configuration_stats(analysis1, usages1)
        stats2 = self._calculate_configuration_stats(analysis2, usages2)

        # Serialize the dataset usages
        from .serializers import DatasetUsageDetailSerializer
        
        serialized_usages1 = DatasetUsageDetailSerializer(usages1, many=True, context={'request': request}).data
        serialized_usages2 = DatasetUsageDetailSerializer(usages2, many=True, context={'request': request}).data

        return Response({
            'paper': {
                'id': str(paper.id),
                'bibcode': paper.bibcode,
                'title': paper.title,
                'created_at': paper.created_at.isoformat() if paper.created_at else None
            },
            'configurations': {
                config1: {
                    'analysis': {
                        'id': analysis1.id,
                        'created_at': analysis1.created_at.isoformat(),
                        'status': analysis1.status
                    },
                    'statistics': stats1,
                    'dataset_usages': serialized_usages1
                },
                config2: {
                    'analysis': {
                        'id': analysis2.id,
                        'created_at': analysis2.created_at.isoformat(),
                        'status': analysis2.status
                    },
                    'statistics': stats2,
                    'dataset_usages': serialized_usages2
                }
            },
            'comparison': {
                'instrument_analysis': overlap_analysis,
                'summary': {
                    'shared_instruments': overlap_analysis['metrics']['shared_count'],
                    'config1_only_instruments': overlap_analysis['unique_to_config1_count'],
                    'config2_only_instruments': overlap_analysis['unique_to_config2_count'],
                    'total_unique_instruments': overlap_analysis['metrics']['total_unique_instruments'],
                    'jaccard_index': overlap_analysis['metrics']['jaccard_index'],
                    'f1_score': overlap_analysis['metrics']['f1_score'],
                    'precision': overlap_analysis['metrics']['precision'],
                    'recall': overlap_analysis['metrics']['recall'],
                    'overlap_percentage': overlap_analysis['overlap_percentage']
                }
            }
        })

    def _analyze_instrument_sets(self, usages1, usages2):
        """
        Simple instrument set comparison between two configurations
        Returns instrument overlap analysis using standard set operations
        """
        # Extract unique instruments from each configuration
        instruments1 = set(usage.instrument.short_name for usage in usages1)
        instruments2 = set(usage.instrument.short_name for usage in usages2)
        
        # Perform set operations
        intersection = instruments1 & instruments2
        unique_to_config1 = instruments1 - instruments2
        unique_to_config2 = instruments2 - instruments1
        union = instruments1 | instruments2
        
        # Calculate standard set comparison metrics
        jaccard_index = len(intersection) / len(union) if union else 0
        precision = len(intersection) / len(instruments1) if instruments1 else 0
        recall = len(intersection) / len(instruments2) if instruments2 else 0
        f1_score = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0
        
        return {
            'shared_instruments': sorted(list(intersection)),
            'config1_only_instruments': sorted(list(unique_to_config1)),
            'config2_only_instruments': sorted(list(unique_to_config2)),
            'metrics': {
                'jaccard_index': round(jaccard_index, 3),
                'precision': round(precision, 3),
                'recall': round(recall, 3),
                'f1_score': round(f1_score, 3),
                'config1_count': len(instruments1),
                'config2_count': len(instruments2),
                'shared_count': len(intersection),
                'total_unique_instruments': len(union)
            },
            # Legacy compatibility - map to old structure for gradual migration
            'overlapping_count': len(intersection),
            'unique_to_config1_count': len(unique_to_config1),
            'unique_to_config2_count': len(unique_to_config2),
            'overlap_percentage': round(jaccard_index * 100, 1)
        }


    def _calculate_configuration_stats(self, analysis, usages):
        """
        Calculate statistics for a configuration
        """
        total_usages = usages.count()
        
        validation_stats = {}
        for status_choice in ['pending', 'approved', 'rejected', 'needs_review']:
            validation_stats[status_choice] = usages.filter(validation_status=status_choice).count()
        
        completed_validations = validation_stats['approved'] + validation_stats['rejected']
        validation_progress = round(completed_validations / total_usages * 100, 1) if total_usages > 0 else 0
        
        # Count unique instruments and observatories
        unique_instruments = usages.values('instrument').distinct().count()
        unique_observatories = usages.values('instrument__observatory').distinct().count()
        
        return {
            'total_usages': total_usages,
            'validation_stats': validation_stats,
            'validation_progress': validation_progress,
            'unique_instruments': unique_instruments,
            'unique_observatories': unique_observatories,
            'analysis_date': analysis.created_at.isoformat()
        }


class AggregateConfigurationComparisonView(APIView):
    """
    Provides aggregate comparison analysis across ALL papers that have multiple configurations.
    Shows overall statistics, distributions, and patterns in configuration performance.
    """
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        """
        Get aggregate configuration comparison data
        Query params:
        - config1, config2: configurations to compare (optional, defaults to most common pair)
        - paper_filter: filter papers by characteristics (optional)
        - page: page number for pagination (default: 1)
        - page_size: number of papers per page (default: 50, max: 200)
        """
        config1 = request.query_params.get('config1')
        config2 = request.query_params.get('config2')

        # Pagination parameters
        try:
            page = int(request.query_params.get('page', 1))
            page_size = int(request.query_params.get('page_size', 50))
        except ValueError:
            return Response({
                'error': 'page and page_size must be valid integers'
            }, status=status.HTTP_400_BAD_REQUEST)

        # Validate pagination parameters
        if page < 1:
            return Response({
                'error': 'page must be >= 1'
            }, status=status.HTTP_400_BAD_REQUEST)

        if page_size < 1 or page_size > 200:
            return Response({
                'error': 'page_size must be between 1 and 200'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Get all papers that have multiple configurations
        papers_with_multiple_configs = self._get_papers_with_multiple_configs()
        
        if not papers_with_multiple_configs:
            # For now, return a helpful message with current database state
            config_counts = {}
            for analysis in PaperAnalysis.objects.all():
                config_name = analysis.configuration_name or 'legacy'
                config_counts[config_name] = config_counts.get(config_name, 0) + 1
            
            return Response({
                'error': 'No papers found with multiple configurations',
                'debug_info': {
                    'total_papers': Paper.objects.count(),
                    'total_analyses': PaperAnalysis.objects.count(),
                    'configuration_distribution': config_counts,
                    'suggestion': 'Run analyses with different configurations on the same papers to enable comparison'
                }
            }, status=status.HTTP_404_NOT_FOUND)
        
        # If no configurations specified, return available options
        if not config1 and not config2:
            return Response({
                'available_config_pairs': self._get_available_config_pairs(papers_with_multiple_configs),
                'total_papers_with_multiple_configs': len(papers_with_multiple_configs)
            })
        
        # Require both configurations to be specified  
        if not config1 or not config2:
            return Response({
                'error': 'Both config1 and config2 parameters are required',
                'available_config_pairs': self._get_available_config_pairs(papers_with_multiple_configs)
            }, status=status.HTTP_400_BAD_REQUEST)
        
        config1_filter = config1
        config2_filter = config2
        
        # Filter papers that have both requested configurations
        comparable_papers = self._filter_papers_with_configs(
            papers_with_multiple_configs, config1_filter, config2_filter
        )
        
        if not comparable_papers:
            # Valid configurations but no overlap - return empty results instead of error
            return Response({
                'configurations_compared': {
                    'config1': config1,
                    'config2': config2
                },
                'overview': {
                    'total_papers': 0,
                    'total_papers_with_multiple_configs': len(papers_with_multiple_configs),
                    'comparison_coverage': 0.0
                },
                'aggregate_metrics': {
                    'total_comparisons': 0,
                    'f1_score': {'mean': 0, 'median': 0, 'std': 0, 'min': 0, 'max': 0},
                    'jaccard_index': {'mean': 0, 'median': 0, 'std': 0},
                    'precision': {'mean': 0, 'median': 0, 'std': 0},
                    'recall': {'mean': 0, 'median': 0, 'std': 0},
                    'instrument_counts': {
                        'config1': {'mean': 0, 'median': 0, 'total': 0},
                        'config2': {'mean': 0, 'median': 0, 'total': 0},
                        'shared': {'mean': 0, 'median': 0, 'total': 0}
                    }
                },
                'distributions': {
                    'f1_score_histogram': [],
                    'agreement_level_distribution': []
                },
                'paper_summaries': [],
                'available_config_pairs': self._get_available_config_pairs(papers_with_multiple_configs)
            })
        
        # Perform aggregate analysis
        aggregate_stats = self._calculate_aggregate_stats(
            comparable_papers, config1_filter, config2_filter
        )
        
        # Get per-paper comparison summaries
        paper_summaries = self._get_paper_comparison_summaries(
            comparable_papers, config1_filter, config2_filter
        )

        # Calculate distribution statistics (based on all papers, not just current page)
        distributions = self._calculate_distributions(paper_summaries)

        # Apply pagination to paper summaries
        total_papers = len(paper_summaries)
        start_index = (page - 1) * page_size
        end_index = start_index + page_size
        paginated_summaries = paper_summaries[start_index:end_index]

        # Calculate pagination metadata
        total_pages = (total_papers + page_size - 1) // page_size
        has_next = page < total_pages
        has_previous = page > 1

        return Response({
            'configurations_compared': {
                'config1': config1,
                'config2': config2
            },
            'overview': {
                'total_papers': len(comparable_papers),
                'total_papers_with_multiple_configs': len(papers_with_multiple_configs),
                'comparison_coverage': round(len(comparable_papers) / len(papers_with_multiple_configs) * 100, 1)
            },
            'aggregate_metrics': aggregate_stats,
            'distributions': distributions,
            'paper_summaries': paginated_summaries,
            'pagination': {
                'current_page': page,
                'page_size': page_size,
                'total_papers': total_papers,
                'total_pages': total_pages,
                'has_next': has_next,
                'has_previous': has_previous,
                'start_index': start_index + 1 if paginated_summaries else 0,
                'end_index': min(end_index, total_papers) if paginated_summaries else 0
            },
            'available_config_pairs': self._get_available_config_pairs(papers_with_multiple_configs)
        })
    
    def _get_papers_with_multiple_configs(self):
        """Get all papers that have analyses from multiple configurations"""
        # Get papers that have more than one distinct configuration (including None/legacy)
        papers_with_analyses = Paper.objects.filter(
            paperanalysis__isnull=False
        ).prefetch_related('paperanalysis_set').distinct()
        
        papers_with_multiple = []
        for paper in papers_with_analyses:
            # Get unique configuration names for this paper (None counts as 'legacy')
            configs = set(paper.paperanalysis_set.values_list('configuration_name', flat=True))
            if len(configs) >= 2:
                papers_with_multiple.append(paper)
        
        return papers_with_multiple
    
    def _find_most_common_config_pair(self, papers):
        """Find the most common configuration pair across papers"""
        from collections import Counter
        
        config_pairs = []
        for paper in papers:
            configs = list(paper.paperanalysis_set.values_list('configuration_name', flat=True).distinct())
            # Handle legacy None configuration
            configs = ['legacy' if c is None else c for c in configs]
            
            # Generate all pairs for this paper
            for i, c1 in enumerate(configs):
                for c2 in configs[i+1:]:
                    pair = tuple(sorted([c1, c2]))
                    config_pairs.append(pair)
        
        if not config_pairs:
            return None
        
        # Return the most common pair
        most_common = Counter(config_pairs).most_common(1)[0]
        return most_common[0]
    
    def _filter_papers_with_configs(self, papers, config1, config2):
        """Filter papers to only those that have both requested configurations"""
        filtered = []
        for paper in papers:
            configs = set(paper.paperanalysis_set.values_list('configuration_name', flat=True))
            if config1 in configs and config2 in configs:
                filtered.append(paper)
        return filtered
    
    def _calculate_aggregate_stats(self, papers, config1_filter, config2_filter):
        """Calculate aggregate statistics across all papers"""
        total_comparisons = len(papers)
        
        f1_scores = []
        jaccard_scores = []
        precisions = []
        recalls = []
        
        config1_instrument_counts = []
        config2_instrument_counts = []
        shared_instrument_counts = []
        
        for paper in papers:
            # Get paper analyses for both configurations
            try:
                analysis1 = PaperAnalysis.objects.get(paper=paper, configuration_name=config1_filter)
                analysis2 = PaperAnalysis.objects.get(paper=paper, configuration_name=config2_filter)
            except PaperAnalysis.DoesNotExist:
                continue  # Skip if either analysis not found

            # Get usages for both configurations using paper_analysis FK
            usages1 = DatasetUsage.objects.filter(
                paper_analysis=analysis1
            ).select_related('instrument')

            usages2 = DatasetUsage.objects.filter(
                paper_analysis=analysis2
            ).select_related('instrument')
            
            # Calculate comparison for this paper
            instruments1 = set(u.instrument.short_name for u in usages1)
            instruments2 = set(u.instrument.short_name for u in usages2)
            
            intersection = instruments1 & instruments2
            union = instruments1 | instruments2
            
            # Calculate metrics
            jaccard = len(intersection) / len(union) if union else 0
            precision = len(intersection) / len(instruments1) if instruments1 else 0
            recall = len(intersection) / len(instruments2) if instruments2 else 0
            f1 = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0
            
            # Collect data points
            f1_scores.append(f1)
            jaccard_scores.append(jaccard)
            precisions.append(precision)
            recalls.append(recall)
            
            config1_instrument_counts.append(len(instruments1))
            config2_instrument_counts.append(len(instruments2))
            shared_instrument_counts.append(len(intersection))
        
        import statistics
        
        return {
            'total_comparisons': total_comparisons,
            'f1_score': {
                'mean': round(statistics.mean(f1_scores), 3),
                'median': round(statistics.median(f1_scores), 3),
                'std': round(statistics.stdev(f1_scores), 3) if len(f1_scores) > 1 else 0,
                'min': round(min(f1_scores), 3),
                'max': round(max(f1_scores), 3)
            },
            'jaccard_index': {
                'mean': round(statistics.mean(jaccard_scores), 3),
                'median': round(statistics.median(jaccard_scores), 3),
                'std': round(statistics.stdev(jaccard_scores), 3) if len(jaccard_scores) > 1 else 0
            },
            'precision': {
                'mean': round(statistics.mean(precisions), 3),
                'median': round(statistics.median(precisions), 3),
                'std': round(statistics.stdev(precisions), 3) if len(precisions) > 1 else 0
            },
            'recall': {
                'mean': round(statistics.mean(recalls), 3),
                'median': round(statistics.median(recalls), 3), 
                'std': round(statistics.stdev(recalls), 3) if len(recalls) > 1 else 0
            },
            'instrument_counts': {
                'config1': {
                    'mean': round(statistics.mean(config1_instrument_counts), 1),
                    'median': round(statistics.median(config1_instrument_counts), 1),
                    'total': sum(config1_instrument_counts)
                },
                'config2': {
                    'mean': round(statistics.mean(config2_instrument_counts), 1),
                    'median': round(statistics.median(config2_instrument_counts), 1),
                    'total': sum(config2_instrument_counts)
                },
                'shared': {
                    'mean': round(statistics.mean(shared_instrument_counts), 1),
                    'median': round(statistics.median(shared_instrument_counts), 1),
                    'total': sum(shared_instrument_counts)
                }
            }
        }
    
    def _get_paper_comparison_summaries(self, papers, config1_filter, config2_filter):
        """Get summary comparison data for each paper"""
        summaries = []

        for paper in papers:
            # Get the PaperAnalysis objects for each config
            try:
                analysis1 = PaperAnalysis.objects.get(paper=paper, configuration_name=config1_filter)
                analysis2 = PaperAnalysis.objects.get(paper=paper, configuration_name=config2_filter)
            except PaperAnalysis.DoesNotExist:
                # Skip papers that don't have both analyses
                continue

            usages1 = DatasetUsage.objects.filter(
                paper_analysis=analysis1
            ).select_related('instrument')

            usages2 = DatasetUsage.objects.filter(
                paper_analysis=analysis2
            ).select_related('instrument')
            
            instruments1 = set(u.instrument.short_name for u in usages1)
            instruments2 = set(u.instrument.short_name for u in usages2)
            intersection = instruments1 & instruments2
            union = instruments1 | instruments2
            
            # Calculate metrics
            jaccard = len(intersection) / len(union) if union else 0
            precision = len(intersection) / len(instruments1) if instruments1 else 0
            recall = len(intersection) / len(instruments2) if instruments2 else 0
            f1 = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0
            
            summaries.append({
                'paper_id': str(paper.id),
                'bibcode': paper.bibcode,
                'title': paper.title,
                'metrics': {
                    'f1_score': round(f1, 3),
                    'jaccard_index': round(jaccard, 3),
                    'precision': round(precision, 3),
                    'recall': round(recall, 3)
                },
                'instrument_counts': {
                    'config1_count': len(instruments1),
                    'config2_count': len(instruments2),
                    'shared_count': len(intersection),
                    'total_unique': len(union)
                },
                'agreement_level': self._categorize_agreement(f1)
            })
        
        # Sort by F1 score descending
        return sorted(summaries, key=lambda x: x['metrics']['f1_score'], reverse=True)
    
    def _calculate_distributions(self, paper_summaries):
        """Calculate distribution statistics for visualization"""
        f1_scores = [p['metrics']['f1_score'] for p in paper_summaries]
        
        # Create histogram bins for F1 scores
        import numpy as np
        
        bins = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]
        hist, _ = np.histogram(f1_scores, bins=bins)
        
        f1_distribution = []
        for i, count in enumerate(hist):
            f1_distribution.append({
                'range': f'{bins[i]:.1f} - {bins[i+1]:.1f}',
                'count': int(count),
                'percentage': round(count / len(f1_scores) * 100, 1)
            })
        
        # Agreement level distribution
        agreement_levels = [p['agreement_level'] for p in paper_summaries]
        from collections import Counter
        agreement_counts = Counter(agreement_levels)
        
        agreement_distribution = []
        for level in ['High', 'Moderate', 'Low']:
            count = agreement_counts.get(level, 0)
            agreement_distribution.append({
                'level': level,
                'count': count,
                'percentage': round(count / len(paper_summaries) * 100, 1)
            })
        
        return {
            'f1_score_histogram': f1_distribution,
            'agreement_level_distribution': agreement_distribution
        }
    
    def _categorize_agreement(self, f1_score):
        """Categorize agreement level based on F1 score"""
        if f1_score >= 0.7:
            return 'High'
        elif f1_score >= 0.4:
            return 'Moderate'
        else:
            return 'Low'
    
    def _get_available_config_pairs(self, papers):
        """Get all available configuration pairs for filtering"""
        from collections import Counter

        config_pairs = []
        for paper in papers:
            configs = list(paper.paperanalysis_set.values_list('configuration_name', flat=True).distinct())
            configs = ['legacy' if c is None else c for c in configs]

            for i, c1 in enumerate(configs):
                for c2 in configs[i+1:]:
                    pair = tuple(sorted([c1, c2]))
                    config_pairs.append(pair)

        pair_counts = Counter(config_pairs).most_common()

        return [
            {
                'config1': pair[0],
                'config2': pair[1],
                'paper_count': count
            }
            for (pair, count) in pair_counts
        ]


def wilson_score_ci(successes, total, z=1.96):
    """Wilson score confidence interval for a binomial proportion."""
    if total == 0:
        return (0.0, 0.0)
    p_hat = successes / total
    denom = 1 + z ** 2 / total
    center = (p_hat + z ** 2 / (2 * total)) / denom
    margin = (z / denom) * math.sqrt(
        p_hat * (1 - p_hat) / total + z ** 2 / (4 * total ** 2)
    )
    return (round(max(0.0, center - margin), 4), round(min(1.0, center + margin), 4))


class MonitoringDashboardView(APIView):
    """
    High-level monitoring dashboard: aggregate counts, overall precision
    with Wilson score CI, and per-instrument precision breakdown.
    Cached for 5 minutes.
    """
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        # ?needs_review=exclude (default) | as_denominator
        nr_mode = request.query_params.get('needs_review', 'exclude')
        if nr_mode not in ('exclude', 'as_denominator'):
            nr_mode = 'exclude'

        configuration = request.query_params.get('configuration', None)

        cache_key = f"monitoring_dashboard:{nr_mode}:{configuration or 'all'}"
        cached = cache.get(cache_key)
        if cached is not None:
            return Response(cached)

        # Always query all three decided statuses; nr_mode only affects denominator
        reviewed_statuses = ['approved', 'rejected', 'needs_review']

        # Base queryset — optionally filtered by configuration
        base_qs = DatasetUsage.objects.all()
        if configuration:
            base_qs = base_qs.filter(paper_analysis__configuration_name=configuration)

        # Aggregate counts
        total_papers = Paper.objects.count()
        total_dataset_usages = base_qs.count()
        total_observatories = Observatory.objects.filter(
            instrument__datasetusage__in=base_qs
        ).distinct().count()
        total_instruments = Instrument.objects.filter(
            datasetusage__in=base_qs
        ).distinct().count()
        validated_papers = Paper.objects.filter(
            dataset_usages__in=base_qs,
            dataset_usages__validation_status__in=['approved', 'rejected']
        ).distinct().count()

        # Overall precision
        overall_agg = base_qs.filter(
            validation_status__in=reviewed_statuses
        ).aggregate(
            approved=Count('id', filter=Q(validation_status='approved')),
            rejected=Count('id', filter=Q(validation_status='rejected')),
            needs_review=Count('id', filter=Q(validation_status='needs_review')),
        )
        overall_approved = overall_agg['approved']
        overall_rejected = overall_agg['rejected']
        overall_needs_review = overall_agg['needs_review']

        if nr_mode == 'as_denominator':
            overall_denom = overall_approved + overall_rejected + overall_needs_review
        else:
            overall_denom = overall_approved + overall_rejected

        overall_precision = round(overall_approved / overall_denom, 4) if overall_denom > 0 else None
        overall_ci = wilson_score_ci(overall_approved, overall_denom)

        # Per-instrument precision
        per_instrument_qs = (
            base_qs
            .filter(validation_status__in=reviewed_statuses)
            .values(
                'instrument__id',
                'instrument__short_name',
                'instrument__display_name',
                'instrument__observatory__id',
                'instrument__observatory__short_name',
                'instrument__observatory__display_name',
            )
            .annotate(
                approved=Count('id', filter=Q(validation_status='approved')),
                rejected=Count('id', filter=Q(validation_status='rejected')),
                needs_review=Count('id', filter=Q(validation_status='needs_review')),
            )
        )

        per_instrument = []
        for row in per_instrument_qs:
            approved = row['approved']
            rejected = row['rejected']
            needs_review = row['needs_review']
            if nr_mode == 'as_denominator':
                total = approved + rejected + needs_review
            else:
                total = approved + rejected
            precision = round(approved / total, 4) if total > 0 else None
            ci_low, ci_high = wilson_score_ci(approved, total)
            per_instrument.append({
                'instrument_id': str(row['instrument__id']),
                'instrument_short_name': row['instrument__short_name'],
                'instrument_display_name': row['instrument__display_name'],
                'observatory_id': str(row['instrument__observatory__id']),
                'observatory_short_name': row['instrument__observatory__short_name'],
                'observatory_display_name': row['instrument__observatory__display_name'],
                'approved': approved,
                'rejected': rejected,
                'needs_review': needs_review,
                'total_validated': total,
                'precision': precision,
                'ci_low': ci_low,
                'ci_high': ci_high,
            })

        response_data = {
            'needs_review_mode': nr_mode,
            'configuration': configuration,
            'counts': {
                'total_papers': total_papers,
                'total_observatories': total_observatories,
                'total_instruments': total_instruments,
                'total_dataset_usages': total_dataset_usages,
                'validated_papers': validated_papers,
                'needs_review_total': overall_needs_review,
            },
            'overall_precision': {
                'approved': overall_approved,
                'rejected': overall_rejected,
                'needs_review': overall_needs_review,
                'total_validated': overall_denom,
                'precision': overall_precision,
                'ci_low': overall_ci[0],
                'ci_high': overall_ci[1],
            },
            'per_instrument': per_instrument,
        }

        cache.set(cache_key, response_data, 300)
        return Response(response_data)


class CostMonitoringView(APIView):
    """
    Cost breakdown for LLM calls: batch vs real-time, by pipeline stage, by model.
    Cached for 5 minutes. Optional date range filtering.
    """
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    STAGE_GROUPS = {
        "Extraction": [
            "paper_analysis",
            "structure_analysis",           # LLM-based structured output path
            "structure_validation_time_range",  # deterministic-parse patch path
        ],
        "Grounding": [
            "mission_identification", "mission_selection",
            "instrument_selection", "instrument_multiple_selection",
            "instrument_validation",
        ],
        "Normalization": [
            "time_normalization", "wavelength_normalization",
            "physobs_normalization", "cadence_normalization",
            "detector_normalization",
        ],
    }

    CONFIG_DISPLAY_NAMES = {
        'standard': 'Standard (GPT-5)',
        'budget': 'Budget (GPT-5 Mini)',
        'super-budget': 'Super Budget (GPT-5 Nano)',
        'bedrock-test': 'Bedrock (GPT-OSS)',
        'hybrid': 'Hybrid',
    }

    MODEL_DISPLAY_NAMES = {
        "openai/gpt-5": "GPT-5",
        "openai/gpt-5-mini": "GPT-5 Mini",
        "openai/gpt-5-nano": "GPT-5 Nano",
        "bedrock/converse/openai.gpt-oss-120b-1:0": "GPT-OSS 120B (Bedrock)",
        "bedrock/converse/openai.gpt-oss-20b-1:0": "GPT-OSS 20B (Bedrock)",
        "openai/text-embedding-3-small": "Embeddings (small)",
    }

    def get(self, request):
        start_date = request.query_params.get('start_date')
        end_date = request.query_params.get('end_date')

        cache_key = f"cost_monitoring:{start_date}:{end_date}"
        cached = cache.get(cache_key)
        if cached is not None:
            return Response(cached)

        qs = LLMCall.objects.all()
        is_default = True
        if start_date:
            qs = qs.filter(created_at__date__gte=start_date)
            is_default = False
        if end_date:
            qs = qs.filter(created_at__date__lte=end_date)
            is_default = False

        # Totals
        totals_agg = qs.aggregate(
            total_cost=Sum('estimated_cost_usd'),
            total_calls=Count('id'),
            total_tokens=Sum('total_tokens'),
        )
        total_cost = float(totals_agg['total_cost'] or 0)
        total_calls = totals_agg['total_calls'] or 0
        total_tokens = totals_agg['total_tokens'] or 0

        distinct_papers = (
            PaperAnalysis.objects
            .filter(llm_calls__in=qs)
            .values('paper_id')
            .distinct()
            .count()
        )
        avg_cost_per_paper = round(total_cost / distinct_papers, 6) if distinct_papers > 0 else 0

        # Date range boundaries
        if is_default and total_calls > 0:
            date_bounds = qs.aggregate(start=Min('created_at'), end=Max('created_at'))
            range_start = date_bounds['start'].date().isoformat() if date_bounds['start'] else None
            range_end = date_bounds['end'].date().isoformat() if date_bounds['end'] else None
        else:
            range_start = start_date
            range_end = end_date

        # Batch vs real-time
        batch_agg = qs.filter(metadata__batch_job_id__isnull=False).aggregate(
            cost=Sum('estimated_cost_usd'), calls=Count('id'), tokens=Sum('total_tokens'),
        )
        realtime_agg = qs.exclude(metadata__batch_job_id__isnull=False).aggregate(
            cost=Sum('estimated_cost_usd'), calls=Count('id'), tokens=Sum('total_tokens'),
        )

        # By call_type
        by_call_type_qs = (
            qs.values('call_type')
            .annotate(
                cost=Sum('estimated_cost_usd'),
                calls=Count('id'),
                tokens=Sum('total_tokens'),
            )
            .order_by('-cost')
        )

        # Build inverted mapping: call_type -> stage
        ct_to_stage = {}
        for stage, types in self.STAGE_GROUPS.items():
            for ct in types:
                ct_to_stage[ct] = stage

        stage_data = {}  # stage -> {cost, calls, tokens, breakdown: []}
        for row in by_call_type_qs:
            ct = row['call_type']
            stage = ct_to_stage.get(ct, 'Other')
            if stage not in stage_data:
                stage_data[stage] = {'stage': stage, 'cost_usd': 0, 'calls': 0, 'tokens': 0, 'breakdown': []}
            stage_data[stage]['cost_usd'] += float(row['cost'] or 0)
            stage_data[stage]['calls'] += row['calls']
            stage_data[stage]['tokens'] += row['tokens'] or 0
            stage_data[stage]['breakdown'].append({
                'call_type': ct,
                'cost_usd': round(float(row['cost'] or 0), 6),
                'calls': row['calls'],
                'tokens': row['tokens'] or 0,
            })

        # Compute percentages and sort
        by_stage = sorted(stage_data.values(), key=lambda s: s['cost_usd'], reverse=True)
        for s in by_stage:
            s['cost_usd'] = round(s['cost_usd'], 6)
            s['pct'] = round(s['cost_usd'] / total_cost * 100, 1) if total_cost > 0 else 0
            s['breakdown'].sort(key=lambda b: b['cost_usd'], reverse=True)

        # By model
        by_model_qs = (
            qs.values('model_name', 'provider')
            .annotate(
                cost=Sum('estimated_cost_usd'),
                calls=Count('id'),
                prompt_tokens=Sum('prompt_tokens'),
                completion_tokens=Sum('completion_tokens'),
            )
            .order_by('-cost')
        )
        by_model = []
        for row in by_model_qs:
            cost = float(row['cost'] or 0)
            by_model.append({
                'model_name': row['model_name'],
                'display_name': self.MODEL_DISPLAY_NAMES.get(row['model_name'], row['model_name']),
                'provider': row['provider'],
                'cost_usd': round(cost, 6),
                'calls': row['calls'],
                'prompt_tokens': row['prompt_tokens'] or 0,
                'completion_tokens': row['completion_tokens'] or 0,
                'pct': round(cost / total_cost * 100, 1) if total_cost > 0 else 0,
            })

        # By day (temporal spend trend)
        from django.db.models.functions import TruncDate
        by_day_qs = (
            qs.annotate(day=TruncDate('created_at'))
            .values('day')
            .annotate(cost=Sum('estimated_cost_usd'), calls=Count('id'))
            .order_by('day')
        )
        by_day = [
            {
                'day': row['day'].isoformat() if row['day'] else None,
                'cost': round(float(row['cost'] or 0), 6),
                'calls': row['calls'],
            }
            for row in by_day_qs
        ]

        # By configuration (via M2M through PaperAnalysis)
        through_model = PaperAnalysis.llm_calls.through
        config_ct_qs = (
            through_model.objects
            .filter(llmcall_id__in=qs)
            .values(
                configuration=F('paperanalysis__configuration_name'),
                call_type=F('llmcall__call_type'),
            )
            .annotate(
                cost=Sum('llmcall__estimated_cost_usd'),
                calls=Count('llmcall_id', distinct=True),
                tokens=Sum('llmcall__total_tokens'),
            )
            .order_by('configuration', '-cost')
        )

        # Count distinct papers per configuration
        config_papers_qs = (
            PaperAnalysis.objects
            .filter(llm_calls__in=qs)
            .values('configuration_name')
            .annotate(papers=Count('paper_id', distinct=True))
        )
        config_paper_counts = {
            (row['configuration_name'] or 'legacy'): row['papers']
            for row in config_papers_qs
        }

        # Per-paper costs for each configuration (for distribution viz)
        paper_cost_qs = (
            through_model.objects
            .filter(llmcall_id__in=qs)
            .values(
                configuration=F('paperanalysis__configuration_name'),
                paper_id=F('paperanalysis__paper_id'),
                bibcode=F('paperanalysis__paper__bibcode'),
            )
            .annotate(cost=Sum('llmcall__estimated_cost_usd'))
            .order_by('configuration', 'cost')
        )
        config_paper_costs = {}
        for row in paper_cost_qs:
            config = row['configuration'] or 'legacy'
            if config not in config_paper_costs:
                config_paper_costs[config] = []
            config_paper_costs[config].append({
                'cost': round(float(row['cost'] or 0), 4),
                'paper_id': str(row['paper_id']),
                'bibcode': row['bibcode'] or '',
            })

        # Group call-type rows into per-config stage breakdowns
        config_data = {}
        for row in config_ct_qs:
            config = row['configuration'] or 'legacy'
            ct = row['call_type']
            stage = ct_to_stage.get(ct, 'Other')
            cost_val = float(row['cost'] or 0)

            if config not in config_data:
                config_data[config] = {'cost_usd': 0, 'calls': 0, 'tokens': 0, 'stages': {}}
            config_data[config]['cost_usd'] += cost_val
            config_data[config]['calls'] += row['calls']
            config_data[config]['tokens'] += row['tokens'] or 0

            if stage not in config_data[config]['stages']:
                config_data[config]['stages'][stage] = {'stage': stage, 'cost_usd': 0, 'calls': 0, 'breakdown': []}
            config_data[config]['stages'][stage]['cost_usd'] += cost_val
            config_data[config]['stages'][stage]['calls'] += row['calls']
            config_data[config]['stages'][stage]['breakdown'].append({
                'call_type': ct,
                'cost_usd': round(cost_val, 6),
                'calls': row['calls'],
            })

        # Per-paper costs per call_type (for stage/call_type histogram filtering)
        paper_cost_by_ct_qs = (
            through_model.objects
            .filter(llmcall_id__in=qs)
            .values(
                configuration=F('paperanalysis__configuration_name'),
                call_type=F('llmcall__call_type'),
                paper_id=F('paperanalysis__paper_id'),
                bibcode=F('paperanalysis__paper__bibcode'),
            )
            .annotate(cost=Sum('llmcall__estimated_cost_usd'))
            .order_by('configuration', 'call_type', 'cost')
        )
        config_ct_paper_costs = {}
        for row in paper_cost_by_ct_qs:
            config = row['configuration'] or 'legacy'
            ct = row['call_type']
            if config not in config_ct_paper_costs:
                config_ct_paper_costs[config] = {}
            if ct not in config_ct_paper_costs[config]:
                config_ct_paper_costs[config][ct] = []
            config_ct_paper_costs[config][ct].append({
                'cost': round(float(row['cost'] or 0), 4),
                'paper_id': str(row['paper_id']),
                'bibcode': row['bibcode'] or '',
            })

        by_configuration = []
        for config, cd in sorted(config_data.items(), key=lambda x: x[1]['cost_usd'], reverse=True):
            papers = config_paper_counts.get(config, 0)
            config_cost = cd['cost_usd']
            stages_list = sorted(cd['stages'].values(), key=lambda s: s['cost_usd'], reverse=True)
            for s in stages_list:
                s['cost_usd'] = round(s['cost_usd'], 6)
                s['pct'] = round(s['cost_usd'] / config_cost * 100, 1) if config_cost > 0 else 0
                s['breakdown'].sort(key=lambda b: b['cost_usd'], reverse=True)
                # Inject per-paper costs into each call_type
                for ct_item in s['breakdown']:
                    ct_item['paper_costs'] = config_ct_paper_costs.get(config, {}).get(ct_item['call_type'], [])
                # Aggregate per-paper stage costs from call_type costs
                stage_paper_map = {}
                for ct_item in s['breakdown']:
                    for pc in ct_item['paper_costs']:
                        pid = pc['paper_id']
                        if pid not in stage_paper_map:
                            stage_paper_map[pid] = {'cost': 0.0, 'paper_id': pid, 'bibcode': pc['bibcode']}
                        stage_paper_map[pid]['cost'] += pc['cost']
                s['paper_costs'] = [
                    {'cost': round(v['cost'], 4), 'paper_id': v['paper_id'], 'bibcode': v['bibcode']}
                    for v in stage_paper_map.values()
                ]

            by_configuration.append({
                'configuration': config,
                'display_name': self.CONFIG_DISPLAY_NAMES.get(config, config),
                'cost_usd': round(config_cost, 6),
                'calls': cd['calls'],
                'tokens': cd['tokens'],
                'papers': papers,
                'avg_cost_per_paper': round(config_cost / papers, 6) if papers > 0 else 0,
                'pct': round(config_cost / total_cost * 100, 1) if total_cost > 0 else 0,
                'by_stage': stages_list,
                'paper_costs': config_paper_costs.get(config, []),
            })

        response_data = {
            'date_range': {
                'start': range_start,
                'end': range_end,
                'is_default': is_default,
            },
            'totals': {
                'total_cost_usd': round(total_cost, 6),
                'total_calls': total_calls,
                'total_tokens': total_tokens,
                'distinct_papers': distinct_papers,
                'avg_cost_per_paper': round(avg_cost_per_paper, 6),
            },
            'by_mode': {
                'batch': {
                    'cost_usd': round(float(batch_agg['cost'] or 0), 6),
                    'calls': batch_agg['calls'] or 0,
                    'tokens': batch_agg['tokens'] or 0,
                },
                'realtime': {
                    'cost_usd': round(float(realtime_agg['cost'] or 0), 6),
                    'calls': realtime_agg['calls'] or 0,
                    'tokens': realtime_agg['tokens'] or 0,
                },
            },
            'by_stage': by_stage,
            'by_model': by_model,
            'by_configuration': by_configuration,
            'by_day': by_day,
        }

        cache.set(cache_key, response_data, 300)
        return Response(response_data)


class PipelineTreeView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, analysisId):
        pa = PaperAnalysis.objects.filter(id=analysisId).first()
        if pa is None:
            return Response({'detail': 'Not found.'}, status=404)
        roots = (
            pa.pipeline_nodes
            .filter(parent=None)
            .prefetch_related('llm_calls', 'children', 'dataset_usages', 'dataset_usages__instrument', 'dataset_usages__instrument__observatory')
            .order_by('started_at')
        )
        return Response({
            'pipeline_completed_at': pa.pipeline_completed_at,
            'nodes': PipelineNodeSerializer(roots, many=True).data,
        })


class BatchJobListView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        status_filter = request.query_params.get('status')  # 'in_progress' or 'completed'
        page = max(1, int(request.query_params.get('page', 1)))
        page_size = min(50, int(request.query_params.get('page_size', 25)))

        qs = BatchJob.objects.order_by('-created_at')

        if status_filter == 'in_progress':
            qs = qs.exclude(status__in=['completed', 'failed', 'cancelled'])
        elif status_filter == 'completed':
            qs = qs.filter(status__in=['completed', 'failed', 'cancelled'])

        total = qs.count()
        start = (page - 1) * page_size
        jobs = qs[start:start + page_size]

        return Response({
            'count': total,
            'page': page,
            'page_size': page_size,
            'num_pages': max(1, (total + page_size - 1) // page_size),
            'results': BatchJobSerializer(jobs, many=True).data,
        })


class BatchJobPapersView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, batch_id):
        from django.shortcuts import get_object_or_404
        batch = get_object_or_404(BatchJob, id=batch_id)

        page = max(1, int(request.query_params.get('page', 1)))
        page_size = min(200, int(request.query_params.get('page_size', 50)))

        all_paper_ids = list(batch.paper_mapping.keys())
        total = len(all_paper_ids)
        start = (page - 1) * page_size
        paper_ids = all_paper_ids[start:start + page_size]

        analyses = {
            str(pa.paper_id): pa
            for pa in PaperAnalysis.objects.filter(paper_id__in=paper_ids)
                                           .select_related('paper')
        }

        # Build per-paper "deepest stage" — last iteration wins = latest stage
        latest_nodes = {}
        for pn in PipelineNode.objects.filter(
            analysis__paper_id__in=paper_ids
        ).values('analysis__paper_id', 'stage', 'status').order_by('started_at'):
            latest_nodes[str(pn['analysis__paper_id'])] = pn

        has_running = set(
            str(pid) for pid in PipelineNode.objects.filter(
                analysis__paper_id__in=paper_ids, status='running'
            ).values_list('analysis__paper_id', flat=True)
        )

        has_failed = set(
            str(pid) for pid in PipelineNode.objects.filter(
                analysis__paper_id__in=paper_ids, status='failed'
            ).values_list('analysis__paper_id', flat=True)
        )

        papers = []
        for paper_id in paper_ids:
            pa = analyses.get(paper_id)
            node = latest_nodes.get(paper_id)
            papers.append({
                'paper_id': paper_id,
                'bibcode': pa.paper.bibcode if pa else '—',
                'analysis_id': pa.id if pa else None,
                'pipeline_completed_at': pa.pipeline_completed_at if pa else None,
                'current_stage': node['stage'] if node else None,
                'has_running_nodes': paper_id in has_running,
                'has_failed_nodes': paper_id in has_failed,
            })

        return Response({
            'id': batch.id,
            'batch_id': batch.batch_id,
            'configuration_name': batch.configuration_name,
            'provider': batch.provider,
            'created_at': batch.created_at,
            'total_requests': batch.total_requests,
            'papers_pipeline_done': PaperAnalysis.objects.filter(
                paper_id__in=all_paper_ids,
                pipeline_completed_at__isnull=False,
            ).count(),
            'count': total,
            'page': page,
            'page_size': page_size,
            'num_pages': max(1, (total + page_size - 1) // page_size),
            'papers': BatchPaperStatusSerializer(papers, many=True).data,
        })


class PublicPaperInstrumentMentionsView(APIView):
    """
    Public, read-only list of InstrumentMentions for a paper, ordered by match_level.

    Query params:
      ?match_level=mission_only,instrument_no_time,partial,full,unmatched
          Comma-separated filter on match_level. Defaults to all levels.

    Returns every instrument grounding attempt for the paper, including partial
    matches where a full DatasetUsage could not be created.
    """
    permission_classes = [AllowAny]

    _LEVEL_ORDER = {
        InstrumentMention.MATCH_LEVEL_MISSION_ONLY: 0,
        InstrumentMention.MATCH_LEVEL_INSTRUMENT_NO_TIME: 1,
        InstrumentMention.MATCH_LEVEL_PARTIAL: 2,
        InstrumentMention.MATCH_LEVEL_UNMATCHED: 3,
        InstrumentMention.MATCH_LEVEL_FULL: 4,
    }

    def get(self, request, bibcode: str):
        try:
            paper = Paper.objects.get(bibcode=bibcode)
        except Paper.DoesNotExist:
            raise Http404("Paper not found")

        qs = (
            InstrumentMention.objects
            .filter(paper_analysis__paper=paper)
            .select_related(
                'matched_observatory',
                'matched_instrument',
                'matched_instrument__observatory',
            )
        )

        # Optional match_level filter
        raw_levels = request.query_params.get('match_level', '')
        if raw_levels:
            levels = [lvl.strip() for lvl in raw_levels.split(',') if lvl.strip()]
            valid_levels = {choice[0] for choice in InstrumentMention.MATCH_LEVEL_CHOICES}
            levels = [lvl for lvl in levels if lvl in valid_levels]
            if levels:
                qs = qs.filter(match_level__in=levels)

        mentions = sorted(qs, key=lambda m: self._LEVEL_ORDER.get(m.match_level, 99))
        serializer = PublicInstrumentMentionSerializer(mentions, many=True)
        return Response({'mentions': serializer.data})


# ---------------------------------------------------------------------------
# Phenomenon validation views
# ---------------------------------------------------------------------------

def annotate_my_phenomenon_validation(queryset, user):
    """Annotate a PhenomenonMention queryset with the requesting user's vote."""
    if user and user.is_authenticated:
        return queryset.annotate(
            _my_validation_status=Subquery(
                PhenomenonMentionValidation.objects.filter(
                    phenomenon_mention=OuterRef('pk'),
                    user=user,
                ).values('validation_status')[:1]
            )
        )
    return queryset


class PhenomenonMentionValidationView(APIView):
    """
    POST /builder/phenomenon-mentions/<uuid>/validate/

    Submit a validation judgment for a PhenomenonMention (authenticated or anonymous).
    Recomputes consensus after each submission.
    """
    authentication_classes = [JWTAuthentication]
    permission_classes = []

    def post(self, request, mention_id):
        try:
            mention = PhenomenonMention.objects.get(id=mention_id)
        except PhenomenonMention.DoesNotExist:
            return Response(
                {"error": "Phenomenon mention not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        validation_status_value = request.data.get('validation_status')
        validation_notes = request.data.get('validation_notes', '') or ''

        valid_statuses = ['accepted', 'rejected', 'needs_review']
        if validation_status_value not in valid_statuses:
            return Response(
                {"error": f"Invalid status. Must be one of: {valid_statuses}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        is_authenticated = bool(request.user and request.user.is_authenticated)

        if is_authenticated:
            validation_obj, created = PhenomenonMentionValidation.objects.update_or_create(
                phenomenon_mention=mention,
                user=request.user,
                defaults={
                    'validation_status': validation_status_value,
                    'validation_notes': validation_notes,
                },
            )
            rater_label = request.user.username
        else:
            anon_id_str = request.headers.get('X-Anonymous-ID')
            if not anon_id_str:
                return Response(
                    {"error": "X-Anonymous-ID header is required for unauthenticated validation"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            import uuid as uuid_mod
            try:
                anon_uuid = uuid_mod.UUID(anon_id_str)
            except ValueError:
                return Response(
                    {"error": "X-Anonymous-ID must be a valid UUID"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            try:
                validation_obj = PhenomenonMentionValidation.objects.get(
                    phenomenon_mention=mention,
                    user__isnull=True,
                    anonymous_id=anon_uuid,
                )
                validation_obj.validation_status = validation_status_value
                validation_obj.validation_notes = validation_notes
                validation_obj.save(update_fields=['validation_status', 'validation_notes'])
                created = False
            except PhenomenonMentionValidation.DoesNotExist:
                validation_obj = PhenomenonMentionValidation.objects.create(
                    phenomenon_mention=mention,
                    user=None,
                    anonymous_id=anon_uuid,
                    validation_status=validation_status_value,
                    validation_notes=validation_notes,
                )
                created = True
            rater_label = f'anonymous:{anon_uuid}'

        if is_authenticated:
            from django.utils import timezone
            mention.validated_by = request.user
            mention.save(update_fields=['validated_by'])

        recompute_phenomenon_consensus(mention)
        mention.refresh_from_db(fields=['validation_status', 'validated_at'])

        return Response({
            "message": "Validation submitted successfully",
            "mention_id": str(mention.id),
            "validation_id": str(validation_obj.id),
            "created": created,
            "validation_status": validation_status_value,
            "consensus_status": mention.validation_status,
            "rater": rater_label,
        }, status=status.HTTP_200_OK)


class PhenomenonValidationQueueView(ListAPIView):
    """
    GET /builder/phenomenon-mentions/validation-queue/

    Returns pending PhenomenonMention records with paper/instrument context,
    ready for human validation.
    """
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]
    serializer_class = PhenomenonMentionSerializer
    pagination_class = PublicPapersPagination

    def get_queryset(self):
        qs = PhenomenonMention.objects.select_related(
            'phenomenon',
            'paper_analysis__paper',
        )

        validation_status_param = self.request.query_params.get('validation_status', 'pending')
        if validation_status_param != 'all':
            qs = qs.filter(validation_status=validation_status_param)

        bibcode = self.request.query_params.get('bibcode')
        if bibcode:
            qs = qs.filter(paper_analysis__paper__bibcode__icontains=bibcode)

        instrument = self.request.query_params.get('instrument')
        if instrument:
            qs = qs.filter(instrument_name__icontains=instrument)

        phenomenon = self.request.query_params.get('phenomenon')
        if phenomenon:
            qs = qs.filter(phenomenon__name__icontains=phenomenon)

        qs = annotate_my_phenomenon_validation(qs, self.request.user)
        return qs.order_by('paper_analysis__paper__bibcode', 'instrument_name', 'created_at')


class PaperPhenomenaView(APIView):
    """
    GET /builder/papers/<uuid:paper_id>/phenomena/

    Returns all PhenomenonMention records for a given paper (across all analyses).
    """
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, paper_id):
        try:
            paper = Paper.objects.get(id=paper_id)
        except Paper.DoesNotExist:
            return Response({"error": "Paper not found"}, status=status.HTTP_404_NOT_FOUND)

        qs = PhenomenonMention.objects.filter(
            paper_analysis__paper=paper,
        ).select_related(
            'phenomenon',
            'paper_analysis__paper',
            'supporting_quote',
        ).prefetch_related('supporting_quotes')

        configuration_name = request.query_params.get('configuration_name')
        if configuration_name:
            qs = qs.filter(paper_analysis__configuration_name=configuration_name)

        qs = annotate_my_phenomenon_validation(qs, request.user)
        qs = qs.order_by('instrument_name', 'phenomenon__name')

        serializer = PhenomenonMentionSerializer(qs, many=True)
        return Response({'mentions': serializer.data, 'paper': {'id': str(paper.id), 'bibcode': paper.bibcode}})


class PhenomenaQueuePapersView(ListAPIView):
    """
    GET /builder/phenomenon-mentions/papers-queue/

    Returns papers that have PhenomenonMention records, annotated with
    pending/total mention counts. Mirrors PaperValidationQueueView for instruments.
    """
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]
    pagination_class = PublicPapersPagination

    def get_queryset(self):
        qs = Paper.objects.annotate(
            total_mentions=Count(
                'paperanalysis__phenomenon_mentions',
                distinct=True,
            ),
            pending_mentions=Count(
                'paperanalysis__phenomenon_mentions',
                filter=Q(paperanalysis__phenomenon_mentions__validation_status='pending'),
                distinct=True,
            ),
            accepted_mentions=Count(
                'paperanalysis__phenomenon_mentions',
                filter=Q(paperanalysis__phenomenon_mentions__validation_status='accepted'),
                distinct=True,
            ),
        ).filter(total_mentions__gt=0)

        validation_status = self.request.query_params.get('validation_status', 'pending')
        if validation_status == 'pending':
            qs = qs.filter(pending_mentions__gt=0)
        elif validation_status == 'complete':
            qs = qs.filter(pending_mentions=0)

        search = self.request.query_params.get('search', '').strip()
        if search:
            qs = qs.filter(bibcode__icontains=search)

        return qs.order_by('-pending_mentions', 'bibcode')

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        items = page if page is not None else queryset

        data = []
        for paper in items:
            data.append({
                'id': str(paper.id),
                'bibcode': paper.bibcode,
                'title': paper.title,
                'authors': paper.authors,
                'year': paper.year,
                'total_mentions': paper.total_mentions,
                'pending_mentions': paper.pending_mentions,
                'accepted_mentions': paper.accepted_mentions,
            })

        if page is not None:
            return self.get_paginated_response(data)
        return Response(data)
