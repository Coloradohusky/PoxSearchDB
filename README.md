# PoxSearch Database

A Django-based web application for managing and visualizing poxvirus research data, including host species information, pathogen testing results, and genetic sequence data.

**🌐 Access the application at: [https://poxsearch.onrender.com/](https://poxsearch.onrender.com/)**

## Overview

PoxSearch Database is designed to store, manage, and provide searchable access to scientific data related to poxvirus research. It supports hierarchical data relationships connecting full-text publications with descriptive datasets, host specimens, pathogen test results, and genetic sequences.

## Features

- **Data Management**: Import and manage scientific data from Excel files with automated validation
- **Hierarchical Data Model**: Link publications → datasets → hosts → pathogens → sequences
- **RESTful API**: Full API access to all data models with search and filtering capabilities
- **Geographic Visualization**: Interactive maps showing host specimen locations
- **Search Functionality**: Advanced search across all data types
- **Data Export**: Export data in CSV format for analysis
- **User Authentication**: Secure login system for data upload and management
- **GBIF Integration**: Automatic species name validation using the Global Biodiversity Information Facility (GBIF) API

## Data Models

### FullText
Publication metadata including title, author, publication year, and extraction decisions.

### Descriptive
Dataset-level information including sampling effort, data access, and resolution details.

### Host
Host specimen records with:
- Scientific names
- Geographic locations (with coordinates)
- Individual counts and trap effort
- Event dates and localities

### Pathogen
Pathogen testing results:
- Scientific names and taxonomic families
- Assay methods
- Test results (tested, positive, negative, inconclusive)

### Sequence
Genetic sequence information:
- GenBank accession numbers
- Sequence types (Host/Pathogen)
- Associated taxa
- Sampling dates and locations
- Sequencing methods

## Technology Stack

- **Backend**: Django 5.2.7
- **Database**: PostgreSQL with PostGIS (spatial data support)
- **Frontend**: Django templates with Leaflet.js for mapping
- **API**: Django REST Framework
- **Spatial Data**: GeoDjango with GDAL
- **Data Processing**: Pandas, NumPy, OpenPyXL
- **External APIs**: pygbif for species validation
- **Deployment**: Docker, Gunicorn, WhiteNoise

## Getting Started

### Accessing the Application

Visit [https://poxsearch.onrender.com/](https://poxsearch.onrender.com/) to access the live application.

### User Accounts

- Browse public data without authentication
- Contact administrators for upload access credentials

## Usage

### Data Import

1. Navigate to `/upload/` (requires authentication)
2. Upload an Excel file with the following sheets:
   - `FullText` - Publication information
   - `Descriptive` - Dataset metadata
   - `Host` or `Rodent` - Host specimen data
   - `Pathogen` - Pathogen testing results
   - `Sequence` - Genetic sequence data

The system automatically:
- Validates column names using aliases
- Checks relationships between records
- Validates species names via GBIF
- Creates linked records across tables

### API Endpoints

Base URL: `https://poxsearch.onrender.com/api/`

- `/api/fulltext/` - Publication records
- `/api/descriptive/` - Dataset records
- `/api/host/` - Host specimen records
- `/api/pathogen/` - Pathogen test records
- `/api/sequence/` - Sequence records

API features:
- Search: `?search=query`
- Ordering: `?ordering=field_name`
- Filtering by field values
- CSV export: `/api/model/export_csv/`

### Search

Navigate to `/search/` to:
- Search across all data types
- Filter by model type
- View detailed records
- Export results

### Maps

- `/map/` - View all host locations on an interactive map
- Individual host detail pages include location maps

## Project Structure

```
PoxSearchDB/
├── extracteddata/          # Main Django app
│   ├── models.py           # Data models
│   ├── views.py            # Views and API viewsets
│   ├── serializers.py      # REST API serializers
│   ├── forms.py            # Form definitions
│   ├── urls.py             # URL routing
│   ├── templates/          # HTML templates
│   ├── utils/              # Utility modules
│   │   ├── data_import.py  # Excel import logic
│   │   ├── column_mappings.py  # Column aliases
│   │   └── logging.py      # Logging utilities
│   └── tests/              # Test suite
├── PoxSearchDB/            # Project settings
│   ├── settings.py
│   ├── urls.py
│   └── wsgi.py
├── static/                 # Static files
├── staticfiles/            # Collected static files
├── Dockerfile              # Docker configuration
├── entrypoint.sh           # Docker entrypoint
├── requirements.txt        # Python dependencies
└── manage.py               # Django management script
```

## Architecture

Key settings in `settings.py`:
- `DEBUG`: Enable/disable debug mode
- `ALLOWED_HOSTS`: Permitted hostnames
- `DATABASES`: Database configuration
- `GDAL_LIBRARY_PATH`: Path to GDAL libraries (for spatial operations)

## Contact

For questions, access requests, or collaboration inquiries, please [add contact information here].

## Acknowledgments

- GBIF (Global Biodiversity Information Facility) for species validation
- Django and Django REST Framework communities
- PostGIS for spatial database capabilities