# Generated manually during MVP step 28.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('routes', '0009_alter_drawing_mode_default'),
    ]

    operations = [
        migrations.AlterField(
            model_name='drawing',
            name='mode',
            field=models.CharField(choices=[('graph', 'Graf'), ('geometry', 'Geometria'), ('plot', 'Wykresy')], default='graph', max_length=30),
        ),
    ]
