# categorize_instruments.py

import json
import time
import os
from openai import OpenAI  # Import the OpenAI library
from dotenv import load_dotenv  # Import dotenv

# --- Configuration ---
INPUT_FILENAME = "instruments_output.json"  # Your existing JSON file
OUTPUT_FILENAME = "instruments_categorized_by_openai.json"
# Define the categories you want the LLM to use. Be clear and distinct.
CATEGORIES = [
    "Physical Instrument/Sensor",  # e.g., Magnetometer, Spectrometer, Detector, Probe, Camera
    "Instrument Suite/Experiment",  # e.g., A collection of instruments like '3DP', 'CIS', 'SWOOPS'
    "Observatory/Ground Station/Location",  # e.g., 'Ascension Island', 'Boulder, Colorado', 'CHBR'
    "Data Product Descriptor/Resolution/Level",  # e.g., '1MIN', 'L2 Data', 'Fluxes', 'Counts Level 1'
    "Spacecraft System/Subsystem (Non-Science)",  # e.g., 'Attitude Determination System', 'Power Systems'
    "Mission/Spacecraft Name",  # e.g., 'Voyager', 'Parker Solar Probe' (if these appear)
    "Event/Phenomena Descriptor",  # e.g., 'Auroral Kilometric Radiation', 'Solar Flare Data'
    "Software/Model/Processing Tool",  # e.g., 'TOPIST program', 'Selesnick model'
    "Generic/Placeholder/Null",  # For items like 'null', 'AUX', 'Unknown'
    "Other (Specify if possible)"  # Fallback
]
OPENAI_MODEL = "gpt-4.1-nano"  # Or any other model you prefer, e.g., "gpt-4"


# --- OpenAI API Interaction ---
def get_openai_category(client, item_name, item_short_desc, item_long_desc):
    """
    Calls the OpenAI API to categorize an instrument item.
    Uses a synchronous client.
    """
    # Ensure descriptions are not None for the prompt
    name_str = str(item_name) if item_name else "Not specified"
    short_desc_str = str(item_short_desc) if item_short_desc else "No short description"
    long_desc_str = str(item_long_desc) if item_long_desc else "No long description"

    prompt_system = f"""
    You are an expert in space physics and scientific instrumentation.
    Your task is to categorize an item from a list provided by NASA's CDAS (Coordinated Data Analysis System).
    The list contains various entries, some are physical instruments, some are locations, some are data product types, etc.
    Please categorize the following item into ONE of the predefined categories.
    Provide ONLY the category name as your response.

    Predefined Categories:
    {json.dumps(CATEGORIES, indent=2)}
    """
    prompt_user = f"""
    Item Details:
    Name: "{name_str}"
    Short Description: "{short_desc_str}"
    Long Description: "{long_desc_str}"

    Based on the item details, which of the predefined categories is most appropriate?
    Respond with ONLY the category name. For example, if you think it's a physical instrument, respond with:
    Physical Instrument/Sensor
    """

    try:
        completion = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": prompt_system},
                {"role": "user", "content": prompt_user}
            ],
            temperature=0.0  # For more deterministic output
        )

        category_text = completion.choices[0].message.content.strip()

        # Validate if the returned category is one of the predefined ones
        if category_text in CATEGORIES:
            return category_text
        else:
            print(f"Warning: OpenAI returned an unexpected category: '{category_text}'. Attempting to match.")
            # Attempt to find the closest match or default to 'Other'
            for cat in CATEGORIES:
                # Check if the LLM response starts with a known category (case-insensitive)
                if category_text.lower().startswith(cat.lower().split('/')[0].split('(')[0].strip()):
                    print(f"Matched to: '{cat}'")
                    return cat
            print(f"Could not confidently match. Defaulting to 'Other (LLM Mismatch)' for '{category_text}'")
            return "Other (LLM Mismatch)"

    except Exception as e:
        print(f"An error occurred during OpenAI API call for '{item_name}': {e}")
        return "LLM_Request_Exception"


def main():
    """
    Main function to read, process, and write the instrument data.
    """
    # Load environment variables from .env file
    load_dotenv()
    api_key = os.getenv("OPENAI_API_KEY")

    if not api_key:
        print("Error: OPENAI_API_KEY not found in environment variables.")
        print("Please create a .env file with your OPENAI_API_KEY or set it in your environment.")
        return

    # Initialize OpenAI client
    client = OpenAI(api_key=api_key)

    try:
        with open(INPUT_FILENAME, 'r', encoding='utf-8') as f:
            instruments_data = json.load(f)
    except FileNotFoundError:
        print(f"Error: Input file '{INPUT_FILENAME}' not found.")
        return
    except json.JSONDecodeError:
        print(f"Error: Could not decode JSON from '{INPUT_FILENAME}'.")
        return

    categorized_instruments = []
    total_items = len(instruments_data)
    print(f"Starting categorization for {total_items} items using OpenAI model {OPENAI_MODEL}...")

    for i, item in enumerate(instruments_data):
        name = item.get("Name")
        short_desc = item.get("ShortDescription")
        long_desc = item.get("LongDescription")

        print(f"Processing item {i + 1}/{total_items}: {name if name else 'Unnamed Item'}")

        # Get category from OpenAI
        llm_category = get_openai_category(client, name, short_desc, long_desc)

        # Create a new dictionary with the original item and the new category
        new_item = item.copy()  # Start with a copy of the original item
        new_item["LLMCategory_OpenAI"] = llm_category  # Changed field name for clarity
        categorized_instruments.append(new_item)

        # # Optional: Add a small delay to avoid hitting API rate limits too quickly
        # if (i + 1) % 20 == 0:  # Every 20 requests (OpenAI free tier has rate limits like 3/min for some models)
        #     print("Pausing for a moment to respect API rate limits...")
        #     time.sleep(60)  # Pause for 60 seconds. Adjust as needed.
        # elif (i + 1) % 5 == 0:  # Shorter pause more frequently
        #     time.sleep(1)
        # ^ usage tier 4 for gpt-4.1-nano does not need this delay.

    print(f"\nCategorization complete. Processed {len(categorized_instruments)} items.")

    try:
        with open(OUTPUT_FILENAME, 'w', encoding='utf-8') as f:
            json.dump(categorized_instruments, f, indent=4)
        print(f"Categorized instrument data has been written to '{OUTPUT_FILENAME}'")
    except IOError as e:
        print(f"Error writing to file {OUTPUT_FILENAME}: {e}")


# --- Execution ---
if __name__ == "__main__":
    main()
