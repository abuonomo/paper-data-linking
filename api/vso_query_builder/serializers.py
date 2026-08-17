from rest_framework import serializers

from .models import SupportQuote, PaperAnalysis, LLMCall, PipelineNode
from .models import DatasetUsage, DatasetUsageValidation, BatchJob
from .models import Paper, InstrumentMention
from .models import Phenomenon, PhenomenonMention, PhenomenonMentionValidation


class DatasetUsageValidationSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source='user.username', read_only=True, default=None)

    class Meta:
        model = DatasetUsageValidation
        fields = [
            'id', 'dataset_usage', 'user', 'username', 'anonymous_id',
            'validation_status', 'validation_notes',
            'mission_correct', 'instrument_correct', 'window_correct',
            'created_at',
        ]
        read_only_fields = ['id', 'created_at', 'user', 'username']


class PaperSerializer(serializers.ModelSerializer):
    user_name = serializers.CharField(source='user.username', read_only=True)

    class Meta:
        model = Paper
        fields = ['id', 'bibcode', 'full_text', 'pdf', 'created_at', 'user', 'user_name', 'tags',
                  'title', 'authors', 'year', 'journal', 'journal_abbrev', 'abstract']
        read_only_fields = ('id', 'created_at', 'user')


class MinimalPaperSerializer(serializers.ModelSerializer):
    """
    A serializer for Paper that only includes essential identifying information.
    """

    class Meta:
        model = Paper
        # Only include fields needed for listing/identifying the paper
        fields = ['id', 'bibcode']
        read_only_fields = ('id', 'bibcode')


class PaperQueueSerializer(serializers.ModelSerializer):
    """
    Lightweight serializer for the paper validation queue.
    Avoids expensive relation-based counts to keep the endpoint fast.
    """
    class Meta:
        model = Paper
        fields = ['id', 'bibcode', 'title', 'created_at', 'tags']
        read_only_fields = ('id', 'created_at')



class DatasetUsageThinSerializer(serializers.ModelSerializer):
    paper_id    = serializers.UUIDField(source="paper.id")
    instrument  = serializers.CharField(source="instrument.short_name")
    observatory = serializers.SerializerMethodField()
    start_time  = serializers.SerializerMethodField()
    end_time    = serializers.SerializerMethodField()

    class Meta:
        model  = DatasetUsage          # or CanonicalDatasetUsage
        fields = ["id", "paper_id", "instrument",
                  "observatory", "start_time", "end_time", "extra_params"]

    def get_observatory(self, obj):
        return obj.instrument.observatory.short_name if obj.instrument.observatory else None

    def get_start_time(self, obj):
        return obj.observation_window.lower.isoformat()

    def get_end_time(self, obj):
        return obj.observation_window.upper.isoformat()


class DatasetUsageListSerializer(serializers.ModelSerializer):
    """
    Serializer for dataset usage list view with essential fields
    """
    paper_bibcode = serializers.CharField(source="paper.bibcode", read_only=True)
    instrument_name = serializers.SerializerMethodField()
    observatory_name = serializers.CharField(source="instrument.observatory.display_name", read_only=True)
    observatory_short_name = serializers.CharField(source="instrument.observatory.short_name", read_only=True)
    start_time = serializers.SerializerMethodField()
    end_time = serializers.SerializerMethodField()
    supporting_quotes_count = serializers.SerializerMethodField()
    has_analysis = serializers.SerializerMethodField()
    physical_observable = serializers.SerializerMethodField()
    wavelengths = serializers.SerializerMethodField()

    class Meta:
        model = DatasetUsage
        fields = [
            'id', 'paper_bibcode', 'instrument_name', 'observatory_name',
            'observatory_short_name', 'start_time', 'end_time',
            'supporting_quotes_count', 'has_analysis', 'physical_observable',
            'wavelengths', 'extra_params'
        ]

    def get_instrument_name(self, obj):
        if obj.instrument is None:
            return None
        return obj.instrument.display_name or obj.instrument.short_name

    def get_start_time(self, obj):
        return obj.observation_window.lower.isoformat() if obj.observation_window and obj.observation_window.lower else None

    def get_end_time(self, obj):
        return obj.observation_window.upper.isoformat() if obj.observation_window and obj.observation_window.upper else None

    def get_supporting_quotes_count(self, obj):
        return obj.supporting_quotes.count()

    def get_has_analysis(self, obj):
        return hasattr(obj, 'analysis')

    def get_physical_observable(self, obj):
        # Handle nested normalized structure
        physobs_data = obj.extra_params.get('physical_observable', {}) if obj.extra_params else {}
        return physobs_data.get('physical_observable') if isinstance(physobs_data, dict) else None

    def get_wavelengths(self, obj):
        # Handle nested normalized structure with new range-based schema
        wavelength_data = obj.extra_params.get('wavelengths', {}) if obj.extra_params else {}
        if not isinstance(wavelength_data, dict):
            return None
        # Return the ranges list directly (new schema format)
        return wavelength_data.get('ranges', [])


class SupportQuoteDetailSerializer(serializers.ModelSerializer):
    """
    Detailed serializer for support quotes
    """
    class Meta:
        model = SupportQuote
        fields = [
            'id', 'quote', 'instrument', 'parameter', 'page_number',
            'x_coord_start', 'x_coord_end', 'y_coord_start', 'y_coord_end',
            'coordinate_regions'
        ]


class PaperDatasetUsageListSerializer(serializers.ModelSerializer):
    """
    A lightweight serializer for listing DatasetUsage instances for the
    paper-centric validation queue. Only includes fields needed for the list view,
    making it much faster and more efficient than the detail serializer.
    """
    # Get nested data directly using the 'source' argument.
    # This is very fast when paired with `select_related` in the view.
    instrument_name = serializers.SerializerMethodField()
    instrument_full_name = serializers.CharField(source='instrument.full_name', read_only=True)
    observatory_short_name = serializers.CharField(source='instrument.observatory.short_name', read_only=True)
    observatory_name = serializers.CharField(source='instrument.observatory.display_name', read_only=True)

    # Compute values from the observation_window range field
    start_time = serializers.SerializerMethodField()
    end_time = serializers.SerializerMethodField()
    my_validation_status = serializers.SerializerMethodField()

    class Meta:
        model = DatasetUsage
        fields = [
            'id',
            'instrument_name',
            'instrument_full_name',
            'observatory_short_name',
            'observatory_name',
            'start_time',
            'end_time',
            'validation_status',
            'my_validation_status',
        ]
        read_only_fields = fields

    def get_my_validation_status(self, obj):
        if hasattr(obj, '_my_validation_status'):
            return obj._my_validation_status
        return None

    def get_instrument_name(self, obj):
        if obj.instrument is None:
            return None
        return obj.instrument.display_name or obj.instrument.short_name

    def get_start_time(self, obj):
        """Safely gets the start time from the observation window."""
        if obj.observation_window and obj.observation_window.lower:
            return obj.observation_window.lower.isoformat()
        return None

    def get_end_time(self, obj):
        """Safely gets the end time from the observation window."""
        if obj.observation_window and obj.observation_window.upper:
            return obj.observation_window.upper.isoformat()
        return None


class DatasetUsageDetailSerializer(serializers.ModelSerializer):
    """
    Detailed serializer for individual dataset usage with all related data
    """
    paper = serializers.SerializerMethodField()
    instrument = serializers.SerializerMethodField()
    observatory = serializers.SerializerMethodField()
    start_time = serializers.SerializerMethodField()
    end_time = serializers.SerializerMethodField()
    supporting_quotes = SupportQuoteDetailSerializer(many=True, read_only=True)
    categorized_quotes = serializers.SerializerMethodField()
    analysis = serializers.SerializerMethodField()
    duration_hours = serializers.SerializerMethodField()
    validated_by_username = serializers.CharField(source='validated_by.username', read_only=True)
    my_validation_status = serializers.SerializerMethodField()

    class Meta:
        model = DatasetUsage
        fields = [
            'id', 'paper', 'instrument', 'observatory', 'start_time', 'end_time',
            'duration_hours', 'extra_params', 'supporting_quotes',
            'categorized_quotes', 'analysis', 'validation_status',
            'validated_by_username', 'validated_at', 'validation_notes',
            'my_validation_status',
        ]

    def get_my_validation_status(self, obj):
        """Return the current user's validation status for this usage, or null."""
        # Prefer the annotation set by the queryset (efficient, single query)
        if hasattr(obj, '_my_validation_status'):
            return obj._my_validation_status
        return None

    def get_paper(self, obj):
        return {
            'id': obj.paper.id,
            'bibcode': obj.paper.bibcode,
            'pdf_url': obj.paper.pdf.url if obj.paper.pdf else None
        }

    def get_instrument(self, obj):
        if obj.instrument:
            return {
                'id': obj.instrument.id,
                'short_name': obj.instrument.short_name,
                'full_name': obj.instrument.full_name,
                'display_name': obj.instrument.display_name or obj.instrument.short_name,
                'data_source': {
                    'name': obj.instrument.observatory.datasource.name
                } if obj.instrument.observatory and obj.instrument.observatory.datasource else None
            }
        return None

    def get_observatory(self, obj):
        obs = obj.instrument.observatory if obj.instrument else None
        if not obs:
            return None
        return {
            'short_name': obs.short_name,
            'name': obs.name,
            'display_name': obs.display_name or obs.short_name,
        }
    
    def get_start_time(self, obj):
        return obj.observation_window.lower.isoformat() if obj.observation_window and obj.observation_window.lower else None
    
    def get_end_time(self, obj):
        return obj.observation_window.upper.isoformat() if obj.observation_window and obj.observation_window.upper else None
    
    def get_duration_hours(self, obj):
        if obj.observation_window and obj.observation_window.lower and obj.observation_window.upper:
            delta = obj.observation_window.upper - obj.observation_window.lower
            return round(delta.total_seconds() / 3600, 2)
        return None
    
    def get_analysis(self, obj):
        if hasattr(obj, 'analysis'):
            return {
                'id': obj.analysis.id,
                'is_valid_syntax': obj.analysis.is_valid_syntax,
                'execution_successful': obj.analysis.execution_successful,
                'total_results_found': obj.analysis.total_results_found,
                'python_snippet': obj.analysis.python_snippet
            }
        return None
    
    def get_categorized_quotes(self, obj):
        """Return quotes with their categories for simpler display."""
        from .models import QuoteUsageLink
        
        # Get all categorized quote links for this dataset usage
        quote_links = QuoteUsageLink.objects.filter(dataset_usage=obj).select_related('quote')
        
        # Create a simple list of quotes with their categories
        categorized_quotes = []
        for link in quote_links:
            quote_data = SupportQuoteDetailSerializer(link.quote).data
            quote_data['category'] = link.support_category
            categorized_quotes.append(quote_data)
        
        return categorized_quotes
    

class PublicDatasetUsageSerializer(serializers.Serializer):
    """Minimal, public-facing shape for dataset usages (validated or all)."""
    id = serializers.UUIDField()
    instrument = serializers.SerializerMethodField()
    observatory = serializers.SerializerMethodField()
    datasource = serializers.SerializerMethodField()
    start_time = serializers.SerializerMethodField()
    end_time = serializers.SerializerMethodField()
    duration_hours = serializers.SerializerMethodField()
    validation_status = serializers.CharField()
    validated_by_username = serializers.SerializerMethodField()
    validated_at = serializers.SerializerMethodField()
    validation_notes = serializers.CharField(allow_null=True, allow_blank=True, required=False)
    python_snippet = serializers.SerializerMethodField()
    script_analysis = serializers.SerializerMethodField()
    supporting_quotes = serializers.SerializerMethodField()

    def get_instrument(self, obj):
        inst = obj.instrument
        if not inst:
            return None
        return {
            'short_name': inst.short_name,
            'display_name': inst.display_name or inst.full_name or inst.short_name,
            'full_name': inst.full_name,
        }

    def get_observatory(self, obj):
        obs = obj.instrument.observatory if obj.instrument else None
        if not obs:
            return None
        return {
            'short_name': obs.short_name,
            'display_name': obs.display_name or obs.name or obs.short_name,
            'name': obs.name,
        }

    def get_datasource(self, obj):
        obs = obj.instrument.observatory if obj.instrument else None
        if not obs or not obs.datasource:
            return None
        return {
            'slug': obs.datasource.slug,
            'name': obs.datasource.name,
        }

    def get_start_time(self, obj):
        return obj.observation_window.lower.isoformat() if obj.observation_window and obj.observation_window.lower else None

    def get_end_time(self, obj):
        return obj.observation_window.upper.isoformat() if obj.observation_window and obj.observation_window.upper else None

    def get_duration_hours(self, obj):
        if obj.observation_window and obj.observation_window.lower and obj.observation_window.upper:
            delta = obj.observation_window.upper - obj.observation_window.lower
            return round(delta.total_seconds() / 3600, 2)
        return None
    
    def get_python_snippet(self, obj):
        """Get the generated Python script for this dataset usage."""
        try:
            analysis = obj.analysis
            return analysis.python_snippet if analysis else None
        except:
            return None

    def get_validated_by_username(self, obj):
        try:
            return obj.validated_by.username if obj.validated_by else None
        except:
            return None

    def get_validated_at(self, obj):
        try:
            return obj.validated_at.isoformat() if obj.validated_at else None
        except:
            return None
    
    def get_script_analysis(self, obj):
        """Get script validation results."""
        try:
            analysis = obj.analysis
            if not analysis:
                return None
            return {
                'is_valid_syntax': analysis.is_valid_syntax,
                'execution_successful': analysis.execution_successful,
                'syntax_error': analysis.syntax_error or None,
                'execution_error': analysis.execution_error or None,
                'total_results_found': analysis.total_results_found
            }
        except:
            return None
    
    def get_supporting_quotes(self, obj):
        """Get supporting quotes from the paper that validate this usage."""
        try:
            quotes = []
            for quote_link in obj.quote_links.select_related('quote'):
                quote = quote_link.quote
                quotes.append({
                    'id': quote.id,
                    'quote': quote.quote,
                    'page_number': quote.page_number,
                    'instrument': quote.instrument,
                    'parameter': quote.parameter,
                    'support_category': quote_link.support_category,
                    'x_coord_start': quote.x_coord_start,
                    'x_coord_end': quote.x_coord_end,
                    'y_coord_start': quote.y_coord_start,
                    'y_coord_end': quote.y_coord_end,
                    'coordinate_regions': quote.coordinate_regions or [],
                })
            return quotes
        except:
            return []


class PublicInstrumentMentionSerializer(serializers.ModelSerializer):
    """Public-facing serializer for InstrumentMention records."""
    observatory = serializers.SerializerMethodField()
    instrument = serializers.SerializerMethodField()

    class Meta:
        model = InstrumentMention
        fields = [
            'id', 'match_level',
            'observatory', 'instrument', 'created_at',
        ]

    def get_observatory(self, obj):
        # For instrument-resolved mentions, derive observatory from the instrument
        if obj.matched_instrument and obj.matched_instrument.observatory:
            obs = obj.matched_instrument.observatory
        else:
            obs = obj.matched_observatory
        if not obs:
            return None
        return {
            'short_name': obs.short_name,
            'display_name': obs.display_name or obs.name or obs.short_name,
            'name': obs.name,
            'datasource': {
                'slug': obs.datasource.slug,
                'name': obs.datasource.name,
            } if obs.datasource else None,
        }

    def get_instrument(self, obj):
        inst = obj.matched_instrument
        if not inst:
            return None
        return {
            'short_name': inst.short_name,
            'display_name': inst.display_name or inst.full_name or inst.short_name,
            'full_name': inst.full_name,
        }


class PublicValidatedPaperSerializer(serializers.Serializer):
    """Minimal public listing row for papers with dataset usages."""
    id = serializers.UUIDField()
    bibcode = serializers.CharField()
    validated_count = serializers.IntegerField()
    total_count = serializers.IntegerField(required=False)
    mission_only_match_count = serializers.IntegerField(required=False)
    has_matching_dataset_usage = serializers.BooleanField(required=False)
    latest_end = serializers.DateTimeField(allow_null=True)
    title = serializers.CharField(required=False, allow_blank=True)
    authors = serializers.ListField(child=serializers.CharField(), required=False)
    year = serializers.CharField(required=False, allow_blank=True)
    journal = serializers.CharField(required=False, allow_blank=True)


class SupportQuoteSearchSerializer(serializers.ModelSerializer):
    paper_analysis = serializers.SerializerMethodField()
    distance = serializers.FloatField()

    class Meta:
        model = SupportQuote
        fields = [
            'quote', 'instrument', 'parameter', 'page_number',
            'y_coord', 'x_coord_start', 'x_coord_end',
            'y_coord_start', 'y_coord_end', 'paper_analysis',
            'distance'
        ]

    def get_paper_analysis(self, obj):
        request = self.context.get('request')
        annotated_pdf_url = obj.paper_analysis.annotated_pdf.url

        # Build absolute URI if request is available
        if request:
            annotated_pdf_url = request.build_absolute_uri(annotated_pdf_url)

        return {
            'annotated_pdf': annotated_pdf_url,
            'paper_bibcode': obj.paper_analysis.paper.bibcode
        }


class LLMCallSerializer(serializers.ModelSerializer):
    """
    Serializer for LLMCall to expose LLM call details.
    """
    class Meta:
        model = LLMCall
        fields = [
            'id',
            'call_type',
            'model_name',
            'provider',
            'prompt_tokens',
            'completion_tokens',
            'total_tokens',
            'estimated_cost_usd',
            'input_messages',
            'output_content',
            'duration_ms',
            'metadata',
            'created_at',
        ]

class PaperAnalysisSerializer(serializers.ModelSerializer):
    paper_id = serializers.UUIDField(source='paper.id', read_only=True)
    paper_bibcode = serializers.CharField(source='paper.bibcode')
    is_wind_paper = serializers.BooleanField()
    tags = serializers.ListField(source='paper.tags')

    llm_calls = LLMCallSerializer(many=True, read_only=True)

    class Meta:
        model = PaperAnalysis
        fields = [
            'id',
            'paper_id',
            'paper_bibcode',
            'configuration_name',
            'context',
            'instruments_details',
            'annotated_pdf',
            'created_at',
            'is_wind_paper',
            'tags',
            'llm_calls',
        ]


class PaperAnalysisPhenomenaSerializer(serializers.ModelSerializer):
    """Analysis fields used by the phenomena validation detail page."""

    class Meta:
        model = PaperAnalysis
        fields = ['id', 'configuration_name', 'instruments_details']



class PDFAnnotationsSerializer(serializers.Serializer):
    """
    Serializer that converts PaperAnalysis and related SupportQuotes to the 
    JSON format expected by the PDF viewer frontend.
    """
    
    def to_representation(self, instance):
        """
        Convert PaperAnalysis instance to the PDF annotations format
        """
        # Group support quotes by instrument
        quotes_by_instrument = {}
        for quote in instance.support_quotes.all():
            instrument = quote.instrument or "Unknown"
            if instrument not in quotes_by_instrument:
                quotes_by_instrument[instrument] = []
            
            # Convert coordinates to the expected format
            pdf_location = {
                "page_number": quote.page_number,
                "x0": quote.x_coord_start,
                "y0": quote.y_coord_start,
                "x1": quote.x_coord_end,
                "y1": quote.y_coord_end
            }
            
            quotes_by_instrument[instrument].append({
                "quote": quote.quote,
                "parameter": quote.parameter,
                "pdf_location": pdf_location,
                "quote_id": quote.id
            })
        
        # Build the instrumentation details structure
        instrumentation_details = []
        for instrument, quotes in quotes_by_instrument.items():
            # Group quotes by parameter for this instrument
            quotes_by_parameter = {}
            for quote_data in quotes:
                parameter = quote_data["parameter"] or "general_comments"
                if parameter not in quotes_by_parameter:
                    quotes_by_parameter[parameter] = {
                        "pdf_locations": [],
                        "quotes": []
                    }
                
                quotes_by_parameter[parameter]["pdf_locations"].append(quote_data["pdf_location"])
                quotes_by_parameter[parameter]["quotes"].append({
                    "id": quote_data["quote_id"],
                    "text": quote_data["quote"],
                    "page_number": quote_data["pdf_location"]["page_number"]
                })
            
            # Create the instrument entry
            instrument_entry = {
                "instrument_name": instrument,
                **quotes_by_parameter
            }
            instrumentation_details.append(instrument_entry)
        
        return {
            "instrumentation_details": instrumentation_details,
            "paper_bibcode": instance.paper.bibcode,
            "analysis_id": instance.id,
            "created_at": instance.created_at.isoformat() if instance.created_at else None
        }


class PipelineNodeDatasetUsageSerializer(serializers.ModelSerializer):
    paper_id = serializers.UUIDField(source='paper.id', read_only=True)
    instrument_label = serializers.SerializerMethodField()
    observatory_label = serializers.SerializerMethodField()
    start_time = serializers.SerializerMethodField()
    end_time = serializers.SerializerMethodField()

    class Meta:
        model = DatasetUsage
        fields = ['id', 'paper_id', 'instrument_label', 'observatory_label', 'start_time', 'end_time', 'validation_status']

    def get_instrument_label(self, obj):
        i = obj.instrument
        return i.display_name or i.short_name or ''

    def get_observatory_label(self, obj):
        o = obj.instrument.observatory
        return o.display_name or o.name or o.short_name or ''

    def get_start_time(self, obj):
        return obj.observation_window.lower.isoformat() if obj.observation_window and obj.observation_window.lower else None

    def get_end_time(self, obj):
        return obj.observation_window.upper.isoformat() if obj.observation_window and obj.observation_window.upper else None


class BatchJobSerializer(serializers.ModelSerializer):
    papers_pipeline_done = serializers.SerializerMethodField()

    class Meta:
        model = BatchJob
        fields = [
            'id', 'batch_id', 'status', 'provider', 'configuration_name',
            'total_requests', 'completed_requests', 'failed_requests',
            'papers_pipeline_done',
            'created_at', 'submitted_at', 'completed_at',
        ]

    def get_papers_pipeline_done(self, obj):
        paper_ids = list(obj.paper_mapping.keys())
        if not paper_ids:
            return 0
        return PaperAnalysis.objects.filter(
            paper_id__in=paper_ids,
            pipeline_completed_at__isnull=False,
        ).count()


class BatchPaperStatusSerializer(serializers.Serializer):
    paper_id = serializers.UUIDField()
    bibcode = serializers.CharField()
    analysis_id = serializers.IntegerField(allow_null=True)
    pipeline_completed_at = serializers.DateTimeField(allow_null=True)
    current_stage = serializers.CharField(allow_null=True)
    has_running_nodes = serializers.BooleanField()
    has_failed_nodes = serializers.BooleanField()


class PipelineNodeSerializer(serializers.ModelSerializer):
    llm_calls = LLMCallSerializer(many=True, read_only=True)
    dataset_usages = PipelineNodeDatasetUsageSerializer(many=True, read_only=True)
    children = serializers.SerializerMethodField()

    def get_children(self, obj):
        return PipelineNodeSerializer(
            obj.children.prefetch_related(
                'llm_calls', 'dataset_usages', 'dataset_usages__instrument',
                'dataset_usages__instrument__observatory'
            ).order_by('started_at'),
            many=True,
            context=self.context
        ).data

    class Meta:
        model = PipelineNode
        fields = ['id', 'stage', 'label', 'status', 'started_at', 'completed_at',
                  'metadata', 'llm_calls', 'dataset_usages', 'children']


# ---------------------------------------------------------------------------
# Phenomenon serializers
# ---------------------------------------------------------------------------

class PhenomenonSerializer(serializers.ModelSerializer):
    class Meta:
        model = Phenomenon
        fields = ['id', 'name', 'iri']


class PhenomenonMentionValidationSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source='user.username', read_only=True, default=None)

    class Meta:
        model = PhenomenonMentionValidation
        fields = [
            'id', 'phenomenon_mention', 'user', 'username', 'anonymous_id',
            'validation_status', 'validation_notes', 'created_at',
        ]
        read_only_fields = ['id', 'created_at', 'user', 'username']


class PhenomenonMentionSerializer(serializers.ModelSerializer):
    phenomenon_name = serializers.CharField(source='phenomenon.name', read_only=True)
    phenomenon_iri = serializers.CharField(source='phenomenon.iri', read_only=True)
    bibcode = serializers.CharField(source='paper_analysis.paper.bibcode', read_only=True)
    paper_id = serializers.UUIDField(source='paper_analysis.paper.id', read_only=True)
    paper_analysis_id = serializers.IntegerField(source='paper_analysis.id', read_only=True)
    grounded_instrument_name = serializers.SerializerMethodField()
    grounded_time_range = serializers.SerializerMethodField()
    my_validation_status = serializers.SerializerMethodField()
    supporting_quote = SupportQuoteDetailSerializer(read_only=True)
    supporting_quotes = SupportQuoteDetailSerializer(many=True, read_only=True)

    class Meta:
        model = PhenomenonMention
        fields = [
            'id',
            'paper_id',
            'bibcode',
            'paper_analysis_id',
            'phenomenon_name',
            'phenomenon_iri',
            'instrument_name',
            'grounded_instrument_name',
            'period_name',
            'grounded_time_range',
            'physical_observable',
            'quote',
            'supporting_quote',
            'supporting_quotes',
            'validation_status',
            'validated_at',
            'validation_notes',
            'created_at',
            'my_validation_status',
        ]
        read_only_fields = fields

    def get_grounded_instrument_name(self, obj):
        def _short(iri_or_code):
            if iri_or_code and iri_or_code.startswith('spase://'):
                return iri_or_code.rstrip('/').rsplit('/', 1)[-1]
            return iri_or_code

        code = _short(obj.matched_instrument_code)
        mission = _short(obj.matched_mission_code)
        if code and mission:
            return f"{mission}/{code}"
        return code or mission or None

    def get_grounded_time_range(self, obj):
        normalized = getattr(obj.paper_analysis, 'normalized_instrument_details', None)
        if not normalized:
            return None
        for inst in normalized.get('instruments', []):
            if inst.get('name', {}).get('original') != obj.instrument_name:
                continue
            for period in inst.get('data_collection_periods', []):
                if period.get('period_name') != obj.period_name:
                    continue
                tr = period.get('time_range', {})
                norm = tr.get('normalized', {}) if isinstance(tr, dict) else {}
                start = norm.get('start_datetime')
                end = norm.get('end_datetime')
                if start or end:
                    return {'start': start, 'end': end}
        return None

    def get_my_validation_status(self, obj):
        return getattr(obj, '_my_validation_status', None)
