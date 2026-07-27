# get_observatory_groups_and_instruments.py

from cdasws import CdasWs
import json


def get_and_display_observatory_groups_and_instruments():
    """
    Retrieves and displays observatory groups and their associated instruments
    using the cdasws library.
    """
    print("Initializing CDAS Web Services client...")
    try:
        cdas = CdasWs()

        print("Requesting observatory groups and their instruments...")
        # The get_observatory_groups_and_instruments() method fetches this hierarchical data.
        # It may take an optional 'dataview' argument, but defaults to 'sp_phys' (space physics).
        data = cdas.get_observatory_groups_and_instruments()

        if not data:
            print("No data returned for observatory groups and instruments.")
            return

        print(f"\nSuccessfully retrieved data for {len(data)} observatory groups.")
        print("----------------------------------------------------")

        # The structure returned is typically a list of observatory group objects.
        # Each object contains the group's name and a list of instrument objects.
        # Example structure:
        # [
        #   {
        #     "Name": "Observatory Group Name 1",
        #     "InstrumentDescription": [
        #       {"Name": "Instrument A", "Observatory": "Observatory X", ...},
        #       {"Name": "Instrument B", "Observatory": "Observatory Y", ...}
        #     ]
        #   },
        #   {
        #     "Name": "Observatory Group Name 2",
        #     "InstrumentDescription": [
        #       {"Name": "Instrument C", "Observatory": "Observatory Z", ...}
        #     ]
        #   }
        # ]

        for i, group_info in enumerate(data):
            group_name = group_info.get("Name", "Unnamed Group")
            instruments = group_info.get("InstrumentDescription", [])

            print(f"\nObservatory Group {i + 1}: {group_name}")
            if instruments:
                print(f"  Instruments ({len(instruments)}):")
                for j, instrument in enumerate(instruments):
                    inst_name = instrument.get("Name", "Unnamed Instrument")
                    # Other instrument details can be accessed here if needed, e.g.:
                    # inst_observatory = instrument.get("Observatory", "N/A")
                    # inst_short_desc = instrument.get("ShortDescription", "N/A")
                    print(f"    {j + 1}. {inst_name}")
            else:
                print("  No instruments listed for this group.")
            print("----------------------------------------------------")

        # Optionally, save the full raw data to a JSON file for inspection
        output_filename = "observatory_groups_and_instruments.json"
        try:
            with open(output_filename, 'w') as f:
                json.dump(data, f, indent=4)
            print(f"\nFull raw data saved to '{output_filename}'")
        except IOError as e:
            print(f"Error writing raw data to file: {e}")

    except ImportError:
        print("Error: The 'cdasws' library is not installed.")
        print("Please install it using: pip install cdasws")
    except Exception as e:
        print(f"An error occurred: {e}")
        print("This could be due to network issues, problems with the CDASWS service,")
        print("or an issue with the cdasws library itself.")


if __name__ == "__main__":
    get_and_display_observatory_groups_and_instruments()
