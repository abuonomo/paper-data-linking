from django.core.management.base import BaseCommand, CommandError

from vso_query_builder.models import Paper
from vso_query_builder.tasks import analyze_paper_task

class Command(BaseCommand):
    help = 'Run paper analysis on specified papers with a given model configuration'

    def add_arguments(self, parser):
        parser.add_argument(
            '--model',
            type = str,
            required = True,
            # May be better to dynamically fetch the current configured models incase new ones are added in the future. 
            choices = ['standard', 'budget', 'super-budget', 'hybrid', 'bedrock-test'],
            help = "LLM configuration name"
        )

        parser.add_argument(
            '--file',
            type = str,
            required = True,
            help = "Path to file containg a bibcodes for paper analysis task"
        )

    def handle(self, *args, **options):
        model_name = options['model']
        file_path = options['file']

        try:
            with open(file_path, 'r') as f:
                bibcodes = [line.strip() for line in f if line.strip()]
                self.stdout.write(f"Starting analysis for {len(bibcodes)} papers with model: {model_name}")

                for count, bibcode in enumerate(bibcodes, start=1):
                    try: 
                        cur_paper = Paper.objects.get(bibcode=bibcode)
                        self.stdout.write(f"Starting ({count}) paper analysis for bibcode: {bibcode}")
                        analyze_paper_task.delay(str(cur_paper.id), model_name)
                    except Paper.DoesNotExist:
                        self.stdout.write(f"WARNING: Paper not found for bibcode: {bibcode}")

        except FileNotFoundError:
            raise CommandError(f"File not found {file_path}")
