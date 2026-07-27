# paper_data_linking/clients/litellm_client.py

import litellm
import logging
import time
from typing import Dict, List, Any, Union

logger = logging.getLogger(__name__)
litellm.drop_params = True


class LiteLLMClient:
    """
    Base LiteLLM client that wraps litellm.completion() calls and returns structured call data.
    This class has no Django dependencies and can be used in any context.
    """
    
    def __init__(self):
        self.logger = logger
    
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
    
    def completion(
        self,
        call_type: str,
        model: str,
        messages: List[Dict[str, str]],
        **kwargs
    ) -> Any:
        """
        Make a LiteLLM completion call and return response object.
        
        Args:
            call_type: Type of call for tracking (e.g., 'paper_analysis', 'time_normalization')
            model: LiteLLM model string (e.g., 'openai/gpt-4o')
            messages: List of message dicts for the conversation
            **kwargs: Additional parameters passed to litellm.completion()
            
        Returns:
            LiteLLM response object
        """
        start_time = time.time()

        try:
            self.logger.debug(f"Making LiteLLM call: {call_type} with model {model}")

            # Extract prompt_context before passing to litellm (it's for logging/tracking only)
            prompt_context = kwargs.pop('prompt_context', None)

            # gpt-5 and o-series models use max_completion_tokens instead of max_tokens
            model_name = model.split('/')[-1] if '/' in model else model
            if 'max_tokens' in kwargs and any(model_name.startswith(p) for p in ('o1', 'o3', 'gpt-5')):
                kwargs['max_completion_tokens'] = kwargs.pop('max_tokens')

            # litellm.drop_params=True silently discards params a model doesn't
            # support. That once hid reasoning_effort being dropped for bedrock
            # gpt-oss (the whole config ran at default effort, unnoticed). Surface
            # it: warn if a reasoning_effort we passed won't actually be honored.
            # Best-effort only — a diagnostic must never break the real call.
            if kwargs.get('reasoning_effort') is not None:
                try:
                    supported = litellm.get_supported_openai_params(model=model) or []
                    if 'reasoning_effort' not in supported:
                        self.logger.warning(
                            f"reasoning_effort={kwargs['reasoning_effort']!r} passed for "
                            f"model '{model}', but litellm does not list it as supported; "
                            f"it will be silently dropped (litellm.drop_params=True)."
                        )
                except Exception:
                    pass

            response = litellm.completion(
                model=model,
                messages=messages,
                **kwargs
            )
            
            end_time = time.time()
            duration_ms = int((end_time - start_time) * 1000)
            
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
                "duration_ms": duration_ms,
                "metadata": {
                    "finish_reason": response.choices[0].finish_reason if response.choices else None,
                    "kwargs": self._serialize_kwargs(kwargs)
                }
            }
            
            self.logger.info(
                f"LiteLLM call completed: {call_type} | "
                f"Model: {model} | "
                f"Tokens: {call_data['total_tokens']} | "
                f"Cost: {'${:.6f}'.format(call_data['estimated_cost_usd']) if call_data['estimated_cost_usd'] is not None else 'N/A'} | "
                f"Duration: {duration_ms}ms"
            )
            
            return response
            
        except Exception as e:
            end_time = time.time()
            duration_ms = int((end_time - start_time) * 1000)
            
            self.logger.error(
                f"LiteLLM call failed: {call_type} | "
                f"Model: {model} | "
                f"Duration: {duration_ms}ms | "
                f"Error: {str(e)}"
            )
            
            # Re-raise the exception so calling code can handle it
            raise
    
    def _calculate_cost(self, response) -> float:
        """
        Get actual cost from LiteLLM response using the official API.
        
        Args:
            response: LiteLLM response object
            
        Returns:
            Actual cost in USD from LiteLLM, or 0.0 if unavailable
        """
        try:
            import litellm
            cost = litellm.completion_cost(completion_response=response)
            if cost is not None and isinstance(cost, (int, float)):
                self.logger.debug(f"Real cost from LiteLLM: ${cost:.8f}")
                return float(cost)
            else:
                self.logger.info("No cost data available from LiteLLM")
                return None

        except Exception as e:
            self.logger.warning(f"Unable to get cost from LiteLLM: {e}")
            return None
    
    def embedding(
        self,
        call_type: str,
        model: str,
        input_text: Union[str, List[str]],
        **kwargs
    ) -> Any:
        """
        Make a LiteLLM embedding call and return response object.
        
        Args:
            call_type: Type of call for tracking (e.g., 'embedding_generation')
            model: LiteLLM model string (e.g., 'openai/text-embedding-ada-002')
            input_text: Text(s) to embed
            **kwargs: Additional parameters passed to litellm.embedding()
            
        Returns:
            LiteLLM response object
        """
        start_time = time.time()
        
        try:
            self.logger.debug(f"Making LiteLLM embedding call: {call_type} with model {model}")
            
            response = litellm.embedding(
                model=model,
                input=input_text,
                **kwargs
            )
            
            end_time = time.time()
            duration_ms = int((end_time - start_time) * 1000)
            
            # Extract provider from model string
            provider = model.split('/')[0] if '/' in model else 'unknown'
            
            # For embeddings, we typically only have input tokens
            input_tokens = response.usage.prompt_tokens if response.usage else 0
            total_tokens = response.usage.total_tokens if response.usage else input_tokens
            
            # Calculate estimated cost for embeddings
            estimated_cost_usd = self._calculate_embedding_cost(response, input_tokens)
            
            call_data = {
                "call_type": call_type,
                "model_name": model,
                "provider": provider,
                "prompt_tokens": input_tokens,
                "completion_tokens": 0,  # Embeddings don't have completion tokens
                "total_tokens": total_tokens,
                "estimated_cost_usd": estimated_cost_usd,
                "input_messages": [{"role": "user", "content": str(input_text)}],  # Store input text
                "output_content": f"Generated {len(response.data)} embeddings",  # Summary of output
                "duration_ms": duration_ms,
                "metadata": {
                    "embedding_dimensions": len(response.data[0].embedding) if response.data else 0,
                    "num_embeddings": len(response.data) if response.data else 0,
                    "kwargs": self._serialize_kwargs(kwargs)
                }
            }
            
            self.logger.info(
                f"LiteLLM embedding call completed: {call_type} | "
                f"Model: {model} | "
                f"Tokens: {call_data['total_tokens']} | "
                f"Cost: {'${:.6f}'.format(call_data['estimated_cost_usd']) if call_data['estimated_cost_usd'] is not None else 'N/A'} | "
                f"Duration: {duration_ms}ms"
            )
            
            return response
            
        except Exception as e:
            end_time = time.time()
            duration_ms = int((end_time - start_time) * 1000)
            
            self.logger.error(
                f"LiteLLM embedding call failed: {call_type} | "
                f"Model: {model} | "
                f"Duration: {duration_ms}ms | "
                f"Error: {str(e)}"
            )
            
            # Re-raise the exception so calling code can handle it
            raise
    
    def _calculate_embedding_cost(self, response, input_tokens: int) -> float:
        """
        Get actual cost for embedding calls from LiteLLM using the official API.
        
        Args:
            response: LiteLLM embedding response object
            input_tokens: Number of input tokens
            
        Returns:
            Actual cost in USD from LiteLLM, or 0.0 if unavailable
        """
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