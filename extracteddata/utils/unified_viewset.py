import csv
import sys

from django.db.models import CharField, Q, TextField
from django.http import JsonResponse, StreamingHttpResponse
from rest_framework import filters, viewsets
from rest_framework.decorators import action

from extracteddata.models import Descriptive, FullText, Host, Pathogen, Sequence
from extracteddata.serializers import AutoFlattenSerializer


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


class UnifiedViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = AutoFlattenSerializer
    filter_backends = [filters.OrderingFilter]
    ordering_fields = "__all__"

    # Map of model names to their classes and select_related configs
    MODEL_CONFIG = {
        "pathogen": {
            "model": Pathogen,
            "select_related": ["host", "host__study", "host__study__full_text"],
        },
        "host": {
            "model": Host,
            "select_related": ["study", "study__full_text"],
        },
        "sequence": {
            "model": Sequence,
            "select_related": ["pathogen", "host", "study"],
        },
        "descriptive": {
            "model": Descriptive,
            "select_related": ["full_text"],
        },
        "fulltext": {
            "model": FullText,
            "select_related": [],
        },
    }

    def _get_filterable_fields(self, model, max_depth=2):
        """Automatically detect filterable fields from a model.
        Returns a list of field definitions with metadata for UI generation.
        """
        from django.db import models as django_models

        fields = []

        def add_field(field, prefix="", depth=0):
            if depth > max_depth:
                return

            field_name = f"{prefix}{field.name}"

            # Generate label with > separator for nested fields (matching columns function)
            field_label = field_name.replace("__", " > ").replace("_", " ").title()

            # Determine filter configuration based on field type
            filter_config = None

            # Text fields
            if isinstance(field, (django_models.CharField, django_models.TextField)):
                filter_config = {
                    "name": field_name,
                    "label": field_label,
                    "type": "text",
                    "filter_type": "icontains",
                }

            # Numeric fields
            elif isinstance(
                field,
                (
                    django_models.IntegerField,
                    django_models.FloatField,
                    django_models.DecimalField,
                    django_models.PositiveIntegerField,
                ),
            ):
                filter_config = {
                    "name": field_name,
                    "label": field_label,
                    "type": "number",
                    "filter_type": "range",  # Supports __gte and __lte
                }

            # Date fields
            elif isinstance(
                field, (django_models.DateField, django_models.DateTimeField)
            ):
                filter_config = {
                    "name": field_name,
                    "label": field_label,
                    "type": "date",
                    "filter_type": "range",  # Supports __gte and __lte
                }

            # Boolean fields
            elif isinstance(field, django_models.BooleanField):
                filter_config = {
                    "name": field_name,
                    "label": field_label,
                    "type": "boolean",
                    "filter_type": "exact",
                }

            if filter_config:
                fields.append(filter_config)

            # Follow foreign keys to add related fields
            if (
                hasattr(field, "related_model")
                and field.related_model
                and depth < max_depth
            ):
                try:
                    for related_field in field.related_model._meta.get_fields():
                        if not (
                            related_field.one_to_many or related_field.many_to_many
                        ):
                            add_field(related_field, f"{field_name}__", depth + 1)
                except Exception as e:
                    # Skip if there's an issue with the related model
                    print(
                        f"Could not traverse related field {field_name}: {e}",
                        file=sys.stderr,
                    )

        # Process all model fields
        for field in model._meta.get_fields():
            if not (field.one_to_many or field.many_to_many):
                add_field(field)

        return fields

    def _apply_filter(self, queryset, field_config, value):
        """Apply a filter to the queryset based on field configuration."""
        field_name = field_config["name"]
        filter_type = field_config["filter_type"]

        if filter_type == "icontains":
            return queryset.filter(**{f"{field_name}__icontains": value})
        elif filter_type == "exact":
            # Handle boolean conversion
            if field_config["type"] == "boolean":
                bool_value = value.lower() in ("true", "1", "yes", "t", "y")
                return queryset.filter(**{field_name: bool_value})
            return queryset.filter(**{field_name: value})
        # Note: range filters are handled in get_queryset() via _from and _to suffixes

        return queryset

    def get_queryset(self):
        params = self.request.query_params

        # Get the selected model (default to pathogen for backwards compatibility)
        model_name = params.get("model", "pathogen").lower()

        # Validate model name
        if model_name not in self.MODEL_CONFIG:
            model_name = "pathogen"  # Fallback to default

        config = self.MODEL_CONFIG[model_name]

        # Get the model class and build queryset
        model_class = config["model"]
        queryset = model_class.objects.all()

        # Apply select_related for performance
        if config["select_related"]:
            queryset = queryset.select_related(*config["select_related"])

        # Handle search programmatically
        search_value = params.get("search")
        if search_value:
            search_query = _build_search_query(search_value, model_class)
            queryset = queryset.filter(search_query)

        # Apply dynamic filters based on filterable fields
        filterable_fields = self._get_filterable_fields(model_class)
        for field_config in filterable_fields:
            field_name = field_config["name"]

            # Handle range filters (e.g., year_from, year_to or field__gte/field__lte)
            if field_config["filter_type"] == "range":
                # Check for __gte suffix (Django ORM style from frontend)
                gte_value = params.get(f"{field_name}__gte")
                if gte_value:
                    try:
                        queryset = queryset.filter(**{f"{field_name}__gte": gte_value})
                    except (ValueError, TypeError) as e:
                        # Invalid value for range filter, skip it
                        print(
                            f"Invalid range filter value for {field_name}__gte: {e}",
                            file=sys.stderr,
                        )

                # Check for __lte suffix (Django ORM style from frontend)
                lte_value = params.get(f"{field_name}__lte")
                if lte_value:
                    try:
                        queryset = queryset.filter(**{f"{field_name}__lte": lte_value})
                    except (ValueError, TypeError) as e:
                        # Invalid value for range filter, skip it
                        print(
                            f"Invalid range filter value for {field_name}__lte: {e}",
                            file=sys.stderr,
                        )
            else:
                # Handle text and boolean filters with operator suffixes
                # Check for each possible operator: exact, icontains, istartswith, iendswith
                operators = ["exact", "icontains", "istartswith", "iendswith"]
                applied = False

                for operator in operators:
                    param_key = f"{field_name}__{operator}"
                    param_value = params.get(param_key)

                    if param_value:
                        try:
                            # Handle boolean conversion for exact matches
                            if (
                                operator == "exact"
                                and field_config["type"] == "boolean"
                            ):
                                bool_value = param_value.lower() in (
                                    "true",
                                    "1",
                                    "yes",
                                    "t",
                                    "y",
                                )
                                queryset = queryset.filter(**{field_name: bool_value})
                            else:
                                # Apply the filter with the appropriate Django ORM lookup
                                queryset = queryset.filter(**{param_key: param_value})
                            applied = True
                            break  # Only apply one operator per field
                        except (ValueError, TypeError) as e:
                            # Invalid filter value, skip it
                            print(
                                f"Invalid filter value for {param_key}: {e}",
                                file=sys.stderr,
                            )

                # Also check for direct field name (for backwards compatibility)
                if not applied:
                    param_value = params.get(field_name)
                    if param_value:
                        try:
                            queryset = self._apply_filter(
                                queryset, field_config, param_value
                            )
                        except (ValueError, TypeError) as e:
                            # Invalid filter value, skip it
                            print(
                                f"Invalid filter value for {field_name}: {e}",
                                file=sys.stderr,
                            )

        # Handle ordering
        ordering = params.get("ordering")
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
            {"data": key, "title": key.replace("__", " > ").replace("_", " ").title()}
            for key in sample_data.keys()
        ]
        return JsonResponse({"columns": columns})

    @action(detail=False, methods=["get"])
    def models(self, request):
        """Return available model types for filtering"""
        models = [
            {"value": key, "label": key.replace("_", " ").title()}
            for key in self.MODEL_CONFIG.keys()
        ]
        return JsonResponse({"models": models})

    @action(detail=False, methods=["get"])
    def filters(self, request):
        """Return available filters for the selected model"""
        model_name = request.query_params.get("model", "pathogen").lower()
        config = self.MODEL_CONFIG.get(model_name, self.MODEL_CONFIG["pathogen"])
        model_class = config["model"]

        filterable_fields = self._get_filterable_fields(model_class)
        return JsonResponse({"filters": filterable_fields})

    @action(detail=False, methods=["get"])
    def export(self, request):
        queryset = self.filter_queryset(self.get_queryset())

        # Get requested columns from query params
        columns_param = request.query_params.get("columns", "")
        requested_columns = [
            col.strip() for col in columns_param.split(",") if col.strip()
        ]

        def row_iterator():
            # Use iterator() to avoid caching the whole queryset
            for obj in queryset.iterator():
                row = self.get_serializer(obj).data
                if requested_columns:
                    yield {key: row.get(key, "") for key in requested_columns}
                else:
                    yield row

        def csv_stream():
            iterator = row_iterator()
            first_row = next(iterator, None)
            if first_row is None:
                return

            # Determine fieldnames from requested columns or first row
            if requested_columns:
                fieldnames = requested_columns
            else:
                fieldnames = list(first_row.keys())

            # Write header
            yield ",".join(fieldnames) + "\n"

            def row_to_csv(row):
                from io import StringIO

                buffer = StringIO()
                writer = csv.DictWriter(buffer, fieldnames=fieldnames)
                writer.writerow(row)
                return buffer.getvalue()

            # Write first row, then rest
            yield row_to_csv(first_row)
            for row in iterator:
                yield row_to_csv(row)

        response = StreamingHttpResponse(csv_stream(), content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="results.csv"'
        return response
