from django.urls import path, include
from django.contrib.auth import views as auth_views
from rest_framework.routers import DefaultRouter
from .views import *

router = DefaultRouter()
router.register(r'fulltext', FullTextViewSet)
router.register(r'descriptive', DescriptiveViewSet)
router.register(r'rodents', HostViewSet)
router.register(r'pathogens', PathogenViewSet)
router.register(r'sequences', SequenceViewSet)
router.register(r'unified', UnifiedViewSet, basename="unified")

urlpatterns = [
    path("", index, name="index"),
    path('fulltext/<int:pk>/', fulltext_detail, name='fulltext_detail'),
    path('descriptive/<int:pk>/', descriptive_detail, name='descriptive_detail'),
    path('host/<int:pk>/', host_detail, name='host_detail'),
    path('pathogen/<int:pk>/', pathogen_detail, name='pathogen_detail'),
    path('sequence/<int:pk>/', sequence_detail, name='sequence_detail'),
    path('api/', include(router.urls)),
    path('api/host-geojson/', host_geojson_api, name='host_geojson_api'),
    path('search/', search_view, name='search'),
    path('upload_data/', upload_data, name='upload_data'),
    path('login/', auth_views.LoginView.as_view(template_name='registration/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('register/', register, name='register'),
    path('map/', map, name='map'),
]