import io
import copy
import fitz
import unicodedata
import re
from pathlib import Path


class PDFAnnotator:
    """Handles PDF annotation and quote location finding."""

    def __init__(self, pdf_content):
        if isinstance(pdf_content, (str, Path)):
            self.pdf_document = fitz.open(pdf_content)
        elif isinstance(pdf_content, bytes):
            self.pdf_document = fitz.open(stream=pdf_content, filetype="pdf")
        else:
            self.pdf_document = fitz.open(stream=pdf_content.read(), filetype="pdf")
        self.annotation_column_width = 150

    def add_debug_info(self, page_numbers, output_file="pdf_debug_info.txt"):
        """Extracts detailed text data from specified pages for debugging."""
        print(f"--- Writing debug info for pages {page_numbers} to '{output_file}' ---")
        with open(output_file, "w", encoding="utf-8") as f:
            for page_num in page_numbers:
                if page_num >= len(self.pdf_document):
                    f.write(f"\n--- PAGE {page_num + 1} (Out of Bounds) ---\n")
                    continue

                page = self.pdf_document.load_page(page_num)
                f.write(f"\n=======================================================\n")
                f.write(f" DEBUG INFO FOR PAGE {page_num + 1}\n")
                f.write(f"=======================================================\n\n")

                # Get text blocks with detailed info
                data = page.get_text("dict")
                blocks = data.get("blocks", [])
                for b in blocks:  # iterate through the text blocks
                    if 'lines' in b:
                        for l in b["lines"]:  # iterate through the text lines
                            for s in l["spans"]:  # iterate through the text spans
                                f.write(f"Font: '{s['font']}', Size: {s['size']:.2f}, Color: #{s['color']:06x}\n")
                                f.write(
                                    f"  Bbox: [ {s['bbox'][0]:.2f}, {s['bbox'][1]:.2f}, {s['bbox'][2]:.2f}, {s['bbox'][3]:.2f} ]\n")
                                f.write(f"  Text: \"{s['text']}\"\n\n")

    def _try_chained_search(self, page, phrases):
        """
        Finds a sequence of phrases by applying the full search algorithm to each
        part and chaining them together based on proximity.
        """

        def get_instance_bbox(rects):
            if not rects: return None
            return fitz.Rect(min(r.x0 for r in rects), min(r.y0 for r in rects),
                             max(r.x1 for r in rects), max(r.y1 for r in rects))

        all_phrase_locations = []
        for phrase in phrases:
            if '...' in phrase or '…' in phrase: return None
            instances, _ = self.find_quote_location(page, phrase.strip())
            if not instances: return None
            if not isinstance(instances[0], list): instances = [instances]
            all_phrase_locations.append(instances)

        if not all_phrase_locations: return None
        valid_paths = [[loc] for loc in all_phrase_locations[0]]

        for i in range(1, len(all_phrase_locations)):
            next_valid_paths, candidate_locations = [], all_phrase_locations[i]
            for path in valid_paths:
                last_instance_in_path, last_bbox = path[-1], get_instance_bbox(path[-1])
                best_candidate, min_distance = None, float('inf')
                for candidate_locs in candidate_locations:
                    candidate_bbox = get_instance_bbox(candidate_locs)
                    if candidate_bbox.y0 >= last_bbox.y0:
                        distance = candidate_bbox.y0 - last_bbox.y1
                        if 0 <= distance < min_distance and distance < 400:
                            min_distance, best_candidate = distance, candidate_locs
                if best_candidate:
                    next_valid_paths.append(path + [best_candidate])
            valid_paths = next_valid_paths
            if not valid_paths: return None

        if not valid_paths: return None
        best_path_of_instances = valid_paths[0]
        return [rect for instance in best_path_of_instances for rect in instance]

    def find_quote_location(self, page, quote):
        """Find all instances of a quote on a page, with automatic handling for multiple ellipses."""
        if isinstance(quote, str):
            ellipsis_char = None
            if '...' in quote:
                ellipsis_char = '...'
            elif '…' in quote:
                ellipsis_char = '…'
            if ellipsis_char:
                parts = [p.strip() for p in quote.split(ellipsis_char) if p.strip()]
                if len(parts) > 1:
                    instances = self._try_chained_search(page, parts)
                    if instances: 
                        return instances, "chained_ellipsis_search"
                elif len(parts) == 1:
                    # Quote ends with ellipsis, try searching for the main part
                    main_part = parts[0]
                    # Try exact match for the main part
                    instances = page.search_for(main_part, flags=0)
                    if instances:
                        return instances, "exact_match"
                    instances = page.search_for(main_part, flags=fitz.TEXT_INHIBIT_SPACES)
                    if instances:
                        return instances, "case_insensitive"

        if not isinstance(quote, str): return None, None

        instances = self._try_comprehensive_fragment_search(page, quote)
        if instances: 
            return instances, "comprehensive_fragment"

        instances = page.search_for(quote, flags=0)
        if instances: 
            return instances, "exact_match"

        instances = page.search_for(quote, flags=fitz.TEXT_INHIBIT_SPACES)
        if instances: 
            return instances, "case_insensitive"

        normalized_quote = self._normalize_text(quote)
        if normalized_quote != quote:
            instances = page.search_for(normalized_quote, flags=0)
            if instances: 
                return instances, "normalized_exact"
            instances = page.search_for(normalized_quote, flags=fitz.TEXT_INHIBIT_SPACES)
            if instances: 
                return instances, "normalized_insensitive"

        instances = self._try_enhanced_substring_matches(page, quote)
        if instances: 
            return instances, "enhanced_substring"

        instances = self._try_fuzzy_text_matching(page, quote)
        if instances: 
            return instances, "fuzzy_match"

        return None, None

    def _find_cross_page_instances(self, page_num, quote):
        """Attempts to find a quote spanning page_num and page_num + 1."""
        if not isinstance(quote, str) or ('...' not in quote and '…' not in quote):
            return None, None

        page1 = self.pdf_document.load_page(page_num)
        page2 = self.pdf_document.load_page(page_num + 1)
        page_height = page1.rect.height

        ellipsis_char = '...' if '...' in quote else '…'
        start_phrase, end_phrase = [p.strip() for p in quote.split(ellipsis_char, 1)]

        start_instances, _ = self.find_quote_location(page1, start_phrase)
        if not start_instances: return None, None

        bottom_threshold = page_height * 0.75
        candidate_starts = [rects for rects in
                            ([start_instances] if not isinstance(start_instances[0], list) else start_instances) if
                            fitz.Rect(rects[0]).y1 > bottom_threshold]
        if not candidate_starts: return None, None

        end_instances, _ = self.find_quote_location(page2, end_phrase)
        if not end_instances: return None, None

        top_threshold = page_height * 0.25
        candidate_ends = [rects for rects in
                          ([end_instances] if not isinstance(end_instances[0], list) else end_instances) if
                          fitz.Rect(rects[0]).y0 < top_threshold]
        if not candidate_ends: return None, None

        cross_page_rects = {
            page_num: candidate_starts[0],
            page_num + 1: candidate_ends[0]
        }
        return cross_page_rects, "cross_page_ellipsis"

    def find_best_quote_location_in_pdf(self, quote):
        """Find the best location for a quote, searching within single pages and across page boundaries."""
        candidates = []
        for page_num in range(len(self.pdf_document)):
            page = self.pdf_document.load_page(page_num)
            instances, method = self.find_quote_location(page, quote)
            if instances:
                score = self._score_quote_match(page, quote, instances, method)
                candidates.append({'page_num': page_num, 'instances': instances, 'score': score, 'method': method})

            if page_num < len(self.pdf_document) - 1:
                cross_page_instances, cross_method = self._find_cross_page_instances(page_num, quote)
                if cross_page_instances:
                    candidates.append(
                        {'page_num': page_num, 'instances': cross_page_instances, 'score': 999, 'method': cross_method})

        if not candidates:
            return None

        return max(candidates, key=lambda x: x['score'])

    def process_quotes(self, quotes, debug_pages=None):
        """Process all quotes to find locations and add annotations, handling cross-page results."""
        if debug_pages:
            self.add_debug_info(debug_pages)

        processed_quotes = copy.deepcopy(quotes)
        for quote_info in processed_quotes:
            quote_text = quote_info['quote']
            best_location = self.find_best_quote_location_in_pdf(quote_text)

            if not best_location:
                quote_info['location'] = None
                continue

            instances = best_location['instances']

            if isinstance(instances, dict):
                all_rects_by_page = instances
                first_page_num = min(all_rects_by_page.keys())
                first_rect = all_rects_by_page[first_page_num][0]
                for page_num, rects in all_rects_by_page.items():
                    page = self.pdf_document.load_page(page_num)
                    page_width = self.add_annotation_column(page)
                    added_annotations = []
                    for rect in rects:
                        self.add_highlight_and_annotation(page, quote_info, rect, page_width, added_annotations)
                quote_info['location'] = {'page_number': first_page_num + 1, 'x0': first_rect.x0, 'y0': first_rect.y0,
                                          'x1': first_rect.x1, 'y1': first_rect.y1, 'is_cross_page': True}
            else:
                page_num = best_location['page_num']
                page = self.pdf_document.load_page(page_num)
                page_width = self.add_annotation_column(page)
                added_annotations = []
                rectangles = instances if isinstance(instances, list) else [instances]
                for rect in rectangles:
                    self.add_highlight_and_annotation(page, quote_info, rect, page_width, added_annotations)
                first_rect = rectangles[0]
                coordinate_regions = [{'page': page_num + 1, 'x0': r.x0, 'y0': r.y0, 'x1': r.x1, 'y1': r.y1} for r in
                                      rectangles]
                quote_info['location'] = {'page_number': page_num + 1, 'x0': first_rect.x0, 'y0': first_rect.y0,
                                          'x1': first_rect.x1, 'y1': first_rect.y1, 'is_cross_page': False,
                                          'coordinate_regions': coordinate_regions, 'is_multiline': len(rectangles) > 1}
        return processed_quotes

    def _score_quote_match(self, page, quote, instances, method="unknown"):
        """Score a quote match to determine quality."""
        if not instances: return 0
        
        clean_quote = quote.replace('...', ' ').replace('…', ' ') if isinstance(quote, str) else ""
        all_text = " ".join([page.get_textbox(inst).strip() for inst in instances])
        quote_words = clean_quote.lower().split()
        
        if not quote_words: return 0
        
        # Base score from word coverage
        words_found = sum(1 for word in quote_words if word.lower() in all_text.lower())
        word_coverage = words_found / len(quote_words)
        score = word_coverage * 100
        
        # Method-based bonuses (exact matches are much better)
        method_bonuses = {
            "exact_match": 200,
            "case_insensitive": 180,
            "normalized_exact": 160,
            "normalized_insensitive": 140,
            "chained_ellipsis_search": 120,
            "comprehensive_fragment": 50,  # Much lower priority
            "enhanced_substring": 30,
            "fuzzy_match": 10
        }
        score += method_bonuses.get(method, 0)
        
        # Length similarity bonus
        text_length_ratio = len(all_text) / len(clean_quote) if clean_quote else 0
        if 0.8 <= text_length_ratio <= 1.2:  # Similar length
            score += 50
        elif 0.5 <= text_length_ratio <= 2.0:  # Reasonable length
            score += 25
        
        # Penalty for very short matches
        if len(all_text) < len(clean_quote) * 0.3:
            score -= 100
            
        # Penalty for too many fragments (suggests poor match)
        if len(instances) > 5:
            score -= 50
            
        return score

    def _normalize_text(self, text):
        """Normalize text for better PDF matching."""
        normalized = unicodedata.normalize('NFKD', text)
        replacements = {
            '−': '-', '–': '-', '—': '-',
            '‘': "'", '’': "'", '“': '"', '”': '"', '…': '...',
            'ﬁ': 'fi', 'ﬂ': 'fl', 'ﬀ': 'ff', 'ﬃ': 'ffi', 'ﬄ': 'ffl',
        }
        for unicode_char, ascii_char in replacements.items():
            normalized = normalized.replace(unicode_char, ascii_char)
        return normalized.replace('\u00ad', '').replace('\u200b', '')

    def _try_comprehensive_fragment_search(self, page, quote):
        """Try to find ALL fragments of a quote by searching for distinctive phrases and important terms."""
        words = quote.split()
        if len(words) < 3: return []
        
        all_fragments = []
        common_words = {'and', 'the', 'of', 'in', 'to', 'for', 'with', 'on', 'at', 'by', 'from', 'a', 'an', 'is', 'are',
                        'was', 'were', 'we', 'it', 'that', 'this', 'as', 'not', 'can', 'be', 'or', 'but', 'will', 'have', 'has'}
        
        # First pass: Look for longer phrases (more reliable)
        for i in range(len(words)):
            for phrase_len in [6, 5, 4]:  # Start with longer phrases
                if i + phrase_len > len(words): continue
                phrase = ' '.join(words[i:i + phrase_len])
                if len(phrase.strip()) < 15: continue  # Higher threshold for quality
                
                # Skip phrases that are mostly common words
                phrase_words = phrase.lower().split()
                common_word_ratio = sum(1 for w in phrase_words if w in common_words) / len(phrase_words)
                if common_word_ratio > 0.6: continue
                
                for flags in [0, fitz.TEXT_INHIBIT_SPACES]:
                    for match in page.search_for(phrase, flags=flags):
                        all_fragments.append(
                            {'rect': match, 'text': phrase, 'word_start': i, 'word_end': i + phrase_len,
                             'word_count': phrase_len, 'quality': 'high'})

        # Calculate coverage from high-quality fragments only
        covered_indices = {i for frag in all_fragments for i in range(frag['word_start'], frag['word_end'])}
        word_coverage = len(covered_indices) / len(words) if words else 0

        # Second pass: Only if coverage is still low, look for distinctive individual words
        if word_coverage < 0.5:  # Higher threshold
            for i, word in enumerate(words):
                if i in covered_indices: continue
                word_clean = word.strip('.,;:!?"()[]{}…')
                is_distinctive = (
                    word_clean.isnumeric() or
                    (word_clean.isupper() and len(word_clean) >= 2) or
                    word_clean.lower() in ['january', 'february', 'march', 'april', 'may', 'june', 'july',
                                           'august', 'september', 'october', 'november', 'december'] or
                    (len(word_clean) >= 6 and word_clean.lower() not in common_words) or
                    word_clean.lower() in ['aia', 'soho', 'stereo', 'sdo', 'ace', 'wind', 'cluster', 'themis', 'van', 'allen']  # Instrument names
                )
                if is_distinctive:
                    for match in page.search_for(word_clean, flags=fitz.TEXT_INHIBIT_SPACES):
                        all_fragments.append(
                            {'rect': match, 'text': word_clean, 'word_start': i, 'word_end': i + 1, 'word_count': 1, 'quality': 'medium'})

        if not all_fragments: 
            return []

        # Calculate final coverage
        covered_indices = {i for frag in all_fragments for i in range(frag['word_start'], frag['word_end'])}
        final_coverage = len(covered_indices) / len(words) if words else 0
        
        # Require much higher coverage for acceptance
        if final_coverage < 0.7:
            return []

        # Sort by quality and word count
        all_fragments.sort(key=lambda x: (x['quality'] == 'high', x['word_count']), reverse=True)
        anchor_fragment = all_fragments[0]
        anchor_y_center = (anchor_fragment['rect'].y0 + anchor_fragment['rect'].y1) / 2
        
        # More restrictive clustering - fragments must be close together
        clustered_fragments = [f for f in all_fragments if
                               abs((f['rect'].y0 + f['rect'].y1) / 2 - anchor_y_center) < 50]

        # Remove overlapping fragments more aggressively
        unique_fragments = []
        clustered_fragments.sort(key=lambda x: x['word_start'])
        for frag in clustered_fragments:
            if not any(frag['word_start'] >= ex['word_start'] and frag['word_end'] <= ex['word_end'] for ex in unique_fragments):
                unique_fragments.append(frag)

        return [fragment['rect'] for fragment in unique_fragments] if len(unique_fragments) <= 10 else []

    def _try_enhanced_substring_matches(self, page, text, max_attempts=10, min_length=20):
        # This method can be kept for fallback cases but is less critical now.
        return []

    def _try_fuzzy_text_matching(self, page, quote):
        # This method can also be kept for fallback cases.
        return []

    def add_annotation_column(self, page):
        """Add the annotation column to the right side of the page."""
        page_width, page_height = page.rect.width, page.rect.height
        page.set_mediabox(fitz.Rect(0, 0, page_width + self.annotation_column_width, page_height))
        border_rect = fitz.Rect(page_width, 0, page_width + 2, page_height)
        page.add_rect_annot(border_rect)
        return page_width

    def add_highlight_and_annotation(self, page, quote_info, instance, page_width, added_annotations):
        """Add highlight to quote and its annotation in the margin."""
        highlight = page.add_highlight_annot(instance)
        highlight.update()
        vertical_middle = (instance.y0 + instance.y1) / 2
        if any(abs(vertical_middle - y) < 5 for y in added_annotations): return
        annotation_text = f"{quote_info['instrument']} - {quote_info['parameter']}"
        annot_rect = fitz.Rect(page_width + 10, instance.y0, page_width + self.annotation_column_width - 10,
                               instance.y1)
        page.insert_text(annot_rect.top_left, annotation_text, fontsize=8, fontname="helv")
        added_annotations.append(vertical_middle)

    def save(self) -> bytes:
        """Save the annotated PDF and return raw bytes."""
        buf = io.BytesIO()
        self.pdf_document.save(buf, garbage=4, deflate=True)
        self.pdf_document.close()
        return buf.getvalue()


def annotate_pdf(infile, search_details, debug_pages=None):
    """Main function to annotate PDF and find quote locations."""
    annotator = PDFAnnotator(infile)
    processed_quotes = annotator.process_quotes(search_details, debug_pages=debug_pages)
    annotated_pdf = annotator.save()
    return annotated_pdf, processed_quotes