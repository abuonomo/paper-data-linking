from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('vso_query_builder', '0077_remove_paper_name_from_instrument_mention'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='DatasetUsageValidation',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('anonymous_id', models.UUIDField(blank=True, help_text='Client-generated UUID for anonymous tracking (used when user is null)', null=True)),
                ('validation_status', models.CharField(choices=[('approved', 'Approved'), ('rejected', 'Rejected'), ('needs_review', 'Needs Review')], max_length=20)),
                ('validation_notes', models.TextField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('dataset_usage', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='validations', to='vso_query_builder.datasetusage')),
                ('user', models.ForeignKey(blank=True, help_text='Authenticated user who submitted this validation (null for anonymous)', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='dataset_usage_validations', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Dataset Usage Validation',
                'verbose_name_plural': 'Dataset Usage Validations',
            },
        ),
        migrations.AddConstraint(
            model_name='datasetusagevalidation',
            constraint=models.UniqueConstraint(condition=models.Q(user__isnull=False), fields=['dataset_usage', 'user'], name='unique_user_validation'),
        ),
        migrations.AddConstraint(
            model_name='datasetusagevalidation',
            constraint=models.UniqueConstraint(condition=models.Q(user__isnull=True), fields=['dataset_usage', 'anonymous_id'], name='unique_anon_validation'),
        ),
        migrations.AddIndex(
            model_name='datasetusagevalidation',
            index=models.Index(fields=['dataset_usage', 'created_at'], name='dsuv_dataset_created_idx'),
        ),
    ]
