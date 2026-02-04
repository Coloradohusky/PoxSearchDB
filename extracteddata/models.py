from django.contrib.gis.db import models


class FullText(models.Model):
    id = models.IntegerField(primary_key=True)
    original_id = models.CharField(max_length=25)
    extractor = models.CharField(max_length=500, blank=True, null=True)
    community = models.CharField(max_length=500, blank=True, null=True)
    spatio_temporal_extraction = models.CharField(max_length=500, blank=True, null=True)
    decision = models.CharField(max_length=500, blank=True, null=True)
    reason = models.TextField(blank=True, null=True)
    key = models.CharField(max_length=50, blank=True, null=True)
    publication_year = models.PositiveIntegerField(blank=True, null=True)
    author = models.CharField(max_length=1000, blank=True, null=True)
    title = models.TextField()
    processed = models.BooleanField(default=False)

    def __str__(self):
        return f"ft_{self.id} - {self.title}"


class Descriptive(models.Model):
    id = models.IntegerField(primary_key=True)
    original_id = models.CharField(max_length=25)
    full_text = models.ForeignKey(
        FullText,
        on_delete=models.CASCADE,
        related_name="descriptive_records",
        null=True,
        blank=False,
    )
    dataset_name = models.CharField(max_length=500, blank=True, null=True)
    sampling_effort = models.CharField(max_length=500, blank=True, null=True)
    data_access = models.CharField(max_length=100, blank=True, null=True)
    data_resolution = models.CharField(max_length=100, blank=True, null=True)
    linked_manuscripts = models.TextField(blank=True, null=True)
    notes = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"ds_{self.id} - {self.dataset_name}"


class Host(models.Model):
    id = models.IntegerField(primary_key=True)
    original_id = models.CharField(max_length=25)
    study = models.ForeignKey(
        Descriptive,
        on_delete=models.CASCADE,
        related_name="rodents",
        null=True,
        blank=False,
    )
    scientific_name = models.CharField(max_length=500, blank=True, null=True)
    event_date = models.CharField(max_length=500, blank=True, null=True)
    locality = models.CharField(max_length=500, blank=True, null=True)
    country = models.CharField(max_length=100, blank=True, null=True)
    verbatim_locality = models.CharField(max_length=500, blank=True, null=True)
    coordinate_resolution = models.CharField(max_length=100, blank=True, null=True)
    location_latitude = models.FloatField(blank=True, null=True)
    location_longitude = models.FloatField(blank=True, null=True)
    individual_count = models.PositiveIntegerField()
    trap_effort = models.PositiveIntegerField(blank=True, null=True)
    trap_effort_resolution = models.CharField(max_length=500, blank=True, null=True)

    def __str__(self):
        return f"{self.scientific_name} ({self.locality})"


class Pathogen(models.Model):
    id = models.IntegerField(primary_key=True)
    original_id = models.CharField(max_length=25)
    host = models.ForeignKey(
        Host, on_delete=models.CASCADE, related_name="pathogens", null=True, blank=False
    )
    family = models.CharField(max_length=500, blank=True, null=True)
    scientific_name = models.CharField(max_length=500, blank=True, null=True)
    assay = models.CharField(max_length=500, blank=True, null=True)
    tested = models.PositiveIntegerField(blank=True, null=True)
    positive = models.PositiveIntegerField(blank=True, null=True)
    negative = models.PositiveIntegerField(blank=True, null=True)
    number_inconclusive = models.PositiveIntegerField(blank=True, null=True)
    note = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"{self.scientific_name} ({self.family})"


class Sequence(models.Model):
    id = models.IntegerField(primary_key=True)
    original_id = models.CharField(max_length=25)
    scientific_name = models.CharField(max_length=500, blank=True, null=True)
    associated_taxa = models.CharField(max_length=500, blank=True, null=True)
    sequence_type = models.CharField(max_length=100, blank=True, null=True)
    # If sequenceType is Pathogen
    pathogen = models.ForeignKey(
        Pathogen,
        on_delete=models.SET_NULL,
        related_name="sequences",
        null=True,
        blank=False,
    )
    # If sequenceType is Host
    host = models.ForeignKey(
        Host,
        on_delete=models.SET_NULL,
        related_name="sequences",
        null=True,
        blank=False,
    )
    # If obtained from humans
    study = models.ForeignKey(
        Descriptive,
        on_delete=models.SET_NULL,
        related_name="sequences",
        null=True,
        blank=False,
    )
    accession_number = models.CharField(max_length=500, blank=True, null=True)
    method = models.CharField(max_length=500, blank=True, null=True)
    note = models.TextField(blank=True, null=True)
    date_sampled = models.DateField(blank=True, null=True)
    sample_location = models.CharField(max_length=500, blank=True, null=True)

    def __str__(self):
        return f"Sequence {self.id} ({self.accession_number})"
