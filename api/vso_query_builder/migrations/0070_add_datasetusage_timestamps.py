import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('vso_query_builder', '0069_paper_tags_jsonfield_to_arrayfield'),
    ]

    operations = [
        migrations.AddField(
            model_name='datasetusage',
            name='created_at',
            field=models.DateTimeField(auto_now_add=True, default=django.utils.timezone.now),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='datasetusage',
            name='updated_at',
            field=models.DateTimeField(auto_now=True),
        ),
    ]
