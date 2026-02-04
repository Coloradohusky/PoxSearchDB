from django.urls import path, include
from django.contrib.auth import views as auth_views
from .utils.unified_viewset import UnifiedViewSet
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r"fulltext", views.FullTextViewSet)
router.register(r"descriptive", views.DescriptiveViewSet)
router.register(r"rodents", views.HostViewSet)
router.register(r"pathogens", views.PathogenViewSet)
router.register(r"sequences", views.SequenceViewSet)
router.register(r"unified", UnifiedViewSet, basename="unified")

urlpatterns = [
    path("", views.index, name="index"),
    path("fulltext/<int:pk>/", views.fulltext_detail, name="fulltext_detail"),
    path("descriptive/<int:pk>/", views.descriptive_detail, name="descriptive_detail"),
    path("host/<int:pk>/", views.host_detail, name="host_detail"),
    path("pathogen/<int:pk>/", views.pathogen_detail, name="pathogen_detail"),
    path("sequence/<int:pk>/", views.sequence_detail, name="sequence_detail"),
    path("api/", include(router.urls)),
    path("api/host-geojson/", views.host_geojson_api, name="host_geojson_api"),
    path("search/", views.search_view, name="search"),
    path("upload_data/", views.upload_data, name="upload_data"),
    path(
        "login/",
        auth_views.LoginView.as_view(template_name="registration/login.html"),
        name="login",
    ),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("register/", views.register, name="register"),
    path("map/", views.map, name="map"),
]
