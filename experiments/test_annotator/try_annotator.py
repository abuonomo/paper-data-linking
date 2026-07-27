# Import the class and function from your other file
from paper_data_linking.processing.pdf_annotator import annotate_pdf
import json

# ==============================================================================
#  Test Execution Block
# ==============================================================================
if __name__ == '__main__':

    # --------------------------------------------------------------------------
    #  ✍️ EDIT THIS SECTION
    # --------------------------------------------------------------------------

    # 1. Set the path to your PDF file.
    pdf_path = "annotator_test3.pdf"

    # 2. Define the list of quotes you want to find.
    quotes_to_find = [
        {
            'quote': "Due to the AIA limited FOV, partial blob and the leading edge are not imaged by the AIA at 15:55:30 UT. We acquire the blob outline based on the observation at 15:55:06 UT...",
            'instrument': "Test Case",
            'parameter': "Inline Citations"
        },
        # {
        #     'quote': "Figures 1(a) and 1(c) show the location of STA",
        #     'instrument': "Test Case",
        #     'parameter': "Inline Citations"
        # },
        # {
        #     'quote': "a constant solar wind speed of 320 km s−1.",
        #     'instrument': "Test Case",
        #     'parameter': "Scientific Units & Superscript"
        # },
        # {
        #     'quote': "In Appendix B we describe the particle intensity enhancements",
        #     'instrument': "Test Case",
        #     'parameter': "Internal Document Reference"
        # },
        # {
        #     'quote': "Figure 2(e) shows the hourly proton intensity from May 27 to June 3",
        #     'instrument': "Test Case",
        #     'parameter': "Date Range"
        # },
        # {
        #     'quote': "the center axis of LET-A was pointed ~45° east",
        #     'instrument': "Test Case",
        #     'parameter': "Special Symbols (~ and °)"
        # },
    ]

    # quotes_to_find = [
    #     {
    #         'quote': "The limitations of using Equation 1 were discussed by Kecskem´ety",
    #         'instrument': "Category A",
    #         'parameter': "Finding 1"
    #     },
    #     # {
    #     #     'quote': "…STA/EUVI **in the 195 Å and 304 Å passbands** …",
    #     #     'instrument': "Category A",
    #     #     'parameter': "Finding 1"
    #     # },
    #     # {
    #     #     'quote': "Figures 3(d)… show the CME3 eruption in STA/EUVI-304 Å …",
    #     #     'instrument': "Category A",
    #     #     'parameter': "Finding 1"
    #     # },
    #     # {
    #     #     'quote': "Figure 1 shows...the weak CME as it passes PSP",
    #     #     'instrument': "Category A",
    #     #     'parameter': "Finding 1"
    #     # },
    #     # {
    #     #     'quote': "Figure 1 shows...the weak CME as it passes PSP...The figure is generated using",
    #     #     'instrument': "Category A",
    #     #     'parameter': "Finding 1"
    #     # },
    #     # {
    #     #     'quote': "This is a second quote, which might be very long and could potentially span across two or more lines in the PDF file.",
    #     #     'instrument': "Category B",
    #     #     'parameter': "Multi-line Test"
    #     # },
    # ]

    # 3. Set the desired name for the output file.
    output_filename = "annotated_output3.pdf"

    # --------------------------------------------------------------------------
    #  (No more edits needed below this line)
    # --------------------------------------------------------------------------

    print(f"Processing '{pdf_path}'...")

    try:
        # Run the annotation process using the imported function
        # The first return value here is a Django ContentFile object
        annotated_pdf_file_object, processed_quotes_data = annotate_pdf(pdf_path, quotes_to_find, debug_pages=[5, 12])

        # Save the output file to disk
        with open(output_filename, "wb") as f:
            f.write(annotated_pdf_file_object)

        print(f"✅ Success! Annotation complete.")
        print(f"Please check the output file: '{output_filename}'")

        print("\n--- Found Location Data ---")
        print(json.dumps(processed_quotes_data, indent=2))

    except FileNotFoundError:
        print(f"❌ ERROR: The file was not found at '{pdf_path}'.")