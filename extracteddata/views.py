from rest_framework import viewsets, filters
from .forms import DataUploadForm
from django.http import StreamingHttpResponse
from .serializers import (
    FullTextSerializer, DescriptiveSerializer, HostSerializer,
    PathogenSerializer, SequenceSerializer
)
from .utils.data_import import *
from .utils.logging import log_message
from django.shortcuts import render, redirect
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth import login
from rest_framework.decorators import action
from django.http import HttpResponse, JsonResponse
import csv
from .models import Pathogen, Sequence, FullText, Descriptive, Host
from django.shortcuts import get_object_or_404
from .serializers import AutoFlattenSerializer
from .utils.column_mappings import MODEL_MAP
from django.db.models import Q, CharField, TextField
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
import sys
from django.core.cache import cache
import folium
from folium.plugins import HeatMap
import json
from django.conf import settings
import xyzservices.providers as xyz


def _build_tiles_from_config():
    """
    Build tile layers from xyzservices providers defined in settings.
    """
    config = getattr(settings, 'LEAFLET_CONFIG', {})
    provider_names = config.get('TILE_PROVIDERS', {})
    
    tiles = []
    for name, provider_path in provider_names.items():
        try:
            # Navigate the xyz object using the dot notation path
            provider = xyz
            for attr in provider_path.split('.'):
                provider = getattr(provider, attr)
            
            tiles.append({
                'name': name,
                'url': provider.build_url(),
                'attribution': provider.get('attribution', ''),
                'maxZoom': int(provider.get('max_zoom', 19)),
            })
        except Exception as e:
            print(f"Error loading tile provider {name}: {e}", file=sys.stderr)
    
    return tiles


def get_map_config():
    """
    Returns map configuration from Django settings.
    This centralizes all map settings in Python instead of hardcoding in HTML/JS.
    """
    config = getattr(settings, 'LEAFLET_CONFIG', {})
    return {
        'center': config.get('DEFAULT_CENTER', [20, 0]),
        'zoom': config.get('DEFAULT_ZOOM', 2),
        'minZoom': config.get('MIN_ZOOM', 2),
        'maxZoom': config.get('MAX_ZOOM', 18),
        'tiles': _build_tiles_from_config(),
        'clusterOptions': config.get('CLUSTER_OPTIONS', {}),
        'markerStyle': config.get('MARKER_STYLE', {})
    }


class FullTextViewSet(viewsets.ModelViewSet):
    queryset = FullText.objects.all()
    serializer_class = FullTextSerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['title', 'author', 'decision']
    ordering_fields = ['publication_year', 'author']

class DescriptiveViewSet(viewsets.ModelViewSet):
    queryset = Descriptive.objects.all()
    serializer_class = DescriptiveSerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['dataset_name']
    ordering_fields = ['dataset_name']

class HostViewSet(viewsets.ModelViewSet):
    queryset = Host.objects.all()
    serializer_class = HostSerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['scientific_name', 'locality', 'country']
    ordering_fields = ['scientific_name', 'individual_count']

class PathogenViewSet(viewsets.ModelViewSet):
    queryset = Pathogen.objects.all()
    serializer_class = PathogenSerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['scientific_name', 'family', 'assay']
    ordering_fields = ['tested', 'positive']

class SequenceViewSet(viewsets.ModelViewSet):
    queryset = Sequence.objects.all()
    serializer_class = SequenceSerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['scientific_name', 'accession_number']
    ordering_fields = ['date_sampled']

def index(request):
    # Provide counts for the front-page feature cards
    descriptive_count = Descriptive.objects.count()
    host_count = Host.objects.count()
    pathogen_count = Pathogen.objects.count()
    sequence_count = Sequence.objects.count()
    
    # Check cache first (cache for 1 hour)
    cache_key = 'home_host_heatmap_html'
    host_map_html = cache.get(cache_key)
    
    if host_map_html is None:
        print("Generating Folium heatmap", file=sys.stderr)
        
        # Create heatmap for host locations
        hosts = Host.objects.filter(
            location_latitude__isnull=False,
            location_longitude__isnull=False
        ).values('location_latitude', 'location_longitude', 'individual_count')
        
        # Build heatmap data with individual_count as weight
        heat_data = []
        for host in hosts:
            lat = float(host['location_latitude'])
            lng = float(host['location_longitude'])
            weight = float(host['individual_count'] or 1)
            heat_data.append([lat, lng, weight])
        
        # Create Folium map
        host_map = folium.Map(
            location=[20, 0],
            zoom_start=2,
            tiles='Esri WorldImagery',
            max_zoom=6,
            min_zoom=2,
            zoom_control=False,
            scrollWheelZoom=False,
            dragging=False,
            doubleClickZoom=False,
            boxZoom=False,
            keyboard=False,
            attributionControl=False
        )
        
        # Add heatmap layer
        if heat_data:
            HeatMap(
                heat_data,
                radius=18,
                blur=15,
                max_zoom=6,
                min_opacity=0.25
            ).add_to(host_map)
        
        # Get map HTML and cache it
        host_map_html = host_map._repr_html_()
        cache.set(cache_key, host_map_html, 43200)  # Cache for 12 hours
        print(f"Heatmap cached", file=sys.stderr)
    
    return render(request, "index.html", {
        'descriptive_count': descriptive_count,
        'host_count': host_count,
        'pathogen_count': pathogen_count,
        'sequence_count': sequence_count,
        'host_map': host_map_html,
    })

def search_view(request):
    return render(request, "search.html")

@login_required
def upload_data(request):
    # Permission map for each upload field -> required add permission
    perm_map = {
        "inclusion_full_text": "extracteddata.add_fulltext",
        "descriptive": "extracteddata.add_descriptive",
        "host": "extracteddata.add_host",
        "pathogen": "extracteddata.add_pathogen",
        "sequence": "extracteddata.add_sequence",
    }

    # Deny access if the user does not have any add permissions for these models
    if not any(request.user.has_perm(p) for p in perm_map.values()):
        return HttpResponseForbidden("You do not have permission to upload data.")
    if request.method == 'POST':
        form = DataUploadForm(request.POST, request.FILES)
        if form.is_valid():
            file_type = form.cleaned_data['file_type']
            verbose = form.cleaned_data.get('log_verbose', True)

            def stream_processing():
                msg = log_message("Starting data upload...\n", verbose)
                if msg:
                    yield msg
                id_mapping = {
                    "inclusion_full_text": {},
                    "descriptive": {},
                    "host": {},
                    "pathogen": {},
                    "sequence": {}
                }
                try:
                    if file_type == 'csv':
                        msg = log_message("Processing CSV files...\n", verbose)
                        if msg:
                            yield msg
                        for field_name, model_class in MODEL_MAP.items():
                            file = form.cleaned_data.get(field_name)
                            if file:
                                # Check permission for this specific model before processing
                                required_perm = perm_map.get(field_name)
                                if required_perm and not request.user.has_perm(required_perm):
                                    msg = log_message(f"Skipping {field_name} - insufficient permission.\n", verbose)
                                    if msg:
                                        yield msg
                                    continue

                                msg = log_message(f"Processing CSV for: {field_name}\n", verbose)
                                if msg:
                                    yield msg
                                for log in handle_csv_upload(file, field_name, id_mapping, verbose):
                                    if log:
                                        yield log + "\n"

                    elif file_type == 'excel':
                        excel_file = form.cleaned_data['excel_file']
                        msg = log_message(f"Processing Excel file: {excel_file.name}\n", verbose)
                        if msg:
                            yield msg
                        for log in handle_excel_upload(excel_file, id_mapping, verbose):
                            if log:
                                yield log + "\n"

                    msg = log_message("Data upload completed successfully!\n", verbose)
                    if msg:
                        yield msg

                except Exception as e:
                    msg = log_message(f"Error during upload: {str(e)}\n", verbose)
                    if msg:
                        yield msg

            return StreamingHttpResponse(stream_processing(), content_type='text/plain')
        else:
            # Form has validation errors - return them as plain text for the streaming response
            error_messages = []
            for field, errors in form.errors.items():
                for error in errors:
                    error_messages.append(f"Error: {error}\n")
            
            def stream_errors():
                for error in error_messages:
                    yield error
            
            return StreamingHttpResponse(stream_errors(), content_type='text/plain')

    else:
        form = DataUploadForm()

    return render(request, 'upload_data.html', {'form': form})

def register(request):
    if request.method == 'POST':
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)  # Automatically log the user in after registering
            return redirect('/')  # Redirect to home or dashboard
    else:
        form = UserCreationForm()
    return render(request, 'registration/register.html', {'form': form})


def fulltext_detail(request, pk):
    fulltext = get_object_or_404(FullText, pk=pk)
    # include related descriptives via related_name 'descriptive_records'
    descriptives = fulltext.descriptive_records.all()
    return render(request, 'fulltext_detail.html', {'fulltext': fulltext, 'descriptives': descriptives})


def descriptive_detail(request, pk):
    descriptive = get_object_or_404(Descriptive, pk=pk)
    hosts = descriptive.rodents.all()
    sequences = descriptive.sequences.all()
    return render(request, 'descriptive_detail.html', {'descriptive': descriptive, 'hosts': hosts, 'sequences': sequences})


def host_detail(request, pk):
    host = get_object_or_404(Host, pk=pk)
    pathogens = host.pathogens.all()
    sequences = host.sequences.all()
    return render(request, 'host_detail.html', {'host': host, 'pathogens': pathogens, 'sequences': sequences})


def pathogen_detail(request, pk):
    pathogen = get_object_or_404(Pathogen, pk=pk)
    sequences = pathogen.sequences.all()
    return render(request, 'pathogen_detail.html', {'pathogen': pathogen, 'sequences': sequences})


def sequence_detail(request, pk):
    sequence = get_object_or_404(Sequence, pk=pk)
    return render(request, 'sequence_detail.html', {'sequence': sequence})

def _build_search_query(search_value, model, max_depth=2):
    """
    Build a search query that searches across all text fields in a model.
    Note: max_depth is 2 to match _get_filterable_fields for consistency.
    """
    def get_searchable_fields(model, prefix='', depth=0):
        if depth > max_depth:
            return []

        fields = []
        for field in model._meta.get_fields():
            # Skip reverse relationships and many-to-many
            if field.one_to_many or field.many_to_many:
                continue

            field_name = f"{prefix}{field.name}"

            # Add text fields
            if isinstance(field, (CharField, TextField)):
                fields.append(field_name)

            # Follow foreign keys
            elif hasattr(field, 'related_model') and field.related_model:
                try:
                    related_fields = get_searchable_fields(
                        field.related_model,
                        f"{field_name}__",
                        depth + 1
                    )
                    fields.extend(related_fields)
                except Exception as e:
                    # Skip if there's an issue with the related model
                    print(f"Could not traverse related field {field_name}: {e}", file=sys.stderr)

        return fields

    # Get all searchable fields for the given model
    searchable_fields = get_searchable_fields(model)

    # Build Q objects
    q_objects = Q()
    for field_name in searchable_fields:
        q_objects |= Q(**{f"{field_name}__icontains": search_value})

    return q_objects

class UnifiedViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = AutoFlattenSerializer
    filter_backends = [filters.OrderingFilter]
    ordering_fields = '__all__'
    
    # Map of model names to their classes and select_related configs
    MODEL_CONFIG = {
        'pathogen': {
            'model': Pathogen,
            'select_related': ["host", "host__study", "host__study__full_text"],
        },
        'host': {
            'model': Host,
            'select_related': ["study", "study__full_text"],
        },
        'sequence': {
            'model': Sequence,
            'select_related': ["pathogen", "host", "study"],
        },
        'descriptive': {
            'model': Descriptive,
            'select_related': ["full_text"],
        },
        'fulltext': {
            'model': FullText,
            'select_related': [],
        },
    }

    def _get_filterable_fields(self, model, max_depth=2):
        """
        Automatically detect filterable fields from a model.
        Returns a list of field definitions with metadata for UI generation.
        """
        from django.db import models as django_models
        
        fields = []
        
        def add_field(field, prefix='', depth=0):
            if depth > max_depth:
                return
            
            field_name = f"{prefix}{field.name}"
            field_type = type(field).__name__
            
            # Generate label with > separator for nested fields (matching columns function)
            field_label = field_name.replace('__', ' > ').replace('_', ' ').title()
            
            # Determine filter configuration based on field type
            filter_config = None
            
            # Text fields
            if isinstance(field, (django_models.CharField, django_models.TextField)):
                filter_config = {
                    'name': field_name,
                    'label': field_label,
                    'type': 'text',
                    'filter_type': 'icontains',
                }
            
            # Numeric fields
            elif isinstance(field, (django_models.IntegerField, django_models.FloatField, 
                                   django_models.DecimalField, django_models.PositiveIntegerField)):
                filter_config = {
                    'name': field_name,
                    'label': field_label,
                    'type': 'number',
                    'filter_type': 'range',  # Supports __gte and __lte
                }
            
            # Date fields
            elif isinstance(field, (django_models.DateField, django_models.DateTimeField)):
                filter_config = {
                    'name': field_name,
                    'label': field_label,
                    'type': 'date',
                    'filter_type': 'range',  # Supports __gte and __lte
                }
            
            # Boolean fields
            elif isinstance(field, django_models.BooleanField):
                filter_config = {
                    'name': field_name,
                    'label': field_label,
                    'type': 'boolean',
                    'filter_type': 'exact',
                }
            
            if filter_config:
                fields.append(filter_config)
            
            # Follow foreign keys to add related fields
            if hasattr(field, 'related_model') and field.related_model and depth < max_depth:
                try:
                    for related_field in field.related_model._meta.get_fields():
                        if not (related_field.one_to_many or related_field.many_to_many):
                            add_field(related_field, f"{field_name}__", depth + 1)
                except Exception as e:
                    # Skip if there's an issue with the related model
                    print(f"Could not traverse related field {field_name}: {e}", file=sys.stderr)
        
        # Process all model fields
        for field in model._meta.get_fields():
            if not (field.one_to_many or field.many_to_many):
                add_field(field)
        
        return fields

    def _apply_filter(self, queryset, field_config, value):
        """
        Apply a filter to the queryset based on field configuration.
        """
        field_name = field_config['name']
        filter_type = field_config['filter_type']
        
        if filter_type == 'icontains':
            return queryset.filter(**{f"{field_name}__icontains": value})
        elif filter_type == 'exact':
            # Handle boolean conversion
            if field_config['type'] == 'boolean':
                bool_value = value.lower() in ('true', '1', 'yes', 't', 'y')
                return queryset.filter(**{field_name: bool_value})
            return queryset.filter(**{field_name: value})
        # Note: range filters are handled in get_queryset() via _from and _to suffixes
        
        return queryset

    def get_queryset(self):
        params = self.request.query_params
        
        # Get the selected model (default to pathogen for backwards compatibility)
        model_name = params.get('model', 'pathogen').lower()
        
        # Validate model name
        if model_name not in self.MODEL_CONFIG:
            model_name = 'pathogen'  # Fallback to default
        
        config = self.MODEL_CONFIG[model_name]
        
        # Get the model class and build queryset
        model_class = config['model']
        queryset = model_class.objects.all()
        
        # Apply select_related for performance
        if config['select_related']:
            queryset = queryset.select_related(*config['select_related'])
        
        # Handle search programmatically
        search_value = params.get('search')
        if search_value:
            search_query = _build_search_query(search_value, model_class)
            queryset = queryset.filter(search_query)
        
        # Apply dynamic filters based on filterable fields
        filterable_fields = self._get_filterable_fields(model_class)
        for field_config in filterable_fields:
            field_name = field_config['name']
            
            # Handle range filters (e.g., year_from, year_to)
            if field_config['filter_type'] == 'range':
                # Check for _from suffix
                from_value = params.get(f"{field_name}_from")
                if from_value:
                    try:
                        queryset = queryset.filter(**{f"{field_name}__gte": from_value})
                    except (ValueError, TypeError) as e:
                        # Invalid value for range filter, skip it
                        print(f"Invalid range filter value for {field_name}_from: {e}", file=sys.stderr)
                
                # Check for _to suffix
                to_value = params.get(f"{field_name}_to")
                if to_value:
                    try:
                        queryset = queryset.filter(**{f"{field_name}__lte": to_value})
                    except (ValueError, TypeError) as e:
                        # Invalid value for range filter, skip it
                        print(f"Invalid range filter value for {field_name}_to: {e}", file=sys.stderr)
            else:
                # Handle direct filters
                param_value = params.get(field_name)
                if param_value:
                    try:
                        queryset = self._apply_filter(queryset, field_config, param_value)
                    except (ValueError, TypeError) as e:
                        # Invalid filter value, skip it
                        print(f"Invalid filter value for {field_name}: {e}", file=sys.stderr)
        
        # Handle ordering
        ordering = params.get('ordering')
        if ordering:
            try:
                queryset = queryset.order_by(ordering)
            except Exception as e:
                # Invalid ordering field, skip it
                print(f"Invalid ordering field {ordering}: {e}", file=sys.stderr)
            
        return queryset

    @action(detail=False, methods=["get"])
    def columns(self, request):
        """Return available columns from the serializer"""
        sample_obj = self.get_queryset().first()
        if not sample_obj:
            return JsonResponse({"columns": []})
            
        sample_data = self.get_serializer(sample_obj).data
        columns = [
            {"data": key, "title": key.replace('__', ' > ').replace('_', ' ').title()}
            for key in sample_data.keys()
        ]
        return JsonResponse({"columns": columns})
    
    @action(detail=False, methods=["get"])
    def models(self, request):
        """Return available model types for filtering"""
        models = [
            {"value": key, "label": key.replace('_', ' ').title()}
            for key in self.MODEL_CONFIG.keys()
        ]
        return JsonResponse({"models": models})
    
    @action(detail=False, methods=["get"])
    def filters(self, request):
        """Return available filters for the selected model"""
        model_name = request.query_params.get('model', 'pathogen').lower()
        config = self.MODEL_CONFIG.get(model_name, self.MODEL_CONFIG['pathogen'])
        model_class = config['model']
        
        filterable_fields = self._get_filterable_fields(model_class)
        return JsonResponse({"filters": filterable_fields})

    @action(detail=False, methods=["get"])
    def export(self, request):
        queryset = self.filter_queryset(self.get_queryset())
        
        # Get requested columns from query params
        columns_param = request.query_params.get('columns', '')
        requested_columns = [col.strip() for col in columns_param.split(',') if col.strip()]
        
        # Serialize all rows
        rows = [self.get_serializer(obj).data for obj in queryset]
        if not rows:
            return HttpResponse("No data", content_type="text/plain")

        # Filter to only requested columns if specified
        if requested_columns:
            filtered_rows = []
            for row in rows:
                filtered_row = {key: value for key, value in row.items() if key in requested_columns}
                filtered_rows.append(filtered_row)
            rows = filtered_rows
            fieldnames = requested_columns
        else:
            fieldnames = rows[0].keys()

        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="results.csv"'
        writer = csv.DictWriter(response, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
        return response

# API endpoint to return GeoJSON data for all hosts
def host_geojson_api(request):
    """
    Returns GeoJSON of all host locations for client-side rendering.
    Can handle 100k+ records efficiently.
    """
    # Check cache first (cache for 1 hour)
    cache_key = 'host_geojson_data'
    geojson_data = cache.get(cache_key)
    
    if geojson_data is None:
        print("Generating GeoJSON from database", file=sys.stderr)
        
        # Get ALL hosts with coordinates
        hosts = Host.objects.filter(
            location_latitude__isnull=False,
            location_longitude__isnull=False
        ).values(
            'id', 'location_latitude', 'location_longitude', 
            'scientific_name', 'country', 'individual_count', 'event_date'
        )

        # Build GeoJSON features
        features = []
        for host in hosts:
            features.append({
                'type': 'Feature',
                'geometry': {
                    'type': 'Point',
                    'coordinates': [host['location_longitude'], host['location_latitude']]
                },
                'properties': {
                    'id': host['id'],
                    'name': host['scientific_name'] or 'Unknown',
                    'country': host['country'] or 'Unknown',
                    'count': host['individual_count'],
                    'date': str(host['event_date']) if host['event_date'] else 'Unknown',
                }
            })

        geojson_data = {
            'type': 'FeatureCollection',
            'features': features
        }
        
        # Cache for 1 hour
        cache.set(cache_key, geojson_data, 3600)
        print(f"GeoJSON cached with {len(features)} features", file=sys.stderr)
    
    return JsonResponse(geojson_data)


# Map view - renders client-side Leaflet map
def map(request):
    """
    Renders a Leaflet map that loads GeoJSON via AJAX.
    Can efficiently display 100k+ points using Canvas renderer.
    All map configuration is defined in Python (settings.py) and passed to template.
    """
    map_config = get_map_config()
    return render(request, 'host_map.html', {
        'map_config': json.dumps(map_config),
        'data_endpoint': '/api/host-geojson/'
    })

