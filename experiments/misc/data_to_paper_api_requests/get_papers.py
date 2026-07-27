import requests
import json

# --- Configuration ---
# Replace with the actual base URL where your Django API is running
BASE_URL = "http://localhost:8000/builder"
ENDPOINT_PATH = "/papers/search_by_script_params/"
search_instrument = "LASCO"

# --- Construct the full URL and parameters ---
full_url = f"{BASE_URL}{ENDPOINT_PATH}"
params = {
    'instrument': search_instrument,
    # 'start_date': '2011-01-01', # Example start date
    # 'end_date': '2011-12-31',   # Example end date
}

print(f"Querying: {full_url}")
print(f"Params: {params}")

try:
    # Pass headers=headers if authentication is needed
    response = requests.get(full_url, params=params)

    # --- Handle the Response ---
    # Check if the request was successful (status code 200 OK)
    if response.status_code == 200:
        try:
            # Parse the JSON response
            papers_data = response.json()
            print("\n--- Success! Found Papers: ---")
            # Pretty print the JSON response
            print(json.dumps(papers_data, indent=2))
            print(f"\nFound {len(papers_data)} paper(s) matching the criteria.")

        except json.JSONDecodeError:
            print("\n--- Error: Could not decode JSON response ---")
            print(response.text)
    elif response.status_code == 401:
         print(f"\n--- Error: Authentication Failed ({response.status_code}) ---")
         print("If authentication is required, please provide a valid AUTH_TOKEN.")
         print("Response body:", response.text)
    elif response.status_code == 403:
         print(f"\n--- Error: Permission Denied ({response.status_code}) ---")
         print("You may be authenticated but lack permission to access this resource.")
         print("Response body:", response.text)
    elif response.status_code == 404:
         print(f"\n--- Error: Endpoint Not Found ({response.status_code}) ---")
         print("Please check the BASE_URL and ENDPOINT_PATH.")
         print("Response body:", response.text)
    else:
        # Print error details for other status codes
        print(f"\n--- Error: Received status code {response.status_code} ---")
        print("Response body:", response.text)

except requests.exceptions.ConnectionError as e:
    print(f"\n--- Connection Error ---")
    print(f"Could not connect to the server at {BASE_URL}.")
    print("Please ensure the Django development server is running.")
    print(f"Error details: {e}")
except requests.exceptions.RequestException as e:
    # Handle other potential request errors (e.g., timeout)
    print(f"\n--- Request Error ---")
    print(f"An error occurred during the request: {e}")

