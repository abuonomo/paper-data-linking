"""OpenAI API Client for multi-model testing"""

import openai
import litellm
import time
from typing import Dict, Any, Optional
import os
from dotenv import load_dotenv
import logging
from pydantic import BaseModel, Field

load_dotenv()

class OpenAIClient:
    """Client for OpenAI models (GPT-4, GPT-3.5, etc.)"""
    
    def __init__(self, model_name: str, config: Dict[str, Any]):
        self.model_name = model_name
        self.config = config
        self.client = openai.OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
    
    async def generate_response(self, system_message: str, user_message: str, response_fromat: type[BaseModel]) -> Dict[str, Any]:
        """Generate response using OpenAI API"""
        start_time = time.time()
        
        try:
            response = self.client.beta.chat.completions.parse(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": system_message},
                    {"role": "user", "content": user_message}
                ],
                temperature=self.config.get('temperature', 1.0),
                response_format=response_fromat
            )
            
            end_time = time.time()
            response_time = int((end_time - start_time) * 1000)
            
            # Calculate cost using LiteLLM's built-in pricing
            prompt_tokens = response.usage.prompt_tokens
            completion_tokens = response.usage.completion_tokens
            cost_estimate = litellm.completion_cost(response)
            
            # Store cost prediction for tracking
            cost_prediction = {
                'total_cost': cost_estimate,
                'cost_per_token': cost_estimate / response.usage.total_tokens if response.usage.total_tokens > 0 else 0,
                'pricing_source': 'litellm_builtin'
            }
            
            # With structured output, the parsed object is in response.choices[0].message.parsed
            parsed_content = response.choices[0].message.parsed
            # Convert the Pydantic model back to JSON string for compatibility
            content_json = parsed_content.model_dump_json() if parsed_content else ""
            
            return {
                'content': content_json,
                'tokens_used': {
                    'prompt_tokens': prompt_tokens,
                    'completion_tokens': completion_tokens,
                    'total_tokens': response.usage.total_tokens
                },
                'response_time_ms': response_time,
                'cost_estimate': cost_estimate,
                'cost_prediction': cost_prediction,
                'finish_reason': response.choices[0].finish_reason
            }
            
        except Exception as e:
            raise Exception(f"OpenAI API error for {self.model_name}: {str(e)}")