# api/vso_query_builder/clients.py

import logging
from typing import Dict, List, Any

from django.utils import timezone

from paper_data_linking.clients.litellm_client import LiteLLMClient
from paper_data_linking.pipeline_context import (
    current_pipeline_node, pipeline_mode, current_batch_run_id, note_deferred_call,
)
from paper_data_linking.clients.batch_replay import (
    DeferredCall, canonical_request, request_hash, generation_params,
    response_format_to_forced_tool, make_response_shim,
)
from .models import LLMCall, PipelineNode, CachedLLMResponse


from functools import lru_cache


@lru_cache(maxsize=1024)
def _run_is_corpus_mode(run_id: str) -> bool:
    """Whether a batch run wants storage-lean provenance. Cached per process —
    the flag is immutable for a run's lifetime, and commit replays make ~50
    cached-completion calls per paper."""
    from .models import BatchDownstreamRun
    return bool(BatchDownstreamRun.objects.filter(id=run_id)
                .values_list('corpus_mode', flat=True).first())

logger = logging.getLogger(__name__)


class DjangoLiteLLMClient(LiteLLMClient):
    """
    Django-aware LiteLLM client that automatically creates LLMCall database records
    for every API call. Optionally associates LLMCalls with models via callback.
    """
    
    def __init__(self, association_callback=None):
        super().__init__()
        self.logger = logger
        self.association_callback = association_callback
    
    def completion(
        self,
        call_type: str,
        model: str,
        messages: List[Dict[str, str]],
        **kwargs
    ) -> Any:
        """
        Make a completion call, dispatching on the wave-batch execution mode.

        - mode 'off' (default): live LiteLLM call + LLMCall record (unchanged behavior).
        - mode 'collection': serve a resolved response from the run's durable cache,
          or register the call as pending and raise PendingBatch to defer it into the
          current batch wave. No LLMCall / live call.
        - mode 'commit': serve from the warm cache and write the LLMCall exactly once
          (falling back to a live call only on a cache miss / straggler).
        """
        mode = pipeline_mode.get()
        run_id = current_batch_run_id.get()
        if mode == 'off' or run_id is None:
            return self._completion_live(call_type, model, messages, **kwargs)

        rf = kwargs.get('response_format')
        gen = generation_params(kwargs)
        h = request_hash(canonical_request(model, messages, rf, gen))
        if mode == 'collection':
            return self._completion_collection(call_type, model, messages, run_id, h, rf, gen, kwargs)
        if mode == 'commit':
            return self._completion_commit(call_type, model, messages, run_id, h, **kwargs)
        # Unknown mode: be safe, run live.
        return self._completion_live(call_type, model, messages, **kwargs)

    def _completion_collection(self, call_type, model, messages, run_id, h, response_format, gen, kwargs):
        """Collection pass: replay resolved responses; otherwise defer (PendingBatch).

        Structured-output calls carry their schema as a FORCED tool in the batch
        payload — this is exactly how litellm enforces response_format on Bedrock
        (it never sends response_format; it forces a json_tool_call). Bedrock's batch
        honors forced tools but ignores response_format, so this is what makes
        structured output batchable — no live lane, no prompt change.
        """
        row = CachedLLMResponse.objects.filter(run_id=run_id, request_hash=h).first()
        if row is not None and row.status == 'resolved':
            u = row.usage or {}
            return make_response_shim(
                row.response_content,
                prompt_tokens=u.get('prompt_tokens', 0),
                completion_tokens=u.get('completion_tokens', 0),
                total_tokens=u.get('total_tokens', 0),
                finish_reason=row.finish_reason or 'stop',
                model=model,
            )
        if row is not None and row.status == 'failed':
            # The batch returned an error for this record; surface as a normal
            # exception so the paper is marked failed by the orchestrator.
            raise RuntimeError(f"batch LLM call failed ({h[:12]}): {row.error}")

        tools, tool_choice = response_format_to_forced_tool(response_format)
        payload = {
            'model': model, 'messages': messages,
            'params': gen, 'call_type': call_type,
            'tools': tools, 'tool_choice': tool_choice,
        }
        # Register a pending row (unique (run, request_hash) collapses identical
        # calls across papers/branches), note the deferral for the collector, and
        # raise an ORDINARY exception: the pipeline's per-branch error isolation
        # absorbs it, so sibling branches keep running and register THEIR calls
        # in this same pass (frontier discovery — waves scale with depth).
        CachedLLMResponse.objects.get_or_create(
            run_id=run_id, request_hash=h,
            defaults={'call_type': call_type, 'status': 'pending', 'request_payload': payload},
        )
        note_deferred_call()
        raise DeferredCall(h)

    def _completion_commit(self, call_type, model, messages, run_id, h, **kwargs):
        """Commit pass: serve from the warm cache and record the LLMCall once."""
        row = CachedLLMResponse.objects.filter(
            run_id=run_id, request_hash=h, status='resolved').first()
        if row is None:
            # Straggler / parse-retry / cache miss — fall back to a live call.
            return self._completion_live(call_type, model, messages, **kwargs)
        u = row.usage or {}
        shim = make_response_shim(
            row.response_content,
            prompt_tokens=u.get('prompt_tokens', 0),
            completion_tokens=u.get('completion_tokens', 0),
            total_tokens=u.get('total_tokens', 0),
            finish_reason=row.finish_reason or 'stop',
            model=model,
        )
        self._record_llm_call_from_cache(call_type, model, messages, row, kwargs)
        return shim

    def _record_llm_call_from_cache(self, call_type, model, messages, row, kwargs):
        """Create the LLMCall + associations from a cached batch response.

        Full provenance ALWAYS — including in corpus mode. Measured cost is
        ~8.5KB/call => ~360GB at 1M papers (~$30-40/mo), cheap for the audit
        record it is; and because input+output live here permanently, pruning
        the cache's payloads at run completion loses nothing.
        """
        prompt_context = kwargs.get('prompt_context')
        u = row.usage or {}
        provider = model.split('/')[0] if '/' in model else 'unknown'
        call_data = {
            "call_type": call_type,
            "model_name": model,
            "provider": provider,
            "prompt_tokens": u.get('prompt_tokens', 0),
            "completion_tokens": u.get('completion_tokens', 0),
            "total_tokens": u.get('total_tokens', 0),
            "estimated_cost_usd": self._cost_from_usage(model, u),
            "input_messages": list(messages),
            "output_content": row.response_content,
            "duration_ms": 0,
            "metadata": {
                "finish_reason": row.finish_reason,
                "source": "batch",
                "request_hash": row.request_hash,
                "batch_job_id": str(row.batch_job_id) if row.batch_job_id else None,
                "kwargs": self._serialize_kwargs(
                    {k: v for k, v in kwargs.items() if k != 'prompt_context'}),
            },
        }
        if prompt_context is not None:
            call_data["render_context"] = prompt_context
        llm_call = LLMCall.objects.create(**call_data)
        if self.association_callback:
            self.association_callback(llm_call)
        node_id = current_pipeline_node.get()
        if node_id:
            try:
                PipelineNode.objects.get(id=node_id).llm_calls.add(llm_call)
            except PipelineNode.DoesNotExist:
                pass
        return llm_call

    def _cost_from_usage(self, model: str, usage: dict):
        """Best-effort cost from cached token usage, applying the 50% batch discount."""
        try:
            import litellm
            cost_model = model.rsplit('/', 1)[-1]
            input_cost, output_cost = litellm.cost_per_token(
                model=cost_model,
                prompt_tokens=usage.get('prompt_tokens', 0),
                completion_tokens=usage.get('completion_tokens', 0),
            )
            return (input_cost + output_cost) * 0.5
        except Exception:
            return None

    def _completion_live(
        self,
        call_type: str,
        model: str,
        messages: List[Dict[str, str]],
        **kwargs
    ) -> Any:
        """Live LiteLLM completion + LLMCall record (the original behavior)."""
        try:
            # Extract prompt_context before passing to parent (parent doesn't need it)
            prompt_context = kwargs.pop('prompt_context', None)

            # Call the parent class to get response - parent now handles call_data internally
            response = super().completion(call_type, model, messages, **kwargs)

            # We need to extract call data from the response manually for database storage
            # TODO: This is a temporary workaround - we may want to refactor this
            call_data = self._extract_call_data_from_response(
                call_type, model, messages, response, prompt_context=prompt_context, **kwargs
            )
            
            # Create LLMCall database record from the call data
            llm_call = LLMCall.objects.create(**call_data)

            cost = call_data['estimated_cost_usd']
            cost_str = f"${cost:.6f}" if cost is not None else "N/A"
            self.logger.info(
                f"Created LLMCall record {llm_call.id} for {call_type} "
                f"({cost_str}, {call_data['total_tokens']} tokens)"
            )

            # Automatically associate with models if callback provided
            if self.association_callback:
                self.association_callback(llm_call)

            # Associate with current pipeline node if one is active
            node_id = current_pipeline_node.get()
            if node_id:
                try:
                    PipelineNode.objects.get(id=node_id).llm_calls.add(llm_call)
                except PipelineNode.DoesNotExist:
                    pass

            # Return only the response object - LLMCall tracking is handled internally
            return response

        except Exception as e:
            self.logger.error(
                f"Failed to create LLMCall record for {call_type}: {str(e)}"
            )
            # Re-raise the exception so calling code can handle it
            raise

    def embedding(
        self,
        call_type: str,
        model: str,
        input_text,
        **kwargs
    ):
        """
        Make a LiteLLM embedding call and automatically create an LLMCall database record.
        
        Args:
            call_type: Type of call for tracking (e.g., 'embedding_generation')
            model: LiteLLM model string (e.g., 'openai/text-embedding-ada-002')
            input_text: Text(s) to embed
            **kwargs: Additional parameters passed to litellm.embedding()
            
        Returns:
            LiteLLM response object (LLMCall creation and association handled internally)
        """
        # During throwaway collection passes, compute the embedding live (it is
        # deterministic and high-quota) but write no LLMCall — the single commit
        # pass records it exactly once, matching the synchronous path.
        if pipeline_mode.get() == 'collection' and current_batch_run_id.get() is not None:
            return super().embedding(call_type, model, input_text, **kwargs)
        try:
            # Call the parent class to get response - parent now handles call_data internally
            response = super().embedding(call_type, model, input_text, **kwargs)
            
            # We need to extract call data from the response manually for database storage
            call_data = self._extract_embedding_call_data_from_response(call_type, model, input_text, response, **kwargs)
            
            # Create LLMCall database record from the call data
            llm_call = LLMCall.objects.create(**call_data)

            cost = call_data['estimated_cost_usd']
            cost_str = f"${cost:.6f}" if cost is not None else "N/A"
            self.logger.info(
                f"Created LLMCall record {llm_call.id} for {call_type} "
                f"({cost_str}, {call_data['total_tokens']} tokens)"
            )

            # Automatically associate with models if callback provided
            if self.association_callback:
                self.association_callback(llm_call)

            # Associate with current pipeline node if one is active
            node_id = current_pipeline_node.get()
            if node_id:
                try:
                    PipelineNode.objects.get(id=node_id).llm_calls.add(llm_call)
                except PipelineNode.DoesNotExist:
                    pass

            # Return only the response object - LLMCall tracking is handled internally
            return response

        except Exception as e:
            self.logger.error(
                f"Failed to create LLMCall record for {call_type}: {str(e)}"
            )
            # Re-raise the exception so calling code can handle it
            raise

    def _extract_call_data_from_response(self, call_type: str, model: str, messages: List[Dict[str, str]], response, prompt_context=None, **kwargs) -> Dict[str, Any]:
        """Extract call data from LiteLLM response for database storage."""
        # Extract provider from model string (e.g., 'openai/gpt-4o' -> 'openai')
        provider = model.split('/')[0] if '/' in model else 'unknown'

        # Calculate estimated cost
        estimated_cost_usd = self._calculate_cost(response)

        call_data = {
            "call_type": call_type,
            "model_name": model,
            "provider": provider,
            "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
            "completion_tokens": response.usage.completion_tokens if response.usage else 0,
            "total_tokens": response.usage.total_tokens if response.usage else 0,
            "estimated_cost_usd": estimated_cost_usd,
            "input_messages": messages.copy(),  # Store a copy to avoid mutation
            "output_content": response.choices[0].message.content if response.choices else None,
            "duration_ms": 0,  # We don't track duration at this level
            "metadata": {
                "finish_reason": response.choices[0].finish_reason if response.choices else None,
                "kwargs": self._serialize_kwargs(kwargs)
            }
        }

        # Add render_context if prompt_context was provided
        if prompt_context is not None:
            call_data["render_context"] = prompt_context

        return call_data
    
    def _extract_embedding_call_data_from_response(self, call_type: str, model: str, input_text, response, **kwargs) -> Dict[str, Any]:
        """Extract call data from LiteLLM embedding response for database storage."""
        # Extract provider from model string
        provider = model.split('/')[0] if '/' in model else 'unknown'
        
        # For embeddings, we typically only have input tokens
        input_tokens = response.usage.prompt_tokens if response.usage else 0
        total_tokens = response.usage.total_tokens if response.usage else input_tokens
        
        # Calculate estimated cost for embeddings
        estimated_cost_usd = self._calculate_embedding_cost(response, input_tokens)
        
        return {
            "call_type": call_type,
            "model_name": model,
            "provider": provider,
            "prompt_tokens": input_tokens,
            "completion_tokens": 0,  # Embeddings don't have completion tokens
            "total_tokens": total_tokens,
            "estimated_cost_usd": estimated_cost_usd,
            "input_messages": [{"role": "user", "content": str(input_text)}],  # Store input text
            "output_content": f"Generated {len(response.data)} embeddings",  # Summary of output
            "duration_ms": 0,  # We don't track duration at this level
            "metadata": {
                "embedding_dimensions": len(response.data[0].embedding) if response.data else 0,
                "num_embeddings": len(response.data) if response.data else 0,
                "kwargs": self._serialize_kwargs(kwargs)
            }
        }
    
    def _serialize_kwargs(self, kwargs):
        """Filter kwargs to only include JSON-serializable values"""
        serializable_kwargs = {}
        
        for k, v in kwargs.items():
            # Skip 'messages' and 'model' as they're stored separately
            if k in ['messages', 'model']:
                continue
                
            # Handle different types
            try:
                if v is None or isinstance(v, (str, int, float, bool, list, dict)):
                    serializable_kwargs[k] = v
                elif hasattr(v, '__name__'):
                    # For classes/functions, store the name
                    serializable_kwargs[k] = f"<{v.__name__}>"
                else:
                    # For other objects, store string representation
                    serializable_kwargs[k] = str(v)
            except Exception:
                # If anything fails, store a safe representation
                serializable_kwargs[k] = f"<{type(v).__name__}>"
        
        return serializable_kwargs
    
    def _calculate_cost(self, response) -> float:
        """Calculate actual cost for the LiteLLM response using the official API."""
        try:
            import litellm
            cost = litellm.completion_cost(completion_response=response)
            if cost is not None and isinstance(cost, (int, float)):
                self.logger.debug(f"Real cost from LiteLLM: ${cost:.8f}")
                return float(cost)
            else:
                self.logger.info("No cost data available from LiteLLM")
                return 0.0
            
        except Exception as e:
            self.logger.warning(f"Unable to get cost from LiteLLM: {e}")
            return 0.0
    
    def _calculate_embedding_cost(self, response, input_tokens: int) -> float:
        """Calculate actual cost for embedding calls using the official LiteLLM API."""
        try:
            import litellm
            cost = litellm.completion_cost(completion_response=response)
            if cost is not None and isinstance(cost, (int, float)):
                self.logger.debug(f"Real embedding cost from LiteLLM: ${cost:.8f}")
                return float(cost)
            else:
                self.logger.info("No embedding cost data available from LiteLLM")
                return 0.0
            
        except Exception as e:
            self.logger.warning(f"Unable to get embedding cost from LiteLLM: {e}")
            return 0.0