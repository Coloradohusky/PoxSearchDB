"""
Tests for the flexible search and filtering functionality.
"""
from django.test import TestCase, Client
from django.urls import reverse
from rest_framework.test import APITestCase
from extracteddata.models import FullText, Descriptive, Host, Pathogen, Sequence
import json


class UnifiedViewSetTestCase(APITestCase):
    """Test the UnifiedViewSet with multi-model support and flexible filtering."""

    @classmethod
    def setUpTestData(cls):
        """Create test data for all models."""
        # Create FullText (let Django auto-generate ID)
        cls.fulltext = FullText.objects.create(
            original_id='ft_001',
            title='Test Publication About Monkeypox',
            author='John Doe',
            publication_year=2020,
            processed=False
        )
        
        # Create Descriptive
        cls.descriptive = Descriptive.objects.create(
            original_id='ds_001',
            full_text=cls.fulltext,
            dataset_name='Test Dataset',
            sampling_effort='High'
        )
        
        # Create Host
        cls.host = Host.objects.create(
            original_id='h_001',
            study=cls.descriptive,
            scientific_name='Mus musculus',
            country='United States',
            locality='Colorado',
            individual_count=10,
            location_latitude=39.5,
            location_longitude=-105.5
        )
        
        # Create Pathogen
        cls.pathogen = Pathogen.objects.create(
            original_id='p_001',
            host=cls.host,
            family='Poxviridae',
            scientific_name='Monkeypox virus',
            assay='PCR',
            tested=100,
            positive=15,
            negative=85
        )
        
        # Create Sequence
        cls.sequence = Sequence.objects.create(
            original_id='s_001',
            scientific_name='Monkeypox virus',
            sequence_type='Pathogen',
            pathogen=cls.pathogen,
            accession_number='MN123456'
        )

    def test_default_model_is_pathogen(self):
        """Test that the default model is pathogen for backwards compatibility."""
        response = self.client.get('/api/unified/')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('results', data)
        self.assertEqual(len(data['results']), 1)
        
        # Check that it returns pathogen data
        result = data['results'][0]
        self.assertIn('family', result)
        self.assertEqual(result['family'], 'Poxviridae')

    def test_model_selection_host(self):
        """Test querying the Host model."""
        response = self.client.get('/api/unified/', {'model': 'host'})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data['results']), 1)
        
        result = data['results'][0]
        self.assertIn('scientific_name', result)
        self.assertEqual(result['scientific_name'], 'Mus musculus')

    def test_model_selection_sequence(self):
        """Test querying the Sequence model."""
        response = self.client.get('/api/unified/', {'model': 'sequence'})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data['results']), 1)
        
        result = data['results'][0]
        self.assertIn('accession_number', result)
        self.assertEqual(result['accession_number'], 'MN123456')

    def test_model_selection_descriptive(self):
        """Test querying the Descriptive model."""
        response = self.client.get('/api/unified/', {'model': 'descriptive'})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data['results']), 1)
        
        result = data['results'][0]
        self.assertIn('dataset_name', result)
        self.assertEqual(result['dataset_name'], 'Test Dataset')

    def test_model_selection_fulltext(self):
        """Test querying the FullText model."""
        response = self.client.get('/api/unified/', {'model': 'fulltext'})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data['results']), 1)
        
        result = data['results'][0]
        self.assertIn('title', result)
        self.assertIn('Monkeypox', result['title'])

    def test_search_across_models(self):
        """Test that search works across different models."""
        # Search in pathogen model
        response = self.client.get('/api/unified/', {
            'model': 'pathogen',
            'search': 'Monkeypox'
        })
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data['results']), 1)
        
        # Search in fulltext model
        response = self.client.get('/api/unified/', {
            'model': 'fulltext',
            'search': 'Monkeypox'
        })
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data['results']), 1)

    def test_text_filter(self):
        """Test text filtering (icontains)."""
        # Filter by family in pathogen
        response = self.client.get('/api/unified/', {
            'model': 'pathogen',
            'family': 'Poxviridae'
        })
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data['results']), 1)
        
        # Filter with non-matching value
        response = self.client.get('/api/unified/', {
            'model': 'pathogen',
            'family': 'NonExistent'
        })
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data['results']), 0)

    def test_range_filter(self):
        """Test range filtering for numeric fields."""
        # Filter by publication year
        response = self.client.get('/api/unified/', {
            'model': 'fulltext',
            'publication_year_from': '2019',
            'publication_year_to': '2021'
        })
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data['results']), 1)
        
        # Filter outside range
        response = self.client.get('/api/unified/', {
            'model': 'fulltext',
            'publication_year_from': '2021'
        })
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data['results']), 0)

    def test_filters_endpoint(self):
        """Test the /filters/ endpoint that returns available filters."""
        response = self.client.get('/api/unified/filters/', {'model': 'pathogen'})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        
        self.assertIn('filters', data)
        filters = data['filters']
        self.assertIsInstance(filters, list)
        self.assertGreater(len(filters), 0)
        
        # Check that filter definitions have required fields
        for filter_def in filters:
            self.assertIn('name', filter_def)
            self.assertIn('label', filter_def)
            self.assertIn('type', filter_def)
            self.assertIn('filter_type', filter_def)

    def test_filters_endpoint_different_models(self):
        """Test that filters endpoint returns different filters for different models."""
        # Get filters for pathogen
        response_pathogen = self.client.get('/api/unified/filters/', {'model': 'pathogen'})
        filters_pathogen = response_pathogen.json()['filters']
        
        # Get filters for host
        response_host = self.client.get('/api/unified/filters/', {'model': 'host'})
        filters_host = response_host.json()['filters']
        
        # Get filters for fulltext
        response_fulltext = self.client.get('/api/unified/filters/', {'model': 'fulltext'})
        filters_fulltext = response_fulltext.json()['filters']
        
        # They should have different fields
        pathogen_field_names = {f['name'] for f in filters_pathogen}
        host_field_names = {f['name'] for f in filters_host}
        fulltext_field_names = {f['name'] for f in filters_fulltext}
        
        # Each model should have some unique fields
        self.assertTrue(len(pathogen_field_names) > 0)
        self.assertTrue(len(host_field_names) > 0)
        self.assertTrue(len(fulltext_field_names) > 0)

    def test_columns_endpoint(self):
        """Test the /columns/ endpoint returns columns for the selected model."""
        response = self.client.get('/api/unified/columns/', {'model': 'pathogen'})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        
        self.assertIn('columns', data)
        columns = data['columns']
        self.assertIsInstance(columns, list)
        self.assertGreater(len(columns), 0)
        
        # Check column structure
        for col in columns:
            self.assertIn('data', col)
            self.assertIn('title', col)

    def test_models_endpoint(self):
        """Test the /models/ endpoint returns available models."""
        response = self.client.get('/api/unified/models/')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        
        self.assertIn('models', data)
        models = data['models']
        self.assertIsInstance(models, list)
        
        # Check that all expected models are present
        model_values = {m['value'] for m in models}
        expected_models = {'pathogen', 'host', 'sequence', 'descriptive', 'fulltext'}
        self.assertEqual(model_values, expected_models)

    def test_nested_field_filtering(self):
        """Test filtering on nested fields through relationships."""
        # Filter pathogen by host country
        response = self.client.get('/api/unified/', {
            'model': 'pathogen',
            'host__country': 'United States'
        })
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data['results']), 1)


class SearchPageTestCase(TestCase):
    """Test the search page view."""

    def test_search_page_loads(self):
        """Test that the search page loads successfully."""
        response = self.client.get('/search/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Unified Database Search')
        self.assertContains(response, 'Select Data Type')

    def test_search_page_has_model_selector(self):
        """Test that the search page includes the model selector."""
        response = self.client.get('/search/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'modelSelect')
        self.assertContains(response, 'Pathogen')
        self.assertContains(response, 'Host')
        self.assertContains(response, 'Sequence')
