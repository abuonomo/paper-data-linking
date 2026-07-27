# analyze_categories.py
import json
import os
from collections import Counter
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker

# --- Configuration ---
# This should be the filename of the JSON file output by your synchronous categorization script.
CATEGORIZED_DATA_FILENAME = "instruments_categorized_by_openai.json"
CATEGORY_KEY = "LLMCategory_OpenAI"  # The key in the JSON where the category is stored

# These are the categories defined in your categorization script.
# Used for consistent ordering and ensuring all potential categories are shown, even if count is 0.
DEFINED_CATEGORIES = [
    "Physical Instrument/Sensor",
    "Instrument Suite/Experiment",
    "Observatory/Ground Station/Location",
    "Data Product Descriptor/Resolution/Level",
    "Spacecraft System/Subsystem (Non-Science)",
    "Mission/Spacecraft Name",
    "Event/Phenomena Descriptor",
    "Software/Model/Processing Tool",
    "Generic/Placeholder/Null",
    "Other (Specify if possible)",
    "Other (LLM Mismatch)",  # From categorization script's fallback
    "LLM_Request_Exception"  # From categorization script's error handling
]


def parse_categorized_data(filename, category_key):
    """
    Parses the JSON output file from the synchronous categorization script.
    Extracts the category assigned by the LLM for each item.
    """
    extracted_categories = []

    if not os.path.exists(filename):
        print(f"Error: Categorized data file '{filename}' not found.")
        return []

    print(f"Reading categorized data from '{filename}'...")
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            data_list = json.load(f)  # The file contains a JSON list of objects

            for i, item in enumerate(data_list):
                category = item.get(category_key)
                if category:
                    extracted_categories.append(category)
                else:
                    print(f"Warning: No category found under key '{category_key}' for item {i + 1}.")
                    # Optionally, add a placeholder if a category is missing
                    # extracted_categories.append("CategoryNotAssigned")

    except json.JSONDecodeError:
        print(f"Error: Could not decode JSON from '{filename}'. Ensure it's a valid JSON file.")
        return []
    except Exception as e:
        print(f"An error occurred while reading or parsing '{filename}': {e}")
        return []

    print(
        f"Successfully parsed {len(extracted_categories)} categories from {len(data_list) if isinstance(data_list, list) else 0} items.")
    return extracted_categories


def plot_category_frequencies(categories_list, all_possible_categories):
    """
    Counts the frequency of each category and plots a bar chart.
    """
    if not categories_list:
        print("No categories to plot.")
        return

    counts = Counter(categories_list)

    # Ensure all defined categories are present in the plot, even with 0 count
    # And prepare data for plotting
    labels = []
    values = []

    # Add categories found in data but not predefined (e.g., new error types)
    # to all_possible_categories for plotting
    current_categories_in_data = list(counts.keys())
    for cat_in_data in current_categories_in_data:
        if cat_in_data not in all_possible_categories:
            all_possible_categories.append(cat_in_data)  # Add it to the list to be plotted

    for category in all_possible_categories:
        labels.append(category)
        values.append(counts[category])  # Counter returns 0 for missing keys

    if not labels:
        print("No data to plot after processing categories.")
        return

    fig, ax = plt.subplots(figsize=(14, 9))  # Adjust figure size for better label display

    bars = ax.bar(labels, values, color='lightcoral')  # Changed color for variety

    ax.set_ylabel('Frequency (Number of Items)')
    ax.set_xlabel('Category')
    ax.set_title('Frequency of Instrument Categories (from OpenAI Categorization)')

    # Rotate x-axis labels for better readability
    plt.xticks(rotation=45, ha="right", fontsize=9)  # ha="right" aligns the end of the label with the tick

    # Ensure y-axis shows integer ticks if counts are integers
    ax.yaxis.set_major_locator(ticker.MaxNLocator(integer=True))

    # Add text labels on top of each bar
    for bar in bars:
        yval = bar.get_height()
        if yval > 0:  # Only add label if count is > 0
            plt.text(bar.get_x() + bar.get_width() / 2.0, yval + 0.02 * max(values, default=1),
                     # Adjust vertical offset
                     int(yval), ha='center', va='bottom', fontsize=8)

    plt.tight_layout()  # Adjust layout to prevent labels from overlapping
    print("\nDisplaying category frequency chart...")
    plt.show()


def main():
    """
    Main function to parse categorized data and plot frequencies.
    """
    print("Starting script to analyze categorized instrument data...")

    # Parse the categorized data file
    extracted_categories = parse_categorized_data(CATEGORIZED_DATA_FILENAME, CATEGORY_KEY)

    if extracted_categories:
        # Plot the frequencies
        plot_category_frequencies(extracted_categories, DEFINED_CATEGORIES.copy())  # Pass a copy
    else:
        print("No categories were extracted from the data file.")

    print("\nScript finished.")


if __name__ == "__main__":
    main()
