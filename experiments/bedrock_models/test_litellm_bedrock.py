#!/usr/bin/env python3
"""
Test script for LiteLLM + AWS Bedrock integration.

This script tests using the paper-data-linking LiteLLMClient with AWS Bedrock models,
comparing the results with the existing direct boto3 approach.
"""

import os
import sys
import argparse
import json
from typing import Dict, List, Any

# Add the project root to the path so we can import our modules
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, project_root)

from paper_data_linking.clients.litellm_client import LiteLLMClient


class BedrockModelTester:
    """Test different approaches to calling Bedrock models."""
    
    # Available Bedrock models to test
    BEDROCK_MODELS = {
        "gpt-oss-120b": "bedrock/openai.gpt-oss-120b-1:0",
        "gpt-oss-20b": "bedrock/openai.gpt-oss-20b-1:0"
    }
    
    def __init__(self):
        self.litellm_client = LiteLLMClient()
        self.results = {}
    
    def test_litellm_bedrock(self, model_name: str, prompt: str, **kwargs) -> Dict[str, Any]:
        """Test calling a Bedrock model through LiteLLM."""
        print(f"\n=== Testing LiteLLM with {model_name} ===")
        
        if model_name not in self.BEDROCK_MODELS:
            raise ValueError(f"Model {model_name} not found in available models: {list(self.BEDROCK_MODELS.keys())}")
        
        model_id = self.BEDROCK_MODELS[model_name]
        messages = [{"role": "user", "content": prompt}]
        
        try:
            print(f"Model ID: {model_id}")
            print(f"Prompt: {prompt}")
            
            # Call through our LiteLLMClient wrapper with region support
            response = self.litellm_client.completion(
                call_type="bedrock_test",
                model=model_id,
                messages=messages,
                aws_region_name=kwargs.pop('aws_region_name', 'us-west-2'),
                **kwargs
            )
            
            result = {
                "success": True,
                "model_id": model_id,
                "response_content": response.choices[0].message.content if response.choices else None,
                "usage": {
                    "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                    "completion_tokens": response.usage.completion_tokens if response.usage else 0,
                    "total_tokens": response.usage.total_tokens if response.usage else 0
                },
                "finish_reason": response.choices[0].finish_reason if response.choices else None,
                "provider": "bedrock"
            }
            
            print(f"✅ Success!")
            print(f"Response: {result['response_content'][:200]}...")
            print(f"Tokens: {result['usage']['total_tokens']}")
            
            return result
            
        except Exception as e:
            print(f"❌ Error: {str(e)}")
            return {
                "success": False,
                "model_id": model_id,
                "error": str(e),
                "error_type": type(e).__name__
            }
    
    def test_openai_comparison(self, prompt: str, **kwargs) -> Dict[str, Any]:
        """Test with OpenAI model for comparison."""
        print(f"\n=== Testing OpenAI for comparison ===")
        
        model_id = "openai/gpt-4o-mini"
        messages = [{"role": "user", "content": prompt}]
        
        try:
            print(f"Model ID: {model_id}")
            print(f"Prompt: {prompt}")
            
            response = self.litellm_client.completion(
                call_type="openai_comparison_test",
                model=model_id,
                messages=messages,
                **kwargs
            )
            
            result = {
                "success": True,
                "model_id": model_id,
                "response_content": response.choices[0].message.content if response.choices else None,
                "usage": {
                    "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                    "completion_tokens": response.usage.completion_tokens if response.usage else 0,
                    "total_tokens": response.usage.total_tokens if response.usage else 0
                },
                "finish_reason": response.choices[0].finish_reason if response.choices else None,
                "provider": "openai"
            }
            
            print(f"✅ Success!")
            print(f"Response: {result['response_content'][:200]}...")
            print(f"Tokens: {result['usage']['total_tokens']}")
            
            return result
            
        except Exception as e:
            print(f"❌ Error: {str(e)}")
            return {
                "success": False,
                "model_id": model_id,
                "error": str(e),
                "error_type": type(e).__name__
            }
    
    def run_test_suite(self, prompt: str, models: List[str] = None, include_openai: bool = True, **kwargs):
        """Run tests on multiple models and collect results."""
        print(f"🚀 Starting Bedrock LiteLLM Test Suite")
        print(f"Prompt: '{prompt}'")
        
        models_to_test = models or list(self.BEDROCK_MODELS.keys())
        
        # Test Bedrock models
        for model_name in models_to_test:
            try:
                result = self.test_litellm_bedrock(model_name, prompt, **kwargs)
                self.results[model_name] = result
            except Exception as e:
                print(f"❌ Failed to test {model_name}: {e}")
                self.results[model_name] = {"success": False, "error": str(e)}
        
        # Test OpenAI for comparison
        if include_openai:
            try:
                result = self.test_openai_comparison(prompt, **kwargs)
                self.results["openai_comparison"] = result
            except Exception as e:
                print(f"❌ Failed to test OpenAI: {e}")
                self.results["openai_comparison"] = {"success": False, "error": str(e)}
    
    def print_summary(self):
        """Print a summary of all test results."""
        print(f"\n📊 Test Results Summary")
        print("=" * 50)
        
        successful_tests = [name for name, result in self.results.items() if result.get("success")]
        failed_tests = [name for name, result in self.results.items() if not result.get("success")]
        
        print(f"✅ Successful: {len(successful_tests)}")
        print(f"❌ Failed: {len(failed_tests)}")
        
        if successful_tests:
            print(f"\nSuccessful models:")
            for model_name in successful_tests:
                result = self.results[model_name]
                tokens = result.get("usage", {}).get("total_tokens", "N/A")
                print(f"  - {model_name}: {tokens} tokens")
        
        if failed_tests:
            print(f"\nFailed models:")
            for model_name in failed_tests:
                result = self.results[model_name]
                error = result.get("error", "Unknown error")
                print(f"  - {model_name}: {error}")
    
    def save_results(self, filename: str = "bedrock_test_results.json"):
        """Save results to a JSON file."""
        filepath = os.path.join(os.path.dirname(__file__), filename)
        with open(filepath, 'w') as f:
            json.dump(self.results, f, indent=2, default=str)
        print(f"💾 Results saved to: {filepath}")


def main():
    parser = argparse.ArgumentParser(
        description="Test LiteLLM integration with AWS Bedrock models",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument(
        "--prompt",
        default="What is AWS Bedrock and how does it work?",
        help="Prompt to send to the models"
    )
    parser.add_argument(
        "--models",
        nargs="*",
        help=f"Models to test. Available: {list(BedrockModelTester.BEDROCK_MODELS.keys())}"
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=100,
        help="Maximum tokens to generate"
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=0.7,
        help="Temperature for generation"
    )
    parser.add_argument(
        "--no-openai",
        action="store_true",
        help="Skip OpenAI comparison test"
    )
    parser.add_argument(
        "--save-results",
        default="bedrock_test_results.json",
        help="Filename to save results (in experiments/bedrock_models/)"
    )
    parser.add_argument(
        "--aws-region",
        default="us-west-2",
        help="AWS region for Bedrock API calls"
    )
    
    args = parser.parse_args()
    
    # Create tester and run tests
    tester = BedrockModelTester()
    
    kwargs = {
        "max_tokens": args.max_tokens,
        "temperature": args.temperature,
        "aws_region_name": args.aws_region
    }
    
    tester.run_test_suite(
        prompt=args.prompt,
        models=args.models,
        include_openai=not args.no_openai,
        **kwargs
    )
    
    # Print results
    tester.print_summary()
    
    # Save results
    if args.save_results:
        tester.save_results(args.save_results)
    
    print(f"\n🎉 Test suite completed!")


if __name__ == "__main__":
    main()