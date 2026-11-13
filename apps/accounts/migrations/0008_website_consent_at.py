from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0007_show_on_website'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='website_consent_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]