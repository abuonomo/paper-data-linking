import os
from django.core.management.base import BaseCommand
from django.core.files import File
from ...models import Paper


class Command(BaseCommand):
    help = 'Bulk upload papers from a directory'

    def add_arguments(self, parser):
        parser.add_argument('directory', type=str, help='Directory containing PDF files. This command assumes that the PDF filenames (without the .pdf extension) are the bibcodes.')

    def handle(self, *args, **options):
        directory = options['directory']
        skipped = []
        imported = 0
        for filename in os.listdir(directory):
            if filename.endswith(".pdf"):
                bibcode = os.path.splitext(filename)[0]  # Assumes filename (without .pdf) is the bibcode
                filepath = os.path.join(directory, filename)

                if Paper.objects.filter(bibcode=bibcode).exists():
                    skipped.append(bibcode)
                    self.stdout.write(self.style.WARNING(f'Skipped {filename}: bibcode already exists'))
                    continue

                paper = Paper.objects.create(bibcode=bibcode)
                with open(filepath, 'rb') as f:
                    paper.pdf.save(filename, File(f))
                imported += 1
                self.stdout.write(self.style.SUCCESS(f'Successfully uploaded {filename}'))

        self.stdout.write(self.style.SUCCESS(f'Import completed. {imported} papers imported.'))
        if skipped:
            self.stdout.write(
                self.style.WARNING(f'Skipped {len(skipped)} papers (bibcodes already exist): {", ".join(skipped)}'))