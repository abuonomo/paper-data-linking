from django.db import migrations, models
import django.contrib.postgres.fields
import django.contrib.postgres.indexes


class Migration(migrations.Migration):

    dependencies = [
        ('vso_query_builder', '0068_add_batchjob_aws_region'),
    ]

    operations = [
        # Step 1: add a temporary array column
        migrations.AddField(
            model_name='paper',
            name='tags_new',
            field=django.contrib.postgres.fields.ArrayField(
                base_field=models.CharField(max_length=100),
                default=list,
                blank=True,
            ),
        ),
        # Step 2: copy data from JSONB → native array in a single SQL pass
        migrations.RunSQL(
            sql="""
                UPDATE vso_query_builder_paper
                SET tags_new = CASE
                    WHEN tags IS NULL THEN ARRAY[]::varchar[]
                    ELSE ARRAY(SELECT jsonb_array_elements_text(tags))
                END
            """,
            reverse_sql="""
                UPDATE vso_query_builder_paper
                SET tags = to_jsonb(tags_new)
            """,
        ),
        # Step 3: drop the old JSON column
        migrations.RemoveField(
            model_name='paper',
            name='tags',
        ),
        # Step 4: rename the temp column to 'tags'
        migrations.RenameField(
            model_name='paper',
            old_name='tags_new',
            new_name='tags',
        ),
        # Step 5: add GIN index for fast array containment queries
        migrations.AddIndex(
            model_name='paper',
            index=django.contrib.postgres.indexes.GinIndex(
                fields=['tags'],
                name='paper_tags_gin_idx',
            ),
        ),
    ]
