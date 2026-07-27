from django.db import migrations, models


class Migration(migrations.Migration):
    """
    matched_instrument_code and matched_mission_code were added to the model
    in a previous deployment without a committed migration file, so the columns
    may already exist. Using IF NOT EXISTS makes this idempotent.
    """

    dependencies = [
        ('vso_query_builder', '0089_phenomenonmention_supporting_quotes_m2m'),
    ]

    operations = [
        migrations.RunSQL(
            sql=[
                "ALTER TABLE vso_query_builder_phenomenonmention ADD COLUMN IF NOT EXISTS matched_instrument_code varchar(255) NULL;",
                "ALTER TABLE vso_query_builder_phenomenonmention ADD COLUMN IF NOT EXISTS matched_mission_code varchar(255) NULL;",
            ],
            reverse_sql=[
                "ALTER TABLE vso_query_builder_phenomenonmention DROP COLUMN IF EXISTS matched_instrument_code;",
                "ALTER TABLE vso_query_builder_phenomenonmention DROP COLUMN IF EXISTS matched_mission_code;",
            ],
            state_operations=[
                migrations.AddField(
                    model_name='phenomenonmention',
                    name='matched_instrument_code',
                    field=models.CharField(blank=True, max_length=255, null=True),
                ),
                migrations.AddField(
                    model_name='phenomenonmention',
                    name='matched_mission_code',
                    field=models.CharField(blank=True, max_length=255, null=True),
                ),
            ],
        ),
    ]
