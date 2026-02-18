import os

import pygbif
from pygbif import species as _gbif_species

from .logging import log

# Enable pygbif API caching only in production (not during tests)
if not os.environ.get("TESTING", False):
    list(log(True, "Caching enabled for pygbif API"))
    pygbif.caching(True)
else:
    # Disable caching during tests to allow VCR to intercept requests
    list(log(True, "Caching disabled for pygbif API"))
    pygbif.caching(False)


def resolve_species_name(name, verbose, min_confidence=85):
    """
    Attempt to resolve a taxonomic name to an accepted/canonical name using GBIF.

    Args:
        name: The taxonomic name to resolve (string)
        verbose: Boolean flag to enable verbose logging
        min_confidence: Minimum confidence threshold (0-100) for accepting results

    Returns:
        str: A canonical name string if resolution succeeds, otherwise None.

    Note:
        This function requires the `pygbif` package and network access to GBIF.

    """
    if not name or not isinstance(name, str):
        return None

    # Strip whitespace
    name = name.strip()
    if not name:
        return None
    if name.lower() in ["na", "n/a", "none", "unknown", ""]:
        return None

    try:
        # Try name_backbone first - this is the primary matching service
        resp = _gbif_species.name_backbone(scientificName=name)

        if resp and isinstance(resp, dict):
            # Check confidence if available
            confidence = resp.get("diagnostics", {}).get("confidence", 0)
            # list(log(verbose, f"Confidence '{confidence}'"))

            # Only use result if confidence meets threshold
            if confidence >= min_confidence:
                # Prefer accepted names over synonyms
                status = resp.get("usage", {}).get("status", "")
                if status == "SYNONYM":
                    # If it's a synonym, try to get the accepted name
                    accepted_key = resp.get("acceptedUsage", {}).get("canonicalName")
                    if accepted_key:
                        try:
                            accepted_resp = _gbif_species.name_usage(key=accepted_key)
                            if accepted_resp and isinstance(accepted_resp, dict):
                                canonical = accepted_resp.get("usage", {}).get(
                                    "canonicalName", name
                                )
                                if canonical:
                                    return canonical
                        except Exception as e:
                            print(log(verbose, f"Error: {e}"))
                            pass

                # Return canonical name from backbone response
                canonical = resp.get("usage", {}).get("canonicalName", name)
                if canonical:
                    return canonical

    except Exception as e:
        list(log(True, f"GBIF lookup error for '{name}': {e}"))
        return name

    list(log(True, f"Unable to find match for '{name}'"))
    return name
