# AWS Bedrock Invocation with MFA using Temporary Credentials File

This guide explains how to set up and use two Python scripts to interact with AWS Bedrock models programmatically, handling Multi-Factor Authentication (MFA) by generating temporary credentials and storing them in a local JSON file.

This setup uses the AWS `sts:GetSessionToken` API call, which requires an MFA device that generates a 6-digit code (like a virtual authenticator app). **It will not work with U2F/FIDO hardware security keys.** For U2F keys, using AWS IAM Identity Center (SSO) is the recommended approach.

**Scripts:**

1.  `generate_temp_creds.py`: Prompts for your MFA code and generates temporary AWS credentials, saving them to a JSON file (`temp_aws_creds.json` by default).
2.  `call_bedrock_generic.py`: Reads the temporary credentials from the JSON file and uses the generic Bedrock `Converse` API to invoke a specified model, allowing interaction with various supported models without model-specific code.

---

## Prerequisites

### Software (macOS)

1.  **Python 3:** Version 3.7 or higher is recommended (these scripts were tested with 3.10+). Check your version with `python3 --version`. If needed, download from [python.org](https://www.python.org/downloads/macos/).
2.  **Homebrew:** A package manager for macOS. If you don't have it, install from [brew.sh](https://brew.sh/).
3.  **pipx:** Recommended for installing Python command-line tools in isolated environments. Install via Homebrew:
    ```bash
    brew install pipx
    pipx ensurepath
    ```
    *(Close and reopen your terminal after running `pipx ensurepath`)*

### Required AWS Information & Setup

This guide assumes you have an AWS IAM user account with the necessary permissions already assigned by an administrator. You'll need to ensure you have MFA configured with an authenticator app and generate access keys for programmatic use.

1.  **Navigate to Security Credentials:**
    * Log in to the [AWS Management Console](https://aws.amazon.com/console/) as your IAM user.
    * Click on your **account name/user name** in the top-right corner of the console.
    * Select **"Security credentials"** from the dropdown menu.

2.  **Configure MFA & Get ARN:**
    * On the Security credentials page, find the **Multi-factor authentication (MFA)** section.
    * If you haven't already, click **"Assign MFA device"** (or manage existing) and ensure you have an active **"Authenticator app"** (Virtual MFA device like Google Authenticator, Authy, etc.) registered. Follow the on-screen steps completely (scan QR, enter codes).
    * **Crucially, copy the "Device ARN"** shown for your active Authenticator app. It looks like `arn:aws:iam::YOUR_ACCOUNT_ID:mfa/YOUR_IAM_USERNAME`. You'll need this ARN for the `~/.aws/config` file later. *(Note: These scripts require an Authenticator app, not a U2F/hardware key).*

3.  **Create Access Keys:**
    * On the same Security credentials page, find the **Access keys** section.
    * Click **"Create access key"**.
    * Choose **"Command Line Interface (CLI)"** as the use case, acknowledge the recommendations, and proceed.
    * **IMPORTANT:** On the final screen, **copy both the Access Key ID and the Secret Access Key**. Download the `.csv` file for safekeeping if needed, but **save the Secret Access Key securely right away**, as you cannot view it again after closing this screen.

4.  **Prepare for Configuration:**
    * You now have your **Access Key ID**, **Secret Access Key**, and **MFA Device ARN**.
    * These details are used to set up your local AWS environment, primarily through the `~/.aws/credentials` and `~/.aws/config` files (or using the `aws configure` command for the keys, then manually editing the config file for the MFA ARN, as detailed in the next section).
---

## Installation

1.  **Install AWS CLI (via pipx):**
    ```bash
    pipx install awscli
    ```
    Verify the installation:
    ```bash
    aws --version
    ```

2.  **Install Python Dependencies (Boto3):**
    ```bash
    pip3 install boto3
    ```
    *(Use `pip` instead of `pip3` if that's your system default for Python 3)*

3.  **Download Scripts:**
    * Save the code for `generate_temp_creds.py` into a file with that name.
    * Save the code for `call_bedrock_generic.py` into a file with that name.
    * Place both files in the same directory where you plan to run them.

---

## AWS Configuration Files

The AWS CLI and Boto3 use configuration files located in `~/.aws/`.

1.  **Credentials File (`~/.aws/credentials`):**
    * Stores your secret Access Keys. Create this file if it doesn't exist.
    * Add your IAM user's keys, typically under the `[default]` profile unless you prefer named profiles.

    *Example `~/.aws/credentials`:*
    ```ini
    [default]
    aws_access_key_id = YOUR_ACCESS_KEY_ID_HERE
    aws_secret_access_key = YOUR_SECRET_ACCESS_KEY_HERE
    ```
    *Replace the placeholders with your actual keys.*
    * **Set Permissions:** Secure this file:
        ```bash
        chmod 600 ~/.aws/credentials
        ```

2.  **Config File (`~/.aws/config`):**
    * Stores non-secret settings like region and the **MFA device ARN**. Create this file if it doesn't exist.
    * Find your **Virtual MFA Device ARN** in the AWS Console: IAM -> Users -> Your Username -> Security credentials tab -> Assigned MFA device ARN (will look like `arn:aws:iam::ACCOUNT_ID:mfa/USERNAME`).
    * Add the region and MFA ARN to the corresponding profile (`[default]` shown).

    *Example `~/.aws/config`:*
    ```ini
    [default]
    region = us-east-1  # Or your preferred default region
    output = json
    # Add your Virtual MFA device ARN below
    mfa_serial = arn:aws:iam::YOUR_ACCOUNT_ID:mfa/YOUR_IAM_USERNAME
    ```
    *Replace placeholders with your actual Account ID, IAM username, and default region.*

---

## Script Descriptions

* **`generate_temp_creds.py`**:
    * Reads your base AWS credentials (from the specified `--source-profile`, default is `default`).
    * Looks up the `mfa_serial` in your `~/.aws/config` file for that profile (unless overridden with `--mfa-serial`).
    * Prompts you for the 6-digit code from your virtual authenticator app.
    * Calls AWS STS `GetSessionToken`.
    * Saves the resulting temporary `AccessKeyId`, `SecretAccessKey`, `SessionToken`, and `Expiration` into a JSON file (default: `temp_aws_creds.json`).

* **`call_bedrock_generic.py`**:
    * Reads the temporary credentials from the specified JSON file (`--creds-file`, default: `temp_aws_creds.json`).
    * Initializes the Boto3 Bedrock Runtime client using these temporary credentials.
    * Uses the **Bedrock `Converse` API** to interact with the specified model (`--model-id`). This allows it to work with many different models without requiring specific code for each.
    * Takes your `--prompt` and common inference parameters (`--max-tokens`, `--temperature`, `--top-p`).
    * Prints the model's response text.

---

## Usage Instructions

1.  **Step 1: Generate Temporary Credentials**
    * Open your terminal and navigate to the directory where you saved the scripts.
    * Run the generation script:
        ```bash
        python3 generate_temp_creds.py
        ```
        *(If your base credentials/MFA ARN are under a named profile like `[profile work]`, use:*
        `python3 generate_temp_creds.py --source-profile work`*)*
    * When prompted, enter the current 6-digit code from your virtual authenticator app associated with your IAM user.
    * If successful, the script will create/update `temp_aws_creds.json` (or the file specified with `--output-file`) and print the expiration time.

2.  **Step 2: Invoke Bedrock Model**
    * Now, run the invocation script, providing the model ID and your prompt:
        ```bash
        # Example using default Claude 3 Sonnet
        python3 call_bedrock_generic.py --prompt "What is AWS Bedrock?"

        # Example using DeepSeek
        python3 call_bedrock_generic.py --model-id us.deepseek.r1-v1:0 --prompt "Write python code for a basic calculator"

        # Example using Claude 3 Haiku with specific parameters
        python3 call_bedrock_generic.py \
            --model-id anthropic.claude-3-haiku-20240307-v1:0 \
            --prompt "Tell me a short joke about clouds" \
            --max-tokens 50 \
            --temperature 0.8

        # Example using a different credentials file location
        # python3 call_bedrock_generic.py --creds-file /path/to/my_session.json --prompt "Hello"
        ```
    * The script will use the credentials from the JSON file to make the API call and print the response.

3.  **Step 3: Re-generate Credentials**
    * The temporary credentials expire (default is 1 hour, set by `--duration` in `generate_temp_creds.py`).
    * When they expire, or when you start a new terminal session, you will need to **repeat Step 1** to generate fresh credentials before running the invocation script again.

---

## Important Notes & Troubleshooting

* **Security:** The `temp_aws_creds.json` file contains sensitive, albeit temporary, credentials. Ensure it's stored securely (the script sets permissions to 600) and consider deleting it when you are finished with your session. Do not commit it to version control (e.g., Git).
* **MFA Type:** `generate_temp_creds.py` **only works with Virtual MFA devices** (authenticator apps). If your IAM user uses a U2F/FIDO key, you must use the AWS IAM Identity Center (SSO) flow (`aws configure sso` / `aws sso login`) instead of these scripts.
* **Converse API Support:** `call_bedrock_generic.py` uses the `Converse` API. Most modern text/chat models support it, but if you encounter errors with a specific `model-id`, that model might require using the `invoke_model` API with a model-specific request body format.
* **Permissions:** If you get `AccessDeniedException` errors, double-check the IAM permissions attached to your user. Ensure `sts:GetSessionToken` and `bedrock:Converse` (for the correct model resource ARN or wildcard) are allowed.
* **Model IDs:** Verify the exact `model-id` strings for the models you want to use are available in the AWS region you are targeting (`--region`). Check the AWS Bedrock console.
* **File Not Found:** Ensure you run `generate_temp_creds.py` successfully *before* `call_bedrock_generic.py`, and that both scripts are run from a location where the `temp_aws_creds.json` file can be found (or use the `--creds-file` argument to specify the path).