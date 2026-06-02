from django.urls import path
from . import views

urlpatterns = [

    path('', views.DrawingListView.as_view(), name='home'),
    path('drawings/', views.DrawingListView.as_view(), name='drawing_list'),
    path('drawings/create/', views.DrawingCreateView.as_view(), name='drawing_create'),
    path('drawings/import/', views.import_drawing_json, name='drawing_import_json'),
    path('drawings/<int:pk>/', views.DrawingDetailView.as_view(), name='drawing_detail'),
    path('drawings/<int:pk>/delete/', views.DrawingDeleteView.as_view(), name='drawing_delete'),
    path('drawings/<int:pk>/duplicate/', views.duplicate_drawing, name='drawing_duplicate'),
    path('drawings/<int:pk>/export/tikz/', views.export_drawing_tikz, name='drawing_export_tikz'),
    path('drawings/<int:pk>/export/json/', views.export_drawing_json, name='drawing_export_json'),
    path('drawings/<int:pk>/export/tikz/preview/', views.drawing_tikz_preview, name='drawing_tikz_preview'),
    path('drawings/<int:pk>/settings/', views.drawing_settings_api, name='drawing_settings_api'),
    path('drawings/<int:drawing_id>/objects/', views.drawing_objects_collection, name='drawing_objects_collection'),
    path('drawings/<int:drawing_id>/objects/<str:object_id>/', views.drawing_object_detail, name='drawing_object_detail'),
    # Legacy graph-route editor kept for reference/migration, but hidden from the main UI.
    path('legacy/routes/', views.RouteListView.as_view(), name='route_list'),
    path('legacy/routes/create/', views.RouteCreateView.as_view(), name='route_create'),
    path('legacy/routes/<int:pk>/', views.RouteDetailView.as_view(), name='route_detail'),
    path('legacy/routes/<int:pk>/delete/', views.RouteDeleteView.as_view(), name='route_delete'),
    path('legacy/routes/<int:route_id>/add_point/', views.add_point, name='add_point'),
    path('legacy/routes/<int:route_id>/add_edge/', views.add_edge, name='add_edge'),
    path('legacy/routes/<int:route_id>/export/latex/', views.export_latex, name='export_latex'),
    path('legacy/routes/<int:route_id>/export/png/', views.export_png, name='export_png'),
    path('legacy/routes/<int:route_id>/update_style/', views.update_route_style, name='update_route_style'),
    path('legacy/points/<int:pk>/delete/', views.delete_point, name='delete_point'),
    path('legacy/edges/<int:pk>/delete/', views.delete_edge, name='delete_edge'),
]
