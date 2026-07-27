from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('vso_query_builder', '0088_add_supporting_quote_to_phenomenon_mention'),
    ]

    operations = [
        migrations.AddField(
            model_name='phenomenonmention',
            name='supporting_quotes',
            field=models.ManyToManyField(
                blank=True,
                help_text='All physobs supporting quotes collected across periods for this instrument/phenomenon pair',
                related_name='phenomenon_mention_set',
                to='vso_query_builder.supportquote',
            ),
        ),
    ]
