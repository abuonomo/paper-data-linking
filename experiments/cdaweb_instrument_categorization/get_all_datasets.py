import json

# Assuming 'datasets' is the list containing your 2833 dataset dictionaries
# For example, if you just ran:
from cdasws import CdasWs
cdas = CdasWs()
datasets = cdas.get_datasets()
# # Or however you populated the 'datasets' variable to get 2833 items

output_filename = "all_datasets.jsonl"
count = 0

try:
    with open(output_filename, 'w', encoding='utf-8') as f:
        for dataset_dict in datasets:
            # Convert the Python dictionary to a JSON string
            json_string = json.dumps(dataset_dict)
            # Write the JSON string as a new line in the file
            f.write(json_string + '\n')
            count += 1
    print(f"Successfully wrote {count} datasets to '{output_filename}'")
except IOError as e:
    print(f"An I/O error occurred: {e}")
except Exception as e:
    print(f"An unexpected error occurred: {e}")