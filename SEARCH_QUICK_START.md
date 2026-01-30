# Search Page Enhancement - Quick Start Guide

## What Changed

The search page (`/search/`) has been significantly enhanced to support **flexible multi-model searching** with **automatic filter generation**.

## Quick Usage

### 1. Select a Data Type
At the top of the search page, use the dropdown to select which type of data you want to search:
- **Pathogen** - Pathogen testing results
- **Host** - Host/rodent specimen records
- **Sequence** - Genetic sequence data
- **Descriptive** - Dataset metadata
- **Full Text** - Publication information

### 2. Use Filters
The filter controls will automatically update based on your selection:
- **Text filters** - Type to search (case-insensitive)
- **Number/Date range filters** - Use "From" and "To" fields
- **Boolean filters** - Select Yes/No/All from dropdown

### 3. Search
Use the main search box to search across all text fields in the selected model.

### 4. Export
Click "Export to CSV" to download filtered results.

## Key Features

### ✨ Multi-Model Support
Search across all 5 data types from a single interface.

### 🔍 Smart Filtering
Filters automatically adapt to the selected model:
- Detects field types (text, number, date, boolean)
- Generates appropriate filter controls
- Supports nested field filtering (e.g., searching pathogen by host country)

### 💾 Remember Your Preferences
Column visibility settings are saved per model in your browser.

### 🚀 Performance Optimized
- Efficient database queries with relationship prefetching
- Server-side pagination for large datasets
- Smart caching of filter configurations

## API Endpoints

### Get Available Filters
```
GET /api/unified/filters/?model=pathogen
```
Returns filter definitions for the specified model.

### Get Available Models
```
GET /api/unified/models/
```
Returns list of searchable models.

### Query Data
```
GET /api/unified/?model=host&country=United%20States&search=mouse
```
Query with model selection, filters, and search term.

## Developer Notes

### Adding a New Model
Add to `MODEL_CONFIG` in `extracteddata/views.py`:
```python
MODEL_CONFIG = {
    'yourmodel': {
        'model': YourModel,
        'select_related': ['foreign_key_field'],
    },
}
```

The system will automatically:
- Detect filterable fields
- Generate appropriate UI controls
- Handle filtering logic

### Supported Filter Types
- **Text** (CharField, TextField) → icontains filter
- **Number** (IntegerField, FloatField, etc.) → range filter (gte/lte)
- **Date** (DateField, DateTimeField) → range filter (gte/lte)
- **Boolean** (BooleanField) → exact match

## Files Modified

1. `extracteddata/views.py` - Backend filtering engine
2. `extracteddata/serializers.py` - Model-agnostic serializer
3. `extracteddata/templates/search.html` - Dynamic UI
4. Documentation files (SEARCH_IMPROVEMENTS.md, IMPLEMENTATION_SUMMARY.md)

## Technical Details

See `SEARCH_IMPROVEMENTS.md` for detailed technical documentation and `IMPLEMENTATION_SUMMARY.md` for a complete summary of changes.

## Security

✅ **CodeQL Scan**: Passed - No security vulnerabilities detected
✅ **Input Validation**: Model names validated before use
✅ **Error Handling**: Specific exception handling with logging
✅ **SQL Injection**: Protected by Django ORM

## Support

For issues or questions about the search functionality, refer to the detailed documentation files or contact the development team.
