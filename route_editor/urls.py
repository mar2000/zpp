from django.contrib import admin
from django.urls import path, include
from django.contrib.auth import views as auth_views
from routes import views as route_views
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [

    path('', route_views.DrawingListView.as_view(), name='home'),
    path('drawings/', route_views.DrawingListView.as_view(), name='drawing_list'),
    path('drawings/create/', route_views.DrawingCreateView.as_view(), name='drawing_create'),
    path('drawings/import/', route_views.import_drawing_json, name='drawing_import_json'),
    path('drawings/<int:pk>/', route_views.DrawingDetailView.as_view(), name='drawing_detail'),
    path('drawings/<int:pk>/delete/', route_views.DrawingDeleteView.as_view(), name='drawing_delete'),
    path('drawings/<int:pk>/duplicate/', route_views.duplicate_drawing, name='drawing_duplicate'),
    path('drawings/<int:pk>/export/tikz/', route_views.export_drawing_tikz, name='drawing_export_tikz'),
    path('drawings/<int:pk>/export/json/', route_views.export_drawing_json, name='drawing_export_json'),
    path('drawings/<int:pk>/export/tikz/preview/', route_views.drawing_tikz_preview, name='drawing_tikz_preview'),
    path('drawings/<int:pk>/settings/', route_views.drawing_settings_api, name='drawing_settings_api'),
    path('drawings/<int:drawing_id>/objects/', route_views.drawing_objects_collection, name='drawing_objects_collection'),
    path('drawings/<int:drawing_id>/objects/<str:object_id>/', route_views.drawing_object_detail, name='drawing_object_detail'),
    path('admin/', admin.site.urls),
    path('login/', auth_views.LoginView.as_view(template_name='routes/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('register/', route_views.register, name='register'),
    
    # Legacy graph-route editor kept for reference/migration, but hidden from the main UI.
    path('legacy/routes/', route_views.RouteListView.as_view(), name='route_list'),
    path('legacy/routes/create/', route_views.RouteCreateView.as_view(), name='route_create'),
    path('legacy/routes/<int:pk>/', route_views.RouteDetailView.as_view(), name='route_detail'),
    path('legacy/routes/<int:pk>/delete/', route_views.RouteDeleteView.as_view(), name='route_delete'),
    path('legacy/routes/<int:route_id>/add_point/', route_views.add_point, name='add_point'),
    path('legacy/routes/<int:route_id>/add_edge/', route_views.add_edge, name='add_edge'),
    path('legacy/routes/<int:route_id>/export/latex/', route_views.export_latex, name='export_latex'),
    path('legacy/routes/<int:route_id>/export/png/', route_views.export_png, name='export_png'),
    path('legacy/routes/<int:route_id>/update_style/', route_views.update_route_style, name='update_route_style'),
    path('legacy/points/<int:pk>/delete/', route_views.delete_point, name='delete_point'),
    path('legacy/edges/<int:pk>/delete/', route_views.delete_edge, name='delete_edge'),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
