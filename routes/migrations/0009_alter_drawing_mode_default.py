# Generated manually during MVP step 24.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('routes', '0008_drawing_settings'),
    ]

    operations = [
        migrations.AlterField(
            model_name='drawing',
            name='mode',
            field=models.CharField(choices=[('graph', 'Graf'), ('geometry', 'Geometria'), ('plot', 'Wykresy'), ('mixed', 'Wszystko')], default='mixed', max_length=30),
        ),
    ]
