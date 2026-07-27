from django.core.management.base import BaseCommand
from vso_query_builder.models import SupportQuote
from litellm import completion_cost
from openai import OpenAI
import time


class Command(BaseCommand):
    help = 'Calculate costs and generate embeddings for quotes'

    def handle(self, *args, **kwargs):
        quotes = SupportQuote.objects.filter(embedding__isnull=True)
        texts = [q.quote for q in quotes]

        # Calculate cost
        estimated_cost = completion_cost(
            model="text-embedding-3-small",
            prompt="\n".join(texts)
        )

        self.stdout.write(f"Found {len(quotes)} quotes without embeddings")
        self.stdout.write(f"Estimated cost: ${estimated_cost:.4f}")

        confirm = input("Continue? [y/N]: ")
        if confirm.lower() != 'y':
            return

        # Generate embeddings in batches
        client = OpenAI()
        batch_size = 100

        for i in range(0, len(quotes), batch_size):
            batch = quotes[i:i + batch_size]
            response = client.embeddings.create(
                model="text-embedding-3-small",
                input=[q.quote for q in batch]
            )

            # Update quotes
            for quote, embedding_data in zip(batch, response.data):
                quote.embedding = embedding_data.embedding

            SupportQuote.objects.bulk_update(batch, ['embedding'])
            time.sleep(0.5)  # Rate limiting
            self.stdout.write(f"Processed {i + len(batch)}/{len(quotes)} quotes")