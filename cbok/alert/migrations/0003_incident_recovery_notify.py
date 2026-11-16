from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('alert', '0002_anomalytype_detectorcheck_modelprofile_and_more')]

    operations = [
        migrations.AddField(
            model_name='incident', name='recovery_notify',
            field=models.BooleanField(default=False),
        ),
    ]
