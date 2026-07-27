# get_all_instruments.py

from cdasws import CdasWs # Import the cdasws library
import json # Import the json library for file writing


def get_all_cdas_instruments_with_library():
    """
    Retrieves a list of all instruments from the CDASWS API
    using the cdasws Python library and writes them to a JSON file.

    This function uses the CdasWs.get_instruments() method and
    saves the instrument details to 'instruments_output.json'.
    """
    print("Initializing CDAS Web Services client...")
    output_filename = "instruments_output.json" # Define the output filename
    try:
        # Initialize the cdasws client
        cdas = CdasWs()

        print("Requesting instrument list using cdasws library...")
        # Get all instruments.
        # The get_instruments() method without arguments should return all instruments.
        # The library handles the API endpoint and JSON parsing internally.
        instruments_data = cdas.get_instruments()

        if instruments_data:
            # The get_instruments() method returns a list of dictionaries,
            # each representing an instrument.
            print(f"\nSuccessfully retrieved {len(instruments_data)} instruments.")

            # Write the data to a JSON file with indentation
            with open(output_filename, 'w') as f:
                json.dump(instruments_data, f, indent=4)
            print(f"Instrument data has been written to {output_filename}")

        else:
            print("No instruments found or an empty list was returned.")
            # Optionally, write an empty list to the file if no instruments are found
            with open(output_filename, 'w') as f:
                json.dump([], f, indent=4)
            print(f"Empty instrument list written to {output_filename}")


    # The cdasws library might raise its own specific exceptions or general Python errors.
    # Catching a general Exception here for simplicity, but more specific error
    # handling could be added if the library's exceptions are known.
    except ImportError:
        print("Error: The 'cdasws' library is not installed.")
        print("Please install it using: pip install cdasws")
    except IOError as e:
        print(f"Error writing to file {output_filename}: {e}")
    except Exception as e:
        print(f"An error occurred: {e}")
        print("This could be due to network issues, problems with the CDASWS service,")
        print("or an issue with the cdasws library itself.")

if __name__ == "__main__":
    get_all_cdas_instruments_with_library()
