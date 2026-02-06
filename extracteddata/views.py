import json
import sys

import folium
import xyzservices.providers as xyz
from django.conf import settings
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.core.cache import cache
from django.db.models import CharField, Q, TextField
from django.http import HttpResponseForbidden, JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from folium.plugins import HeatMap
from rest_framework import filters, viewsets

from .forms import DataUploadForm
from .models import Descriptive, FullText, Host, Pathogen, Sequence
from .serializers import (
    DescriptiveSerializer,
    FullTextSerializer,
    HostSerializer,
    PathogenSerializer,
    SequenceSerializer,
)
from .utils.column_mappings import MODEL_MAP
from .utils.data_import import handle_csv_upload, handle_excel_upload
from .utils.logging import log_message


def _build_tiles_from_config():
    """Build tile layers from xyzservices providers defined in settings."""
    config = getattr(settings, "LEAFLET_CONFIG", {})
    provider_names = config.get("TILE_PROVIDERS", {})

    tiles = []
    for name, provider_path in provider_names.items():
        try:
            # Navigate the xyz object using the dot notation path
            provider = xyz
            for attr in provider_path.split("."):
                provider = getattr(provider, attr)

            tiles.append(
                {
                    "name": name,
                    "url": provider.build_url(),
                    "attribution": provider.get("attribution", ""),
                    "maxZoom": int(provider.get("max_zoom", 19)),
                }
            )
        except Exception as e:
            print(f"Error loading tile provider {name}: {e}", file=sys.stderr)

    return tiles


def get_map_config():
    """Returns map configuration from Django settings.
    This centralizes all map settings in Python instead of hardcoding in HTML/JS.
    """
    config = getattr(settings, "LEAFLET_CONFIG", {})
    return {
        "center": config.get("DEFAULT_CENTER", [20, 0]),
        "zoom": config.get("DEFAULT_ZOOM", 2),
        "minZoom": config.get("MIN_ZOOM", 2),
        "maxZoom": config.get("MAX_ZOOM", 18),
        "tiles": _build_tiles_from_config(),
        "clusterOptions": config.get("CLUSTER_OPTIONS", {}),
        "markerStyle": config.get("MARKER_STYLE", {}),
    }


class FullTextViewSet(viewsets.ModelViewSet):
    queryset = FullText.objects.all()
    serializer_class = FullTextSerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["title", "author", "decision"]
    ordering_fields = ["publication_year", "author"]


class DescriptiveViewSet(viewsets.ModelViewSet):
    queryset = Descriptive.objects.all()
    serializer_class = DescriptiveSerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["dataset_name"]
    ordering_fields = ["dataset_name"]


class HostViewSet(viewsets.ModelViewSet):
    queryset = Host.objects.all()
    serializer_class = HostSerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["scientific_name", "locality", "country"]
    ordering_fields = ["scientific_name", "individual_count"]


class PathogenViewSet(viewsets.ModelViewSet):
    queryset = Pathogen.objects.all()
    serializer_class = PathogenSerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["scientific_name", "family", "assay"]
    ordering_fields = ["tested", "positive"]


class SequenceViewSet(viewsets.ModelViewSet):
    queryset = Sequence.objects.all()
    serializer_class = SequenceSerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["scientific_name", "accession_number"]
    ordering_fields = ["date_sampled"]


def index(request):
    # Provide counts for the front-page feature cards
    descriptive_count = Descriptive.objects.count()
    host_count = Host.objects.count()
    pathogen_count = Pathogen.objects.count()
    sequence_count = Sequence.objects.count()

    # Check cache first (cache for 1 hour)
    cache_key = "home_host_heatmap_html"
    host_map_html = cache.get(cache_key)

    if host_map_html is None:
        print("Generating Folium heatmap", file=sys.stderr)

        # Create heatmap for host locations
        hosts = Host.objects.filter(
            location_latitude__isnull=False, location_longitude__isnull=False
        ).values("location_latitude", "location_longitude", "individual_count")

        # Build heatmap data with individual_count as weight
        heat_data = []
        for host in hosts:
            lat = float(host["location_latitude"])
            lng = float(host["location_longitude"])
            weight = float(host["individual_count"] or 1)
            heat_data.append([lat, lng, weight])

        # Create Folium map
        host_map = folium.Map(
            location=[20, 0],
            zoom_start=2,
            tiles="Esri WorldImagery",
            max_zoom=6,
            min_zoom=2,
            zoom_control=False,
            scrollWheelZoom=False,
            dragging=False,
            doubleClickZoom=False,
            boxZoom=False,
            keyboard=False,
            attributionControl=False,
        )

        # Add heatmap layer
        if heat_data:
            HeatMap(heat_data, radius=18, blur=15, max_zoom=6, min_opacity=0.25).add_to(
                host_map
            )

        # Get map HTML and cache it
        host_map_html = host_map._repr_html_()
        cache.set(cache_key, host_map_html, 43200)  # Cache for 12 hours
        print("Heatmap cached", file=sys.stderr)

    return render(
        request,
        "index.html",
        {
            "descriptive_count": descriptive_count,
            "host_count": host_count,
            "pathogen_count": pathogen_count,
            "sequence_count": sequence_count,
            "host_map": host_map_html,
        },
    )


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
    if request.method == "POST":
        form = DataUploadForm(request.POST, request.FILES)
        if form.is_valid():
            file_type = form.cleaned_data["file_type"]
            verbose = form.cleaned_data.get("log_verbose", True)

            def stream_processing():
                msg = log_message("Starting data upload...\n", verbose)
                if msg:
                    yield msg
                id_mapping = {
                    "inclusion_full_text": {},
                    "descriptive": {},
                    "host": {},
                    "pathogen": {},
                    "sequence": {},
                }
                try:
                    if file_type == "csv":
                        msg = log_message("Processing CSV files...\n", verbose)
                        if msg:
                            yield msg
                        for field_name, _ in MODEL_MAP.items():
                            file = form.cleaned_data.get(field_name)
                            if file:
                                # Check permission for this specific model before processing
                                required_perm = perm_map.get(field_name)
                                if required_perm and not request.user.has_perm(
                                    required_perm
                                ):
                                    msg = log_message(
                                        f"Skipping {field_name} - insufficient permission.\n",
                                        verbose,
                                    )
                                    if msg:
                                        yield msg
                                    continue

                                msg = log_message(
                                    f"Processing CSV for: {field_name}\n", verbose
                                )
                                if msg:
                                    yield msg
                                for log in handle_csv_upload(
                                    file, field_name, id_mapping, verbose
                                ):
                                    if log:
                                        yield log + "\n"

                    elif file_type == "excel":
                        excel_file = form.cleaned_data["excel_file"]
                        msg = log_message(
                            f"Processing Excel file: {excel_file.name}\n", verbose
                        )
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

            return StreamingHttpResponse(stream_processing(), content_type="text/plain")
        else:
            # Form has validation errors - return them as plain text for the streaming response
            error_messages = []
            for _, errors in form.errors.items():
                for error in errors:
                    error_messages.append(f"Error: {error}\n")

            def stream_errors():
                yield from error_messages

            return StreamingHttpResponse(stream_errors(), content_type="text/plain")

    else:
        form = DataUploadForm()

    return render(request, "upload_data.html", {"form": form})


def register(request):
    if request.method == "POST":
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)  # Automatically log the user in after registering
            return redirect("/")  # Redirect to home or dashboard
    else:
        form = UserCreationForm()
    return render(request, "registration/register.html", {"form": form})


def fulltext_detail(request, pk):
    fulltext = get_object_or_404(FullText, pk=pk)
    # include related descriptives via related_name 'descriptive_records'
    descriptives = fulltext.descriptive_records.all()
    return render(
        request,
        "fulltext_detail.html",
        {"fulltext": fulltext, "descriptives": descriptives},
    )


def descriptive_detail(request, pk):
    descriptive = get_object_or_404(Descriptive, pk=pk)
    hosts = descriptive.rodents.all()
    sequences = descriptive.sequences.all()
    return render(
        request,
        "descriptive_detail.html",
        {"descriptive": descriptive, "hosts": hosts, "sequences": sequences},
    )


def host_detail(request, pk):
    host = get_object_or_404(Host, pk=pk)
    pathogens = host.pathogens.all()
    sequences = host.sequences.all()
    return render(
        request,
        "host_detail.html",
        {"host": host, "pathogens": pathogens, "sequences": sequences},
    )


def pathogen_detail(request, pk):
    pathogen = get_object_or_404(Pathogen, pk=pk)
    sequences = pathogen.sequences.all()
    return render(
        request, "pathogen_detail.html", {"pathogen": pathogen, "sequences": sequences}
    )


def sequence_detail(request, pk):
    sequence = get_object_or_404(Sequence, pk=pk)
    return render(request, "sequence_detail.html", {"sequence": sequence})


def _build_search_query(search_value, model, max_depth=2):
    """Build a search query that searches across all text fields in a model.
    Note: max_depth is 2 to match _get_filterable_fields for consistency.
    """

    def get_searchable_fields(model, prefix="", depth=0):
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
            elif hasattr(field, "related_model") and field.related_model:
                try:
                    related_fields = get_searchable_fields(
                        field.related_model, f"{field_name}__", depth + 1
                    )
                    fields.extend(related_fields)
                except Exception as e:
                    # Skip if there's an issue with the related model
                    print(
                        f"Could not traverse related field {field_name}: {e}",
                        file=sys.stderr,
                    )

        return fields

    # Get all searchable fields for the given model
    searchable_fields = get_searchable_fields(model)

    # Build Q objects
    q_objects = Q()
    for field_name in searchable_fields:
        q_objects |= Q(**{f"{field_name}__icontains": search_value})

    return q_objects


# API endpoint to return GeoJSON data for all hosts
def host_geojson_api(request):
    """Returns GeoJSON of all host locations for client-side rendering.
    Can handle 100k+ records efficiently.
    """
    # Check cache first (cache for 1 hour)
    cache_key = "host_geojson_data"
    geojson_data = cache.get(cache_key)

    if geojson_data is None:
        print("Generating GeoJSON from database", file=sys.stderr)

        # Get ALL hosts with coordinates
        hosts = Host.objects.filter(
            location_latitude__isnull=False, location_longitude__isnull=False
        ).values(
            "id",
            "location_latitude",
            "location_longitude",
            "scientific_name",
            "country",
            "individual_count",
            "event_date",
        )

        # Build GeoJSON features
        features = []
        for host in hosts:
            features.append(
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Point",
                        "coordinates": [
                            host["location_longitude"],
                            host["location_latitude"],
                        ],
                    },
                    "properties": {
                        "id": host["id"],
                        "name": host["scientific_name"] or "Unknown",
                        "country": host["country"] or "Unknown",
                        "count": host["individual_count"],
                        "date": str(host["event_date"])
                        if host["event_date"]
                        else "Unknown",
                    },
                }
            )

        geojson_data = {"type": "FeatureCollection", "features": features}

        # Cache for 1 hour
        cache.set(cache_key, geojson_data, 3600)
        print(f"GeoJSON cached with {len(features)} features", file=sys.stderr)

    return JsonResponse(geojson_data)


# Map view - renders client-side Leaflet map
def map(request):
    """Renders a Leaflet map that loads GeoJSON via AJAX.
    Can efficiently display 100k+ points using Canvas renderer.
    All map configuration is defined in Python (settings.py) and passed to template.
    """
    map_config = get_map_config()
    return render(
        request,
        "host_map.html",
        {"map_config": json.dumps(map_config), "data_endpoint": "/api/host-geojson/"},
    )
