from django.core.management.base import BaseCommand
from ...models import Paper  # Replace with your actual app and model name


class Command(BaseCommand):
    help = 'Removes Paper entries with bibcodes starting with "._"'

    def handle(self, *args, **options):
        invalid_papers = Paper.objects.filter(bibcode__startswith='._')
        count = invalid_papers.count()

        for paper in invalid_papers:
            if paper.pdf:
                # Delete the file from storage
                paper.pdf.delete(save=False)
            # Delete the database entry
            paper.delete()

        self.stdout.write(self.style.SUCCESS(f'Successfully removed {count} invalid paper entries'))