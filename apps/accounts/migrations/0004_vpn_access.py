from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0003_authentik_username'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='vpn_access',
            field=models.BooleanField(default=False),
        ),
    ]