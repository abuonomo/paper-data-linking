from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("vso_query_builder", "0055_add_configuration_to_paper_analysis"),
    ]

    operations = [
        migrations.AddField(
            model_name="datasetusage",
            name="configuration_name",
            field=models.CharField(
                max_length=50,
                null=True,
                blank=True,
                help_text="LLM configuration used when creating this usage",
            ),
        ),
    ]

