# signals.py
from django.db.models.signals import post_save
from django.dispatch import receiver
from openai import OpenAI
from django.conf import settings
import logging

from .models import SupportQuote, Instrument
from paper_data_linking.config.settings import get_llm_configuration

INSTRUMENT_EMBEDDINGS_MODEL = get_llm_configuration("standard").embeddings.model

logger = logging.getLogger(__name__)
client = OpenAI(api_key=settings.OPENAI_API_KEY)


@receiver(post_save, sender=SupportQuote)
def create_embedding(sender, instance, created, **kwargs):
    """Create embedding when a new SupportQuote is created or when it's saved without an embedding"""
    if instance.embedding is None:  # This catches both new instances and updates without embeddings
        # Corpus-mode commits defer ALL embeddings to the embed_missing_quotes
        # bulk sweep — one synchronous OpenAI call per quote inside the commit
        # loop is exactly the hot-path cost corpus mode exists to avoid. Gating
        # here (not at each creation site) covers every quote-creation path
        # structurally; interactive/research behavior is unchanged.
        from .tasks import _in_corpus_mode_commit   # lazy: avoids import cycle
        if _in_corpus_mode_commit():
            return
        try:
            response = client.embeddings.create(
                input=[instance.quote],
                model='text-embedding-3-small'
            )
            embedding = response.data[0].embedding

            # Update without triggering the signal again
            SupportQuote.objects.filter(id=instance.id).update(embedding=embedding)
            logger.info(f"Created embedding for SupportQuote {instance.id}")

        except Exception as e:
            logger.error(f"Failed to create embedding for SupportQuote {instance.id}: {str(e)}")


@receiver(post_save, sender=Instrument)
def update_instrument_embedding(sender, instance, created, **kwargs):
    """Regenerate embedding when Instrument description changes"""
    
    # Only regenerate embedding if description has content and either:
    # 1. It's a new instrument without embedding
    # 2. It's an existing instrument and description was updated
    if instance.description and (instance.embedding is None or not created):
        try:
            logger.info(f"Regenerating embedding for Instrument {instance.short_name} ({instance.id})")
            
            response = client.embeddings.create(
                input=[instance.description],
                model=INSTRUMENT_EMBEDDINGS_MODEL
            )
            embedding = response.data[0].embedding

            # Update without triggering the signal again using update()
            Instrument.objects.filter(id=instance.id).update(embedding=embedding)
            logger.info(f"Successfully updated embedding for Instrument {instance.short_name}")

        except Exception as e:
            logger.error(f"Failed to create embedding for Instrument {instance.id}: {str(e)}")