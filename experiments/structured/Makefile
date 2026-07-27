# Makefile for PDF processing and analysis with smart dependency checking

# Default bibcode (can be overridden with make extract BIBCODE=xxxx)
#BIBCODE ?= 2013ApJ...766...65C
BIBCODE ?= 2023A&A...670A..66A

# Directories
PDF_DIR := pdfs
TXT_DIR := txts
OUTPUT_DIR := output
IMAGES_DIR := excerpts_images
HTML_DIR := html

# File paths
PDF_FILE := $(PDF_DIR)/$(BIBCODE).pdf
TXT_FILE := $(TXT_DIR)/$(BIBCODE).txt
JSON_FILE := $(OUTPUT_DIR)/$(BIBCODE)_structured_output.json
QUOTES_FILE := $(OUTPUT_DIR)/$(BIBCODE)_structured_output_with_locations.json
ANNOTATED_PDF := $(PDF_DIR)/$(BIBCODE)_annotated.pdf
LOCATIONS_JSON := $(PDF_DIR)/$(BIBCODE)_annotated_locations.json
TEMPLATE_DIR := templates
HTML_TEMPLATE := $(TEMPLATE_DIR)/viewer.html
HTML_OUTPUT := $(HTML_DIR)/$(BIBCODE)_viewer.html

# Python environment
PYTHON := poetry run python
EXTRACT_SCRIPT := extract_text.py
ANALYZE_SCRIPT := analyze_paper.py
QUOTES_SCRIPT := quote_location_extractor.py
ANNOTATE_SCRIPT := pdf_annotator.py

# Models
MODEL ?= o3-mini

# Fuzzy match threshold
THRESHOLD ?= 80

# Force recreation of outputs even if they exist
FORCE ?= 0

# Set up PYTHONPATH to include the project root
export PYTHONPATH := $(PYTHONPATH):$(shell cd ../.. && pwd)

# Create required directories
$(PDF_DIR) $(TXT_DIR) $(OUTPUT_DIR) $(IMAGES_DIR) $(HTML_DIR):
	@mkdir -p $@

# Extract text from PDF (only if TXT_FILE doesn't exist or FORCE=1)
$(TXT_FILE): $(PDF_FILE) | $(TXT_DIR)
	@echo "Extracting text from PDF: $(BIBCODE)"
	$(PYTHON) $(EXTRACT_SCRIPT) --input "$(PDF_FILE)" --output "$(TXT_FILE)"

# Extract text (explicit target)
extract:
ifeq ($(FORCE),1)
	@echo "Forcing extraction of text from PDF: $(BIBCODE)"
	@mkdir -p $(TXT_DIR)
	$(PYTHON) $(EXTRACT_SCRIPT) --input "$(PDF_FILE)" --output "$(TXT_FILE)"
else
	@$(MAKE) $(TXT_FILE)
endif

# Analyze extracted text (only if JSON_FILE doesn't exist or is older than TXT_FILE or FORCE=1)
$(JSON_FILE): $(TXT_FILE) | $(OUTPUT_DIR)
	@echo "Analyzing paper: $(BIBCODE)"
	$(PYTHON) $(ANALYZE_SCRIPT) --input "$(TXT_FILE)" --bibcode "$(BIBCODE)" --model "$(MODEL)" --output-dir "$(OUTPUT_DIR)"

# Analyze text (explicit target)
analyze:
ifeq ($(FORCE),1)
	@echo "Forcing analysis of paper: $(BIBCODE)"
	@mkdir -p $(OUTPUT_DIR)
	$(PYTHON) $(ANALYZE_SCRIPT) --input "$(TXT_FILE)" --bibcode "$(BIBCODE)" --model "$(MODEL)" --output-dir "$(OUTPUT_DIR)"
else
	@$(MAKE) $(JSON_FILE)
endif

# Extract quote locations (only if QUOTES_FILE doesn't exist or is older than JSON_FILE or FORCE=1)
$(QUOTES_FILE): $(JSON_FILE) $(TXT_FILE) | $(OUTPUT_DIR)
	@echo "Extracting quote locations for: $(BIBCODE)"
	$(PYTHON) $(QUOTES_SCRIPT) --json "$(JSON_FILE)" --text "$(TXT_FILE)" --output "$(QUOTES_FILE)" --threshold "$(THRESHOLD)" --bibcode "$(BIBCODE)"

# Extract quotes (explicit target)
quotes:
ifeq ($(FORCE),1)
	@echo "Forcing quote location extraction for: $(BIBCODE)"
	@mkdir -p $(OUTPUT_DIR)
	$(PYTHON) $(QUOTES_SCRIPT) --json "$(JSON_FILE)" --text "$(TXT_FILE)" --output "$(QUOTES_FILE)" --threshold "$(THRESHOLD)" --bibcode "$(BIBCODE)"
else
	@$(MAKE) $(QUOTES_FILE)
endif

# Annotate PDF with quote locations (only if ANNOTATED_PDF doesn't exist or is older than QUOTES_FILE or FORCE=1)
$(ANNOTATED_PDF): $(QUOTES_FILE) $(PDF_FILE) | $(PDF_DIR) $(IMAGES_DIR)
	@echo "Annotating PDF for: $(BIBCODE)"
	$(PYTHON) $(ANNOTATE_SCRIPT) --pdf "$(PDF_FILE)" --json "$(QUOTES_FILE)" --output "$(ANNOTATED_PDF)" --images-dir "$(IMAGES_DIR)" --bibcode "$(BIBCODE)"

# Annotate PDF (explicit target)
annotate:
ifeq ($(FORCE),1)
	@echo "Forcing PDF annotation for: $(BIBCODE)"
	@mkdir -p $(PDF_DIR) $(IMAGES_DIR)
	$(PYTHON) $(ANNOTATE_SCRIPT) --pdf "$(PDF_FILE)" --json "$(QUOTES_FILE)" --output "$(ANNOTATED_PDF)" --images-dir "$(IMAGES_DIR)" --bibcode "$(BIBCODE)"
else
	@$(MAKE) $(ANNOTATED_PDF)
endif

# Generate HTML viewer target
$(HTML_OUTPUT): $(ANNOTATED_PDF) $(QUOTES_FILE) | $(HTML_DIR)
	@echo "Generating HTML viewer for: $(BIBCODE)"
	$(PYTHON) generate_viewer.py --bibcode "$(BIBCODE)" --template "$(HTML_TEMPLATE)" --output "$(HTML_OUTPUT)"

# Generate HTML viewer (explicit target)
viewer:
ifeq ($(FORCE),1)
	@echo "Forcing HTML viewer generation for: $(BIBCODE)"
	@mkdir -p $(HTML_DIR)
	$(PYTHON) generate_viewer.py --bibcode "$(BIBCODE)" --template "$(HTML_TEMPLATE)" --output "$(HTML_OUTPUT)"
else
	@$(MAKE) $(HTML_OUTPUT)
endif

# Run full pipeline with dependency checking
process: $(ANNOTATED_PDF) $(HTML_OUTPUT)
	@echo "Completed processing for: $(BIBCODE) (skipped any up-to-date files)"
	@echo "HTML viewer available at: $(HTML_OUTPUT)"

# Run full pipeline forcing recreation of all outputs
process-force:
	@$(MAKE) process FORCE=1

# Run partial pipeline up to quote extraction (no annotation)
process-quotes: $(QUOTES_FILE)
	@echo "Completed processing up to quote extraction for: $(BIBCODE)"

# Check if all required inputs exist and print status
status:
	@echo "Status for bibcode: $(BIBCODE)"
	@echo "PDF file ($(PDF_FILE)): $$([ -f "$(PDF_FILE)" ] && echo "exists" || echo "missing")"
	@echo "Text file ($(TXT_FILE)): $$([ -f "$(TXT_FILE)" ] && echo "exists" || echo "missing")"
	@echo "JSON file ($(JSON_FILE)): $$([ -f "$(JSON_FILE)" ] && echo "exists" || echo "missing")"
	@echo "Quotes file ($(QUOTES_FILE)): $$([ -f "$(QUOTES_FILE)" ] && echo "exists" || echo "missing")"
	@echo "Annotated PDF ($(ANNOTATED_PDF)): $$([ -f "$(ANNOTATED_PDF)" ] && echo "exists" || echo "missing")"
	@echo "Locations JSON ($(LOCATIONS_JSON)): $$([ -f "$(LOCATIONS_JSON)" ] && echo "exists" || echo "missing")"
	@echo "HTML Viewer ($(HTML_OUTPUT)): $$([ -f "$(HTML_OUTPUT)" ] && echo "exists" || echo "missing")"
	@echo "Excerpt images directory: $$([ -d "$(IMAGES_DIR)" ] && echo "exists" || echo "missing")"
	@echo "Excerpt images count: $$(find "$(IMAGES_DIR)" -name "excerpt_*.png" 2>/dev/null | wc -l | tr -d ' ' || echo "0")"

# Serve the HTML viewer with a simple HTTP server
serve: $(HTML_OUTPUT)
	@echo "Starting HTTP server for $(BIBCODE) viewer..."
	@echo "Open http://localhost:8000/$(HTML_DIR)/$(BIBCODE)_viewer.html in your browser"
	@python -m http.server 8000

# Clean up generated files for the current bibcode
clean:
	@echo "Removing generated files for: $(BIBCODE)"
	rm -f "$(TXT_FILE)" "$(JSON_FILE)" "$(QUOTES_FILE)" "$(ANNOTATED_PDF)" "$(LOCATIONS_JSON)" "$(HTML_OUTPUT)"
	@echo "Cleaned up successfully"

# Clean up all generated files
clean-all:
	@echo "Removing all generated files"
	rm -f $(TXT_DIR)/*.txt
	rm -f $(OUTPUT_DIR)/*.json $(OUTPUT_DIR)/*.md
	rm -f $(PDF_DIR)/*_annotated.pdf $(PDF_DIR)/*_locations.json
	rm -f $(HTML_DIR)/*.html
	rm -rf $(IMAGES_DIR)/*
	@echo "Cleaned up all files successfully"

.PHONY: extract analyze quotes annotate viewer process process-force process-quotes status serve clean clean-all