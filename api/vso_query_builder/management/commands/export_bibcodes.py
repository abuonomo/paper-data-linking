"""Export all bibcodes in the database (one per line).

Usage: python manage.py export_bibcodes > existing_bibcodes.txt
"""

from django.core.management.base import BaseCommand

from ...models import Paper


class Command(BaseCommand):
    help = "Export all bibcodes in the database (one per line)"

    def handle(self, *args, **options):
        for bibcode in Paper.objects.values_list("bibcode", flat=True).order_by("bibcode"):
            self.stdout.write(bibcode)
