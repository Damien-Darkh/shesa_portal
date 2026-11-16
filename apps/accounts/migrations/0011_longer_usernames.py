from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0010_identity_id'),
    ]

    operations = [
        migrations.AlterField(
            model_name='user',
            name='dsm_username',
            field=models.CharField(blank=True, max_length=255, null=True, unique=True),
        ),
        migrations.AlterField(
            model_name='user',
            name='authentik_username',
            field=models.CharField(blank=True, max_length=255, null=True, unique=True),
        ),
    ]