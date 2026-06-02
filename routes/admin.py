from django.contrib import admin
from .models import BackgroundImage, Route, Point, Edge, Drawing, DrawingObject

class PointInline(admin.TabularInline):
    model = Point
    extra = 0

class EdgeInline(admin.TabularInline):
    model = Edge
    extra = 0
    fk_name = 'route'

@admin.register(Route)
class RouteAdmin(admin.ModelAdmin):
    list_display = ('title', 'user', 'background', 'created_at')
    list_filter = ('user', 'background')
    inlines = [PointInline, EdgeInline]

@admin.register(BackgroundImage)
class BackgroundImageAdmin(admin.ModelAdmin):
    list_display = ('title', 'uploaded_at')

@admin.register(Point)
class PointAdmin(admin.ModelAdmin):
    list_display = ('route', 'x', 'y', 'order')


@admin.register(Edge)
class EdgeAdmin(admin.ModelAdmin):
    list_display = ('id', 'route', 'start_point', 'end_point', 'created_at')
    list_filter = ('route',)



class DrawingObjectInline(admin.TabularInline):
    model = DrawingObject
    extra = 0
    fields = ('object_id', 'type', 'order', 'data', 'style')


@admin.register(Drawing)
class DrawingAdmin(admin.ModelAdmin):
    list_display = ('title', 'user', 'mode', 'created_at', 'updated_at')
    list_filter = ('mode', 'user')
    search_fields = ('title', 'user__username')
    inlines = [DrawingObjectInline]


@admin.register(DrawingObject)
class DrawingObjectAdmin(admin.ModelAdmin):
    list_display = ('object_id', 'type', 'drawing', 'order', 'updated_at')
    list_filter = ('type', 'drawing__mode')
    search_fields = ('object_id', 'type', 'drawing__title')
