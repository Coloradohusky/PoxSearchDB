from ..models import FullText, Descriptive, Host, Pathogen, Sequence

MODEL_MAP = {
    "inclusion_full_text": FullText,
    "descriptive": Descriptive,
    "host": Host,
    "pathogen": Pathogen,
    "sequence": Sequence,
}

MODEL_ALIASES = {
    "inclusion full text": "inclusion_full_text",
    "full_text": "inclusion_full_text",
    "rodent": "host",
    "rodents": "host",
    "sequences": "sequence",
}


def get_model_for_sheet(sheet_name):
    normalized = sheet_name.lower().strip()
    if normalized in MODEL_ALIASES:
        normalized = MODEL_ALIASES[normalized]
    return MODEL_MAP.get(normalized)


COLUMN_ALIASES = {
    "FullText": {
        "id": ["full_text_id"],
        "extractor": ["extractor"],
        "community": ["community"],
        "spatio_temporal_extraction": ["spatio-temporal extraction"],
        "decision": ["decision"],
        "reason": ["reason"],
        "key": ["key"],
        "publication_year": ["publication year"],
        "author": ["author"],
        "title": ["title"],
        "processed": ["processed"],
    },
    "Descriptive": {
        "id": ["study_id"],
        "full_text": ["full_text_id"],
        "dataset_name": ["datasetName"],
        "sampling_effort": ["sampling_effort"],
        "data_access": ["data_access"],
        "data_resolution": ["data_resolution"],
        "linked_manuscripts": ["linked_manuscripts"],
        "notes": ["notes"],
    },
    "Host": {
        "id": ["rodent_record_id", "host_record_id"],
        "study": ["study_id"],
        "scientific_name": ["scientificName"],
        "event_date": ["eventDate"],
        "locality": ["locality"],
        "country": ["country"],
        "verbatim_locality": ["verbatimLocality"],
        "coordinate_resolution": ["coordinate_resolution"],
        # "location": ["decimalLatitude", "decimalLongitude"],
        "location_latitude": ["decimalLatitude"],
        "location_longitude": ["decimalLongitude"],
        "individual_count": ["individualCount"],
        "trap_effort": ["trapEffort"],
        "trap_effort_resolution": ["trapEffortResolution"],
    },
    "Pathogen": {
        "id": ["pathogen_record_id"],
        "host": ["associated_rodent_record_id", "associated_host_record_id"],
        "family": ["family"],
        "scientific_name": ["scientificName"],
        "assay": ["assay"],
        "tested": ["tested"],
        "positive": ["positive"],
        "number_inconclusive": ["number_inconclusive"],
        "note": ["note"],
    },
    "Sequence": {
        "id": ["sequence_record_id"],
        "sequence_type": ["sequenceType"],
        "associated_taxa": ["associatedTaxa"],
        "pathogen": ["associated_pathogen_record_id"],
        "host": ["associated_rodent_record_id", "associated_host_record_id"],
        "study": ["study_id"],
        "accession_number": ["accession_number"],
        "method": ["method"],
        "note": ["note"],
        "date_sampled": ["date_sampled"],
        "sample_location": ["sample_location"],
        "scientific_name": ["scientificName"],
    },
}
