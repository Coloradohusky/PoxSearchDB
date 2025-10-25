from django.contrib.gis import admin

from .models import FullText, Descriptive, Host, Pathogen, Sequence

from django.contrib import admin
from leaflet.admin import LeafletGeoAdmin

admin.site.register(FullText)
admin.site.register(Descriptive)
admin.site.register(Host)
admin.site.register(Pathogen)
admin.site.register(Sequence)