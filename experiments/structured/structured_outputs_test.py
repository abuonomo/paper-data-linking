import hashlib
import json
import os
from jinja2 import Environment, FileSystemLoader
from openai import OpenAI

from experiments.structured.schemas.llm.scientific_observation import ScientificObservationForm

# Define structured output schema with descriptions

# Read content from example_paper.txt
# infile = "txts/2012A&A...538A.138O.txt"
# infile = "txts/2013ApJ...764..170D_analysis.txt"
# infile = "txts/2013ApJ...766...65C_analysis.txt"
infile = "txts/2013ApJ...766...65C.txt"
try:
    with open(infile, "r", encoding="utf-8") as file:
        paper_content = file.read().strip()
except FileNotFoundError:
    print("Error: example_paper.txt not found.")
    exit()


# Initialize OpenAI client
client = OpenAI()


# Load system prompt from XML template using Jinja2
template_dir = "templates"  # Directory where your XML template is stored
template_filename = "system_instructions.xml"  # Your XML template file
env = Environment(loader=FileSystemLoader(template_dir))
template = env.get_template(template_filename)
system_prompt = template.render()  # Render the template (add dynamic values if needed)


# Helper function to generate a unique cache key
def get_cache_key(model: str, content: str) -> str:
    key_string = f"{model}:{content}"
    return hashlib.md5(key_string.encode('utf-8')).hexdigest()


# Function to either return cached completion or make a new API call
def get_cached_completion(model: str, content: str) -> ScientificObservationForm:
    cache_dir = "cache"
    os.makedirs(cache_dir, exist_ok=True)
    cache_key = get_cache_key(model, content)
    cache_path = os.path.join(cache_dir, f"{cache_key}.json")

    if os.path.exists(cache_path):
        print("Loading result from cache...")
        with open(cache_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return ScientificObservationForm.parse_obj(data)
    else:
        print("Making API call...")
        completion = client.beta.chat.completions.parse(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": content},
            ],
            response_format=ScientificObservationForm,
        )
        structured_output = completion.choices[0].message.parsed
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(structured_output.dict(), f, indent=2)
        return structured_output


# Updated intelligent markdown generation function for the updated structure
def generate_markdown(output: ScientificObservationForm) -> str:
    md_lines = []

    # Title
    md_lines.append("# Scientific Observation Instrumentation Form\n")

    # Summary section
    md_lines.append("## Summary of the Paper\n")
    md_lines.append(f"**Content Summary:** {output.summary.content_summary}\n")
    md_lines.append("---\n")

    # Complete Instrument List section
    instrument_list = [f"{instr.instrument_name} ({instr.usage_category.value.capitalize()})"
                       for instr in output.instrumentation_details]
    md_lines.append("## Complete Instrument List\n")
    for idx, instrument in enumerate(instrument_list, start=1):
        md_lines.append(f"- {idx}. {instrument}")
    md_lines.append("---\n")

    # Instrumentation Details section
    md_lines.append("## Instrumentation Details\n")
    for idx, instrument in enumerate(output.instrumentation_details, start=1):
        usage = instrument.usage_category.value.upper()
        md_lines.append(f"### {idx}. {instrument.instrument_name} on board {instrument.spacecraft} ({usage})\n")
        md_lines.append("**General Comments:**")
        md_lines.append(f"> {instrument.general_comments}\n")
        md_lines.append("**Supporting Quote:**")
        md_lines.append(f"> {instrument.general_comments_supporting_quote}\n")

        if instrument.detectors:
            detectors_str = ", ".join(instrument.detectors)
            md_lines.append(f"- **Detectors:** {detectors_str}")
            if instrument.detectors_supporting_quote:
                md_lines.append(f"  - *Supporting Quote:* {instrument.detectors_supporting_quote}\n")

        for period_idx, period in enumerate(instrument.data_collection_periods, start=1):
            md_lines.append(f"#### Data Collection Period {period_idx}: {period.description}\n")

            # Time Range
            end_date = period.end_date if period.end_date is not None else "N/A"
            md_lines.append(f"- **Time Range:** {period.start_date} – {end_date}")
            md_lines.append(f"  - *Supporting Quote:* {period.time_range_supporting_quote}\n")

            # Wavelengths
            wavelengths_str = ", ".join(period.wavelengths) if period.wavelengths else "N/A"
            md_lines.append(f"- **Wavelength(s):** {wavelengths_str}")
            md_lines.append(f"  - *Supporting Quote:* {period.wavelengths_supporting_quote}\n")

            # Physical Observable
            md_lines.append(f"- **Physical Observable:** {period.physical_observable}")
            md_lines.append(f"  - *Supporting Quote:* {period.physical_observable_supporting_quote}\n")

            # Additional Comments
            md_lines.append(f"- **Additional Comments:** {period.additional_comments}\n")

        md_lines.append("---\n")
    return "\n".join(md_lines)


# Function to print and save both JSON and intelligently formatted Markdown output
def save_and_print_output(output: ScientificObservationForm):
    # Serialize to JSON
    output_dict = output.dict()
    json_str = json.dumps(output_dict, indent=2)
    print("Structured Output (JSON):")
    print(json_str)

    # Save JSON to file
    with open("structured_output.json", "w", encoding="utf-8") as f:
        f.write(json_str)

    # Generate intelligently formatted Markdown
    markdown_str = generate_markdown(output)
    print("\nStructured Output (Markdown):")
    print(markdown_str)

    # Save Markdown to file
    with open("structured_output.md", "w", encoding="utf-8") as f:
        f.write(markdown_str)


# Main execution block
if __name__ == "__main__":
    model = "o3-mini"  # or your desired model
    # model = "gpt-4o"  # or your desired model
    structured_output = get_cached_completion(model, paper_content)
    save_and_print_output(structured_output)
    print("Done")
