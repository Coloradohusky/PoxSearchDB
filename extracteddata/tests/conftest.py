"""
Pytest configuration for extracteddata tests.

This module configures the test environment to ensure pygbif caching
is disabled during tests, allowing VCR to properly intercept and record
HTTP requests.
"""

import os
import pytest


@pytest.fixture(scope="session", autouse=True)
def configure_test_environment():
    """Set up test environment variables before any tests run."""
    os.environ["TESTING"] = "True"
    yield
    # Cleanup after all tests
    os.environ.pop("TESTING", None)


@pytest.fixture(autouse=True)
def reset_pygbif_cache():
    """Ensure pygbif caching is disabled for each test."""
    import pygbif

    pygbif.caching(False)
    yield
