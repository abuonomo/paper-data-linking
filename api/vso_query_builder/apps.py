from django.apps import AppConfig


class VsoQueryBuilderConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "vso_query_builder"

    def ready(self):
        import vso_query_builder.signals  # Ensure signals are loaded

