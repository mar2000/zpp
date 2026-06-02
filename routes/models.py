from django.db import models
from django.contrib.auth.models import User

class BackgroundImage(models.Model):
    title = models.CharField(max_length=100)
    image = models.ImageField(upload_to='backgrounds/')
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title

class Route(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    title = models.CharField(max_length=100)
    background = models.ForeignKey(BackgroundImage, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    vertex_color = models.CharField(max_length=7, default='#FF0000')  # czerwony
    vertex_text_color = models.CharField(max_length=7, default='#FFFFFF')  # biały
    edge_color = models.CharField(max_length=7, default='#0000FF')  # niebieski

    def __str__(self):
        return f"{self.title} (by {self.user.username})"

class Point(models.Model):
    route = models.ForeignKey(Route, on_delete=models.CASCADE, related_name='points')
    x = models.IntegerField()
    y = models.IntegerField()
    order = models.IntegerField()

    class Meta:
        ordering = ['order']

    def __str__(self):
        return f"Point ({self.x}, {self.y}) in {self.route.title}"

class Edge(models.Model):
    route = models.ForeignKey(Route, on_delete=models.CASCADE, related_name='edges')
    start_point = models.ForeignKey(Point, on_delete=models.CASCADE, related_name='start_edges')
    end_point = models.ForeignKey(Point, on_delete=models.CASCADE, related_name='end_edges')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']
        unique_together = [['route', 'start_point', 'end_point']]

    def __str__(self):
        return f"Edge from {self.start_point.id} to {self.end_point.id} in {self.route.title}"


class Drawing(models.Model):
    """Ogólny rysunek użytkownika.

    Ten model jest fundamentem pod przyszłe tryby pracy: grafy, geometrię,
    wykresy i pluginy. Na razie działa obok istniejących modeli Route/Point/Edge,
    żeby nie zepsuć obecnego edytora grafowego.
    """
    MODE_GRAPH = 'graph'
    MODE_GEOMETRY = 'geometry'
    MODE_PLOT = 'plot'
    MODE_MIXED = 'mixed'

    # MODE_MIXED zostaje jako stała techniczna dla starszych rysunków,
    # ale nie jest już dostępny w formularzu tworzenia nowych rysunków.
    MODE_CHOICES = [
        (MODE_GRAPH, 'Graf'),
        (MODE_GEOMETRY, 'Geometria'),
        (MODE_PLOT, 'Wykresy'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='drawings')
    title = models.CharField(max_length=120)
    mode = models.CharField(max_length=30, choices=MODE_CHOICES, default=MODE_GRAPH)
    metadata = models.JSONField(default=dict, blank=True)
    settings = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at', '-created_at']

    def __str__(self):
        return f"{self.title} ({self.mode}) by {self.user.username}"


class DrawingObject(models.Model):
    """Pojedynczy obiekt strukturalnego rysunku.

    type jest namespacowany, np. graph.vertex, graph.edge, geometry.circle.
    data przechowuje dane zależne od typu obiektu, a style informacje wizualne.
    """
    drawing = models.ForeignKey(Drawing, on_delete=models.CASCADE, related_name='drawing_objects')
    object_id = models.CharField(max_length=64)
    type = models.CharField(max_length=100)
    data = models.JSONField(default=dict, blank=True)
    style = models.JSONField(default=dict, blank=True)
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['order', 'id']
        constraints = [
            models.UniqueConstraint(
                fields=['drawing', 'object_id'],
                name='unique_object_id_per_drawing',
            )
        ]

    def __str__(self):
        return f"{self.object_id}: {self.type} in {self.drawing.title}"
