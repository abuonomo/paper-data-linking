import boto3
import botocore.exceptions
import configparser
import os
import sys
import argparse
import json
from datetime import datetime, timezone # Import timezone for proper ISO format

# --- Configuration ---
AWS_CONFIG_FILE = os.path.expanduser("~/.aws/config")
DEFAULT_DURATION_SECONDS = 3600  # 1 hour validity
DEFAULT_TEMP_CREDS_FILE = "temp_aws_creds.json"  # File to save credentials
# --- End Configuration ---

def get_mfa_serial_from_config(profile_name):
    """Reads MFA serial ARN from ~/.aws/config for the given profile."""
    config = configparser.ConfigParser()
    if not os.path.exists(AWS_CONFIG_FILE):
        print(f"WARNING: AWS config file not found at {AWS_CONFIG_FILE}. MFA serial must be provided via --mfa-serial.", file=sys.stderr)
        return None
    config.read(AWS_CONFIG_FILE)
    section_name = f"profile {profile_name}" if profile_name != 'default' else 'default'
    if section_name not in config or 'mfa_serial' not in config[section_name]:
        return None # Handled in main if still None
    return config[section_name]['mfa_serial']

def save_creds_to_json(filename, credentials):
    """Saves credentials dictionary to a JSON file."""
    # Convert datetime object to ISO 8601 string format for JSON compatibility
    creds_for_json = {
        "AccessKeyId": credentials['AccessKeyId'],
        "SecretAccessKey": credentials['SecretAccessKey'],
        "SessionToken": credentials['SessionToken'],
        "Expiration": credentials['Expiration'].isoformat() # Use ISO format
    }

    print(f"Saving temporary credentials to '{filename}'")
    try:
        with open(filename, 'w') as f:
            json.dump(creds_for_json, f, indent=4)
        # Set permissions to read/write for owner only (good practice)
        os.chmod(filename, 0o600)
        print("Credentials saved successfully.")
        print(f"Expiration: {creds_for_json['Expiration']}")
    except IOError as e:
        print(f"ERROR: Failed to write credentials file '{filename}': {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
         print(f"ERROR: An unexpected error occurred saving credentials: {e}", file=sys.stderr)
         sys.exit(1)

def main():
    parser = argparse.ArgumentParser(
        description="Get temporary AWS credentials using MFA and save to a JSON file.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument(
        "--source-profile",
        default="default",
        help="AWS profile containing base credentials and mfa_serial config"
    )
    parser.add_argument(
        "--mfa-serial",
        help="MFA device ARN (overrides value from AWS config file)"
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=DEFAULT_DURATION_SECONDS,
        help="Duration (seconds) for temporary credentials validity"
    )
    parser.add_argument(
        "--output-file",
        default=DEFAULT_TEMP_CREDS_FILE,
        help="Path to the JSON file where temporary credentials will be saved"
    )
    args = parser.parse_args()

    # --- Get MFA Serial ---
    mfa_serial = args.mfa_serial or get_mfa_serial_from_config(args.source_profile)
    if not mfa_serial:
        print(f"ERROR: MFA Serial ARN not found for profile '{args.source_profile}' and not provided via --mfa-serial.", file=sys.stderr)
        sys.exit(1)

    print(f"Using MFA device: {mfa_serial}")
    print(f"Using source profile: '{args.source_profile}' for base credentials.")

    # --- Get MFA Token Code ---
    while True:
        try:
            mfa_token_code = input("Enter your 6-digit MFA code: ").strip()
            if len(mfa_token_code) == 6 and mfa_token_code.isdigit():
                break
            else:
                print("Invalid code format. Please enter exactly 6 digits.")
        except EOFError:
            print("\nOperation cancelled.", file=sys.stderr)
            sys.exit(1)

    # --- Call STS GetSessionToken ---
    try:
        base_session = boto3.Session(profile_name=args.source_profile)
        sts_client = base_session.client('sts')
        print("Requesting temporary credentials from AWS STS...")
        response = sts_client.get_session_token(
            DurationSeconds=args.duration,
            SerialNumber=mfa_serial,
            TokenCode=mfa_token_code
        )
        print("Successfully obtained temporary credentials.")

        # --- Save Credentials to JSON File ---
        save_creds_to_json(args.output_file, response['Credentials'])

    except botocore.exceptions.ClientError as e:
        # Specific error handling copied from previous script...
        error_code = e.response.get('Error', {}).get('Code')
        if error_code == 'AccessDenied':
            print("\nERROR: Access Denied during STS GetSessionToken. Check:", file=sys.stderr)
            print(f"  1. MFA code incorrect/expired.", file=sys.stderr)
            print(f"  2. MFA device ARN '{mfa_serial}' wrong.", file=sys.stderr)
            print(f"  3. Base credentials in profile '{args.source_profile}' lack 'sts:GetSessionToken' permission.", file=sys.stderr)
        elif error_code in ['CredentialsError', 'ProfileNotFound', 'NoCredentialsError']:
             print(f"\nERROR: Could not locate base credentials for profile '{args.source_profile}'.", file=sys.stderr)
        else:
            print(f"\nERROR: AWS API error during STS call: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"\nAn unexpected error occurred: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()