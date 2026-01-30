# Search Page Improvements

This document describes the improvements made to the search page to support flexible filtering across multiple models.

## Overview

The search page has been significantly enhanced to support:
1. **Multi-model searching** - Search across Pathogen, Host, Sequence, Descriptive, and FullText models
2. **Flexible filtering engine** - Automatically detects and generates appropriate filters for any model
3. **Dynamic UI** - Filter controls adapt based on selected model

## Key Changes

### 1. Backend Changes

#### `views.py` - UnifiedViewSet
- **Multi-model support**: Added `MODEL_CONFIG` dictionary mapping model names to their classes and configurations
- **Flexible filtering**: Implemented `_get_filterable_fields()` method that automatically detects filterable fields from any model
- **Filter type detection**: Automatically determines appropriate filter types:
  - Text fields → `icontains` filter
  - Numeric fields → range filter (supports `_from` and `_to` suffixes)
  - Date fields → range filter
  - Boolean fields → exact match
- **New API endpoints**:
  - `/api/unified/filters/?model=<model_name>` - Returns available filters for a model
  - `/api/unified/models/` - Returns list of available models
  - `/api/unified/columns/?model=<model_name>` - Returns columns (already existed, now model-aware)

#### `serializers.py` - AutoFlattenSerializer
- Changed from `ModelSerializer` to generic `Serializer`
- Now works dynamically with any model instance, not just Pathogen

### 2. Frontend Changes

#### `search.html` Template
- **Model selector**: Added dropdown to select which model to search
- **Dynamic filter loading**: Filters are now loaded via AJAX from `/api/unified/filters/`
- **Adaptive UI**: Filter controls are generated based on field types:
  - Text fields → text input
  - Number/Date fields → two inputs (From/To) for range filtering
  - Boolean fields → select dropdown (All/Yes/No)
- **Model-specific storage**: Column visibility preferences are stored per-model
- **Updated title**: Changed from "Pathogen Search" to "Unified Database Search"

### 3. Testing

#### `test_search.py`
- Comprehensive test suite covering:
  - Multi-model querying
  - Text filtering
  - Range filtering
  - Search functionality across models
  - API endpoints (`/filters/`, `/models/`, `/columns/`)
  - Nested field filtering
  - Search page rendering

## Usage

### For End Users

1. **Select a model**: Use the dropdown at the top to choose which data type to search (Pathogen, Host, Sequence, etc.)
2. **Apply filters**: The filter controls will automatically update based on your selection
3. **Search**: Use the global search box to search across all text fields
4. **Export**: Export filtered results to CSV

### For Developers

#### Adding a New Model

To add a new model to the search:

1. Add it to `MODEL_CONFIG` in `UnifiedViewSet`:
```python
MODEL_CONFIG = {
    'newmodel': {
        'model': NewModel,
        'select_related': ["foreign_key_field"],  # For performance
    },
    # ... other models
}
```

2. Add default visible columns in `search.html`:
```javascript
const defaultColumns = {
    newmodel: ['id', 'name', 'important_field'],
    // ... other models
};
```

That's it! The flexible filtering engine will automatically:
- Detect all filterable fields
- Generate appropriate filter types
- Create the UI controls
- Apply the filters to queries

## Technical Details

### Automatic Filter Detection

The `_get_filterable_fields()` method inspects a model's fields and:
1. Identifies field types (CharField, IntegerField, DateField, etc.)
2. Maps them to appropriate filter types
3. Follows foreign key relationships (up to 2 levels deep)
4. Returns structured filter definitions for the frontend

### Filter Application

The `_apply_filter()` method handles different filter types:
- **icontains**: Case-insensitive substring match
- **exact**: Exact match (for booleans)
- **range**: Applied via `_from` and `_to` suffixes in `get_queryset()`

### Performance Optimization

- Uses `select_related()` for each model to minimize database queries
- Limits filter depth to 2 levels to prevent excessive joins
- Limits UI to 8 most relevant filters per model
- Caches column definitions in localStorage

## Benefits

1. **Maintainability**: No need to manually define filters for each model
2. **Flexibility**: Easily add new models without frontend changes
3. **Consistency**: All models have the same intuitive interface
4. **Extensibility**: Filter detection can be enhanced without breaking existing functionality
5. **User Experience**: Users can now search across all data types from a single interface

## Future Enhancements

Possible future improvements:
- Add more filter types (e.g., multi-select for choice fields)
- Support for more complex queries (OR conditions, NOT conditions)
- Filter value auto-complete based on existing data
- Save and share filter presets
- Advanced date range pickers
- Geographic filtering for coordinate fields
