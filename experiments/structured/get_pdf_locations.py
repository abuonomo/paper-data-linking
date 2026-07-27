import json
import re
import unicodedata
import fitz  # PyMuPDF
from fuzzywuzzy import fuzz
import os


###############################################################################
# Helper Functions
###############################################################################

def sample_substrings(search_string, max_attempts=5, sample_length=30):
    """
    Generate a list of substrings from a search string for fallback searches.
    """
    substrings = []
    length = len(search_string)
    for i in range(min(max_attempts, length - sample_length + 1)):
        substrings.append(search_string[i:i + sample_length])
    return substrings


def preprocess_text(text):
    """
    Normalize the text by removing extraneous whitespace and standardizing Unicode.
    """
    text = unicodedata.normalize('NFKC', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def find_best_match_location(text, quote, threshold=80):
    """
    Using a sliding window fuzzy match, returns the best match info
    if the score is above threshold.
    """
    processed_text = preprocess_text(text)
    processed_quote = preprocess_text(quote)

    best_start = None
    best_end = None
    best_score = 0
    best_excerpt = ""

    window_size = len(processed_quote)
    for i in range(len(processed_text) - window_size + 1):
        window = processed_text[i:i + window_size]
        score = fuzz.ratio(window, processed_quote)
        if score > best_score:
            best_score = score
            best_start = i
            best_end = i + window_size
            best_excerpt = window

    if best_score >= threshold:
        return {
            'start': best_start,
            'end': best_end,
            'score': best_score,
            'excerpt': best_excerpt
        }
    else:
        return None


###############################################################################
# Finding Bounding Boxes with Subsampling Fallback
###############################################################################

def find_quote_bounding_boxes(pdf_doc, quote, threshold=80):
    """
    Iterates through each page in the PDF.
    For each page, it extracts text and uses fuzzy matching to decide if the quote is present.
    If a match is found, it attempts to get bounding boxes using page.search_for.
    If no boxes are returned for the full quote, it falls back to sampling substrings.

    Returns a list of dictionaries with page number and bbox coordinates.
    """
    quote = preprocess_text(quote)
    found_bboxes = []

    for page_num in range(len(pdf_doc)):
        page = pdf_doc[page_num]
        page_text = page.get_text("text")
        match_info = find_best_match_location(page_text, quote, threshold)
        if match_info:
            # First try to find the full quote in the page
            text_instances = page.search_for(quote, flags=0)
            # If no results, try sampling substrings
            if not text_instances:
                substrings = sample_substrings(quote)
                for substring in substrings:
                    text_instances = page.search_for(substring, flags=0)
                    if text_instances:
                        break
            if text_instances:
                for rect in text_instances:
                    found_bboxes.append({
                        "page": page_num + 1,  # pages are 1-indexed
                        "bbox": [rect.x0, rect.y0, rect.x1, rect.y1]
                    })
            else:
                found_bboxes.append({
                    "page": page_num + 1,
                    "bbox": None,
                    "note": "Fuzzy match found but no exact bounding box."
                })
    return found_bboxes if found_bboxes else None


###############################################################################
# Cropping and Saving Excerpt Images
###############################################################################

def save_excerpt_images(pdf_doc, bboxes, excerpt_key, output_dir):
    """
    For each bounding box, crop the corresponding region from the PDF page
    and save it as an image in the output directory.
    Returns a list of file paths to the saved images.
    """
    saved_files = []
    for idx, box_info in enumerate(bboxes):
        if box_info.get("bbox") is None:
            continue
        page_num = box_info["page"]
        bbox = box_info["bbox"]
        page = pdf_doc[page_num - 1]
        rect = fitz.Rect(bbox)
        pix = page.get_pixmap(clip=rect)
        # Create a safe file name using the excerpt key and page number.
        safe_key = excerpt_key.replace(" ", "_").replace("/", "_")
        filename = os.path.join(output_dir, f"{safe_key}_page{page_num}_box{idx}.png")
        pix.save(filename)
        saved_files.append(filename)
    return saved_files


###############################################################################
# Updating JSON with Bounding Boxes and Images
###############################################################################

def update_json_with_bboxes(data, pdf_doc, threshold=80, output_image_dir=None):
    """
    Recursively traverse the JSON data. When a key ends with '_supporting_quote_excerpt'
    the function uses its value to search for bounding boxes in the PDF (using subsampling
    if necessary) and adds a new key with the found bounding boxes.
    If an output directory is provided, the script also saves cropped images of the excerpts.
    """
    if isinstance(data, dict):
        for key in list(data.keys()):
            value = data[key]
            if isinstance(value, str) and key.endswith("_supporting_quote_excerpt"):
                bboxes = find_quote_bounding_boxes(pdf_doc, value, threshold)
                new_key = key.replace("_excerpt", "_bbox")
                data[new_key] = bboxes
                if output_image_dir and bboxes:
                    image_files = save_excerpt_images(pdf_doc, bboxes, key, output_image_dir)
                    image_key = key.replace("_excerpt", "_images")
                    data[image_key] = image_files
            else:
                update_json_with_bboxes(value, pdf_doc, threshold, output_image_dir)
    elif isinstance(data, list):
        for item in data:
            update_json_with_bboxes(item, pdf_doc, threshold, output_image_dir)


###############################################################################
# Main Function
###############################################################################

def main(json_filepath, pdf_filepath, output_filepath, output_image_dir, threshold=80):
    # Load JSON data
    with open(json_filepath, 'r', encoding='utf-8') as json_file:
        json_data = json.load(json_file)

    # Open the PDF document
    pdf_doc = fitz.open(pdf_filepath)

    # Create the output image directory if it doesn't exist.
    if output_image_dir and not os.path.exists(output_image_dir):
        os.makedirs(output_image_dir)

    # Update the JSON with bounding box information and save excerpt images.
    update_json_with_bboxes(json_data, pdf_doc, threshold, output_image_dir)

    # Save the updated JSON to a new file
    with open(output_filepath, 'w', encoding='utf-8') as output_file:
        json.dump(json_data, output_file, ensure_ascii=False, indent=2)
    print(f"Updated JSON with bounding boxes saved to {output_filepath}")
    if output_image_dir:
        print(f"Excerpt images saved to directory: {output_image_dir}")


###############################################################################
# Main Block
###############################################################################

if __name__ == "__main__":
    # Hardcoded file paths and image output directory.
    json_filepath = "structured_output_with_locations.json"  # Input JSON file
    pdf_filepath = "pdfs/2013ApJ...766...65C.pdf"  # Input PDF file
    output_filepath = "structured_output_with_bboxes.json"  # Output JSON file
    output_image_dir = "excerpt_images"  # Directory to save excerpt images

    # Use default threshold of 80 for fuzzy matching.
    threshold = 80

    # Execute the main function with hardcoded values.
    main(json_filepath, pdf_filepath, output_filepath, output_image_dir, threshold)
