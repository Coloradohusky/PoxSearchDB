import os

# Set TESTING environment variable BEFORE importing data_import to disable pygbif caching
os.environ['TESTING'] = 'True'

from django.test import SimpleTestCase
import unittest.mock as mock
from types import SimpleNamespace
import pandas as pd
import vcr
from django.test import TestCase
from extracteddata.utils import data_import as di
from django.test import TestCase
from .. import models

# Configure VCR with sensible defaults
my_vcr = vcr.VCR(
    cassette_library_dir='extracteddata/tests/fixtures/vcr_cassettes',
    record_mode='once',  # Record once, then replay
    match_on=['uri', 'method'],  # Match requests by URI and HTTP method
    filter_headers=['authorization'],  # Remove sensitive headers if any
    decode_compressed_response=True,
)

class DataImportUtilsTests(SimpleTestCase):
    def test_clean_value_none_and_empty(self):
        self.assertIsNone(di.clean_value(None))
        self.assertIsNone(di.clean_value(''))

    def test_clean_value_numbers(self):
        self.assertEqual(di.clean_value(5), 5)
        self.assertEqual(di.clean_value(5.0), 5)
        self.assertEqual(di.clean_value(5.5, float_to_int=False), 5.5)

    def test_clean_value_underscore_with_digits(self):
        self.assertEqual(di.clean_value('abc_123'), 123)

    def test_normalize_value(self):
        self.assertIsNone(di.normalize_value(None))
        self.assertEqual(di.normalize_value('  a   b  '), 'a b')
        self.assertEqual(di.normalize_value(3.0), 3)

    def test_assign_unique_id(self):
        existing = {1, 2, 3}
        new_id = di.assign_unique_id(existing, None, start_from=1)
        self.assertEqual(new_id, 4)
        # candidate not in existing
        existing2 = {1, 2}
        ret = di.assign_unique_id(existing2, 10)
        self.assertEqual(ret, 10)

    def test_apply_column_aliases_and_make_row_key(self):
        df = pd.DataFrame({'Title': ['A'], ' Latitude ': [' 45.0 ']})
        aliases = {'title': ['Title'], 'location_latitude': [' Latitude ']}
        di.apply_column_aliases(df, aliases)
        # columns should be lowercased and stripped
        self.assertIn('title', df.columns)
        self.assertIn('location_latitude', df.columns)

        # Test make_row_key with lat normalization
        row = {'location_latitude': ' 45.0 ', 'title': ' A '}
        key = di.make_row_key(row, ['location_latitude', 'title'])
        self.assertEqual(key[0], str(float(45.0)))


class DataImportModelLinkageTests(TestCase):
    """Integration-style tests to ensure foreign-key linkages work when IDs are
    reassigned by assign_unique_id during import.

    Scenario covered:
    - There is an existing Host with id=1.
    - We import a Host row whose original id is also '1' (collision). The import
      code should assign a new unique id (2) and record the mapping in
      id_mapping['host'].
    - We then import a Pathogen row that references the original host id '1'.
      The pathogen import should resolve the FK using the mapping and link to
      the newly-created Host (id=2).
    """

    def test_host_and_pathogen_linkage_with_id_reassignment(self):
        # Create initial descriptive/study and existing host
        study = models.Descriptive.objects.create(id=100, original_id='study_orig', full_text=None)
        existing_host = models.Host.objects.create(
            id=1,
            original_id='1',
            study=study,
            scientific_name='ExistingRat',
            individual_count=5,
        )

        # Prepare id_mapping with descriptive mapping so host import doesn't skip
        id_mapping = {
            'inclusion_full_text': {},
            'descriptive': {'study_orig': study.id},
            'host': {},
            'pathogen': {},
            'sequence': {},
        }

        # DataFrame to import a host whose original id collides with existing one
        host_df = pd.DataFrame([
            {
                'id': '1',
                'study': 'study_orig',
                'scientific_name': 'NewRat',
                'individual_count': '10',
            }
        ])

        # Mock GBIF responses so tests behave like pygbif's CI (no network needed)
        fake_species = SimpleNamespace(
            name_backbone=lambda name: {
                'confidence': 100,
                'canonicalName': name,
                'scientificName': name,
                'status': 'ACCEPTED'
            },
            name_lookup=lambda q, limit=5: {'results': [{'taxonomicStatus': 'ACCEPTED', 'canonicalName': q}]}
        )

        with mock.patch.object(di, '_gbif_species', fake_species):
            # Sanity-check species resolver on the incoming value before import
            self.assertEqual(di.resolve_species_name(host_df.loc[0, 'scientific_name'], True), 'NewRat')

            # Print df columns for debugging (helps catch alias/column mismatch)
            print("host_df columns before import:", host_df.columns.tolist())

            # Run host import with verbose logging captured so failures show context
            logs = list(di.import_host(host_df, id_mapping, verbose=True))
            print("import_host logs:", logs)

        # After import, original '1' should be mapped to a new id (not 1)
        self.assertIn('1', id_mapping['host'])
        new_host_id = id_mapping['host']['1']
        self.assertNotEqual(new_host_id, existing_host.id)

        new_host = models.Host.objects.get(id=new_host_id)
        # Show helpful debug info if assertion fails
        self.assertEqual(
            new_host.scientific_name, 'NewRat',
            f"new_host fields={{'id': new_host.id, 'original_id': new_host.original_id, 'scientific_name': new_host.scientific_name, 'study_id': getattr(new_host.study, 'id', None)}}, id_mapping={id_mapping}, logs={logs}"
        )
        # Confirm study linkage preserved
        self.assertIsNotNone(new_host.study)
        self.assertEqual(new_host.study.id, study.id)

        # Print any Hosts that still reference the original_id '1' to help debugging
        h_by_original = list(models.Host.objects.filter(original_id='1').values())
        print("hosts with original_id='1':", h_by_original)

        # Now import a pathogen that references the original host id '1'
        pathogen_df = pd.DataFrame([
            {
                'id': '10',
                'host': '1',
                'scientific_name': 'SomeVirus',
                'tested': '5',
                'positive': '1',
            }
        ])

        list(di.import_pathogen(pathogen_df, id_mapping, verbose=False))

        # Pathogen should be linked to the newly created host (new_host_id)
        p = models.Pathogen.objects.get(scientific_name='SomeVirus')
        self.assertIsNotNone(p.host)
        self.assertEqual(p.host.id, new_host_id)


class SpeciesNormalizationTests(TestCase):
    """Tests for species name normalization and resolution"""
    
    # Tests that don't need GBIF (no decorator needed)
    @my_vcr.use_cassette('gbif_na_tokens.yaml')
    def test_na_tokens_return_none(self):
        """Test GBIF resolution for NA tokens"""
        self.assertIsNone(di.resolve_species_name('na', True))
        self.assertIsNone(di.resolve_species_name('N/A', True))
        self.assertIsNone(di.resolve_species_name('unknown', True))
    
    @my_vcr.use_cassette('gbif_sp_spp_normalization.yaml')
    def test_sp_and_spp_normalization(self):
        """Test GBIF resolution for sp and spp normalization"""
        self.assertEqual(di.resolve_species_name('Rattus sp', True), 'Rattus')
        self.assertEqual(di.resolve_species_name('Rattus spp', True), 'Rattus')
    
    @my_vcr.use_cassette('gbif_homo_sapiens.yaml')
    def test_taxonomic_resolution_with_gbif(self):
        """Test GBIF resolution for Homo sapiens"""
        result = di.resolve_species_name('Homo sapiens', True)
        self.assertIsNotNone(result)
        self.assertIn('sapiens', result.lower())
    
    @my_vcr.use_cassette('gbif_oligoryzomys_utiaritensis.yaml')
    def test_gbif_resolution_oligoryzomys(self):
        """Test GBIF resolution for Oligoryzomys utiaritensis"""
        result = di.resolve_species_name('Olygoryzomys utiaritensis', True)
        self.assertEqual(result, 'Oligoryzomys utiaritensis')
    
    @my_vcr.use_cassette('gbif_synonym_resolution.yaml')
    def test_gbif_synonym_resolution(self):
        """Test that synonyms are resolved to accepted names"""
        # Use a known synonym if you have one
        result = di.resolve_species_name('Mus musculus domesticus', True)
        self.assertIsNotNone(result)
    
    @my_vcr.use_cassette('gbif_low_confidence.yaml')
    def test_gbif_low_confidence_fallback(self):
        """Test fallback when GBIF confidence is too low"""
        result = di.resolve_species_name('SomeFakeSpecies xyz123', True)
        # Should fall back to normalized input
        self.assertIsNotNone(result)

class SequenceModelTests(SimpleTestCase):
    def test_sequence_has_scientific_name_field(self):
        # Ensure the Sequence model includes the new scientific_name field
        field = models.Sequence._meta.get_field('scientific_name')
        self.assertIsNotNone(field)


class ExcelImportTests(TestCase):
    """
    Integration test: build an in-memory Excel file with one row each
    for FullText, Descriptive, Host, and Pathogen, then run the
    Excel handler to import them and verify DB objects and id_mapping.
    Also tests duplicate import handling.
    """
    @my_vcr.use_cassette('gbif_excel_import.yaml')
    def test_import_from_excel(self):
        # Use a previously-created Excel file `test.xlsx` placed next to this test file.
        test_xlsx_path = os.path.join(os.path.dirname(__file__), 'test.xlsx')
        self.assertTrue(os.path.exists(test_xlsx_path), f"test.xlsx not found at {test_xlsx_path}; create the file with the expected sheets to run this test.")

        # Prepare empty id_mapping as expected by the import functions
        id_mapping = {
            'inclusion_full_text': {},
            'descriptive': {},
            'host': {},
            'pathogen': {},
            'sequence': {},
        }

        with open(test_xlsx_path, 'rb') as fh:
            logs = list(di.handle_excel_upload(fh, id_mapping, verbose=True))
        
        self.assertIsNotNone(logs)
        # Verify FullText created and mapped
        ft = models.FullText.objects.all()
        self.assertEqual(ft.count(), 3)
        ft = models.FullText.objects.filter(title='Comparative analysis of rodent and small mammal viromes to better understand the wildlife origin of emerging infectious diseases.').first()
        self.assertIsNotNone(ft)
        self.assertIn('ft_1', id_mapping['inclusion_full_text'])

        # Verify Descriptive created and mapped
        desc = models.Descriptive.objects.all()
        self.assertEqual(desc.count(), 2)
        desc = models.Descriptive.objects.filter(dataset_name='Pygmy rice rat as potential host of Castelo dos Sonhos Hantavirus.').first()
        self.assertIsNotNone(desc)
        self.assertIn('ds_348', id_mapping['descriptive'])

        # Verify Host created and mapped (note Oligoryzomys NOT Olygoryzomys)
        host = models.Host.objects.filter(scientific_name='Olygoryzomys utiaritensis').first()
        self.assertIsNone(host)
        host = models.Host.objects.filter(scientific_name='Oligoryzomys utiaritensis').first()
        self.assertIsNotNone(host)
        self.assertIn('48248', id_mapping['host'])

        # Verify Pathogen created, mapped, and linked to Host
        path = models.Pathogen.objects.filter(scientific_name='ANDV').first()
        self.assertIsNotNone(path)
        self.assertIn('60632', id_mapping['pathogen'])
        self.assertIsNotNone(path.host)
        self.assertEqual(path.host.id, host.id)
        
        # Verify Sequence created, mapped, and linked to Host
        seqc = models.Sequence.objects.filter(accession_number='MW174777').first()
        self.assertIsNotNone(seqc)
        self.assertIn('1006', id_mapping['sequence'])
        self.assertIsNotNone(seqc.pathogen)
        path = models.Pathogen.objects.filter(scientific_name='Wenzhou virus').first()
        self.assertEqual(seqc.pathogen.id, path.id)
        
        # Test duplication handling
        with open(test_xlsx_path, 'rb') as fh:
            logs = list(di.handle_excel_upload(fh, id_mapping, verbose=True))
        
        ft = models.FullText.objects.all()
        self.assertEqual(ft.count(), 3)

        desc = models.Descriptive.objects.all()
        self.assertEqual(desc.count(), 2)

        host = models.Host.objects.all()
        self.assertEqual(host.count(), 2)
        
        path = models.Pathogen.objects.all()
        self.assertEqual(path.count(), 2)
        
        seqc = models.Sequence.objects.all()
        self.assertEqual(seqc.count(), 1)
