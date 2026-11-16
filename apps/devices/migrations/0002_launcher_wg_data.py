from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('devices', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='device',
            name='launcher_wg_data',
            field=models.JSONField(blank=True, null=True),
        ),
    ]