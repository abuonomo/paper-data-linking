import json
from django import forms
from django.contrib import admin
from django.contrib import messages
from django.db.models import Count
from django.db.models import Q
from django.shortcuts import render
from django.utils.html import format_html
from django.utils.html import mark_safe

from paper_data_linking.processing.text_validation import get_text_stats, TextValidationError
from .models import Paper, PaperAnalysis, \
    SupportQuote, DataSource, Observatory, Instrument, DatasetUsage, \
    DatasetUsageAnalysis, LLMCall, BatchJob, PipelineNode, InstrumentMention, \
    Phenomenon, PhenomenonMention
from .tasks import extract_paper_text_task, run_paper_analyses, \
    batch_analyze_instruments_structure, normalize_structured_instrument_details, \
    insert_datasetusages_only, analyze_dataset_usage, run_dataset_usage_analyses, \
    run_batch_normalized_workflow, update_supporting_quote_locations_batch_task, \
    run_batch_normalized_workflow_via_batch_api, upsert_phenomenon_mentions_task, \
    enrich_quote_coordinates
from celery import chain


class HasStructuredInstrumentsFilter(admin.SimpleListFilter):
    title = 'has structured instruments'
    parameter_name = 'has_structured_instruments'

    def lookups(self, request, model_admin):
        return (
            ('yes', 'Yes'),
            ('no', 'No'),
        )

    def queryset(self, request, queryset):
        if self.value() == 'yes':
            return queryset.exclude(structured_instruments_details__isnull=True)
        if self.value() == 'no':
            return queryset.filter(structured_instruments_details__isnull=True)


class ConfigurationSelectionForm(forms.Form):
    configuration_name = forms.ChoiceField(
        choices=[],  # Will be populated in __init__
        initial='standard',
        help_text="Select LLM configuration for paper analysis"
    )
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Dynamically load all available configurations
        from paper_data_linking.config.settings import list_available_configurations
        
        available_configs = list_available_configurations()
        config_choices = []
        
        for config_name in available_configs:
            # Create display names for each configuration
            if config_name == 'standard':
                display_name = 'Standard (GPT-5) - High quality analysis'
            elif config_name == 'budget':
                display_name = 'Budget (GPT-5-mini) - Cost-effective analysis'
            elif config_name == 'super-budget':
                display_name = 'Super Budget (GPT-5-nano) - Maximum cost savings'
            elif config_name == 'hybrid':
                display_name = 'Hybrid (GPT-5 extraction + nano grounding) - Balanced quality and cost'
            elif config_name == 'bedrock-test':
                display_name = 'Bedrock Test (OpenAI OSS) - AWS Bedrock models'
            else:
                # Fallback for any other configurations
                display_name = f'{config_name.title()} Configuration'

            config_choices.append((config_name, display_name))
        
        self.fields['configuration_name'].choices = config_choices


class HasTextFilter(admin.SimpleListFilter):
    title = 'has text'
    parameter_name = 'has_text'

    def lookups(self, request, model_admin):
        return (
            ('yes', 'Yes'),
            ('no', 'No'),
        )

    def queryset(self, request, queryset):
        if self.value() == 'yes':
            return queryset.exclude(full_text__isnull=True).exclude(full_text='')
        if self.value() == 'no':
            return queryset.filter(Q(full_text__isnull=True) | Q(full_text=''))


class HasPaperAnalysisFilter(admin.SimpleListFilter):
    title = 'has paper analysis'
    parameter_name = 'has_paper_analysis'

    def lookups(self, request, model_admin):
        return (
            ('yes', 'Yes'),
            ('no', 'No'),
        )

    def queryset(self, request, queryset):
        if self.value() == 'yes':
            return queryset.filter(paperanalysis__isnull=False)
        if self.value() == 'no':
            return queryset.filter(paperanalysis__isnull=True)


class PaperTagFilter(admin.SimpleListFilter):
    title = 'tag'
    parameter_name = 'tag'

    def lookups(self, request, model_admin):
        from django.db import connection
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT DISTINCT unnest(tags) FROM vso_query_builder_paper WHERE cardinality(tags) > 0 ORDER BY 1"
            )
            return [(row[0], row[0]) for row in cursor.fetchall()]

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(tags__contains=[self.value()])


@admin.register(Paper)
class PaperAdmin(admin.ModelAdmin):
    list_display = ('bibcode', 'created_at', 'user', 'has_text', 'ocr_status')
    search_fields = ('bibcode', 'user__username')
    list_select_related = ('user',)
    list_filter = ('created_at', 'user', HasTextFilter, HasPaperAnalysisFilter, 'used_ocr', PaperTagFilter)
    actions = ['run_paper_analyses', 'extract_text_from_pdf', 'analyze_paper_dataset_usages', 'run_complete_normalized_workflow', 'run_complete_normalized_workflow_batch_api']

    @admin.display(boolean=True)
    def has_text(self, obj):
        return bool(obj.full_text)
    has_text.short_description = 'Has Text'

    def ocr_status(self, obj):
        if not obj.full_text:
            return '-'
        return 'OCR' if obj.used_ocr else 'Native'
    ocr_status.short_description = 'Text Source'

    # Multi-configuration paper analysis action
    def run_paper_analyses(self, request, queryset):
        if 'apply' in request.POST:
            # Process the form
            form = ConfigurationSelectionForm(request.POST)
            if form.is_valid():
                configuration_name = form.cleaned_data['configuration_name']
                # Get paper IDs from queryset (Django admin preserves this automatically)
                paper_ids = list(queryset.values_list('id', flat=True))
                
                # Check for papers with problematic text lengths
                large_papers = []
                failed_papers = []
                
                for paper in queryset.filter(full_text__isnull=False).exclude(full_text=''):
                    try:
                        stats = get_text_stats(paper.full_text)
                        if not stats['is_valid']:
                            failed_papers.append(f"{paper.bibcode} ({stats['length']:,} chars)")
                        elif stats['exceeds_warning_threshold']:
                            large_papers.append(f"{paper.bibcode} ({stats['length']:,} chars)")
                    except Exception as e:
                        failed_papers.append(f"{paper.bibcode} (validation error)")
                
                # Show warnings for large papers
                if large_papers:
                    self.message_user(
                        request,
                        f"Warning: {len(large_papers)} papers exceed size threshold and may be slow/expensive to process: {', '.join(large_papers[:5])}{'...' if len(large_papers) > 5 else ''}",
                        level=messages.WARNING
                    )
                    
                # Show errors for failed validation
                if failed_papers:
                    self.message_user(
                        request,
                        f"Error: {len(failed_papers)} papers failed validation and will be skipped: {', '.join(failed_papers[:3])}{'...' if len(failed_papers) > 3 else ''}",
                        level=messages.ERROR
                    )
                
                run_paper_analyses.delay(paper_ids, configuration_name)
                config_display = dict(ConfigurationSelectionForm().fields['configuration_name'].choices)[configuration_name]
                self.message_user(
                    request,
                    f"Started paper analysis for {len(paper_ids)} papers using {config_display} configuration.",
                    level=messages.SUCCESS
                )
                return None
        else:
            # Show the form
            form = ConfigurationSelectionForm()
        
        return render(request, 'admin/configuration_selection.html', {
            'form': form,
            'papers': queryset,
            'title': 'Select Configuration for Paper Analysis',
            'action_name': 'run_paper_analyses',
            'description': 'Choose an LLM configuration to analyze the selected papers.'
        })
    run_paper_analyses.short_description = "Run paper analysis on selected papers"

    @admin.action(description="Extract text from selected papers' PDFs")
    def extract_text_from_pdf(self, request, queryset):
        papers_with_pdf = queryset.exclude(pdf='')
        if not papers_with_pdf:
            self.message_user(request, "No PDFs found in selected papers", level=messages.WARNING)
            return

        count = 0
        for paper in papers_with_pdf:
            extract_paper_text_task.delay(paper.id)
            count += 1

        self.message_user(
            request,
            f"Started text extraction for {count} papers. Check paper records for results.",
            messages.SUCCESS
        )

    @admin.action(description="Analyze dataset usages for selected papers")
    def analyze_paper_dataset_usages(self, request, queryset):
        """
        Admin action to analyze all dataset usages for selected papers.
        """
        total_usage_ids = []
        for paper in queryset:
            usage_ids = [str(usage.id) for usage in paper.dataset_usages.all()]
            total_usage_ids.extend(usage_ids)
        
        if total_usage_ids:
            run_dataset_usage_analyses.delay(total_usage_ids)
            self.message_user(
                request,
                f"Started analysis for {len(total_usage_ids)} dataset usages from {len(queryset)} paper(s). "
                f"Check Celery logs for progress.",
                messages.SUCCESS
            )
        else:
            self.message_user(
                request,
                "No dataset usages found for selected papers.",
                messages.WARNING
            )

    @admin.action(description="Run complete normalized workflow on selected papers")
    def run_complete_normalized_workflow(self, request, queryset):
        """
        Admin action to run the complete normalized workflow on selected papers.
        This includes: text extraction, paper analysis, structure analysis, 
        normalization, dataset usage creation, and dataset usage analysis.
        """
        if 'apply' in request.POST:
            # Process the form
            form = ConfigurationSelectionForm(request.POST)
            if form.is_valid():
                configuration_name = form.cleaned_data['configuration_name']
                # Get paper IDs from queryset (Django admin preserves this automatically)
                paper_ids = [str(paper.id) for paper in queryset]
                
                if not paper_ids:
                    self.message_user(
                        request,
                        "No papers selected.",
                        messages.WARNING
                    )
                    return None
                
                # Start the batch normalized workflow task with configuration
                task = run_batch_normalized_workflow.delay(paper_ids, configuration_name)
                config_display = dict(ConfigurationSelectionForm().fields['configuration_name'].choices)[configuration_name]
                
                self.message_user(
                    request,
                    f"Started complete normalized workflow for {len(paper_ids)} papers using {config_display} configuration. Task ID: {task.id}",
                    messages.SUCCESS
                )
                return None
        else:
            # Show the form
            form = ConfigurationSelectionForm()
        
        return render(request, 'admin/configuration_selection.html', {
            'form': form,
            'papers': queryset,
            'title': 'Select Configuration for Complete Normalized Workflow',
            'action_name': 'run_complete_normalized_workflow',
            'description': 'Choose an LLM configuration for the complete normalized workflow (text extraction, analysis, structuring, normalization, and dataset usage creation).'
        })

    def run_complete_normalized_workflow_batch_api(self, request, queryset):
        """
        Admin action to run the normalized workflow using the OpenAI Batch API
        for ~50% cost savings on the paper_analysis step.
        """
        if 'apply' in request.POST:
            form = ConfigurationSelectionForm(request.POST)
            if form.is_valid():
                configuration_name = form.cleaned_data['configuration_name']
                paper_ids = [str(paper.id) for paper in queryset]

                if not paper_ids:
                    self.message_user(request, "No papers selected.", messages.WARNING)
                    return None

                task = run_batch_normalized_workflow_via_batch_api.delay(paper_ids, configuration_name)
                config_display = dict(ConfigurationSelectionForm().fields['configuration_name'].choices)[configuration_name]

                self.message_user(
                    request,
                    f"Submitted Batch API workflow for {len(paper_ids)} papers using {config_display} configuration. "
                    f"Task ID: {task.id}. Check Batch Jobs in admin for progress.",
                    messages.SUCCESS
                )
                return None
        else:
            form = ConfigurationSelectionForm()

        return render(request, 'admin/configuration_selection.html', {
            'form': form,
            'papers': queryset,
            'title': 'Select Configuration for Batch API Workflow (50% cost savings)',
            'action_name': 'run_complete_normalized_workflow_batch_api',
            'description': 'Submit paper_analysis calls via OpenAI Batch API for ~50% cost savings. '
                          'Results are processed asynchronously (may take up to 24h). '
                          'Downstream processing (structuring, normalization, etc.) runs automatically on completion.'
        })
    run_complete_normalized_workflow_batch_api.short_description = "Run normalized workflow (Batch API - 50% savings)"


class HasTagFilter(admin.SimpleListFilter):
    title = 'has tag'
    parameter_name = 'has_tag'

    def lookups(self, request, model_admin):
        from django.db import connection
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT DISTINCT unnest(tags) FROM vso_query_builder_paper WHERE cardinality(tags) > 0 ORDER BY 1"
            )
            return [(row[0], row[0]) for row in cursor.fetchall()]

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(paper__tags__contains=[self.value()])


class PhenomenonMentionInline(admin.TabularInline):
    model = PhenomenonMention
    extra = 0
    readonly_fields = ['phenomenon', 'instrument_name', 'period_name', 'quote', 'created_at']
    fields = ['phenomenon', 'instrument_name', 'period_name', 'quote']
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


class LLMCallInline(admin.TabularInline):
    model = LLMCall.paper_analyses.through
    readonly_fields = ('llmcall', 'call_type', 'model_name', 'provider', 'token_count', 'cost_display', 'duration_display', 'created_at')
    extra = 0
    verbose_name = "LLM Call"
    verbose_name_plural = "Associated LLM Calls"
    
    def llmcall(self, obj):
        return obj.llmcall
    llmcall.short_description = 'Call ID'
    
    def call_type(self, obj):
        return obj.llmcall.call_type
    call_type.short_description = 'Call Type'
    
    def model_name(self, obj):
        return obj.llmcall.model_name
    model_name.short_description = 'Model'
    
    def provider(self, obj):
        return obj.llmcall.provider
    provider.short_description = 'Provider'
    
    def token_count(self, obj):
        return f"{obj.llmcall.total_tokens:,}"
    token_count.short_description = 'Tokens'
    
    def cost_display(self, obj):
        cost = obj.llmcall.estimated_cost_usd
        return f"${cost:.6f}" if cost is not None else "N/A"
    cost_display.short_description = 'Cost (USD)'
    
    def duration_display(self, obj):
        if obj.llmcall.duration_ms:
            return f"{obj.llmcall.duration_ms}ms"
        return "-"
    duration_display.short_description = 'Duration'
    
    def created_at(self, obj):
        return obj.llmcall.created_at.strftime('%Y-%m-%d %H:%M:%S')
    created_at.short_description = 'Created At'


class ConfigurationNameFilter(admin.SimpleListFilter):
    title = 'LLM configuration'
    parameter_name = 'configuration_name'

    def lookups(self, request, model_admin):
        return (
            ('standard', 'Standard (GPT-5)'),
            ('budget', 'Budget (GPT-5-mini)'),
        )

    def queryset(self, request, queryset):
        if self.value() == 'standard':
            return queryset.filter(configuration_name='standard')
        if self.value() == 'budget':
            return queryset.filter(configuration_name='budget')


@admin.register(PaperAnalysis)
class PaperAnalysisAdmin(admin.ModelAdmin):
    list_display = ('paper', 'configuration_name', 'created_at', 'status', 'paper_tags', 'has_structured_instruments', 'dataset_usage_count', 'llm_call_count')
    search_fields = ('paper__bibcode',)
    autocomplete_fields = ('paper',)
    list_select_related = ('paper',)
    list_filter = ('created_at', 'status', 'configuration_name', ConfigurationNameFilter, HasTagFilter, HasStructuredInstrumentsFilter)
    readonly_fields = ('created_at', 'llm_call_summary', 'dataset_usage_link')
    exclude = ('llm_calls',)  # Hide the many-to-many widget that shows ALL LLMCalls
    inlines = [LLMCallInline, PhenomenonMentionInline]  # Show detailed table of only associated LLM calls
    actions = ['run_structured_instruments_analysis',
               'run_structured_normalization',
               "insert_datasetusages_only_action", 'rebuild_normalized_datasetusages',
               'update_supporting_quote_locations',
               'enrich_quote_coordinates_action',
               'run_phenomenon_extraction']

    def get_queryset(self, request):
        from django.db.models import Count
        return super().get_queryset(request).annotate(
            _dataset_usage_count=Count('dataset_usages', distinct=True),
            _llm_call_count=Count('llm_calls', distinct=True),
        )

    def paper_tags(self, obj):
        return ', '.join(obj.paper.tags)

    def has_structured_instruments(self, obj):
        return bool(obj.structured_instruments_details)
    has_structured_instruments.boolean = True
    has_structured_instruments.short_description = "Has Structured Instruments"
    
    def dataset_usage_count(self, obj):
        count = getattr(obj, '_dataset_usage_count', obj.dataset_usages.count())
        if count > 0:
            return format_html('<span style="color: green;">{} usage{}</span>', count, 's' if count != 1 else '')
        return format_html('<span style="color: gray;">No usages</span>')
    dataset_usage_count.short_description = 'Dataset Usages'

    def dataset_usage_link(self, obj):
        count = getattr(obj, '_dataset_usage_count', obj.dataset_usages.count())
        if count > 0:
            url = f"/admin/vso_query_builder/datasetusage/?paper_analysis__id__exact={obj.id}"
            return format_html('<a href="{}" target="_blank">View {} Dataset Usage{}</a>', url, count, 's' if count != 1 else '')
        return format_html('<span style="color: gray;">No dataset usages</span>')
    dataset_usage_link.short_description = 'Dataset Usages'

    def llm_call_count(self, obj):
        count = getattr(obj, '_llm_call_count', obj.llm_calls.count())
        if count > 0:
            return format_html('<span style="color: blue;">{} call{}</span>', count, 's' if count != 1 else '')
        return format_html('<span style="color: gray;">No calls</span>')
    llm_call_count.short_description = 'LLM Calls'
    
    def total_cost_display(self, obj):
        # Use the same approach as llm_call_summary for consistency
        calls = obj.llm_calls.all()
        if not calls:
            return format_html('<span style="color: gray;">$0.000000</span>')
        
        total_cost = sum(float(call.estimated_cost_usd or 0) for call in calls)
        if total_cost > 0:
            return format_html('<span style="color: green;">${:.6f}</span>', total_cost)
        return format_html('<span style="color: gray;">$0.000000</span>')
    total_cost_display.short_description = 'Total Cost (USD)'
    
    def llm_call_summary(self, obj):
        """Detailed summary of LLM calls for readonly field in change view"""
        calls = obj.llm_calls.all().order_by('-created_at')
        if not calls:
            return "No LLM calls associated with this paper analysis."
        
        total_cost = sum(call.estimated_cost_usd or 0 for call in calls)
        total_tokens = sum(call.total_tokens for call in calls)

        call_types = {}
        for call in calls:
            if call.call_type not in call_types:
                call_types[call.call_type] = {'count': 0, 'cost': 0, 'tokens': 0}
            call_types[call.call_type]['count'] += 1
            call_types[call.call_type]['cost'] += call.estimated_cost_usd or 0
            call_types[call.call_type]['tokens'] += call.total_tokens
        
        summary_html = f"""
        <div style="margin: 10px 0;">
            <h4>LLM Call Summary</h4>
            <p><strong>Total:</strong> {len(calls)} calls, {total_tokens:,} tokens, ${total_cost:.6f}</p>
            
            <table style="width: 100%; border-collapse: collapse; margin-top: 10px;">
                <thead>
                    <tr style="background-color: #f8f9fa;">
                        <th style="padding: 8px; border: 1px solid #dee2e6; text-align: left;">Call Type</th>
                        <th style="padding: 8px; border: 1px solid #dee2e6; text-align: right;">Count</th>
                        <th style="padding: 8px; border: 1px solid #dee2e6; text-align: right;">Tokens</th>
                        <th style="padding: 8px; border: 1px solid #dee2e6; text-align: right;">Cost</th>
                    </tr>
                </thead>
                <tbody>
        """
        
        for call_type, stats in sorted(call_types.items()):
            summary_html += f"""
                    <tr>
                        <td style="padding: 8px; border: 1px solid #dee2e6;">{call_type}</td>
                        <td style="padding: 8px; border: 1px solid #dee2e6; text-align: right;">{stats['count']}</td>
                        <td style="padding: 8px; border: 1px solid #dee2e6; text-align: right;">{stats['tokens']:,}</td>
                        <td style="padding: 8px; border: 1px solid #dee2e6; text-align: right;">${stats['cost']:.6f}</td>
                    </tr>
            """
        
        summary_html += """
                </tbody>
            </table>
        </div>
        """
        
        return mark_safe(summary_html)
    llm_call_summary.short_description = 'LLM Call Summary'

    def run_structured_instruments_analysis(self, request, queryset):
        """Run structured instruments analysis on selected paper analyses"""

        # Filter to only completed analyses that have instruments_details
        valid_analyses = queryset.filter(
            status='completed'
        ).exclude(
            instruments_details__isnull=True
        ).exclude(
            instruments_details=''
        )

        if not valid_analyses.exists():
            self.message_user(
                request,
                "No valid paper analyses selected. Selected analyses must be completed and have instruments_details.",
                level=messages.WARNING
            )
            return

        # Queue the batch processing task
        paper_analysis_ids = list(valid_analyses.values_list('id', flat=True))
        batch_task = batch_analyze_instruments_structure.delay(
            paper_analysis_ids=paper_analysis_ids,
            force_reprocess=False
        )

        self.message_user(
            request,
            f"Started structured instruments analysis for {len(paper_analysis_ids)} paper analyses. "
            f"Batch task ID: {batch_task.id}",
            level=messages.SUCCESS
        )

    run_structured_instruments_analysis.short_description = "Run structured instruments analysis on selected analyses"

    def run_structured_normalization(self, request, queryset):
        """
        Admin action that enqueues normalize_structured_instrument_details
        for each selected PaperAnalysis.
        """
        count = 0
        for pa in queryset:
            if not pa.structured_instruments_details:
                # Skip if there's nothing to normalize
                continue
            normalize_structured_instrument_details.delay(pa.id)
            count += 1

        if count:
            self.message_user(
                request,
                f"Enqueued normalization for {count} PaperAnalysis objects.",
                level=messages.SUCCESS
            )
        else:
            self.message_user(
                request,
                "No PaperAnalysis objects with structured_instruments_details found.",
                level=messages.WARNING
            )
    run_structured_normalization.short_description = (
        "Normalize structured_instruments_details via Celery"
    )

    def insert_datasetusages_only_action(self, request, queryset):
        """
        For each selected PaperAnalysis that already has normalized_instrument_details,
        enqueue insert_datasetusages_only(paper_analysis_id).
        """
        count = 0
        skipped = 0

        for pa in queryset:
            if not pa.normalized_instrument_details:
                skipped += 1
                continue

            insert_datasetusages_only.delay(pa.id)
            count += 1

        if count:
            self.message_user(
                request,
                f"Enqueued DatasetUsage insertion for {count} PaperAnalysis object(s).",
                level=messages.SUCCESS
            )
        if skipped:
            self.message_user(
                request,
                f"Skipped {skipped} PaperAnalysis object(s) (no normalized JSON).",
                level=messages.WARNING
            )

    insert_datasetusages_only_action.short_description = (
        "Insert DatasetUsage rows using already‐normalized JSON only"
    )

    @admin.action(description="Delete + re-normalize + reinsert normalized DatasetUsages")
    def rebuild_normalized_datasetusages(self, request, queryset):
        """
        For each selected PaperAnalysis:
        - Delete existing SupportQuote rows for this PaperAnalysis
        - Delete existing DatasetUsage rows for this paper analysis
        - Re-run normalization with the current validator logic
        - Re-insert DatasetUsage rows and SupportQuotes from the freshly normalized JSON

        This avoids re-running the entire workflow and ensures stale usages/quotes are removed.
        """
        total_usages_deleted = 0
        total_quotes_deleted = 0
        enqueued = 0
        skipped = 0

        for pa in queryset:
            # Delete existing quotes for this paper analysis (quotes are recreated during upsert)
            quotes_deleted = pa.support_quotes.count()
            if quotes_deleted:
                pa.support_quotes.all().delete()
                total_quotes_deleted += quotes_deleted

            # Delete existing usages for this paper analysis
            del_qs = DatasetUsage.objects.filter(
                paper_analysis=pa
            )
            deleted_count = del_qs.count()
            if deleted_count:
                del_qs.delete()
                total_usages_deleted += deleted_count

            # Require structured instruments to be present to normalize
            if not pa.structured_instruments_details:
                skipped += 1
                continue

            # Chain: normalize → insert (insert ignores prior result via .si)
            try:
                chain(
                    normalize_structured_instrument_details.s(pa.id, pa.configuration_name),
                    insert_datasetusages_only.si(pa.id)
                ).delay()
                enqueued += 1
            except Exception as e:
                skipped += 1

        # User feedback
        if total_usages_deleted or total_quotes_deleted:
            self.message_user(
                request,
                f"Deleted {total_usages_deleted} DatasetUsage rows and {total_quotes_deleted} SupportQuote rows.",
                level=messages.SUCCESS,
            )
        if enqueued:
            self.message_user(
                request,
                f"Enqueued re-normalization and re-insertion for {enqueued} analysis(es).",
                level=messages.SUCCESS,
            )
        if skipped:
            self.message_user(
                request,
                f"Skipped {skipped} analysis(es) (no structured_instruments_details).",
                level=messages.WARNING,
            )

    def update_supporting_quote_locations(self, request, queryset):
        """
        Admin action to update PDF locations for supporting quotes using the improved PDF annotator.
        """
        count = 0
        skipped = 0
        
        for paper_analysis in queryset:
            # Check if it has supporting quotes
            if not paper_analysis.support_quotes.exists():
                skipped += 1
                continue
                
            # Check if it has a PDF
            if not paper_analysis.paper.pdf:
                skipped += 1
                continue
                
            # Queue the batch task
            update_supporting_quote_locations_batch_task.delay(paper_analysis.id)
            count += 1
        
        if count:
            self.message_user(
                request,
                f"Queued PDF location updates for {count} PaperAnalysis object(s).",
                level=messages.SUCCESS
            )
        if skipped:
            self.message_user(
                request,
                f"Skipped {skipped} PaperAnalysis object(s) (no supporting quotes or no PDF).",
                level=messages.WARNING
            )
    
    update_supporting_quote_locations.short_description = (
        "Update PDF locations for supporting quotes"
    )

    @admin.action(description="Enrich absent quote coordinates (fast, idempotent)")
    def enrich_quote_coordinates_action(self, request, queryset):
        """Bulk-fill review-UI coordinates for the selected analyses' absent quotes.

        Dedupes to DISTINCT papers (one PDF index per paper) and enqueues the
        idempotent per-paper enrich task on the cpu fleet. Papers with no PDF /
        OCR / no absent quotes cost nothing (the task self-skips).
        """
        paper_ids = set()
        for pa in queryset.select_related('paper'):
            paper = pa.paper
            if not paper or not paper.pdf or paper.used_ocr:
                continue
            paper_ids.add(paper.id)

        for pid in paper_ids:
            enrich_quote_coordinates.delay(str(pid))

        if paper_ids:
            self.message_user(
                request,
                f"Queued coordinate enrichment for {len(paper_ids)} paper(s).",
                level=messages.SUCCESS,
            )
        else:
            self.message_user(
                request,
                "No eligible papers selected (need a non-OCR PDF).",
                level=messages.WARNING,
            )

    def run_phenomenon_extraction(self, request, queryset):
        """Run FULL phenomena enrichment (extraction + merge + mention upsert)
        for the selected analyses. Phenomena never run in the standard chain —
        this action and the run_phenomena_enrichment management command are the
        deliberate entry points. Idempotent: already-extracted periods skip."""
        from .tasks import run_phenomena_enrichment
        queued = 0
        skipped = 0
        for paper_analysis in queryset:
            if not paper_analysis.normalized_instrument_details:
                skipped += 1
                continue
            run_phenomena_enrichment.delay(str(paper_analysis.id))
            queued += 1
        if queued:
            self.message_user(
                request,
                f"Queued phenomena enrichment (extract + upsert) for {queued} PaperAnalysis object(s).",
                level=messages.SUCCESS,
            )
        if skipped:
            self.message_user(
                request,
                f"Skipped {skipped} PaperAnalysis object(s) — no normalized instrument details.",
                level=messages.WARNING,
            )

    run_phenomenon_extraction.short_description = "Run phenomena enrichment (extract + upsert mentions)"


@admin.register(SupportQuote)
class SupportQuoteAdmin(admin.ModelAdmin):
    list_display = ('paper_analysis', 'instrument', 'parameter', 'dataset_usage_count', 'created_at')
    search_fields = ('paper_analysis__paper__bibcode', 'quote', 'instrument')
    autocomplete_fields = ('paper_analysis',)
    list_select_related = ('paper_analysis',)
    list_filter = ('instrument', 'parameter', 'created_at')
    readonly_fields = ('created_at', 'embedding_status', 'dataset_usages_links')
    exclude = ('dataset_usages', 'embedding')

    def get_queryset(self, request):
        from django.db.models import Count
        return super().get_queryset(request).annotate(
            _dataset_usage_count=Count('dataset_usages', distinct=True),
        )

    def dataset_usage_count(self, obj):
        count = getattr(obj, '_dataset_usage_count', obj.dataset_usages.count())
        if count > 0:
            return format_html('<span style="color: green;">{} usage{}</span>', count, 's' if count != 1 else '')
        return format_html('<span style="color: gray;">No usages</span>')
    dataset_usage_count.short_description = 'Dataset Usages'

    def embedding_status(self, obj):
        if obj.embedding is not None:
            return format_html('<span style="color: green;">Vector (1536 dimensions)</span>')
        return format_html('<span style="color: gray;">Not generated</span>')
    embedding_status.short_description = 'Embedding'

    def dataset_usages_links(self, obj):
        usages = obj.dataset_usages.select_related('paper', 'instrument').all()
        if not usages:
            return format_html('<span style="color: gray;">No linked dataset usages</span>')
        links = []
        for usage in usages:
            url = f"/admin/vso_query_builder/datasetusage/{usage.id}/change/"
            label = f"{usage.paper.bibcode} - {usage.instrument.short_name if usage.instrument else 'Unknown'}"
            links.append(format_html('<a href="{}">{}</a>', url, label))
        return format_html('<br>'.join(links))
    dataset_usages_links.short_description = 'Linked Dataset Usages'


@admin.register(DataSource)
class DataSourceAdmin(admin.ModelAdmin):
    list_display = ('slug', 'name')
    search_fields = ('slug', 'name')


@admin.register(Observatory)
class ObservatoryAdmin(admin.ModelAdmin):
    list_display = ('short_name', 'name', 'datasource')
    list_filter = ('datasource',)
    search_fields = ('short_name', 'name')


@admin.register(Instrument)
class InstrumentAdmin(admin.ModelAdmin):
    list_display = ('short_name', 'observatory', 'full_name', 'get_datasource')
    list_filter  = ('observatory__datasource', 'observatory')
    list_select_related = ('observatory__datasource',)
    search_fields = ('short_name', 'full_name')

    def get_datasource(self, obj):
        return obj.observatory.datasource.name if obj.observatory else None
    get_datasource.short_description = 'Data Source'


class DatasetUsageAnalysisInline(admin.StackedInline):
    model = DatasetUsageAnalysis
    readonly_fields = ('python_snippet', 'analyzer_outputs', 'is_valid_syntax', 'syntax_error',
                      'execution_successful', 'execution_error', 'total_results_found', 'created_at', 'updated_at')
    exclude = ('llm_calls',)
    extra = 0
    max_num = 1


class SupportQuoteInline(admin.TabularInline):
    model = SupportQuote.dataset_usages.through
    readonly_fields = ('supportquote', 'quote_preview', 'instrument', 'page_number')
    extra = 0
    verbose_name = "Supporting Quote"
    verbose_name_plural = "Supporting Quotes"

    def get_queryset(self, request):
        # Select related supportquote but defer the large embedding vector (1536 dimensions)
        return super().get_queryset(request).select_related('supportquote').defer('supportquote__embedding')

    def supportquote(self, obj):
        return obj.supportquote
    supportquote.short_description = 'Quote ID'
    
    def quote_preview(self, obj):
        quote_text = obj.supportquote.quote
        if len(quote_text) > 100:
            return quote_text[:100] + "..."
        return quote_text
    quote_preview.short_description = 'Quote Text'
    
    def instrument(self, obj):
        return obj.supportquote.instrument
    instrument.short_description = 'Instrument'
    
    def page_number(self, obj):
        return obj.supportquote.page_number
    page_number.short_description = 'Page'


@admin.register(DatasetUsage)
class DatasetUsageAdmin(admin.ModelAdmin):
    list_display = ('paper', 'instrument', 'observation_window', 'has_supporting_quotes', 'has_analysis', 'analysis_status')
    list_filter = ('instrument', 'analysis__is_valid_syntax', 'analysis__execution_successful')
    search_fields = (
        'paper__bibcode',
        'instrument__short_name',
        'instrument__observatory__short_name',
    )
    autocomplete_fields = ('instrument',)
    readonly_fields = ('paper_link', 'paper_analysis_link', 'llm_calls_link', 'analysis_link')
    exclude = ('paper', 'paper_analysis', 'llm_calls')
    inlines = [SupportQuoteInline]
    actions = ['analyze_dataset_usages', 'update_quote_locations_for_dataset_usages']

    def paper_link(self, obj):
        if obj.paper:
            url = f"/admin/vso_query_builder/paper/{obj.paper.id}/change/"
            return format_html('<a href="{}">{}</a>', url, obj.paper.bibcode)
        return "-"
    paper_link.short_description = 'Paper'

    def paper_analysis_link(self, obj):
        if obj.paper_analysis:
            url = f"/admin/vso_query_builder/paperanalysis/{obj.paper_analysis.id}/change/"
            return format_html('<a href="{}">{} - {}</a>', url, obj.paper.bibcode, obj.paper_analysis.configuration_name or 'Analysis')
        return "-"
    paper_analysis_link.short_description = 'Paper Analysis'


    def llm_calls_link(self, obj):
        count = obj.llm_calls.count()
        if count > 0:
            url = f"/admin/vso_query_builder/llmcall/?dataset_usages__id__exact={obj.id}"
            return format_html('<a href="{}">{} LLM call{}</a>', url, count, 's' if count != 1 else '')
        return format_html('<span style="color: gray;">No LLM calls</span>')
    llm_calls_link.short_description = 'LLM Calls'

    def analysis_link(self, obj):
        if hasattr(obj, 'analysis') and obj.analysis:
            url = f"/admin/vso_query_builder/datasetusageanalysis/{obj.analysis.id}/change/"
            status = "✓" if obj.analysis.execution_successful else "✗"
            return format_html('<a href="{}">{} View Analysis</a>', url, status)
        return format_html('<span style="color: gray;">No analysis</span>')
    analysis_link.short_description = 'Analysis'

    def get_queryset(self, request):
        """Optimize queryset to avoid N+1 queries"""
        from django.db.models import Count
        queryset = super().get_queryset(request)
        return queryset.select_related(
            'paper',
            'instrument',
            'instrument__observatory',
            'instrument__observatory__datasource',
            'analysis',
            'paper_analysis'
        ).annotate(_supporting_quote_count=Count('supporting_quotes', distinct=True))

    def has_supporting_quotes(self, obj):
        count = getattr(obj, '_supporting_quote_count', obj.supporting_quotes.count())
        return count > 0
    has_supporting_quotes.boolean = True
    has_supporting_quotes.short_description = 'Has Quotes'
    
    def has_analysis(self, obj):
        return hasattr(obj, 'analysis')
    has_analysis.boolean = True
    has_analysis.short_description = 'Has Analysis'
    
    def analysis_status(self, obj):
        if hasattr(obj, 'analysis'):
            analysis = obj.analysis
            if analysis.execution_successful:
                return format_html('<span style="color: green;">✓ Success</span>')
            elif analysis.is_valid_syntax:
                return format_html('<span style="color: orange;">⚠ Syntax OK</span>')
            else:
                return format_html('<span style="color: red;">✗ Failed</span>')
        return format_html('<span style="color: gray;">- No Analysis</span>')
    analysis_status.short_description = 'Analysis Status'
    
    @admin.action(description="Analyze selected dataset usages")
    def analyze_dataset_usages(self, request, queryset):
        dataset_usage_ids = [str(usage.id) for usage in queryset]
        run_dataset_usage_analyses.delay(dataset_usage_ids)
        
        self.message_user(
            request,
            f"Started analysis for {len(dataset_usage_ids)} dataset usages. Check Celery logs for progress.",
            messages.SUCCESS
        )
    
    def update_quote_locations_for_dataset_usages(self, request, queryset):
        """
        Admin action to update PDF locations for ONLY the supporting quotes
        connected to the selected dataset usages (not all quotes for the entire paper).
        """
        all_quote_ids = []
        total_count = 0
        skipped_count = 0
        debug_messages = []
        
        for dataset_usage in queryset:
            # Get all supporting quotes for this dataset usage
            supporting_quotes = dataset_usage.supporting_quotes.all()
            quote_count = supporting_quotes.count()
            
            debug_messages.append(f"Dataset Usage {dataset_usage.id}: {quote_count} supporting quotes")
            
            if quote_count == 0:
                debug_messages.append(f"  -> SKIPPED: No supporting quotes")
                skipped_count += 1
                continue
                
            # Check if the paper has a PDF
            has_pdf = bool(dataset_usage.paper.pdf)
            debug_messages.append(f"  -> Has PDF: {has_pdf}")
            if not has_pdf:
                debug_messages.append(f"  -> SKIPPED: No PDF")
                skipped_count += 1
                continue
            
            # Check if paper has paper analysis
            paper_analysis = dataset_usage.paper.paperanalysis_set.first()
            if not paper_analysis:
                debug_messages.append(f"  -> SKIPPED: No paper analysis")
                skipped_count += 1
                continue
            
            # Collect the quote IDs from this dataset usage
            quote_ids = list(supporting_quotes.values_list('id', flat=True))
            all_quote_ids.extend(quote_ids)
            total_count += quote_count
            
            debug_messages.append(f"  -> Added {quote_count} quote IDs to processing queue")
        
        # Determine method to use (from quote_normalizer.py setting)
        method = 'ir'  # Default, but this will be overridden by the task based on quote_normalizer setting
        
        if all_quote_ids:
            # Queue the targeted task that processes only these specific quotes
            update_specific_quotes_task.delay(all_quote_ids, method=method)
            
            self.message_user(
                request,
                f"Queued PDF location updates for {total_count} supporting quotes from {len(queryset)} dataset usage(s). "
                f"Processing ONLY the selected quotes (not all quotes for the paper). Method: {method}",
                level=messages.SUCCESS
            )
        
        if skipped_count:
            debug_info = "\\n".join(debug_messages)
            self.message_user(
                request,
                f"Skipped {skipped_count} dataset usage(s). Debug info: {debug_info}",
                level=messages.WARNING
            )
    
    update_quote_locations_for_dataset_usages.short_description = (
        "Update PDF locations for supporting quotes (IR method)"
    )


@admin.register(DatasetUsageAnalysis)
class DatasetUsageAnalysisAdmin(admin.ModelAdmin):
    list_display = ('dataset_usage_summary', 'is_valid_syntax', 'execution_successful', 'total_results_found', 'created_at')
    list_filter = ('is_valid_syntax', 'execution_successful', 'dataset_usage__instrument')
    search_fields = (
        'dataset_usage__paper__bibcode',
        'dataset_usage__instrument__short_name',
        'dataset_usage__instrument__observatory__short_name',
    )
    readonly_fields = ('python_snippet', 'analyzer_outputs', 'created_at', 'updated_at', 'llm_calls_link', 'dataset_usage_link')
    exclude = ('llm_calls', 'dataset_usage')

    def dataset_usage_summary(self, obj):
        usage = obj.dataset_usage
        return f"{usage.paper.bibcode} - {usage.instrument.short_name}"

    def dataset_usage_link(self, obj):
        if obj.dataset_usage:
            url = f"/admin/vso_query_builder/datasetusage/{obj.dataset_usage.id}/change/"
            return format_html('<a href="{}">{} - {}</a>', url, obj.dataset_usage.paper.bibcode, obj.dataset_usage.instrument.short_name if obj.dataset_usage.instrument else 'Unknown')
        return "-"
    dataset_usage_link.short_description = 'Dataset Usage'
    dataset_usage_summary.short_description = 'Dataset Usage'

    def llm_calls_link(self, obj):
        count = obj.llm_calls.count()
        if count > 0:
            url = f"/admin/vso_query_builder/llmcall/?dataset_analyses__id__exact={obj.id}"
            return format_html('<a href="{}">{} LLM call{}</a>', url, count, 's' if count != 1 else '')
        return format_html('<span style="color: gray;">No LLM calls</span>')
    llm_calls_link.short_description = 'LLM Calls'
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            'dataset_usage__paper',
            'dataset_usage__instrument',
            'dataset_usage__instrument__observatory'
        )


@admin.register(LLMCall)
class LLMCallAdmin(admin.ModelAdmin):
    """
    Admin interface for LLM calls with detailed view and filtering.
    """
    list_display = ('id', 'call_type', 'model_name', 'provider', 'total_tokens', 'estimated_cost_usd', 'duration_ms', 'created_at')
    list_filter = ('call_type', 'provider', 'model_name', 'created_at')
    search_fields = ('call_type', 'model_name', 'output_content')
    readonly_fields = ('id', 'call_type', 'model_name', 'provider', 'prompt_tokens', 'completion_tokens', 
                      'total_tokens', 'estimated_cost_usd', 'input_messages', 'output_content', 
                      'duration_ms', 'metadata', 'created_at')
    date_hierarchy = 'created_at'
    
    # Prevent manual creation/editing since these are created programmatically
    def has_add_permission(self, request):
        return False
    
    def has_change_permission(self, request, obj=None):
        return False
    
    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(BatchJob)
class BatchJobAdmin(admin.ModelAdmin):
    """Admin interface for Batch API job tracking."""
    list_display = ('id', 'batch_id_short', 'status', 'configuration_name', 'total_requests',
                    'completed_requests', 'failed_requests', 'created_at', 'completed_at')
    list_filter = ('status', 'configuration_name', 'provider', 'created_at')
    readonly_fields = ('batch_id', 'input_file_id', 'output_file_id', 'status', 'provider',
                      'configuration_name', 'paper_mapping', 'total_requests', 'completed_requests',
                      'failed_requests', 'created_at', 'submitted_at', 'completed_at', 'error_details')
    date_hierarchy = 'created_at'

    @admin.display(description="Batch ID")
    def batch_id_short(self, obj):
        if obj.batch_id:
            return obj.batch_id[:20] + "..." if len(obj.batch_id) > 20 else obj.batch_id
        return "(pending)"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(PipelineNode)
class PipelineNodeAdmin(admin.ModelAdmin):
    list_display = ['stage', 'label', 'status', 'started_at', 'completed_at', 'analysis']
    list_filter = ['stage', 'status']
    search_fields = ['label', 'analysis__paper__bibcode']
    readonly_fields = ['id', 'analysis', 'parent', 'stage', 'label', 'status',
                       'started_at', 'completed_at', 'metadata', 'llm_calls']
    ordering = ['-started_at']

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(InstrumentMention)
class InstrumentMentionAdmin(admin.ModelAdmin):
    list_display = [
        'match_level', 'matched_observatory',
        'matched_instrument', 'paper_analysis', 'created_at',
    ]
    list_filter = ['match_level', 'matched_observatory', 'created_at']
    search_fields = ['paper_analysis__paper__bibcode']
    readonly_fields = ['id', 'created_at', 'updated_at']
    raw_id_fields = ['paper_analysis', 'matched_observatory', 'matched_instrument']
    ordering = ['-created_at']

    def has_add_permission(self, request):
        return False


@admin.register(Phenomenon)
class PhenomenonAdmin(admin.ModelAdmin):
    list_display = ['name', 'iri']
    search_fields = ['name', 'iri']
    ordering = ['name']



@admin.register(PhenomenonMention)
class PhenomenonMentionAdmin(admin.ModelAdmin):
    list_display = ['phenomenon', 'instrument_name', 'bibcode', 'period_name', 'created_at']
    list_filter = ['phenomenon', 'created_at']
    search_fields = ['paper_analysis__paper__bibcode', 'instrument_name', 'phenomenon__name']
    readonly_fields = ['id', 'created_at']
    raw_id_fields = ['paper_analysis', 'phenomenon']
    ordering = ['-created_at']

    @admin.display(description='Bibcode')
    def bibcode(self, obj):
        return obj.paper_analysis.paper.bibcode

    def has_add_permission(self, request):
        return False
