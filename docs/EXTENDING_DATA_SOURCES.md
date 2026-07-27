# Adding New Data Sources Guide

This guide explains how to add support for new data sources (like CDAWEB) to the paper data linking system.

## Overview

The system uses a registry pattern for extensible data source support. Each data source needs:

1. **Normalizers**: Extract and validate data source-specific fields (e.g., cadence, energy ranges)
2. **Script Generator**: Creates data retrieval code specific to the data source  
3. **Analyzers** (optional): Custom validation/analysis logic

## Architecture Flow

The complete pipeline for new data sources:

**Paper Text** → **Structured Analysis** → **Normalizers** → **Database Storage** → **APIs** → **Script Generators** → **Analyzers**

- **Structured Analysis**: Extracts raw field values from paper text
- **Normalizers**: Parse and validate field values into structured data  
- **Database Storage**: Automatically stores normalized data in `DatasetUsage.extra_params`
- **APIs**: Serve rich structured data to frontend and external clients
- **Script Generators**: Use normalized data to create executable code
- **Analyzers**: Validate generated scripts and execution results

## Step 1: Create Normalizers (Optional but Recommended)

If your data source has specific fields that need parsing (like cadence, energy ranges, coordinate systems), create normalizers to extract structured data.

### Create a Normalizer Class

Create a new file like `cadence_normalizer.py`:

```python
from paper_data_linking.linkers.general.normalizers.base_normalizer import BaseNormalizer
from paper_data_linking.linkers.general.normalizers.normalizer_registry import NormalizerRegistry
from paper_data_linking.linkers.general.normalizers.normalization_context import NormalizationContext

@NormalizerRegistry.register("cadence", version="1.0", data_sources=["cdaweb"])
class CadenceNormalizer(BaseNormalizer):
    """Normalizer for cadence/sampling rate information specific to CDAWeb data."""
    
    def normalize(self, context: NormalizationContext) -> dict:
        raw_cadence = context.period_data.cadence  # Access the cadence field
        
        if not raw_cadence:
            return None
            
        # Use LLM to parse cadence strings like "1 minute", "30 seconds", "1 Hz"
        config = settings.llm_pipeline.normalization.cadence
        
        system_msg, user_msg = load_and_render_prompt(
            "cadence_normalization",
            raw_cadence=raw_cadence
        )

        response = self.llm_client.completion(
            call_type="cadence_normalization",
            model=config.model,
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg}
            ],
            response_format=NormalizedCadence,  # Pydantic model
            temperature=config.temperature
        )
        
        parsed_obj = NormalizedCadence.model_validate_json(response.choices[0].message.content)
        return parsed_obj.model_dump()
```

### Define the Pydantic Model

In `paper_data_linking/linkers/general/normalizers/normalizer.py`:

```python
class NormalizedCadence(BaseModel):
    value: float = Field(description="Numeric cadence value")
    unit: str = Field(description="seconds|minutes|hours|Hz|kHz|MHz") 
    original_text: str = Field(description="Original cadence text")
    is_approximate: bool = Field(description="Whether cadence is approximate")
```

### Update Structured Analysis Schema

Add the field to `InternalDataCollectionPeriod` in `normalization_models.py` (this may already exist):

```python
cadence: Optional[str] = Field(
    default=None,
    description="Data cadence/sampling rate (CDAWeb-specific)"
)
```

### Register the Normalizer

Add import to `paper_data_linking/linkers/general/normalizers/__init__.py`:

```python
from .cadence_normalizer import CadenceNormalizer
```

## Step 2: Create a Script Generator

Create a new file like `cdaweb_script_generator.py`:

```python
from .script_generator_base import BaseDatasetUsageScriptGenerator
from .script_generator_registry import DataSourceScriptGeneratorRegistry

@DataSourceScriptGeneratorRegistry.register("cdaweb", data_sources=["cdaweb"])
class CDAWEB_DatasetUsageScriptGenerator(BaseDatasetUsageScriptGenerator):
    def generate_snippet(self, dataset_usage, query_name=None, include_imports=True):
        # Implement your data source's query generation logic
        # Return Python code string that queries your data source
        pass
```

**Key requirements:**
- Inherit from `BaseDatasetUsageScriptGenerator`
- Use `@DataSourceScriptGeneratorRegistry.register()` decorator
- Implement `generate_snippet()` method
- Return executable Python code as string

## Step 2: Create Custom Analyzers (Optional)

Create analyzers for data source-specific validation:

```python
from .registry import DatasetUsageAnalyzerRegistry
from .base import BaseDatasetUsageAnalyzer

@DatasetUsageAnalyzerRegistry.register("QueryExecution.cdaweb", data_sources=["cdaweb"])
class CDAWEBQueryExecutionAnalyzer(BaseDatasetUsageAnalyzer):
    def analyze_snippet(self, dataset_usage, snippet):
        # Implement data source-specific execution and validation
        # Return dict with analysis results
        pass
```

**When to create custom analyzers:**
- Different execution patterns or libraries
- Unique validation requirements  
- Special result parsing needs
- Data source-specific parameter validation

## Step 3: Register Your Implementation

Add imports to `paper_data_linking/analyzers/__init__.py`:

```python
# Import implementations to register them
from . import implementations
from . import vso_script_generator
from . import cdaweb_script_generator  # Add your new generator
from . import cdaweb_analyzers         # Add your analyzers (if any)
```

## Step 4: Handle Dependencies

For optional dependencies:

```python
try:
    from your_data_source_library import SomeClass
    YOUR_DATASOURCE_AVAILABLE = True
except ImportError:
    YOUR_DATASOURCE_AVAILABLE = False
```

Check availability in your analyzers and provide clear error messages.

## Step 5: Test Your Implementation

Verify registration:

```python
from paper_data_linking.analyzers import DataSourceScriptGeneratorRegistry

# Should not raise UnsupportedDataSourceError
generator = DataSourceScriptGeneratorRegistry.get_generator_for_data_source("cdaweb")
```

## Registry Behavior

The system automatically:
- **Normalizer Discovery**: Automatically runs all normalizers registered for your data source
- **Database Storage**: Normalized data automatically stored in `DatasetUsage.extra_params`
- **Script Generation**: Uses your generator for matching data source slugs
- **Analyzer Selection**: Prefers data source-specific analyzers (e.g., `QueryExecution.cdaweb`) over general ones (`QueryExecution`)
- **Error Handling**: Raises `UnsupportedDataSourceError` for missing generators
- **Analysis Pipeline**: Skips analysis for datasets with unsupported data sources

## Automatic Database Integration

The system automatically handles normalized data storage without any additional code:

### How Normalization Creates Database Records

1. **StructuredNormalizer** runs your normalizers and wraps results:
   ```json
   {
     "cadence": {
       "original": "1 minute sampling",
       "normalized": {
         "value": 1.0,
         "unit": "minutes",
         "is_approximate": false,
         "original_text": "1 minute sampling"
       }
     }
   }
   ```

2. **Generic Database Logic** extracts the `normalized` data:
   ```python
   # In tasks.py - this happens automatically
   for field_name, field_data in period.items():
       if isinstance(field_data, dict) and "normalized" in field_data:
           normalized_data = field_data.get("normalized")
           if normalized_data is not None:
               extras[field_name] = normalized_data  # Goes to extra_params
   ```

3. **DatasetUsage Record** is created:
   ```json
   {
     "extra_params": {
       "cadence": {
         "value": 1.0,
         "unit": "minutes", 
         "is_approximate": false,
         "original_text": "1 minute sampling"
       },
       "time_range": {...},
       "wavelengths": {...}
     }
   }
   ```

### Database Querying

Rich normalized data can be queried using Django's JSON field operations:

```python
# Find all datasets with minute-level cadence
DatasetUsage.objects.filter(
    extra_params__cadence__unit='minutes'
)

# Find datasets with cadence faster than 30 seconds
DatasetUsage.objects.filter(
    extra_params__cadence__unit='seconds',
    extra_params__cadence__value__lt=30
)

# Complex queries across multiple normalized fields
DatasetUsage.objects.filter(
    extra_params__cadence__value__lt=60,
    extra_params__wavelengths__unit='angstrom'
)
```

## Analyzer Naming Convention

- **General**: `QuerySyntax`, `QueryExecution`, `InstrumentValidation`
- **Data Source-Specific**: `QueryExecution.cdaweb`, `InstrumentValidation.vso`

The system tries specific variants first, then falls back to general analyzers.

## Data Flow

1. Dataset usage has data source slug (e.g., "cdaweb")
2. Registry selects appropriate script generator
3. Generator creates executable Python code
4. Analysis pipeline selects best analyzers for that data source
5. Analyzers validate and execute the generated code

This architecture allows adding new data sources without modifying existing code.

## Using Normalized Data Downstream

The rich normalized data created by your normalizers is automatically available throughout the system:

### In Script Generators

Access structured data to generate accurate queries:

```python
@DataSourceScriptGeneratorRegistry.register("cdaweb", data_sources=["cdaweb"])
class CDAWEB_DatasetUsageScriptGenerator(BaseDatasetUsageScriptGenerator):
    def generate_snippet(self, dataset_usage, query_name=None, include_imports=True):
        # Access rich normalized data
        cadence_data = dataset_usage.extra_params.get('cadence', {})
        if isinstance(cadence_data, dict):
            cadence_value = cadence_data.get('value', 1.0)
            cadence_unit = cadence_data.get('unit', 'seconds')
            is_approximate = cadence_data.get('is_approximate', False)
            
            # Use in CDAWeb API call
            if cadence_unit == 'seconds':
                cadence_seconds = cadence_value
            elif cadence_unit == 'minutes':
                cadence_seconds = cadence_value * 60
            # ... generate appropriate query code
        
        # Access other normalized fields
        energy_data = dataset_usage.extra_params.get('energy_range', {})
        coord_data = dataset_usage.extra_params.get('coordinate_system', {})
        
        return f"""
        # Query with {cadence_value} {cadence_unit} cadence
        from cdasws import CdasWs
        
        cdas = CdasWs()
        # Use cadence_seconds, energy ranges, etc. in query
        """
```

### In API Serializers

Expose normalized data to frontend and external APIs:

```python
class DatasetUsageListSerializer(serializers.ModelSerializer):
    cadence_value = serializers.SerializerMethodField()
    cadence_unit = serializers.SerializerMethodField()
    energy_range = serializers.SerializerMethodField()
    
    def get_cadence_value(self, obj):
        cadence_data = obj.extra_params.get('cadence', {})
        return cadence_data.get('value') if isinstance(cadence_data, dict) else None
        
    def get_cadence_unit(self, obj):
        cadence_data = obj.extra_params.get('cadence', {})
        return cadence_data.get('unit') if isinstance(cadence_data, dict) else None
        
    def get_energy_range(self, obj):
        energy_data = obj.extra_params.get('energy_range', {})
        if isinstance(energy_data, dict):
            return {
                'min_energy': energy_data.get('min_value'),
                'max_energy': energy_data.get('max_value'),
                'unit': energy_data.get('unit')
            }
        return None
```

### In Frontend Components

Rich structured data is automatically available:

```javascript
// React component accessing normalized data
const DatasetCard = ({ datasetUsage }) => {
  const cadence = datasetUsage.extra_params.cadence;
  const energyRange = datasetUsage.extra_params.energy_range;
  
  return (
    <div>
      <h3>{datasetUsage.instrument_name}</h3>
      
      {cadence && (
        <div>
          <strong>Cadence:</strong> {cadence.value} {cadence.unit}
          {cadence.is_approximate && <span> (approximate)</span>}
        </div>
      )}
      
      {energyRange && (
        <div>
          <strong>Energy Range:</strong> 
          {energyRange.min_value} - {energyRange.max_value} {energyRange.unit}
        </div>
      )}
      
      {/* Access original text for debugging/provenance */}
      <small>Original: "{cadence?.original_text}"</small>
    </div>
  );
};
```

### In Custom Analyzers

Validate that generated scripts properly use normalized data:

```python
@DatasetUsageAnalyzerRegistry.register("CadenceValidation.cdaweb", data_sources=["cdaweb"])
class CDAWEBCadenceAnalyzer(BaseDatasetUsageAnalyzer):
    def analyze_snippet(self, dataset_usage, snippet: str) -> Dict[str, Any]:
        cadence_data = dataset_usage.extra_params.get('cadence', {})
        
        if cadence_data and isinstance(cadence_data, dict):
            expected_cadence = cadence_data.get('value')
            cadence_unit = cadence_data.get('unit')
            
            # Validate script mentions appropriate cadence
            script_mentions_cadence = str(expected_cadence) in snippet
            
            return {
                'cadence_properly_used': script_mentions_cadence,
                'expected_cadence_value': expected_cadence,
                'expected_cadence_unit': cadence_unit,
                'analysis_notes': f"Script should reference {expected_cadence} {cadence_unit} cadence"
            }
        
        return {'cadence_properly_used': True, 'analysis_notes': 'No cadence data to validate'}
```

### In Django Admin

Filter and display rich normalized data:

```python
# Custom admin filters
class CadenceUnitFilter(admin.SimpleListFilter):
    title = 'cadence unit'
    parameter_name = 'cadence_unit'
    
    def lookups(self, request, model_admin):
        return [
            ('seconds', 'Seconds'),
            ('minutes', 'Minutes'),
            ('hours', 'Hours'),
        ]
    
    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(extra_params__cadence__unit=self.value())

# Display normalized data in admin list
class DatasetUsageAdmin(admin.ModelAdmin):
    list_display = ['instrument', 'cadence_display', 'energy_range_display']
    list_filter = [CadenceUnitFilter]
    
    def cadence_display(self, obj):
        cadence = obj.extra_params.get('cadence', {})
        if cadence and isinstance(cadence, dict):
            return f"{cadence.get('value')} {cadence.get('unit')}"
        return "No cadence"
    
    def energy_range_display(self, obj):
        energy = obj.extra_params.get('energy_range', {})
        if energy and isinstance(energy, dict):
            return f"{energy.get('min_value')}-{energy.get('max_value')} {energy.get('unit')}"
        return "No energy range"
```

### Benefits of This Approach

1. **Type Safety**: Rich structured data with validation
2. **Provenance**: Original text preserved alongside parsed values  
3. **Flexibility**: Each component can access the data it needs
4. **Debugging**: Easy to trace from raw text → normalized data → usage
5. **Extensibility**: New normalizers automatically work everywhere
6. **Performance**: Efficient JSON field queries in database
7. **Frontend Ready**: Rich data available without additional API calls

## Testing Your Implementation

### Verify Normalizer Registration

Check that your normalizers are properly registered:

```python
from paper_data_linking.linkers.general.normalizers.normalizer_registry import NormalizerRegistry

# List all registered normalizers
print("All normalizers:", NormalizerRegistry.list())

# Check data source coverage
coverage = NormalizerRegistry.get_data_source_coverage()
print("CDAWeb normalizers:", coverage.get('cdaweb', []))

# Get specific normalizer for data source
cadence_normalizer = NormalizerRegistry.get_normalizer_for_data_source('cadence', 'cdaweb')
print("Cadence normalizer found:", cadence_normalizer is not None)
```

### Test Normalizer in Isolation

Create test cases for your normalizer logic:

```python
from paper_data_linking.linkers.general.normalizers.normalization_context import NormalizationContext

def test_cadence_normalizer():
    # Create mock context
    mock_period_data = MockPeriodData(cadence="1 minute sampling")
    context = NormalizationContext(
        period_data=mock_period_data,
        instrument_code="test_instrument",
        data_system="cdaweb",
        # ... other required fields
    )
    
    # Test normalizer
    normalizer = CadenceNormalizer()
    result = normalizer.normalize(context)
    
    assert result['value'] == 1.0
    assert result['unit'] == 'minutes'
    assert result['original_text'] == "1 minute sampling"
```

### Test Complete Workflow

Verify data flows correctly through the entire pipeline:

```python
# After running normalization on a paper
dataset_usage = DatasetUsage.objects.filter(
    extra_params__has_key='cadence'
).first()

# Check normalized data is stored correctly
cadence_data = dataset_usage.extra_params.get('cadence')
print("Stored cadence data:", cadence_data)

# Test script generator uses the data
from paper_data_linking.analyzers import DataSourceScriptGeneratorRegistry
generator = DataSourceScriptGeneratorRegistry.get_generator_for_data_source('cdaweb')
script = generator.generate_snippet(dataset_usage)
print("Generated script includes cadence:", str(cadence_data.get('value')) in script)
```

### Debug Common Issues

**Normalizer not running:**
- Check it's imported in `__init__.py`
- Verify data source matches in registration
- Ensure field exists in structured analysis schema

**Data not stored:**
- Check `InternalDataCollectionPeriod` has the field
- Verify normalizer returns proper dictionary format
- Look for errors in Celery logs during normalization

**Script generator can't access data:**
- Confirm `DatasetUsage.extra_params` contains expected structure
- Check field names match between normalizer and generator
- Verify proper JSON field access patterns

## Complete Example: Adding CDAWeb Support

Here's the minimal set of files needed for complete CDAWeb support:

### 1. Normalizer (Optional)
`paper_data_linking/linkers/general/normalizers/cadence_normalizer.py`

### 2. Script Generator (Required)
`paper_data_linking/analyzers/cdaweb_script_generator.py`

### 3. Analyzers (Optional)
`paper_data_linking/analyzers/cdaweb_analyzers.py` (already exists as stubs)

### 4. Registration Updates
- Add imports to `paper_data_linking/linkers/general/normalizers/__init__.py`
- Add imports to `paper_data_linking/analyzers/__init__.py`

### 5. Testing
- Unit tests for normalizers
- Integration tests for script generation
- End-to-end workflow tests

**Result**: Papers mentioning CDAWeb instruments will automatically:
1. Extract cadence/energy fields during structured analysis
2. Parse them into validated structured data via normalizers  
3. Store rich normalized data in database
4. Generate accurate CDAWeb queries via script generator
5. Validate results via custom analyzers

All with automatic API integration, frontend access, and database querying capabilities.