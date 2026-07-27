#!/usr/bin/env python3
"""
HTML Viewer Generator

Generates an HTML viewer for annotated PDFs using a Jinja2 template.
"""

import argparse
import os
from pathlib import Path
from jinja2 import Environment, FileSystemLoader


def main():
    parser = argparse.ArgumentParser(description="Generate HTML viewer for annotated PDFs")
    parser.add_argument('--bibcode', required=True, help='Bibcode of the paper')
    parser.add_argument('--template', default='templates/viewer.html', help='Path to HTML template')
    parser.add_argument('--output', help='Output HTML file path')
    args = parser.parse_args()

    # Set up template environment
    template_dir = os.path.dirname(args.template)
    template_file = os.path.basename(args.template)
    env = Environment(loader=FileSystemLoader(template_dir))
    template = env.get_template(template_file)

    # Render the template with bibcode
    rendered_html = template.render(BIBCODE=args.bibcode)

    # Determine output path if not specified
    if not args.output:
        output_path = Path(f"html/{args.bibcode}_viewer.html")
    else:
        output_path = Path(args.output)

    # Create output directory if needed
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Write the output
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(rendered_html)

    print(f"HTML viewer generated at: {output_path}")
    return 0


if __name__ == "__main__":
    exit(main())