from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0006_remove_user_bio'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='show_on_website',
            field=models.BooleanField(default=False),
        ),
    ]