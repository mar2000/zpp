# Generated manually for MVP step 1: Drawing / DrawingObject

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('routes', '0006_remove_route_edge_style'),
    ]

    operations = [
        migrations.CreateModel(
            name='Drawing',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=120)),
                ('mode', models.CharField(choices=[('graph', 'Graph'), ('geometry', 'Geometry'), ('plot', 'Plot'), ('mixed', 'Mixed')], default='graph', max_length=30)),
                ('metadata', models.JSONField(blank=True, default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='drawings', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-updated_at', '-created_at'],
            },
        ),
        migrations.CreateModel(
            name='DrawingObject',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('object_id', models.CharField(max_length=64)),
                ('type', models.CharField(max_length=100)),
                ('data', models.JSONField(blank=True, default=dict)),
                ('style', models.JSONField(blank=True, default=dict)),
                ('order', models.PositiveIntegerField(default=0)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('drawing', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='drawing_objects', to='routes.drawing')),
            ],
            options={
                'ordering': ['order', 'id'],
            },
        ),
        migrations.AddConstraint(
            model_name='drawingobject',
            constraint=models.UniqueConstraint(fields=('drawing', 'object_id'), name='unique_object_id_per_drawing'),
        ),
    ]
