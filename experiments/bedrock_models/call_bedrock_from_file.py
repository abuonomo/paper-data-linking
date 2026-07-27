import boto3
import botocore.exceptions
import json
import sys
import argparse
import os
from datetime import datetime, timezone

# --- Configuration ---
DEFAULT_TEMP_CREDS_FILE = "temp_aws_creds.json"
DEFAULT_BEDROCK_REGION = 'us-east-1'
# Set a reasonable default model - user should override with --model-id
DEFAULT_MODEL_ID = 'us.meta.llama3-3-70b-instruct-v1:0'
# Default inference parameters for Converse API
DEFAULT_MAX_TOKENS = 1024
DEFAULT_TEMPERATURE = 0.7
DEFAULT_TOP_P = 0.9
# --- End Configuration ---

def load_creds_from_json(filename):
    """Loads credentials dictionary from a JSON file."""
    # (Function remains the same as before - snipped for brevity)
    if not os.path.exists(filename):
        print(f"ERROR: Credentials file not found: '{filename}'", file=sys.stderr)
        print(f"       Please run 'generate_temp_creds.py' first.", file=sys.stderr)
        return None
    try:
        with open(filename, 'r') as f:
            creds = json.load(f)
        required_keys = ["AccessKeyId", "SecretAccessKey", "SessionToken", "Expiration"]
        if not all(key in creds for key in required_keys):
             print(f"ERROR: Credentials file '{filename}' is missing required keys.", file=sys.stderr)
             return None
        expiration_dt = datetime.fromisoformat(creds['Expiration'])
        if expiration_dt <= datetime.now(timezone.utc):
            print(f"WARNING: Credentials in '{filename}' appear expired.", file=sys.stderr)
        return creds
    except Exception as e:
        print(f"ERROR: Failed to load credentials from '{filename}': {e}", file=sys.stderr)
        return None

def invoke_model_with_converse(bedrock_runtime, model_id, prompt, max_tokens, temperature, top_p):
    """
    Invokes a Bedrock model using the generic Converse API.
    """
    try:
        print(f"\nInvoking model '{model_id}' using Converse API...")

        # Construct the standardized messages list
        messages = [{"role": "user", "content": [{"text": prompt}]}]

        # Construct the standardized inference config
        inference_config = {
            "maxTokens": max_tokens,
            "temperature": temperature,
            "topP": top_p
        }

        # Call the Converse API
        response = bedrock_runtime.converse(
            modelId=model_id,
            messages=messages,
            inferenceConfig=inference_config
            # Add system prompts here if needed: system=[{'text': 'system prompt'}]
        )

        print("Invocation successful.")

        # Parse the standardized response
        output_message = response['output']['message']
        if output_message['content'] and isinstance(output_message['content'], list):
            # Assuming the first content block is the primary text response
            response_text = output_message['content'][0].get('text', '')
        else:
            response_text = "ERROR: Could not parse response content."

        # Print token usage and stop reason
        usage = response.get('usage', {})
        stop_reason = response.get('stopReason', 'N/A')
        print(f"Stop Reason: {stop_reason}")
        print(f"Token Usage: Input={usage.get('inputTokens', 'N/A')}, Output={usage.get('outputTokens', 'N/A')}")

        return response_text.strip()

    except botocore.exceptions.ClientError as e:
        error_code = e.response.get("Error", {}).get("Code")
        error_message = e.response.get("Error", {}).get("Message", str(e))
        print(f"\nERROR: Bedrock Converse API call failed ({error_code}): {error_message}", file=sys.stderr)
        if error_code == 'ValidationException':
             print("       Check if the model ID is correct and supports the Converse API.", file=sys.stderr)
             print("       Also check if inference parameters are valid for this model.", file=sys.stderr)
        elif error_code == 'AccessDeniedException':
             print("       Verify permissions for 'bedrock:Converse' on the model resource.", file=sys.stderr)
        elif error_code == 'ModelNotReadyException':
             print("       The requested model is not ready. Try again later or check model status.", file=sys.stderr)
        elif error_code == 'ResourceNotFoundException':
             print(f"       Ensure the model ID '{model_id}' exists and is available in region.", file=sys.stderr)
        # Add more specific error handling if needed
        sys.exit(1)
    except Exception as e:
        print(f"\nERROR: An unexpected error occurred during Bedrock invocation: {e}", file=sys.stderr)
        sys.exit(1)

def main():
    parser = argparse.ArgumentParser(
        description="Invoke AWS Bedrock model using the generic Converse API and credentials from a JSON file.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument(
        "--creds-file",
        default=DEFAULT_TEMP_CREDS_FILE,
        help="Path to the JSON file containing temporary AWS credentials"
    )
    parser.add_argument(
        "--region",
        default=DEFAULT_BEDROCK_REGION,
        help="AWS region where the Bedrock model is available"
    )
    parser.add_argument(
        "--model-id",
        default=DEFAULT_MODEL_ID,
        help="The ID of the Bedrock model to invoke (must support Converse API)"
    )
    parser.add_argument(
        "--prompt",
        required=True,
        help="The prompt to send to the Bedrock model"
    )
    # Add arguments for common inference parameters
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=DEFAULT_MAX_TOKENS,
        help="Maximum number of tokens to generate in the response"
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=DEFAULT_TEMPERATURE,
        help="Controls randomness (0.0 - 1.0). Lower is more deterministic"
    )
    parser.add_argument(
        "--top-p",
        type=float,
        default=DEFAULT_TOP_P,
        help="Nucleus sampling parameter (0.0 - 1.0)"
    )
    args = parser.parse_args()

    # --- 1. Load Credentials ---
    print(f"Loading temporary credentials from: {args.creds_file}")
    temp_creds = load_creds_from_json(args.creds_file)
    if temp_creds is None:
        sys.exit(1)

    # --- 2. Initialize Client ---
    try:
        print(f"Initializing Bedrock client in region '{args.region}' using credentials from file...")
        bedrock_runtime = boto3.client(
            'bedrock-runtime',
            region_name=args.region,
            aws_access_key_id=temp_creds['AccessKeyId'],
            aws_secret_access_key=temp_creds['SecretAccessKey'],
            aws_session_token=temp_creds['SessionToken']
        )
        print("Bedrock client initialized.")
    except Exception as e:
        print(f"\nERROR: Failed to initialize Bedrock client: {e}", file=sys.stderr)
        sys.exit(1)

    # --- 3. Invoke Model using Converse API ---
    # No more if/elif needed here!
    model_response = invoke_model_with_converse(
        bedrock_runtime,
        args.model_id,
        args.prompt,
        args.max_tokens,
        args.temperature,
        args.top_p
    )

    # --- 4. Print Response ---
    print("\n--- Model Response ---")
    print(model_response)
    print("--- End Response ---")

if __name__ == "__main__":
    main()