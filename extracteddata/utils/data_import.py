import logging
import re
from datetime import datetime

import pandas as pd
from django.db import transaction

from ..models import Descriptive, FullText, Host, Pathogen, Sequence
from .column_mappings import COLUMN_ALIASES, MODEL_ALIASES, get_model_for_sheet
from .gbif_normalization import resolve_species_name
from .logging import log

# Disable unnecessary caching logs
logging.basicConfig(level=logging.INFO)
logging.getLogger("requests").setLevel(logging.WARNING)
logging.getLogger("requests_cache").setLevel(logging.WARNING)


# More aggressive than normalize_value, used for converting ft_1 to 1
def clean_value(value, float_to_int=True):
    if pd.isna(value):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if float_to_int else value
    if isinstance(value, str):
        if value == "":
            return None
        value = value.strip()
        if value.isdigit():
            return int(value)
        if "_" in value:
            match = re.search(r"\d+", value)
            return int(match.group()) if match else value
        return value
    return None


# Simply used for cleaning strings and converting float to int
def normalize_value(value, float_to_int=True):
    if pd.isna(value):
        return None
    if isinstance(value, str):
        return " ".join(value.split()).strip() or None
    if isinstance(value, (int, float)):
        if float_to_int:
            return int(value)
    return str(value).strip()


# Assign a unique integer ID, ensuring no conflicts with existing_ids.
def assign_unique_id(existing_ids, candidate_id=None, start_from=1):
    if candidate_id is None or candidate_id in existing_ids:
        candidate_id = start_from
        while candidate_id in existing_ids:
            candidate_id += 1
    existing_ids.add(candidate_id)
    return candidate_id


def apply_column_aliases(df, aliases):
    # Normalize existing dataframe columns (strip and lower) to find matches
    # while preserving the actual original column names for renaming.
    col_map = {col.strip().lower(): col for col in df.columns}
    rename_map = {}
    for field, options in aliases.items():
        for option in options:
            norm = option.strip().lower()
            if norm in col_map:
                # map the actual column name to the canonical field name
                rename_map[col_map[norm]] = field
                break

    if rename_map:
        df.rename(columns=rename_map, inplace=True)

    # Finally normalize all column names to stripped, lower-case canonical form
    df.columns = df.columns.str.strip().str.lower()


def make_row_key(row, fields, verbose, float_to_int=True):
    def _normalize_latlon(val):
        if val is None:
            return None
        try:
            if pd.isna(val):
                return None
        except Exception as e:
            print(log(verbose, f"Error: {e}"))
            pass
        if isinstance(val, (int, float)):
            return str(float(val)).strip()
        if isinstance(val, str):
            v = val.strip()
            if v == "":
                return None
            try:
                f = float(v)
                return str(f).strip()
            except Exception:
                return v
        return str(val).strip()

    return tuple(
        _normalize_latlon(row.get(f))
        if f in ("location_longitude", "location_latitude")
        else normalize_value(row.get(f), float_to_int=float_to_int)
        for f in fields
    )


def handle_csv_upload(file, sheet_name, id_mapping, verbose):
    df = pd.read_csv(file, dtype=str, keep_default_na=False).dropna(how="all")
    df.columns = df.columns.str.strip().str.lower()
    yield from handle_upload(df, sheet_name, id_mapping, verbose)


def handle_excel_upload(file, id_mapping, verbose):
    xls = pd.ExcelFile(file)
    for sheet_name in xls.sheet_names:
        model_class = get_model_for_sheet(sheet_name)
        if not model_class:
            yield from log(verbose, f"Error: Unknown sheet {sheet_name}")
            return
        df = pd.read_excel(
            xls, sheet_name=sheet_name, dtype=str, keep_default_na=False
        ).dropna(how="all")
        df.columns = df.columns.str.strip().str.lower()
        yield from log(verbose, f"Processing sheet: {sheet_name} ({len(df)} rows)")
        yield from handle_upload(df, sheet_name, id_mapping, verbose)


# Set up importer function lambdas
IMPORTERS = {
    "inclusion_full_text": lambda df, id_mapping, v: import_fulltext(df, id_mapping, v),
    "descriptive": lambda df, id_mapping, v: import_descriptive(df, id_mapping, v),
    "host": lambda df, id_mapping, v: import_host(df, id_mapping, v),
    "pathogen": lambda df, id_mapping, v: import_pathogen(df, id_mapping, v),
    "sequence": lambda df, id_mapping, v: import_sequence(df, id_mapping, v),
}


# Based on lambda, upload defined sheet
def handle_upload(df, sheet_name, id_mapping, verbose):
    normalized_name = sheet_name.lower().strip()
    if normalized_name in MODEL_ALIASES:
        normalized_name = MODEL_ALIASES[normalized_name]

    importer = IMPORTERS.get(normalized_name)
    if not importer:
        yield from log(True, f"Unknown sheet: {sheet_name}")
        return
    yield from log(True, f"Importing {sheet_name}...")
    yield from importer(df, id_mapping, verbose)


"""
    Generic import function for Django models.

    Args:
        df: DataFrame to import
        model_class: Django model class (e.g., FullText)
        id_mapping_key: Key for id_mapping dict (e.g., "inclusion_full_text")
        id_mapping: Dictionary to store ID mappings
        column_alias_key: Key for COLUMN_ALIASES dict
        dedup_fields: List of fields to use for deduplication
        dedup_with_self: False to only check existing database records
        field_mapping: Dict mapping CSV columns to model field constructors
        required_fields: List of required fields (besides 'id')
        foreign_key_resolver: Optional function that takes row and returns dict of foreign key fields
        foreign_key_validator: Optional function that validates foreign key fields based on criteria
        verbose: Whether to log verbose messages
"""


def import_data(
    df,
    model_class,
    id_mapping_key,
    id_mapping,
    column_alias_key,
    dedup_fields,
    dedup_with_self,
    field_mapping,
    required_fields=None,
    foreign_key_resolver=None,
    foreign_key_validator=None,
    verbose=False,
    chunk_size=None,
):
    # Preparation for importing
    apply_column_aliases(df, COLUMN_ALIASES[column_alias_key])

    required_fields = required_fields or []
    fetch_fields = ["id"] + dedup_fields

    existing_data = list(model_class.objects.values(*fetch_fields))

    existing_keys = {
        make_row_key(obj, dedup_fields, verbose, float_to_int=True)
        for obj in existing_data
    }

    key_to_id = {
        make_row_key(obj, dedup_fields, verbose, float_to_int=True): obj["id"]
        for obj in existing_data
    }

    existing_ids = {obj["id"] for obj in existing_data}

    objects = []
    inserted_count = 0

    # Function for committing accumulated objects to the database
    def flush_objects():
        nonlocal objects, inserted_count
        if not objects:
            return
        # bulk_create supports batch_size; limit DB payloads when chunk_size is set
        kwargs = {"batch_size": chunk_size} if chunk_size else {}
        with transaction.atomic():
            model_class.objects.bulk_create(objects, **kwargs)
        inserted_count += len(objects)
        objects = []

    batch_keys = set()

    # Iterate over each row, apply functions when necessary
    for _, row in df.iterrows():
        original_id = row.get("id")

        skip = False
        for field in required_fields:
            value = normalize_value(row.get(field))
            if not value:
                yield from log(
                    True, f"Skipped row with missing {field} (row={str(row.to_list())})"
                )
                skip = True
                break
        if skip:
            continue

        clean_id = assign_unique_id(existing_ids, clean_value(original_id))
        # Build object fields
        obj_fields = {"id": clean_id, "original_id": original_id}

        # Resolve foreign keys
        if foreign_key_resolver:
            fk_fields = foreign_key_resolver(row)

            # Run custom validation if provided
            if foreign_key_validator:
                should_skip, log_messages = foreign_key_validator(
                    row, fk_fields, original_id
                )
                yield from log_messages
                if should_skip:
                    continue
            # Default behavior: check if any required foreign keys are None
            elif any(v is None for v in fk_fields.values()):
                yield from log(
                    True,
                    f"Skipped: Missing foreign key for row={str(row.to_list())})",
                )
                continue
            obj_fields.update(fk_fields)

        # Add regular fields
        for field_name, field_processor in field_mapping.items():
            obj_fields[field_name] = field_processor(row)

        # Build a key source that prefers resolved foreign-key objects (in obj_fields)
        # for nested dedup fields like 'host__scientific_name'. This allows dedup checks
        # to include related model attributes when the incoming row only contains a
        # reference to the FK (e.g., host original id mapped to a Host instance).
        # For non-nested fields, use the PROCESSED value from field_mapping if available
        # (e.g., canonicalized species names).
        key_source = {}
        for f in dedup_fields:
            if "__" in f:
                base, attr = f.split("__", 1)
                v = None
                if base in obj_fields and obj_fields[base] is not None:
                    try:
                        v = getattr(obj_fields[base], attr)
                    except Exception:
                        v = None
                # Fallback to raw row value if available
                if v is None:
                    v = (
                        row.get(f)
                        if f in row.index or isinstance(row, dict)
                        else row.get(base)
                    )
                key_source[f] = v
            # For non-nested fields, use processed value from obj_fields if available
            # (this ensures canonicalized species names, normalized strings, etc.)
            elif f in obj_fields:
                key_source[f] = obj_fields[f]
            else:
                key_source[f] = row.get(f)

        key = make_row_key(key_source, dedup_fields, verbose)

        # Handle duplicates
        if key in existing_keys:
            existing_id = key_to_id[key]

            # Check if we're trying to overwrite an existing mapping
            if original_id in id_mapping[id_mapping_key]:
                if id_mapping[id_mapping_key][original_id] != existing_id:
                    raise ValueError(
                        f"Duplicate ID '{original_id}' in {model_class.__name__} data with conflicting mappings: "
                        f"existing mapping={id_mapping[id_mapping_key][original_id]}, new mapping={existing_id}"
                    )
            # Same mapping, just skip silently
            else:
                id_mapping[id_mapping_key][original_id] = existing_id

            yield from log(
                verbose,
                f"Mapped duplicate {model_class.__name__} ID {original_id} → existing {existing_id}",
            )
            continue

        if dedup_with_self and key in batch_keys:
            yield from log(
                verbose, f"Skipped duplicate within import batch: {original_id}"
            )
            continue

        # Assign ID
        existing_ids.add(clean_id)
        if dedup_with_self:
            existing_keys.add(key)
            key_to_id[key] = clean_id
            batch_keys.add(key)

        # Check if we're trying to overwrite an existing mapping
        if original_id in id_mapping[id_mapping_key]:
            raise ValueError(
                f"Duplicate ID '{original_id}' in {model_class.__name__} data "
                f"(already mapped to {id_mapping[id_mapping_key][original_id]})"
            )

        id_mapping[id_mapping_key][original_id] = clean_id

        objects.append(model_class(**obj_fields))

        if chunk_size and len(objects) >= chunk_size:
            flush_objects()

    flush_objects()
    yield from log(
        True, f"Inserted {inserted_count} new {model_class.__name__} records."
    )


# Specific import functions for each sheet, as shown in IMPORTERS
def import_fulltext(df, id_mapping, verbose):
    field_mapping = {
        "title": lambda row: normalize_value(row.get("title")),
        "author": lambda row: normalize_value(row.get("author")),
        "publication_year": lambda row: clean_value(row.get("publication_year")),
        "key": lambda row: normalize_value(row.get("key")),
        "extractor": lambda row: normalize_value(row.get("extractor")),
        "community": lambda row: normalize_value(row.get("community")),
        "spatio_temporal_extraction": lambda row: normalize_value(
            row.get("spatio_temporal_extraction")
        ),
        "decision": lambda row: normalize_value(row.get("decision")),
        "reason": lambda row: normalize_value(row.get("reason")),
        "processed": lambda row: bool(row.get("processed", False)),
    }

    yield from import_data(
        df=df,
        model_class=FullText,
        id_mapping_key="inclusion_full_text",
        id_mapping=id_mapping,
        column_alias_key="FullText",
        dedup_fields=["title", "author", "publication_year"],
        dedup_with_self=True,
        field_mapping=field_mapping,
        required_fields=["title"],
        verbose=verbose,
        chunk_size=None,
    )


def import_descriptive(df, id_mapping, verbose):
    fulltexts = FullText.objects.in_bulk(FullText.objects.values_list("id", flat=True))

    def get_fulltext(row):
        ft_val = row.get("full_text")
        mapped_ft_id = id_mapping["inclusion_full_text"].get(ft_val, ft_val)
        return fulltexts.get(mapped_ft_id)

    field_mapping = {
        "dataset_name": lambda row: normalize_value(row.get("dataset_name")),
        "sampling_effort": lambda row: normalize_value(row.get("sampling_effort")),
        "data_access": lambda row: normalize_value(row.get("data_access")),
        "data_resolution": lambda row: normalize_value(row.get("data_resolution")),
        "linked_manuscripts": lambda row: normalize_value(
            row.get("linked_manuscripts")
        ),
        "notes": lambda row: normalize_value(row.get("notes")),
    }

    yield from import_data(
        df=df,
        model_class=Descriptive,
        id_mapping_key="descriptive",
        id_mapping=id_mapping,
        column_alias_key="Descriptive",
        dedup_fields=["dataset_name", "data_access"],
        dedup_with_self=True,
        field_mapping=field_mapping,
        required_fields=[],
        verbose=verbose,
        foreign_key_resolver=lambda row: {"full_text": get_fulltext(row)},
        chunk_size=None,
    )


def import_host(df, id_mapping, verbose):
    studies = Descriptive.objects.in_bulk(
        Descriptive.objects.values_list("id", flat=True)
    )

    def get_study(row):
        study_val = row.get("study")
        mapped_study_id = id_mapping["descriptive"].get(study_val)
        if mapped_study_id is not None:
            return studies.get(int(mapped_study_id))
        return None

    field_mapping = {
        "scientific_name": lambda row: resolve_species_name(
            row.get("scientific_name"), verbose
        ),
        "event_date": lambda row: normalize_value(row.get("event_date")),
        "locality": lambda row: normalize_value(row.get("locality")),
        "country": lambda row: normalize_value(row.get("country")),
        "verbatim_locality": lambda row: normalize_value(row.get("verbatim_locality")),
        "coordinate_resolution": lambda row: normalize_value(
            row.get("coordinate_resolution")
        ),
        "location_latitude": lambda row: clean_value(
            row.get("location_latitude"), float_to_int=False
        ),
        "location_longitude": lambda row: clean_value(
            row.get("location_longitude"), float_to_int=False
        ),
        "individual_count": lambda row: clean_value(row.get("individual_count")),
        "trap_effort": lambda row: normalize_value(row.get("trap_effort")),
        "trap_effort_resolution": lambda row: normalize_value(
            row.get("trap_effort_resolution")
        ),
    }

    yield from import_data(
        df=df,
        model_class=Host,
        id_mapping_key="host",
        id_mapping=id_mapping,
        column_alias_key="Host",
        dedup_fields=[
            "scientific_name",
            "event_date",
            "locality",
            "country",
            "verbatim_locality",
            "coordinate_resolution",
            "location_latitude",
            "location_longitude",
            "individual_count",
        ],
        dedup_with_self=False,
        field_mapping=field_mapping,
        required_fields=["individual_count"],
        verbose=verbose,
        foreign_key_resolver=lambda row: {"study": get_study(row)},
        chunk_size=100,
    )


def import_pathogen(df, id_mapping, verbose):
    hosts = Host.objects.in_bulk(Host.objects.values_list("id", flat=True))

    def get_host(row):
        host_val = row.get("host")
        mapped_host_id = id_mapping["host"].get(host_val)
        if mapped_host_id is not None:
            return hosts.get(int(mapped_host_id))
        return None

    field_mapping = {
        "family": lambda row: normalize_value(row.get("family")),
        "scientific_name": lambda row: resolve_species_name(
            row.get("scientific_name"), verbose
        ),
        "assay": lambda row: normalize_value(row.get("assay")),
        "tested": lambda row: clean_value(row.get("tested")),
        "positive": lambda row: clean_value(row.get("positive")),
        "negative": lambda row: clean_value(row.get("negative")),
        "number_inconclusive": lambda row: clean_value(row.get("number_inconclusive")),
        "note": lambda row: normalize_value(row.get("note")),
    }

    yield from import_data(
        df=df,
        model_class=Pathogen,
        id_mapping_key="pathogen",
        id_mapping=id_mapping,
        column_alias_key="Pathogen",
        # include related host scientific name in dedup checks (host__scientific_name)
        dedup_fields=[
            "family",
            "scientific_name",
            "assay",
            "tested",
            "positive",
            "negative",
            "number_inconclusive",
            "host__scientific_name",
        ],
        dedup_with_self=False,
        field_mapping=field_mapping,
        required_fields=[],
        verbose=verbose,
        foreign_key_resolver=lambda row: {"host": get_host(row)},
        chunk_size=100,
    )


def import_sequence(df, id_mapping, verbose):
    hosts = Host.objects.in_bulk(Host.objects.values_list("id", flat=True))
    pathogens = Pathogen.objects.in_bulk(Pathogen.objects.values_list("id", flat=True))
    studies = Descriptive.objects.in_bulk(
        Descriptive.objects.values_list("id", flat=True)
    )

    def get_host(row):
        host_val = row.get("host")
        mapped_host_id = id_mapping.get("host", {}).get(host_val)
        if mapped_host_id is not None:
            try:
                return hosts.get(int(mapped_host_id))
            except Exception:
                return hosts.get(mapped_host_id)
        return None

    def get_pathogen(row):
        pathogen_val = row.get("pathogen")
        mapped_pathogen_id = id_mapping.get("pathogen", {}).get(pathogen_val)
        if mapped_pathogen_id is not None:
            try:
                return pathogens.get(int(mapped_pathogen_id))
            except Exception:
                return pathogens.get(mapped_pathogen_id)
        return None

    def get_study(row):
        study_val = row.get("study")
        mapped_study_id = id_mapping.get("descriptive", {}).get(study_val)
        if mapped_study_id is not None:
            try:
                return studies.get(int(mapped_study_id))
            except Exception:
                return studies.get(mapped_study_id)
        return None

    def resolve_sequence_fks(row):
        """
        Return a dict with exactly one of 'host', 'pathogen', 'study' set (or all None).

        Rules implemented:
        - If sequence_type == 'pathogen' (case-insensitive) -> attempt to set 'pathogen'
        - Else if sequence_type == 'host' -> attempt to set 'host'
        - After that, if associatedTaxa indicates Homo sapiens (case-insensitive match on
          row key 'associatedtaxa' or 'associated_taxa'), set 'study' and clear host/pathogen
          (study takes precedence and is checked last).
        - If the selected FK object is not found (None), leave it None — validator will decide
          whether to skip.
        """
        # Resolve all candidates first
        candidate_host = get_host(row)
        candidate_pathogen = get_pathogen(row)
        candidate_study = get_study(row)

        # Use normalize_value without float->int conversion to get a safe string
        sequence_type = (
            normalize_value(row.get("sequence_type"), float_to_int=False) or ""
        )
        sequence_type = sequence_type.strip().lower()

        # Start with no selection
        fk = {"host": None, "pathogen": None, "study": None}

        if sequence_type == "pathogen":
            fk["pathogen"] = candidate_pathogen
        elif sequence_type == "host":
            fk["host"] = candidate_host

        assoc_taxa = normalize_value(row.get("associated_taxa"), float_to_int=False)
        if (
            assoc_taxa
            and isinstance(assoc_taxa, str)
            and assoc_taxa.strip().lower() == "homo sapiens"
        ):
            # study takes precedence — set study and clear other FKs
            fk = {"host": None, "pathogen": None, "study": candidate_study}

        return fk

    def validate_sequence_fks(row, fk_fields, original_id):
        """
        Returns (should_skip, log_generator).

        Validation enforces that exactly one FK is present (non-None) according to rules:
        - If associatedTaxa is Homo sapiens, study must be present.
        - Else if sequence_type is 'pathogen', pathogen must be present.
        - Else if sequence_type is 'host', host should be present (warning if not).
        - Otherwise at least one of host/pathogen/study should be present.
        """
        host_obj = fk_fields.get("host")
        pathogen_obj = fk_fields.get("pathogen")
        study_obj = fk_fields.get("study")

        sequence_type = (
            normalize_value(row.get("sequence_type"), float_to_int=False) or ""
        )
        sequence_type = sequence_type.strip().lower()

        assoc_taxa = normalize_value(row.get("associated_taxa"), float_to_int=False)

        # If associatedTaxa is Homo sapiens, require study
        if (
            assoc_taxa
            and isinstance(assoc_taxa, str)
            and assoc_taxa.strip().lower() == "homo sapiens"
        ):
            if not study_obj:
                return True, log(
                    verbose,
                    f"Skipped: associatedTaxa is 'Homo sapiens' but study {row.get('study')} not found for sequence {original_id}",
                )
            return False, ()

        # If sequence is pathogen type, require pathogen
        if sequence_type == "pathogen":
            if not pathogen_obj:
                return True, log(
                    verbose,
                    f"Skipped: Pathogen {row.get('pathogen')} not found for sequence {original_id}",
                )
            return False, ()

        # If sequence is host type, prefer host but only warn if missing
        if sequence_type == "host":
            if not host_obj:
                return False, log(
                    verbose,
                    f"Warning: Host {row.get('host')} not found for host sequence {original_id}",
                )
            return False, ()

        # Fallback: ensure at least one FK exists
        if not pathogen_obj and not host_obj and not study_obj:
            return True, log(
                verbose,
                f"Skipped: No host, pathogen, or study found for sequence {original_id}",
            )

        return False, ()

    field_mapping = {
        "sequence_type": lambda row: normalize_value(row.get("sequence_type")),
        "associated_taxa": lambda row: normalize_value(row.get("associated_taxa")),
        "scientific_name": lambda row: normalize_value(row.get("scientific_name")),
        "accession_number": lambda row: normalize_value(row.get("accession_number")),
        "method": lambda row: normalize_value(row.get("method")),
        "note": lambda row: normalize_value(row.get("note")),
        "date_sampled": lambda row: _parse_date_sampled(row.get("date_sampled")),
        "sample_location": lambda row: normalize_value(row.get("sample_location")),
    }

    def _parse_date_sampled(val):
        """
        Parse a variety of input date values and return YYYY-MM-DD or None.

        Accepts strings like '2020-01-02', '01/02/2020', pandas Timestamp, or numeric values.
        """
        v = normalize_value(val, float_to_int=False)
        if not v:
            return None
        # If it's already in YYYY-MM-DD, fromisoformat handles it
        try:
            if isinstance(v, str):
                # Remove time component if present
                date_part = v.split()[0]
                dt = datetime.fromisoformat(date_part)
                return dt.strftime("%Y-%m-%d")
        except Exception as e:
            print(log(verbose, f"Error: {e}"))
            pass

        # Try common alternative formats
        for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y"):
            try:
                dt = datetime.strptime(v, fmt)
                return dt.strftime("%Y-%m-%d")
            except Exception as e:
                print(log(verbose, f"Error: {e}"))
                continue

        # Give up gracefully
        return None

    yield from import_data(
        df=df,
        model_class=Sequence,
        id_mapping_key="sequence",
        id_mapping=id_mapping,
        column_alias_key="Sequence",
        dedup_fields=["accession_number"],
        dedup_with_self=False,
        field_mapping=field_mapping,
        required_fields=["accession_number"],
        verbose=verbose,
        foreign_key_resolver=resolve_sequence_fks,
        foreign_key_validator=validate_sequence_fks,
        chunk_size=None,
    )
