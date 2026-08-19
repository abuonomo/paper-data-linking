import uuid
from collections import Counter
from django.contrib.auth.models import User
from django.contrib.postgres.fields import ArrayField, DateTimeRangeField
from django.contrib.postgres.indexes import GinIndex, GistIndex
from django.db import models
from django.db.models import Q
from pathlib import Path
from pgvector.django import VectorField, HnswIndex


def paper_pdf_upload_path(instance, filename):
    # Generate a new UUID for the file
    file_uuid = uuid.uuid4()
    # Use pathlib to safely get the file extension
    ext = Path(filename).suffix
    # Construct the filename using the new UUID and the original extension
    new_filename = f"{file_uuid}{ext}"  # ext includes the dot
    # Return the custom path to store the file, using only the new UUID
    return f"papers/{new_filename}"


def annotated_pdf_upload_path(instance, filename):
    # Generate a new UUID for the file
    file_uuid = uuid.uuid4()
    # Use pathlib to safely get the file extension
    ext = Path(filename).suffix
    # Construct the filename using the new UUID and the original extension
    new_filename = f"{file_uuid}{ext}"  # ext includes the dot
    # Return the custom path to store the file, using only the new UUID
    return f"annotated_papers/{new_filename}"


class Paper(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)  # Use UUID as the primary key
    bibcode = models.CharField(max_length=255, unique=True)
    full_text = models.TextField(blank=True, null=True)
    used_ocr = models.BooleanField(default=False)
    pdf = models.FileField(upload_to=paper_pdf_upload_path, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)  # Automatically set to now when the object is first created
    user = models.ForeignKey(User, on_delete=models.SET_NULL, related_name='papers', null=True)
    # ^ keep the papers even if user is deleted

    # to descriminate WIND from SOHO initially.
    tags = ArrayField(models.CharField(max_length=100), default=list, blank=True)
    
    # ADS metadata fields - cached to avoid repeated API calls
    title = models.TextField(blank=True, null=True)
    authors = models.JSONField(default=list, blank=True)
    year = models.CharField(max_length=4, blank=True, null=True)
    journal = models.TextField(blank=True, null=True)
    journal_abbrev = models.CharField(max_length=100, blank=True, null=True)
    abstract = models.TextField(blank=True, null=True)
    ads_metadata_fetched = models.BooleanField(default=False)
    ads_metadata_updated = models.DateTimeField(null=True, blank=True)

    # Denormalized dataset-usage rollups for the public papers listing.
    # These are recomputed periodically (see refresh_paper_usage_stats management
    # command / celery-beat) rather than aggregated on every request, so the
    # public list page does not pay for a full COUNT/MAX over DatasetUsage on
    # each load. Kept nullable/zero-default; the listing falls back to live
    # aggregation whenever request filters make these rollups inapplicable.
    approved_usage_count = models.PositiveIntegerField(default=0)
    pending_usage_count = models.PositiveIntegerField(default=0)
    # upper(observation_window) rollups used as the list sort key.
    latest_observation_end_approved = models.DateTimeField(null=True, blank=True)
    latest_observation_end_all = models.DateTimeField(null=True, blank=True)
    usage_stats_updated = models.DateTimeField(null=True, blank=True)

    def fetch_ads_metadata(self):
        """Fetch and cache ADS metadata for this paper"""
        from .ads_service import ADSService
        from django.utils import timezone
        
        try:
            ads_service = ADSService()
            ads_details = ads_service.get_paper_details_with_abstract(self.bibcode)
            
            self.title = ads_details.get('title', self.bibcode)
            self.authors = ads_details.get('authors', [])
            self.year = ads_details.get('year')
            self.journal = ads_details.get('journal')
            self.journal_abbrev = ads_details.get('journal_abbrev')
            self.abstract = ads_details.get('abstract')
            self.ads_metadata_fetched = True
            self.ads_metadata_updated = timezone.now()
            self.save()
            return True
        except Exception as e:
            # Log the error but don't fail the paper creation
            print(f"Failed to fetch ADS metadata for {self.bibcode}: {e}")
            return False

    def __str__(self):
        return self.bibcode

    class Meta:
        indexes = [
            GinIndex(fields=['tags'], name='paper_tags_gin_idx'),
            # Partial indexes supporting the public listing's
            # WHERE <has usages> ORDER BY <sort key> DESC ... LIMIT. The
            # predicates match the listing's membership filters exactly, so each
            # index holds only the (small) set of papers that actually appear in
            # the listing -- the scan never walks the ~90k paper rows that have
            # no dataset usages.
            models.Index(fields=['-latest_observation_end_approved', 'bibcode'],
                         name='paper_latest_end_appr_idx',
                         condition=Q(approved_usage_count__gt=0)),
            models.Index(fields=['-latest_observation_end_all', 'bibcode'],
                         name='paper_latest_end_all_idx',
                         condition=Q(approved_usage_count__gt=0) | Q(pending_usage_count__gt=0)),
        ]


class PaperAnalysis(models.Model):
    """Stores extracted paper data"""
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]
    status = models.CharField(
        max_length=10,
        choices=STATUS_CHOICES,
        default='pending'
    )
    paper = models.ForeignKey(Paper, on_delete=models.CASCADE)
    configuration_name = models.CharField(
        max_length=50, 
        null=True, 
        blank=True, 
        help_text="LLM configuration used for this analysis"
    )
    context = models.JSONField()
    instruments_details = models.TextField()
    structured_instruments_details = models.JSONField(
        null=True, blank=True, help_text="Structured JSON representation of instrument details from markdown")
    normalized_instrument_details = models.JSONField(null=True, blank=True)
    annotated_pdf = models.FileField(
        upload_to=annotated_pdf_upload_path,
        null=True,
        blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    pipeline_completed_at = models.DateTimeField(
        null=True, blank=True,
        help_text="Set when all downstream pipeline tasks (including usage analysis) have completed."
    )
    token_usage = models.JSONField(blank=True, null=True)
    
    # LLM call tracking
    llm_calls = models.ManyToManyField(
        'LLMCall', 
        blank=True, 
        related_name='paper_analyses',
        help_text="LLM calls associated with this paper analysis"
    )

    class Meta:
        verbose_name = "Paper Analysis"
        verbose_name_plural = "Paper Analyses"
        unique_together = ('paper', 'configuration_name')
        indexes = [
            # latest_analysis_date subquery: WHERE paper_id=$1 ORDER BY created_at DESC LIMIT 1
            models.Index(fields=["paper", "created_at"]),
            # config JOIN filter in conditional COUNT aggregation
            models.Index(fields=["configuration_name"]),
        ]

    def __str__(self):
        config_suffix = f" ({self.configuration_name})" if self.configuration_name else " (legacy)"
        return f"Analysis for {self.paper.bibcode}{config_suffix}"

    @property
    def is_wind_paper(self):
        return 'WIND' in self.paper.tags


class SupportQuote(models.Model):
    """Stores supporting quotes with vector embeddings"""
    paper_analysis = models.ForeignKey(
        PaperAnalysis,
        on_delete=models.CASCADE,
        related_name='support_quotes'
    )
    quote = models.TextField()
    instrument = models.CharField(max_length=100)
    parameter = models.CharField(max_length=100)
    page_number = models.IntegerField()
    y_coord = models.FloatField()

    # New fields for complete location data
    x_coord_start = models.FloatField(default=0.0)
    x_coord_end = models.FloatField(default=0.0)
    y_coord_start = models.FloatField(default=0.0)
    y_coord_end = models.FloatField(default=0.0)

    embedding = VectorField(dimensions=1536, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    # Multi-line quote support
    coordinate_regions = models.JSONField(
        default=list,
        blank=True,
        help_text='Array of coordinate regions for multi-line quotes: [{"page": 1, "x0": 100, "y0": 200, "x1": 300, "y1": 210}, ...]'
    )
    
    # Many-to-many relationship to DatasetUsage for traceability
    dataset_usages = models.ManyToManyField(
        'DatasetUsage',
        related_name='supporting_quotes',
        blank=True,
        help_text="Dataset usages that this quote supports"
    )


    class Meta:
        indexes = [
            HnswIndex(
                name='support_quote_embedding_idx',
                fields=['embedding'],
                m=16,
                ef_construction=64,
                opclasses=['vector_cosine_ops']
            )
        ]
        verbose_name = "Support Quote"
        verbose_name_plural = "Support Quotes"

    def __str__(self):
        return f"Quote from {self.paper_analysis.paper.bibcode}"

class DataSource(models.Model):
    slug = models.SlugField(primary_key=True)       # 'vso', 'cdaweb'
    name = models.CharField(max_length=100)


class Observatory(models.Model):
    """
    Represents a spacecraft, mission, or ground observatory in the instrument registry.

    Each field has a distinct role — do not conflate them:

      short_name   — External catalog ID (VSO slug or SPASE URI). Stable foreign key
                     into CDAWeb/VSO data systems. NEVER change after initial import.

      name         — The mission name shown to the LLM in Stage 1/2 mission-identification
                     prompts ("which missions appear in this paper?"). Must be human-readable
                     and probe-specific for multi-spacecraft missions: use "MMS-1", "GOES-13",
                     "STEREO-A" — not "MMS", "GOES", "STEREO". Managed by the
                     update_instrument_descriptions management command.

      display_name — Short label for the UI only. Not consumed by any pipeline logic.

      description  — Concise scientific description included in LLM mission-identification
                     prompts to help match paper references to catalog entries.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    datasource = models.ForeignKey(
        DataSource, on_delete=models.CASCADE, null=True, blank=True,
        help_text="Data system this observatory belongs to (e.g. 'vso', 'cdaweb').",
    )

    short_name = models.CharField(
        max_length=300,
        blank=True,
        help_text=(
            "External catalog identifier: VSO slug (e.g. 'SOHO') or SPASE URI "
            "(e.g. 'spase://SMWG/Observatory/MMS/1'). Used as mission_code in "
            "grounding catalog entries and as the DB lookup key. "
            "NEVER modify after initial import."
        ),
    )
    name = models.CharField(
        max_length=300,
        help_text=(
            "Mission name used in Stage 1/2 LLM prompts for mission identification. "
            "Must be probe-specific for multi-spacecraft constellations — e.g. 'MMS-1' "
            "not 'MMS', 'GOES-13' not 'GOES', 'STEREO-A' not 'STEREO'. "
            "Managed by the update_instrument_descriptions management command."
        ),
    )
    display_name = models.CharField(
        max_length=200,
        blank=True,
        help_text="Short label for UI display only. Not used in any pipeline logic.",
    )
    description = models.TextField(
        blank=True,
        default="",
        help_text=(
            "Concise scientific description of the mission/observatory for inclusion "
            "in LLM mission-identification prompts. Helps models match paper references "
            "to catalog entries (e.g. geographic location for ground stations, science "
            "domain for spacecraft). Managed by update_observatory_descriptions command."
        ),
    )

    def __str__(self):
        return self.display_name or self.name or self.short_name

    class Meta:
        verbose_name_plural = "Observatories"


class CatalogSource(models.TextChoices):
    """Provenance of an Instrument catalogue row.

    STANDARD rows come from VSO/CDAWeb imports and resolve to a real, queryable
    data-system ID (their `short_name` is fed verbatim into VSO/HDPWS queries by
    the snippet generators). CUSTOM rows are authored by us — currently
    group-level generic instruments (e.g. spase://SMWG/Instrument/GOES/SEM under
    the GOES ObservatoryGroup) used to ground a program mention that names no
    specific spacecraft. CUSTOM rows are first-class grounding targets but are
    NOT real CDAWeb-tagged InstrumentIDs, so snippet generation must skip them
    (a standard CDAWeb query on a custom ID would silently return nothing).
    """
    STANDARD = 'standard', 'Standard (VSO/CDAWeb import)'
    CUSTOM = 'custom', 'Custom (authored, e.g. group-level generic)'


class Instrument(models.Model):
    """
    Represents a single instrument in the instrument registry.

    Each field has a distinct role — do not conflate them:

      short_name   — External catalog ID (VSO slug or SPASE URI). Stable foreign key
                     into CDAWeb/VSO data systems. NEVER change after initial import.
                     For SPASE instruments this is a full URI, e.g.:
                       spase://SMWG/Instrument/ParkerSolarProbe/FIELDS/MAG

      full_name    — Short canonical identifier used as a name anchor in Stage 3 LLM
                     grounding prompts: "[FIELDS/MAG] PSP FIELDS/MAG fluxgate ...".
                     Despite the Django field name, this should be CONCISE — a brief
                     acronym or path that matches how the instrument is cited in papers
                     (e.g. "FIELDS/MAG", "HPCA", "FGM"). Not a verbose long-form name.
                     Maps to instrument_name in catalog/grounding contexts.

      display_name — Short label for the UI only. Not consumed by any pipeline logic.

      description  — Rich scientific noun phrase describing the instrument. This is the
                     PRIMARY grounding signal: it feeds the Stage 3 LLM prompt and is
                     the source text for the embedding vector. Aim for 100–200 chars.
                     Must include instrument type, physical quantity measured, and the
                     probe name for multi-spacecraft missions, e.g.:
                       "MMS-1 FIELDS/FGM fluxgate magnetometer measuring three-axis DC
                        magnetic field vectors in the magnetosphere"
                     Managed by update_instrument_descriptions + enrich_catalog_with_llm.

      embedding    — 1536-dim pgvector embedding of description (text-embedding-3-small).
                     Used to pre-filter candidates before Stage 3 LLM grounding.
                     Auto-regenerated via post_save when description changes; or run
                     update_instrument_descriptions --regenerate-embeddings in bulk.
    """
    observatory = models.ForeignKey(Observatory, on_delete=models.CASCADE)

    short_name = models.CharField(
        max_length=300,
        help_text=(
            "External catalog identifier: VSO slug (e.g. 'LASCO') or SPASE URI "
            "(e.g. 'spase://SMWG/Instrument/SOHO/LASCO'). Used as instrument_code "
            "in grounding catalog entries. NEVER modify after initial import — this "
            "is the stable ID that links records to CDAWeb/VSO data systems."
        ),
    )
    full_name = models.CharField(
        max_length=255,
        blank=True,
        help_text=(
            "Short canonical identifier used as a name anchor in Stage 3 LLM grounding "
            "prompts (e.g. 'FIELDS/MAG', 'HPCA', 'FGM'). Despite the field name, keep "
            "this CONCISE — it should match the abbreviation used in research papers. "
            "Maps to instrument_name in grounding catalog entries."
        ),
    )
    display_name = models.CharField(
        max_length=200,
        blank=True,
        help_text="Short label for UI display only. Not used in any pipeline logic.",
    )
    description = models.TextField(
        blank=True,
        help_text=(
            "Rich scientific noun phrase describing the instrument (~100–200 chars). "
            "Primary LLM grounding signal in Stage 3 and source for the embedding vector. "
            "Should include instrument type, physical quantity measured, and probe name "
            "for multi-spacecraft missions."
        ),
    )
    # Legacy field — not populated for new records and not used in pipeline logic.
    provider = models.CharField(max_length=100, blank=True, null=True)

    catalog_source = models.CharField(
        max_length=20,
        choices=CatalogSource.choices,
        default=CatalogSource.STANDARD,
        db_index=True,
        help_text=(
            "Provenance of this row. 'standard' = VSO/CDAWeb import with a real "
            "queryable data-system ID. 'custom' = authored row (e.g. a group-level "
            "generic instrument); a valid grounding target but NOT a CDAWeb-tagged "
            "InstrumentID, so snippet generation skips it and emits a custom marker."
        ),
    )

    embedding = VectorField(
        dimensions=1536,
        null=True,
        blank=True,
        help_text=(
            "1536-dim pgvector embedding of the description field (text-embedding-3-small). "
            "Pre-filters instrument candidates before Stage 3 LLM grounding. "
            "Auto-regenerated via post_save when description changes."
        ),
    )

    class Meta:
        unique_together = ("observatory", "short_name")
        indexes = [
            HnswIndex(
                name='instrument_embedding_idx',
                fields=['embedding'],
                m=16,
                ef_construction=64,
                opclasses=['vector_cosine_ops']
            )
        ]

    def __str__(self):
        label = self.display_name or self.full_name or self.short_name
        obs_label = (
            self.observatory.display_name or self.observatory.name
            if self.observatory else None
        )
        return f"{label} ({obs_label})" if obs_label else label

    @property
    def to_catalog_dict(self):
        # Fail fast if required data is missing - don't allow silent defaults
        if not self.observatory:
            raise ValueError(
                f"Instrument {self.short_name} has no observatory. "
                f"Cannot determine mission_code, mission_name, or data_system."
            )
        if not self.observatory.datasource:
            raise ValueError(
                f"Observatory {self.observatory.name} has no datasource. "
                f"Cannot determine data_system for instrument {self.short_name}."
            )
        return {
            # instrument_code / mission_code: stable external IDs — never change these
            "instrument_code": self.short_name,
            "mission_code":    self.observatory.short_name,
            # instrument_name / mission_name: human-readable labels for LLM prompts
            "instrument_name": self.full_name,
            "mission_name":    self.observatory.name,
            # grounding signals
            "description":     self.description,
            "data_system":     self.observatory.datasource.slug,
            "provider":        self.provider,
        }


class DatasetUsage(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    paper       = models.ForeignKey(Paper, on_delete=models.CASCADE,
                                    related_name="dataset_usages")
    paper_analysis = models.ForeignKey(
        'PaperAnalysis',
        on_delete=models.CASCADE,
        null=True,  # Allow NULL for legacy records
        blank=True,
        related_name='dataset_usages',
        help_text="PaperAnalysis that generated this dataset usage"
    )
    instrument  = models.ForeignKey(Instrument, on_delete=models.CASCADE)
    observation_window = DateTimeRangeField()
    extra_params = models.JSONField(default=dict, blank=True)

    # Validation fields
    validation_status = models.CharField(
        max_length=20,
        choices=[
            ("pending", "Pending"),
            ("approved", "Approved"),
            ("rejected", "Rejected"),
            ("needs_review", "Needs Review"),
        ],
        default="pending",
        help_text="Validation status of this dataset usage"
    )
    validated_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='validated_dataset_usages',
        help_text="User who validated this dataset usage"
    )
    validated_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When this dataset usage was validated"
    )
    validation_notes = models.TextField(
        blank=True,
        null=True,
        help_text="Optional notes from the validator"
    )
    
    # LLM call tracking
    llm_calls = models.ManyToManyField(
        'LLMCall',
        blank=True,
        related_name='dataset_usages',
        help_text="LLM calls associated with this dataset usage (normalization, grounding, etc.)"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["instrument"]),
            GistIndex(fields=["observation_window"]),
            models.Index(fields=["paper", "validation_status"]),
            models.Index(fields=["validation_status"]),
            # composite replaces single-column (paper_analysis) for conditional COUNT with config filter
            models.Index(fields=["paper_analysis", "validation_status"]),
            models.Index(fields=["validated_at"]),
            # MAX(validated_at) grouped by paper in validation queue query
            models.Index(fields=["paper", "validated_at"]),
        ]


class InstrumentMention(models.Model):
    """
    Records every instrument entry from normalized_instrument_details, capturing
    partial grounding results when a full DatasetUsage cannot be created.
    Always created for all instruments (including fully-resolved ones) for a
    complete audit trail. match_level indicates how far grounding succeeded.

    Complementary to DatasetUsage — both models are independent and share
    instrument/paper_analysis FKs. To find DatasetUsages for a mention:
        DatasetUsage.objects.filter(paper_analysis=mention.paper_analysis,
                                    instrument=mention.matched_instrument)
    """
    MATCH_LEVEL_UNMATCHED = 'unmatched'
    MATCH_LEVEL_MISSION_ONLY = 'mission_only'
    MATCH_LEVEL_INSTRUMENT_NO_TIME = 'instrument_no_time'
    MATCH_LEVEL_PARTIAL = 'partial'
    MATCH_LEVEL_FULL = 'full'

    MATCH_LEVEL_CHOICES = [
        (MATCH_LEVEL_UNMATCHED, 'Unmatched'),
        (MATCH_LEVEL_MISSION_ONLY, 'Mission Only'),
        (MATCH_LEVEL_INSTRUMENT_NO_TIME, 'Instrument, No Valid Time'),
        (MATCH_LEVEL_PARTIAL, 'Partially Resolved'),
        (MATCH_LEVEL_FULL, 'Fully Resolved'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    paper_analysis = models.ForeignKey(
        'PaperAnalysis', on_delete=models.CASCADE, related_name='instrument_mentions'
    )

    # FK identity — these are the canonical keys, not string codes
    matched_observatory = models.ForeignKey(
        Observatory, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='instrument_mentions',
        help_text="Set only for mission_only match level — instrument implies observatory otherwise"
    )
    matched_instrument = models.ForeignKey(
        Instrument, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='instrument_mentions',
        help_text="Catalog instrument matched from the paper text (null if not in catalog)"
    )

    match_level = models.CharField(
        max_length=30, choices=MATCH_LEVEL_CHOICES, db_index=True,
        help_text="How far grounding succeeded for this instrument mention"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            # One mention per instrument per analysis (instrument resolved)
            models.UniqueConstraint(
                fields=['paper_analysis', 'matched_instrument'],
                condition=models.Q(matched_instrument__isnull=False),
                name='unique_mention_per_instrument',
            ),
            # One mention per mission per analysis (mission-only — instrument not in catalog)
            models.UniqueConstraint(
                fields=['paper_analysis', 'matched_observatory'],
                condition=models.Q(matched_instrument__isnull=True, matched_observatory__isnull=False),
                name='unique_mention_per_observatory',
            ),
        ]
        indexes = [
            models.Index(fields=['matched_observatory', 'match_level']),
            models.Index(fields=['matched_instrument', 'match_level']),
        ]

    def __str__(self):
        if self.matched_instrument:
            return f"{self.matched_instrument} [{self.match_level}] ({self.paper_analysis.paper.bibcode})"
        if self.matched_observatory:
            return f"{self.matched_observatory} [{self.match_level}] ({self.paper_analysis.paper.bibcode})"
        return f"[unmatched] ({self.paper_analysis.paper.bibcode})"


class DatasetUsageAnalysis(models.Model):
    """Analysis results for individual dataset usage Python snippets."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    dataset_usage = models.OneToOneField(DatasetUsage, on_delete=models.CASCADE, related_name="analysis")
    
    # Generated snippet
    python_snippet = models.TextField(help_text="Generated Python code snippet for this dataset usage")
    
    # Analysis results
    is_valid_syntax = models.BooleanField(default=False, help_text="Whether the snippet has valid Python syntax")
    syntax_error = models.TextField(blank=True, help_text="Syntax error details if any")
    execution_successful = models.BooleanField(default=False, help_text="Whether the snippet executed successfully")
    execution_error = models.TextField(blank=True, help_text="Execution error details if any")
    total_results_found = models.IntegerField(null=True, blank=True, help_text="Number of results returned by query")
    
    # Raw analyzer outputs (JSON field for extensibility)
    analyzer_outputs = models.JSONField(default=dict, blank=True, help_text="Raw results from all analyzers")
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    # LLM call tracking
    llm_calls = models.ManyToManyField(
        'LLMCall', 
        blank=True, 
        related_name='dataset_analyses',
        help_text="LLM calls associated with this dataset usage analysis"
    )
    
    def __str__(self):
        return f"Analysis for {self.dataset_usage.instrument.full_name} usage in {self.dataset_usage.paper.bibcode}"
    
    class Meta:
        verbose_name = "Dataset Usage Analysis"
        verbose_name_plural = "Dataset Usage Analyses"
        indexes = [
            models.Index(fields=["is_valid_syntax"]),
            models.Index(fields=["execution_successful"]),
            models.Index(fields=["created_at"]),
        ]


class QuoteCategory(models.TextChoices):
    """Categories for what aspect of dataset usage a quote supports"""
    INSTRUMENT = 'instrument', 'Instrument Identification'
    TIME_RANGE = 'time_range', 'Time Range/Period'
    WAVELENGTH = 'wavelength', 'Wavelength/Energy'
    PHYSICAL_OBSERVABLE = 'observable', 'Physical Observable'
    GENERAL = 'general', 'General Reference'


class QuoteUsageLink(models.Model):
    """Intermediate model for categorized quote-dataset usage relationships"""
    quote = models.ForeignKey(
        SupportQuote, 
        on_delete=models.CASCADE,
        related_name='usage_links'
    )
    dataset_usage = models.ForeignKey(
        DatasetUsage, 
        on_delete=models.CASCADE,
        related_name='quote_links'
    )
    support_category = models.CharField(
        max_length=20, 
        choices=QuoteCategory.choices,
        help_text="What aspect of the dataset usage this quote supports"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ('quote', 'dataset_usage', 'support_category')
        verbose_name = "Quote Usage Link"
        verbose_name_plural = "Quote Usage Links"
        indexes = [
            models.Index(fields=['support_category']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return f"{self.quote.instrument} ({self.get_support_category_display()}) -> {self.dataset_usage.instrument.short_name}"


class LLMCall(models.Model):
    """
    Tracks individual LiteLLM API calls with comprehensive token usage and cost data.
    Can be associated with multiple models via many-to-many relationships.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Call identification
    call_type = models.CharField(
        max_length=100,
        help_text="Type of LLM call (e.g., 'paper_analysis', 'time_normalization', 'instrument_validation')"
    )
    
    # LLM details
    model_name = models.CharField(
        max_length=100,
        help_text="Full LiteLLM model string (e.g., 'openai/gpt-4o', 'anthropic/claude-3-haiku')"
    )
    provider = models.CharField(
        max_length=50,
        help_text="LLM provider extracted from model name"
    )
    
    # Token usage
    prompt_tokens = models.IntegerField(default=0)
    completion_tokens = models.IntegerField(default=0)
    total_tokens = models.IntegerField(default=0)
    estimated_cost_usd = models.DecimalField(
        max_digits=10,
        decimal_places=6,
        null=True,
        default=None,
        help_text="Estimated cost in USD"
    )
    
    # Full request/response data (for debugging and analysis)
    input_messages = models.JSONField(
        blank=True, 
        null=True,
        help_text="The messages sent to the LLM"
    )
    output_content = models.TextField(
        blank=True, 
        null=True,
        help_text="The response content from the LLM"
    )
    
    # Performance metadata
    duration_ms = models.IntegerField(
        null=True, 
        blank=True,
        help_text="Duration of the API call in milliseconds"
    )
    
    # Additional metadata
    metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text="Additional call metadata (finish_reason, kwargs, etc.)"
    )

    # Template rendering context
    render_context = models.JSONField(
        null=True,
        blank=True,
        help_text="Template variables used to render this prompt (enables re-testing with different templates)"
    )

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name = "LLM Call"
        verbose_name_plural = "LLM Calls"
        indexes = [
            models.Index(fields=["call_type"]),
            models.Index(fields=["model_name"]),
            models.Index(fields=["provider"]),
            models.Index(fields=["created_at"]),
            models.Index(fields=["estimated_cost_usd"]),
            models.Index(fields=["total_tokens"]),
        ]
    
    def __str__(self):
        cost_str = f"${self.estimated_cost_usd:.6f}" if self.estimated_cost_usd is not None else "N/A"
        return f"{self.call_type} ({self.model_name}) - {self.total_tokens} tokens - {cost_str}"


class PipelineNode(models.Model):
    """Tracks individual nodes in the LLM pipeline execution tree."""
    STAGE_CHOICES = [
        ('paper_analysis', 'Paper Analysis'),
        ('structuring', 'Structuring'),
        ('instrument', 'Instrument'),
        ('grounding', 'Grounding'),
        ('grounding_datasystem', 'Grounding Data System'),
        ('grounding_substep', 'Grounding Substep'),
        ('grounding_match', 'Grounding Match'),
        ('normalization', 'Normalization'),
        ('normalizer', 'Normalizer'),
    ]
    STATUS_CHOICES = [
        ('running', 'Running'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('skipped', 'Skipped'),
    ]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    analysis = models.ForeignKey(PaperAnalysis, on_delete=models.CASCADE, related_name='pipeline_nodes')
    parent = models.ForeignKey('self', null=True, blank=True, on_delete=models.CASCADE, related_name='children')
    stage = models.CharField(max_length=50, choices=STAGE_CHOICES)
    label = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='running')
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    llm_calls = models.ManyToManyField('LLMCall', blank=True, related_name='pipeline_nodes')
    dataset_usages = models.ManyToManyField(
        'DatasetUsage', blank=True, related_name='pipeline_nodes'
    )

    class Meta:
        verbose_name = "Pipeline Node"
        verbose_name_plural = "Pipeline Nodes"
        indexes = [
            models.Index(fields=['analysis', 'stage']),
            models.Index(fields=['parent']),
            models.Index(fields=['status']),
        ]

    def __str__(self):
        return f"{self.stage}/{self.label} [{self.status}]"


class BatchJob(models.Model):
    """Tracks OpenAI Batch API submissions for paper_analysis calls."""
    STATUS_CHOICES = [
        ('preparing', 'Preparing'),
        ('submitted', 'Submitted'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('partially_failed', 'Partially Failed'),
    ]

    batch_id = models.CharField(
        max_length=200, unique=True, null=True, blank=True,
        help_text="OpenAI batch ID (e.g., batch_abc123)"
    )
    input_file_id = models.CharField(max_length=200, null=True, blank=True)
    output_file_id = models.CharField(max_length=200, null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='preparing')
    provider = models.CharField(max_length=50, default='openai')
    configuration_name = models.CharField(max_length=50, default='standard')
    aws_region_name = models.CharField(
        max_length=50, null=True, blank=True,
        help_text="AWS region used at submission time (Bedrock only)"
    )
    # When False, step-1 ingestion stops at PaperAnalysis instead of chaining the
    # old synchronous downstream — used by the batch pipeline, which runs downstream
    # through the wave runner (BatchDownstreamRun) instead.
    trigger_downstream = models.BooleanField(default=True)

    # Maps paper_id (str) → custom_id used in the batch request
    paper_mapping = models.JSONField(
        default=dict,
        help_text="Maps paper IDs to batch custom_ids"
    )

    # Stats
    total_requests = models.IntegerField(default=0)
    completed_requests = models.IntegerField(default=0)
    failed_requests = models.IntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    error_details = models.JSONField(null=True, blank=True)

    class Meta:
        verbose_name = "Batch Job"
        verbose_name_plural = "Batch Jobs"
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["created_at"]),
        ]

    def __str__(self):
        return f"BatchJob {self.batch_id or '(pending)'} - {self.status} ({self.total_requests} requests)"


class BatchDownstreamRun(models.Model):
    """A corpus-scale, wave-synchronous batch run of the downstream pipeline.

    Drives the record-replay execution: papers are re-run in 'collection' mode
    (LLM calls deferred into Bedrock batches, one wave per dependency level) until
    each paper's prefix resolves, then each is replayed once in 'commit' mode with
    a warm cache. Coexists with — and never alters — the synchronous pipeline.
    """
    STATUS_CHOICES = [
        ('preparing', 'Preparing'),
        ('collecting', 'Collecting'),     # running a collection pass to find the wave's calls
        ('batching', 'Batching'),         # a Bedrock batch wave is in flight
        ('committing', 'Committing'),      # replaying LLM-complete papers to write outputs
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    configuration_name = models.CharField(max_length=50)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='preparing')
    aws_region_name = models.CharField(max_length=50, null=True, blank=True)

    # Storage/latency-lean corpus mode: run completion prunes resolved cache
    # rows' response_content (lossless — LLMCall keeps full input+output
    # provenance), commit skips quote-coordinate extraction (enrichable on
    # demand), and quote embeddings are deferred to the embed_missing_quotes
    # sweep. (Cache request_payload is stripped at resolve time for ALL runs —
    # batch inputs are already archived in S3.)
    corpus_mode = models.BooleanField(default=False)

    # Corpus + progress. Per-paper progress lives in RunPaper (one row per paper,
    # indexed state machine). The JSON lists below are LEGACY: paper_ids is still
    # written once at creation (cheap provenance); the progress lists are kept
    # only so pre-RunPaper runs remain readable — whole-list rewrites under
    # select_for_update are O(run size) per chunk merge and die around 50k papers.
    paper_ids = models.JSONField(default=list, help_text="Paper IDs (str) in this run (provenance)")
    current_wave = models.IntegerField(default=0)
    total_papers = models.IntegerField(default=0)
    llm_complete_papers = models.JSONField(
        default=list, help_text="LEGACY (pre-RunPaper runs) — see RunPaper states")
    committed_papers = models.JSONField(
        default=list, help_text="LEGACY (pre-RunPaper runs) — see RunPaper states")
    failed_papers = models.JSONField(default=list, help_text="LEGACY (pre-RunPaper runs)")

    metadata = models.JSONField(default=dict, blank=True)
    error_details = models.JSONField(null=True, blank=True)

    # Lease: only one worker drives a run at a time. A crashed worker's lease
    # expires and the reconciler re-claims the run — no double-submit, no stall.
    leased_until = models.DateTimeField(null=True, blank=True)
    lease_owner = models.CharField(max_length=100, null=True, blank=True)
    last_progress_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    TERMINAL_STATUSES = ('completed', 'failed')

    class Meta:
        verbose_name = "Batch Downstream Run"
        verbose_name_plural = "Batch Downstream Runs"
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["created_at"]),
        ]

    def __str__(self):
        return f"BatchDownstreamRun {self.id} [{self.configuration_name}] - {self.status}"


class RunPaper(models.Model):
    """Per-paper state machine for a BatchDownstreamRun.

    Replaces the run's JSON progress lists: chunk workers flip states with
    indexed UPDATEs instead of rewriting O(run-size) lists under a global lock,
    and every 'is a round outstanding?' question becomes an EXISTS query — which
    structurally eliminates the round-counter/dispatch-storm bug class.

    States:
      pending      — needs (more) collection passes
      collecting   — claimed by a dispatched collection chunk
      llm_complete — prefix fully resolved (zero deferrals); awaiting commit
      committing   — claimed by a dispatched commit chunk
      committed    — terminal: outputs written
      failed       — terminal: unrecoverable in collection or commit

    ``dispatched_at`` is stamped when a chunk claims the row; the driver reclaims
    rows whose chunk evidently died (stale claim) back to their pre-claim state.
    """
    STATES = [
        ('pending', 'Pending'),
        ('collecting', 'Collecting'),
        ('llm_complete', 'LLM complete'),
        ('committing', 'Committing'),
        ('committed', 'Committed'),
        ('failed', 'Failed'),
    ]
    TERMINAL_STATES = ('committed', 'failed')
    CLAIMED_STATES = ('collecting', 'committing')

    run = models.ForeignKey(BatchDownstreamRun, on_delete=models.CASCADE, related_name='papers')
    paper = models.ForeignKey('Paper', on_delete=models.CASCADE, related_name='batch_run_states')
    state = models.CharField(max_length=20, choices=STATES, default='pending')
    attempts = models.IntegerField(default=0, help_text="Commit attempts")
    error = models.TextField(null=True, blank=True)
    dispatched_at = models.DateTimeField(
        null=True, blank=True, help_text="When a chunk claimed this row (stale-claim recovery)")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Run Paper"
        verbose_name_plural = "Run Papers"
        constraints = [
            models.UniqueConstraint(fields=['run', 'paper'], name='uniq_runpaper_run_paper'),
        ]
        indexes = [
            models.Index(fields=['run', 'state']),
        ]

    def __str__(self):
        return f"RunPaper {self.run_id}/{self.paper_id} [{self.state}]"


class CachedLLMResponse(models.Model):
    """Durable per-wave queue AND replay cache for downstream LLM calls.

    A row is created (status='pending') the first time the chokepoint encounters
    an un-resolved logical call during a collection pass; the unique
    (run, request_hash) constraint collapses identical calls across papers and
    branches into a single batch request. Pending rows of the current wave become
    the next Bedrock batch's JSONL; ingestion flips them to 'resolved' with the
    response content. On replay the chokepoint serves 'resolved' rows from here.
    """
    STATUS_CHOICES = [
        ('pending', 'Pending'),      # discovered, not yet batched
        ('batched', 'Batched'),      # included in an in-flight batch job
        ('resolved', 'Resolved'),    # response available for replay
        ('failed', 'Failed'),        # batch returned an error for this record
    ]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    run = models.ForeignKey(
        BatchDownstreamRun, on_delete=models.CASCADE, related_name='cached_responses')
    request_hash = models.CharField(max_length=64, db_index=True)
    call_type = models.CharField(max_length=100, blank=True, default='')

    # Everything needed to (re)build the batch record's modelInput:
    # {"model", "messages", "response_format", "params"}
    request_payload = models.JSONField(default=dict)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    wave = models.IntegerField(null=True, blank=True)
    batch_job = models.ForeignKey(
        BatchJob, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='cached_responses')

    response_content = models.TextField(null=True, blank=True)
    usage = models.JSONField(default=dict, blank=True)
    finish_reason = models.CharField(max_length=50, null=True, blank=True)
    error = models.TextField(null=True, blank=True)
    # Retry count for TRANSIENT failures (Bedrock ServiceUnavailable / throttling /
    # expired token). A transient failure keeps the row retryable (status back to
    # 'pending') up to a cap, then becomes terminal 'failed'. Permanent failures
    # (validation / unparseable) skip retries entirely.
    attempts = models.IntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Cached LLM Response"
        verbose_name_plural = "Cached LLM Responses"
        constraints = [
            models.UniqueConstraint(
                fields=["run", "request_hash"], name="unique_cached_response_per_run"),
        ]
        indexes = [
            models.Index(fields=["run", "status"]),
            models.Index(fields=["run", "request_hash"]),
        ]

    def __str__(self):
        return f"CachedLLMResponse {self.request_hash[:12]} [{self.status}]"


class BatchPipelineRun(models.Model):
    """End-to-end corpus pipeline: extract -> step1 -> downstream -> analyze.

    A single crash-safe driver (advance_pipeline) walks the stages, delegating each
    to the right subsystem (prefork extraction chord, step-1 Bedrock batch,
    BatchDownstreamRun wave runner, prefork analyze chord). Lease + reconciler make
    it resumable, exactly like BatchDownstreamRun. This is the 90k entrypoint.
    """
    STATUS_CHOICES = [('running', 'Running'), ('completed', 'Completed'), ('failed', 'Failed')]
    STAGE_CHOICES = [
        ('extract', 'Extract text'),
        ('step1', 'Paper analysis (step 1)'),
        ('downstream', 'Downstream (wave runner)'),
        ('analyze', 'Snippet analysis'),
        ('done', 'Done'),
    ]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    configuration_name = models.CharField(max_length=50)
    aws_region_name = models.CharField(max_length=50, null=True, blank=True)
    paper_ids = models.JSONField(default=list)
    stage = models.CharField(max_length=20, choices=STAGE_CHOICES, default='extract')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='running')

    allow_ocr = models.BooleanField(default=False)       # extraction: skip OCR for corpus runs
    run_execution = models.BooleanField(default=False)   # analyze: skip live Fido for corpus runs
    corpus_mode = models.BooleanField(default=False)     # downstream: storage-lean provenance

    # Per-stage progress
    extract_dispatched = models.BooleanField(default=False)
    extract_done = models.BooleanField(default=False)
    step1_batch_job = models.ForeignKey(
        BatchJob, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    downstream_run = models.ForeignKey(
        BatchDownstreamRun, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    analyze_dispatched = models.BooleanField(default=False)
    analyze_done = models.BooleanField(default=False)

    # Lease (same crash-safe single-writer pattern as BatchDownstreamRun)
    leased_until = models.DateTimeField(null=True, blank=True)
    lease_owner = models.CharField(max_length=100, null=True, blank=True)
    last_progress_at = models.DateTimeField(null=True, blank=True)

    metadata = models.JSONField(default=dict, blank=True)
    error_details = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    TERMINAL_STATUSES = ('completed', 'failed')

    class Meta:
        verbose_name = "Batch Pipeline Run"
        verbose_name_plural = "Batch Pipeline Runs"
        indexes = [models.Index(fields=["status"]), models.Index(fields=["created_at"])]

    def __str__(self):
        return f"BatchPipelineRun {self.id} [{self.configuration_name}] {self.stage}/{self.status}"


class DatasetUsageValidation(models.Model):
    """
    Records an individual user's (or anonymous visitor's) validation judgment
    for a DatasetUsage.  Multiple validators can each submit one record; the
    consensus is computed by recompute_consensus() and stored back on
    DatasetUsage.validation_status.
    """
    VALIDATION_STATUS_CHOICES = [
        ("approved", "Approved"),
        ("rejected", "Rejected"),
        ("needs_review", "Needs Review"),
    ]

    dataset_usage = models.ForeignKey(
        DatasetUsage,
        related_name='validations',
        on_delete=models.CASCADE,
    )
    user = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='dataset_usage_validations',
        help_text="Authenticated user who submitted this validation (null for anonymous)",
    )
    anonymous_id = models.UUIDField(
        null=True,
        blank=True,
        help_text="Client-generated UUID for anonymous tracking (used when user is null)",
    )
    validation_status = models.CharField(
        max_length=20,
        choices=VALIDATION_STATUS_CHOICES,
    )
    validation_notes = models.TextField(blank=True, null=True)
    # Per-component checkmarks on the claim tuple (validation-campaign reviews).
    # Nullable so historic rows and the legacy validate endpoint are unaffected.
    mission_correct = models.BooleanField(
        null=True,
        blank=True,
        help_text="Whether the observatory/mission of the claim is correct",
    )
    instrument_correct = models.BooleanField(
        null=True,
        blank=True,
        help_text="Whether the instrument of the claim is correct",
    )
    window_correct = models.BooleanField(
        null=True,
        blank=True,
        help_text="Whether the observation window of the claim is correct",
    )
    # Usage-type reason for rejects whose tuple is factually correct (all
    # checkmarks true) — the census taxonomy. Null for approves, unsures, and
    # misattribution rejects (where the unchecked box is the reason).
    REJECT_REASON_CHOICES = [
        ("mention_only", "Mention/background only"),
        ("external_summary", "Cites others' analysis"),
        ("review_reproduction", "Reproduced figure from cited work"),
        ("infrastructure", "Instrument/infrastructure paper"),
        ("theory_context", "Theory only"),
        ("composite_component", "Composite-product component"),
        ("other", "Other (see notes)"),
    ]
    reject_reason = models.CharField(
        max_length=32,
        choices=REJECT_REASON_CHOICES,
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            # One validation per authenticated user per usage
            models.UniqueConstraint(
                fields=['dataset_usage', 'user'],
                condition=Q(user__isnull=False),
                name='unique_user_validation',
            ),
            # One validation per anonymous ID per usage
            models.UniqueConstraint(
                fields=['dataset_usage', 'anonymous_id'],
                condition=Q(user__isnull=True),
                name='unique_anon_validation',
            ),
        ]
        indexes = [
            models.Index(fields=['dataset_usage', 'created_at'], name='dsuv_dataset_created_idx'),
        ]
        verbose_name = "Dataset Usage Validation"
        verbose_name_plural = "Dataset Usage Validations"

    def __str__(self):
        who = self.user.username if self.user_id else f"anon:{self.anonymous_id}"
        return f"{self.validation_status} by {who} on {self.dataset_usage_id}"


def recompute_consensus(usage):
    """
    Recompute DatasetUsage.validation_status from all DatasetUsageValidation
    records for this usage and save the result.

    Rules:
      - 0 validations  → 'pending'
      - majority of same status → that status
      - tie             → 'needs_review'
    """
    from django.utils import timezone

    validations = list(usage.validations.all())
    if not validations:
        usage.validation_status = 'pending'
        usage.validated_at = None
        usage.save(update_fields=['validation_status', 'validated_at'])
        return

    counts = Counter(v.validation_status for v in validations)
    total = len(validations)
    majority = total // 2 + 1

    for s in ['approved', 'rejected', 'needs_review']:
        if counts[s] >= majority:
            usage.validation_status = s
            usage.validated_at = timezone.now()
            usage.save(update_fields=['validation_status', 'validated_at'])
            return

    # Tie → needs_review
    usage.validation_status = 'needs_review'
    usage.validated_at = timezone.now()
    usage.save(update_fields=['validation_status', 'validated_at'])


# ---------------------------------------------------------------------------
# Phenomenon models
# ---------------------------------------------------------------------------

class Phenomenon(models.Model):
    """A space-physics phenomenon from the HelioKNOW ontology."""
    id = models.BigAutoField(primary_key=True)
    name = models.CharField(max_length=255, unique=True)
    iri = models.CharField(
        max_length=500,
        unique=True,
        help_text="HelioKNOW IRI, e.g. 'hkp:SolarWind'",
    )

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


PHENOMENON_VALIDATION_STATUS_CHOICES = [
    ('pending', 'Pending'),
    ('accepted', 'Accepted'),
    ('rejected', 'Rejected'),
    ('needs_review', 'Needs Review'),
]

PHENOMENON_VALIDATION_VOTE_CHOICES = [
    ('accepted', 'Accepted'),
    ('rejected', 'Rejected'),
    ('needs_review', 'Needs Review'),
]


class PhenomenonMention(models.Model):
    """
    Records an extraction result: instrument → phenomenon.
    One record per (paper_analysis, phenomenon, instrument_name).
    All physobs supporting quotes from every period are linked via the M2M.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    paper_analysis = models.ForeignKey(
        PaperAnalysis,
        on_delete=models.CASCADE,
        related_name='phenomenon_mentions',
    )
    phenomenon = models.ForeignKey(
        Phenomenon,
        on_delete=models.CASCADE,
        related_name='mentions',
    )
    instrument_name = models.CharField(max_length=500)
    matched_instrument_code = models.CharField(max_length=255, blank=True, null=True)
    matched_mission_code = models.CharField(max_length=255, blank=True, null=True)
    period_name = models.CharField(max_length=500, blank=True)
    quote = models.TextField(blank=True)
    supporting_quote = models.ForeignKey(
        SupportQuote,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='phenomenon_mentions',
    )
    supporting_quotes = models.ManyToManyField(
        SupportQuote,
        blank=True,
        related_name='phenomenon_mention_set',
        help_text="All physobs supporting quotes collected across periods for this instrument/phenomenon pair",
    )
    physical_observable = models.TextField(
        blank=True,
        help_text="Source physical_observable text from the structured instrument data",
    )

    # Consensus validation fields
    validation_status = models.CharField(
        max_length=20,
        choices=PHENOMENON_VALIDATION_STATUS_CHOICES,
        default='pending',
    )
    validated_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='validated_phenomenon_mentions',
    )
    validated_at = models.DateTimeField(null=True, blank=True)
    validation_notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['paper_analysis']),
            models.Index(fields=['phenomenon']),
            models.Index(fields=['validation_status']),
        ]

    def __str__(self):
        return (
            f"{self.phenomenon.name} | {self.instrument_name} | "
            f"{self.paper_analysis.paper.bibcode}"
        )


class PhenomenonMentionValidation(models.Model):
    """
    Per-user (or per-anonymous-visitor) validation vote for a PhenomenonMention.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    phenomenon_mention = models.ForeignKey(
        PhenomenonMention,
        on_delete=models.CASCADE,
        related_name='validations',
    )
    user = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='phenomenon_mention_validations',
    )
    anonymous_id = models.UUIDField(null=True, blank=True)
    validation_status = models.CharField(
        max_length=20,
        choices=PHENOMENON_VALIDATION_VOTE_CHOICES,
    )
    validation_notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['phenomenon_mention', 'user'],
                condition=Q(user__isnull=False),
                name='unique_phenom_user_validation',
            ),
            models.UniqueConstraint(
                fields=['phenomenon_mention', 'anonymous_id'],
                condition=Q(user__isnull=True),
                name='unique_phenom_anon_validation',
            ),
        ]
        verbose_name = "Phenomenon Mention Validation"
        verbose_name_plural = "Phenomenon Mention Validations"

    def __str__(self):
        who = self.user.username if self.user_id else f"anon:{self.anonymous_id}"
        return f"{self.validation_status} by {who} on {self.phenomenon_mention_id}"


def recompute_phenomenon_consensus(mention):
    """
    Recompute PhenomenonMention.validation_status from all
    PhenomenonMentionValidation records for this mention and save.

    Rules:
      - 0 validations  → 'pending'
      - majority of same status → that status
      - tie             → 'needs_review'
    """
    from django.utils import timezone

    validations = list(mention.validations.all())
    if not validations:
        mention.validation_status = 'pending'
        mention.validated_at = None
        mention.save(update_fields=['validation_status', 'validated_at'])
        return

    counts = Counter(v.validation_status for v in validations)
    total = len(validations)
    majority = total // 2 + 1

    for s in ['accepted', 'rejected', 'needs_review']:
        if counts[s] >= majority:
            mention.validation_status = s
            mention.validated_at = timezone.now()
            mention.save(update_fields=['validation_status', 'validated_at'])
            return

    mention.validation_status = 'needs_review'
    mention.validated_at = timezone.now()
    mention.save(update_fields=['validation_status', 'validated_at'])
