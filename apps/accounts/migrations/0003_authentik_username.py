from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0002_language_photo_text'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='authentik_username',
            field=models.CharField(blank=True, max_length=150, null=True, unique=True),
        ),
    ]