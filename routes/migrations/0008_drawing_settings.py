# Generated for MVP step 15

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('routes', '0007_drawing_drawingobject'),
    ]

    operations = [
        migrations.AddField(
            model_name='drawing',
            name='settings',
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
