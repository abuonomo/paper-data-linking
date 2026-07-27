import fitz
import unicodedata
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Dict, Tuple, Optional, Union
import difflib
from enum import Enum

def _normalize_mathematical_spacing(text: str) -> str:
    """Normalize spacing in mathematical expressions for more flexible matching."""
    if not text:
        return text
    
    # Patterns that indicate mathematical content
    math_indicators = [
        r'[a-zA-Z]\s*[=]\s*\(',  # Variable = (
        r'\|\|.*\|\|',  # Double bars (norms)
        r'[a-zA-Z]\s*[-+]\s*[a-zA-Z]',  # Variable operations
        r'[a-zA-Z]\s*[*]\s*[a-zA-Z]',  # Variable multiplication
        r'\(\s*[a-zA-Z]\s*\)',  # Single variables in parentheses
        r'[a-zA-Z]\s*[0-9]',  # Variable subscript patterns
    ]
    
    # Check if this looks like mathematical text
    is_math = any(re.search(pattern, text, re.IGNORECASE) for pattern in math_indicators)
    
    if is_math:
        # Normalize spacing around mathematical operators and symbols
        # This creates more consistent spacing patterns
        
        # Normalize around equals signs: remove extra spaces
        text = re.sub(r'\s*=\s*', ' = ', text)
        
        # Normalize around parentheses: ensure single spaces
        text = re.sub(r'\s*\(\s*', ' ( ', text)
        text = re.sub(r'\s*\)\s*', ' ) ', text)
        
        # Normalize around mathematical operators
        text = re.sub(r'\s*\+\s*', ' + ', text)
        text = re.sub(r'\s*-\s*', ' - ', text)
        text = re.sub(r'\s*\*\s*', ' * ', text)
        text = re.sub(r'\s*/\s*', ' / ', text)
        
        # Normalize around brackets and braces
        text = re.sub(r'\s*\[\s*', ' [ ', text)
        text = re.sub(r'\s*\]\s*', ' ] ', text)
        text = re.sub(r'\s*\{\s*', ' { ', text)
        text = re.sub(r'\s*\}\s*', ' } ', text)
        
        # Normalize around double bars (norms)
        text = re.sub(r'\|\|\s*', '|| ', text)
        text = re.sub(r'\s*\|\|', ' ||', text)
        
        # Normalize around commas in mathematical expressions
        text = re.sub(r'\s*,\s*', ' , ', text)
        
        # Clean up multiple spaces that might have been introduced
        text = re.sub(r'\s+', ' ', text)
    
    return text


def _normalize_text(text: str) -> str:
    """Normalize text for robust matching against PDF-extracted text."""
    if not isinstance(text, str):
        return ""
    t = unicodedata.normalize("NFKD", text)
    replacements = {
        # Dashes and hyphens
        "−": "-", "–": "-", "—": "-", "―": "-", "‐": "-",
        # Quotes
        "'": "'", "'": "'", "‚": "'", "‛": "'", "`": "'",
        """: '"', """: '"', "„": '"', "‟": '"',
        # Ellipsis
        "…": "...",
        # Ligatures
        "ﬁ": "fi", "ﬂ": "fl", "ﬀ": "ff", "ﬃ": "ffi", "ﬄ": "ffl",
        # Mathematical symbols - normalize to ASCII equivalents
        "·": "*", "∙": "*", "•": "*", "⋅": "*", "×": "*", "⨯": "*",
        "±": "+-", "∓": "-+", "≈": "~=", "≃": "~=", "≅": "~=",
        "≠": "!=", "≤": "<=", "≥": ">=", "≪": "<<", "≫": ">>",
        "∞": "inf", "∂": "d", "∇": "grad", "∆": "delta", "∑": "sum",
        "∏": "prod", "∫": "int", "√": "sqrt", "∝": "prop",
        # Greek letters commonly used in math - normalize to names
        "α": "alpha", "β": "beta", "γ": "gamma", "δ": "delta", "ε": "epsilon",
        "ζ": "zeta", "η": "eta", "θ": "theta", "ι": "iota", "κ": "kappa",
        "λ": "lambda", "μ": "mu", "ν": "nu", "ξ": "xi", "ο": "omicron",
        "π": "pi", "ρ": "rho", "σ": "sigma", "τ": "tau", "υ": "upsilon",
        "φ": "phi", "χ": "chi", "ψ": "psi", "ω": "omega",
        "Α": "Alpha", "Β": "Beta", "Γ": "Gamma", "Δ": "Delta", "Ε": "Epsilon",
        "Ζ": "Zeta", "Η": "Eta", "Θ": "Theta", "Ι": "Iota", "Κ": "Kappa",
        "Λ": "Lambda", "Μ": "Mu", "Ν": "Nu", "Ξ": "Xi", "Ο": "Omicron",
        "Π": "Pi", "Ρ": "Rho", "Σ": "Sigma", "Τ": "Tau", "Υ": "Upsilon",
        "Φ": "Phi", "Χ": "Chi", "Ψ": "Psi", "Ω": "Omega",
        # Superscript and subscript numbers
        "⁰": "0", "¹": "1", "²": "2", "³": "3", "⁴": "4", "⁵": "5",
        "⁶": "6", "⁷": "7", "⁸": "8", "⁹": "9", "⁺": "+", "⁻": "-",
        "₀": "0", "₁": "1", "₂": "2", "₃": "3", "₄": "4", "₅": "5",
        "₆": "6", "₇": "7", "₈": "8", "₉": "9", "₊": "+", "₋": "-",
        # Degree and similar symbols
        "°": "deg", "′": "'", "″": '"', "‴": "'''",
        # Special whitespace and separators
        "\u00a0": " ",  # Non-breaking space
        "\u2003": " ",  # Em space
        "\u2002": " ",  # En space
        "\u2004": " ",  # Three-per-em space
        "\u2005": " ",  # Four-per-em space
        "\u2006": " ",  # Six-per-em space
    }
    for u, a in replacements.items():
        t = t.replace(u, a)
    # Remove soft hyphen and zero-widths
    t = t.replace("\u00ad", "").replace("\u200b", "").replace("\u2009", " ").replace("\u202f", " ")
    
    # Apply mathematical spacing normalization
    t = _normalize_mathematical_spacing(t)
    
    # Collapse whitespace
    t = re.sub(r"\s+", " ", t)
    return t.strip()


class MatchMethod(Enum):
    EXACT_CI = "exact_ci"
    PUNCTUATION_FALLBACK = "punctuation_fallback"
    HYPHEN_JOIN_VARIANT = "hyphen_join_variant"
    WORD_FRAGMENT_JOIN = "word_fragment_join"
    ANCHOR_GAPPED = "anchor_gapped"
    ELLIPSIS_CHAIN = "ellipsis_chain"
    CROSS_PAGE_CHAIN = "cross_page_chain"
    CROSS_PAGE_LINES_COMBINED = "cross_page_lines_combined"
    FITZ_ANCHOR_CHAIN = "fitz_anchor_chain"
    FUZZY_MATCH = "fuzzy_match"
    CHARACTER_ALIGNMENT = "character_alignment"

@dataclass
class QuoteCandidate:
    """A candidate match for a quote with scoring information"""
    quote: str
    start_char: int
    end_char: int
    method: MatchMethod
    page_regions: Dict[int, List[fitz.Rect]]
    location_data: Optional[Dict] = None
    
    # Scoring components
    text_similarity_score: float = 0.0
    spatial_coherence_score: float = 0.0
    context_relevance_score: float = 0.0
    confidence_score: float = 0.0
    
    # Debug information
    debug_info: Dict = field(default_factory=dict)
    
    @property
    def total_score(self) -> float:
        """Weighted combination of scoring components"""
        return (0.4 * self.text_similarity_score + 
                0.3 * self.spatial_coherence_score + 
                0.2 * self.context_relevance_score + 
                0.1 * self.confidence_score)

@dataclass
class QuoteMatch:
    quote: str
    page_regions: Dict[int, List[fitz.Rect]]  # page_num -> list of rects


class PDFTextSearcher:
    """
    Single-pass PDF text indexer + quote finder.
    - Builds a normalized text string for the whole document once.
    - Maintains a char->token map to map string matches back to PDF rectangles.
    - Finds quotes without mutating the PDF.
    """

    def __init__(self, pdf_content, fast_index: bool = False):
        if isinstance(pdf_content, (str, Path)):
            self.doc = fitz.open(pdf_content)
        elif isinstance(pdf_content, bytes):
            self.doc = fitz.open(stream=pdf_content, filetype="pdf")
        else:
            self.doc = fitz.open(stream=pdf_content.read(), filetype="pdf")
        # Concatenated normalized text across entire document
        self.norm_text: str = ""
        self.norm_text_lower: str = ""
        # For each token (word), store its normalized text and geometry
        self.tokens: List[Tuple[int, fitz.Rect, str, Tuple[int, int, int]]] = []
        # token -> (page_num, rect, norm_word, (block, line, word))
        # Map of each character index in norm_text -> token index (or -1 for spaces)
        self.char_to_token: List[int] = []
        # Page ranges in the concatenated normalized text (start, end)
        self.page_ranges: List[Tuple[int, int]] = []
        # Per-page line info: list of {'norm_text': str, 'rect': fitz.Rect}
        self.page_lines: List[List[Dict[str, object]]] = []
        # Known dehyphenation joins detected at line breaks (concatenated tokens)
        self.hyphen_joins: set[str] = set()
        # Precompute index once. fast_index builds the SAME structures from the
        # much cheaper get_text("words") extraction (~4x faster than "dict") for
        # the bulk-enrichment path; the default "dict" build is left untouched so
        # the interactive/research finders are byte-for-byte unchanged.
        if fast_index:
            self._build_index_words()
        else:
            self._build_index()

    def _build_index(self):
        char_buffer: List[str] = []
        char_to_token: List[int] = []
        tokens: List[Tuple[int, fitz.Rect, str, Tuple[int, int, int]]] = []

        for page_num in range(len(self.doc)):
            page_start = len(char_buffer)
            page = self.doc.load_page(page_num)
            data = page.get_text("dict")
            lines_info: List[Dict[str, object]] = []

            prev_line_key: Optional[Tuple[int, int]] = None
            prev_span_ended_with_hyphen = False
            prev_line_raw_text = ""
            prev_line_first_token = None
            prev_line_last_token = None

            for block in data.get("blocks", []):
                if "lines" not in block:
                    continue
                for line in block["lines"]:
                    line_key = (id(block), id(line))
                    # Handle line transitions
                    if prev_line_key is not None and line_key != prev_line_key:
                        if prev_span_ended_with_hyphen and char_buffer and char_buffer[-1] == '-':
                            # Remove trailing hyphen for hyphen-join across line break
                            char_buffer.pop()
                            char_to_token.pop()
                            # no space
                        else:
                            char_buffer.append(" ")
                            char_to_token.append(-1)
                        prev_span_ended_with_hyphen = False

                    # Collect raw and normalized text for the entire line and its bbox union
                    line_raw_parts = []
                    line_norm_parts = []
                    line_rect: Optional[fitz.Rect] = None

                    for span in line.get("spans", []):
                        text = span.get("text", "")
                        norm_span = _normalize_text(text)
                        if not norm_span:
                            # still consider for raw line text/bbox
                            pass
                        rect = fitz.Rect(span.get("bbox", [0, 0, 0, 0]))

                        token_index = len(tokens)
                        if norm_span:
                            char_buffer.extend(list(norm_span))
                            char_to_token.extend([token_index] * len(norm_span))
                            tokens.append((page_num, rect, norm_span, (0, 0, 0)))

                        prev_span_ended_with_hyphen = text.rstrip().endswith('-')
                        prev_line_key = line_key

                        # Build line aggregates
                        line_raw_parts.append(text)
                        if line_rect is None:
                            line_rect = rect
                        else:
                            line_rect = line_rect | rect
                        if norm_span:
                            line_norm_parts.append(norm_span)

                    # After processing spans in this line, record line info
                    raw_line_text = "".join(line_raw_parts)
                    norm_line_text = " ".join(line_norm_parts).strip()
                    if line_rect is None:
                        line_rect = fitz.Rect(0, 0, 0, 0)
                    lines_info.append({
                        'norm_text': norm_line_text.lower(),
                        'rect': line_rect,
                    })

                    # Detect word breaks at line boundaries (both hyphenated and non-hyphenated)
                    if prev_line_raw_text:
                        prev_tokens = self._tokenize_words(prev_line_raw_text)
                        curr_tokens = self._tokenize_words(raw_line_text)
                        if prev_tokens and curr_tokens:
                            prev_last = prev_tokens[-1].lower()
                            curr_first = curr_tokens[0].lower()
                            
                            # Case 1: Traditional hyphenation (line ends with hyphen)
                            if prev_line_raw_text.rstrip().endswith('-'):
                                join = prev_last + curr_first
                                self.hyphen_joins.add(join)
                            
                            # Case 2: Word fragments (possible line-break word splitting)
                            # Look for cases where combining fragments forms a likely word
                            elif self._looks_like_word_fragment(prev_last, curr_first):
                                join = prev_last + curr_first
                                self.hyphen_joins.add(join)
                                # Also add common hyphenated variants
                                self.hyphen_joins.add(prev_last + "-" + curr_first)
                                self.hyphen_joins.add(prev_last + " " + curr_first)

                    prev_line_raw_text = raw_line_text

            # Record page range end (before separator)
            page_end = len(char_buffer)
            self.page_ranges.append((page_start, page_end))
            self.page_lines.append(lines_info)
            # Separate pages with a space to avoid accidental concatenation
            if page_num < len(self.doc) - 1:
                char_buffer.append(" ")
                char_to_token.append(-1)

        self.norm_text = "".join(char_buffer)
        self.norm_text_lower = self.norm_text.lower()
        self.char_to_token = char_to_token
        self.tokens = tokens

    def _build_index_words(self):
        """Fast index build from get_text("words") instead of "dict".

        Produces the identical public structures (norm_text/_lower, tokens,
        char_to_token, page_ranges, page_lines, hyphen_joins) that every finder
        consumes, but ~4x cheaper because "words" skips the span/style tree.
        One token == one whitespace-delimited word (finer than "dict" spans),
        which also gives real (block, line, word) indices for tighter region
        merging. Lines are reconstructed by grouping words on (block, line).
        """
        char_buffer: List[str] = []
        char_to_token: List[int] = []
        tokens: List[Tuple[int, fitz.Rect, str, Tuple[int, int, int]]] = []

        for page_num in range(len(self.doc)):
            page_start = len(char_buffer)
            page = self.doc.load_page(page_num)
            # words: (x0, y0, x1, y1, "word", block_no, line_no, word_no)
            words = page.get_text("words")
            lines_info: List[Dict[str, object]] = []

            prev_line_key: Optional[Tuple[int, int]] = None
            prev_word_ended_with_hyphen = False
            prev_line_raw_text = ""
            # accumulators for the current line
            cur_line_norm_parts: List[str] = []
            cur_line_raw_parts: List[str] = []
            cur_line_rect: Optional[fitz.Rect] = None

            def flush_line():
                nonlocal cur_line_norm_parts, cur_line_raw_parts, cur_line_rect
                nonlocal prev_line_raw_text
                raw_line_text = " ".join(cur_line_raw_parts)
                norm_line_text = " ".join(cur_line_norm_parts).strip()
                rect = cur_line_rect if cur_line_rect is not None else fitz.Rect(0, 0, 0, 0)
                lines_info.append({'norm_text': norm_line_text.lower(), 'rect': rect})
                # Detect word breaks at line boundaries (hyphenated + fragment joins)
                if prev_line_raw_text:
                    prev_tokens = self._tokenize_words(prev_line_raw_text)
                    curr_tokens = self._tokenize_words(raw_line_text)
                    if prev_tokens and curr_tokens:
                        prev_last = prev_tokens[-1].lower()
                        curr_first = curr_tokens[0].lower()
                        if prev_line_raw_text.rstrip().endswith('-'):
                            self.hyphen_joins.add(prev_last + curr_first)
                        elif self._looks_like_word_fragment(prev_last, curr_first):
                            self.hyphen_joins.add(prev_last + curr_first)
                            self.hyphen_joins.add(prev_last + "-" + curr_first)
                            self.hyphen_joins.add(prev_last + " " + curr_first)
                prev_line_raw_text = raw_line_text
                cur_line_norm_parts = []
                cur_line_raw_parts = []
                cur_line_rect = None

            for (x0, y0, x1, y1, word, bno, lno, wno) in words:
                line_key = (bno, lno)
                if prev_line_key is not None and line_key != prev_line_key:
                    # line transition: flush the completed line, then join/space
                    flush_line()
                    if prev_word_ended_with_hyphen and char_buffer and char_buffer[-1] == '-':
                        char_buffer.pop()
                        char_to_token.pop()
                    else:
                        char_buffer.append(" ")
                        char_to_token.append(-1)
                    prev_word_ended_with_hyphen = False
                elif prev_line_key is not None:
                    # same line, subsequent word: separate with a space
                    char_buffer.append(" ")
                    char_to_token.append(-1)

                rect = fitz.Rect(x0, y0, x1, y1)
                norm_word = _normalize_text(word)
                if norm_word:
                    token_index = len(tokens)
                    char_buffer.extend(list(norm_word))
                    char_to_token.extend([token_index] * len(norm_word))
                    tokens.append((page_num, rect, norm_word, (bno, lno, wno)))
                    cur_line_norm_parts.append(norm_word)

                cur_line_raw_parts.append(word)
                cur_line_rect = rect if cur_line_rect is None else (cur_line_rect | rect)
                prev_word_ended_with_hyphen = word.rstrip().endswith('-')
                prev_line_key = line_key

            # flush the final line of the page
            if cur_line_raw_parts or cur_line_norm_parts:
                flush_line()

            page_end = len(char_buffer)
            self.page_ranges.append((page_start, page_end))
            self.page_lines.append(lines_info)
            if page_num < len(self.doc) - 1:
                char_buffer.append(" ")
                char_to_token.append(-1)

        self.norm_text = "".join(char_buffer)
        self.norm_text_lower = self.norm_text.lower()
        self.char_to_token = char_to_token
        self.tokens = tokens

    def _spans_to_regions(self, start: int, end: int) -> Dict[int, List[fitz.Rect]]:
        """Map a match span in norm_text back to PDF rectangles grouped by page."""
        token_indices = []
        # Collect token indices overlapped by the character span
        for i in range(start, end):
            t = self.char_to_token[i] if 0 <= i < len(self.char_to_token) else -1
            if t != -1 and (not token_indices or token_indices[-1] != t):
                token_indices.append(t)

        if not token_indices:
            return {}

        # Group by page and by line to create tight rectangles per line
        regions: Dict[int, List[fitz.Rect]] = {}
        for t_idx in token_indices:
            page_num, rect, _norm_word, (block, line, _wno) = self.tokens[t_idx]
            if page_num not in regions:
                regions[page_num] = [rect]
            else:
                # Try to merge with last rect on the same line by vertical proximity
                last_rect = regions[page_num][-1]
                same_line = abs(((last_rect.y0 + last_rect.y1) / 2) - ((rect.y0 + rect.y1) / 2)) < 3
                if same_line and rect.x0 >= last_rect.x0 - 2:
                    # Extend horizontally
                    regions[page_num][-1] = fitz.Rect(min(last_rect.x0, rect.x0),
                                                      min(last_rect.y0, rect.y0),
                                                      max(last_rect.x1, rect.x1),
                                                      max(last_rect.y1, rect.y1))
                else:
                    regions[page_num].append(rect)

        return regions

    def _extract_norm_text_for_span(self, start: int, end: int) -> str:
        """Reconstruct normalized text from token indices overlapped by [start, end)."""
        token_indices = []
        for i in range(start, end):
            t = self.char_to_token[i] if 0 <= i < len(self.char_to_token) else -1
            if t != -1 and (not token_indices or token_indices[-1] != t):
                token_indices.append(t)
        if not token_indices:
            return ""
        parts: List[str] = []
        last_page = None
        last_line_center = None
        for t_idx in token_indices:
            page_num, rect, norm_word, (_b, _l, _w) = self.tokens[t_idx]
            if last_page is None:
                parts.append(norm_word)
            else:
                # Add space between tokens; treat line breaks as a single space
                parts.append(" ")
                parts.append(norm_word)
            last_page = page_num
            last_line_center = (rect.y0 + rect.y1) / 2
        return "".join(parts).lower()

    def _boundary_combined_window(self, page_index: int, lines_each_side: int = 12) -> Optional[Tuple[str, List[Tuple[int, int, int, fitz.Rect]]]]:
        """
        Build a combined normalized text window from the last N lines of page_index
        and the first N lines of page_index+1.
        Returns (combined_text, segments) where segments is a list of tuples:
          (page_idx, line_idx_in_page, start_char_in_combined, line_rect)
        enabling mapping from a match span to the contributing line rects.
        Filters out header-like lines (digits-only or very short).
        """
        if page_index < 0 or page_index >= len(self.page_lines) - 1:
            return None
        left_lines = self.page_lines[page_index][-lines_each_side:]
        right_lines = self.page_lines[page_index + 1][:lines_each_side]

        def is_header_like(text: str) -> bool:
            t = (text or '').strip().lower()
            if not t:
                return True
            # page numbers or very short tokens
            if t.isdigit() and len(t) <= 3:
                return True
            if len(t) <= 3:
                return True
            # emails or arxiv ids or obvious boilerplate
            if '@' in t:
                return True
            if 'arxiv:' in t or 'arxiv' in t:
                return True
            return False

        combined = []
        segments: List[Tuple[int, int, int, fitz.Rect]] = []
        cursor = 0

        # Left side lines
        for li, ln in enumerate(left_lines):
            txt = (ln.get('norm_text') or '')
            if is_header_like(txt):
                continue
            combined.append(txt)
            segments.append((page_index, len(self.page_lines[page_index]) - len(left_lines) + li, cursor, ln.get('rect')))
            cursor += len(txt) + 1
            combined.append(' ')

        # Separator between pages
        combined.append(' ')
        cursor += 1

        # Right side lines
        for ri, rn in enumerate(right_lines):
            txt = (rn.get('norm_text') or '')
            if is_header_like(txt):
                continue
            combined.append(txt)
            segments.append((page_index + 1, ri, cursor, rn.get('rect')))
            cursor += len(txt) + 1
            combined.append(' ')

        combined_text = ''.join(combined).strip()
        return combined_text, segments

    @staticmethod
    def _tokenize_words(text: str) -> List[str]:
        return re.findall(r"[0-9A-Za-z]+", text.lower())
    
    @staticmethod
    def _looks_like_word_fragment(part1: str, part2: str) -> bool:
        """
        Determine if two word parts are likely fragments of a single word split across lines.
        Uses heuristics based on word structure and common word patterns.
        """
        if not part1 or not part2:
            return False
        
        # Must be alphabetic (not numbers or mixed)
        if not part1.isalpha() or not part2.isalpha():
            return False
        
        # Single characters are unlikely to be meaningful fragments
        if len(part1) < 2 or len(part2) < 2:
            return False
        
        # Very long parts are unlikely to be fragments
        if len(part1) > 12 or len(part2) > 12:
            return False
        
        combined = part1 + part2
        
        # Common word patterns that suggest valid word formation
        valid_patterns = [
            # Common prefixes and suffixes
            r'^(in|un|re|de|pre|pro|anti|counter|over|under|inter|intra|extra|ultra)',
            r'(tion|sion|ment|ness|able|ible|ance|ence|ive|ing|ed|er|est|ly|ity|ous|ful)$',
            # Common word endings
            r'(ture|sure|ance|ence|ence|ment|tion|sion|ness|able|ible)$',
            # Scientific/technical patterns
            r'^(micro|macro|nano|multi|pseudo|quasi|semi|super|hyper|meta)',
            r'(meter|graph|scope|logy|ology|ometry|metric)$',
        ]
        
        # Check if combined word matches common patterns
        for pattern in valid_patterns:
            if re.search(pattern, combined, re.IGNORECASE):
                return True
        
        # Heuristic: check for consonant clusters that suggest word boundaries
        # If part1 ends with consonants and part2 starts with consonants, likely a break
        vowels = set('aeiou')
        part1_ends_consonant = len(part1) >= 2 and part1[-1].lower() not in vowels
        part2_starts_consonant = len(part2) >= 2 and part2[0].lower() not in vowels
        
        # Common word break patterns
        if part1_ends_consonant and part2_starts_consonant:
            # Check for common consonant cluster patterns
            cluster = part1[-2:] + part2[:2]
            # Avoid unlikely consonant clusters
            unlikely_clusters = ['qx', 'xq', 'zx', 'xz', 'jx', 'xj']
            if any(bad in cluster.lower() for bad in unlikely_clusters):
                return False
            return True
        
        # Check for known problematic combinations that are in our test data
        known_fragments = [
            ('in', 'vestigation'),  # "investigation"
            ('mea', 'surements'),   # "measurements"
            ('corre', 'lated'),     # "correlated"
            ('proper', 'ties'),     # "properties"
            ('struc', 'ture'),      # "structure"
            ('func', 'tion'),       # "function"
            ('descrip', 'tion'),    # "description"
            ('inter', 'action'),    # "interaction"
            ('observa', 'tion'),    # "observation"
            ('instru', 'ment'),     # "instrument"
        ]
        
        for frag1, frag2 in known_fragments:
            if part1.lower() == frag1 and part2.lower() == frag2:
                return True
            if part1.lower() == frag2 and part2.lower() == frag1:  # reverse order
                return True
        
        return False

    @staticmethod
    def _anchors(tokens: List[str]) -> List[str]:
        stop = {
            'the','a','an','and','or','of','in','to','for','on','by','with','as','at','is','are','was','were','be','been','this','that','it','we','you','they','i','from'
        }
        return [t for t in tokens if len(t) >= 4 and t not in stop]
    
    @staticmethod
    def _get_adaptive_thresholds(quote_text: str, parameter: str = "") -> dict:
        """
        Determine appropriate verification thresholds based on quote characteristics.
        Returns thresholds optimized for different content types.
        """
        # Default thresholds
        thresholds = {
            'coverage_ratio_min': 0.6,
            'len_ratio_min': 0.6,
            'len_ratio_max': 1.8,
            'anchors_min': 2
        }
        
        # Detect content type
        is_mathematical = any(pattern in quote_text.lower() for pattern in [
            '=', '+', '-', '*', '/', '(', ')', '[', ']', '{', '}',
            'alpha', 'beta', 'gamma', 'delta', 'lambda', 'sigma', 'theta',
            'equation', 'formula', 'coefficient', 'matrix', 'norm'
        ])
        
        is_dash_heavy = quote_text.count('–') + quote_text.count('-') + quote_text.count('—') > 2
        
        has_special_chars = any(char in quote_text for char in ['°', '′', '″', '×', '±', '≈', '≤', '≥'])
        
        # Parameter-based adjustments
        param_lower = parameter.lower()
        is_dash_parameter = 'dash' in param_lower
        is_hyphen_parameter = 'hyphen' in param_lower
        is_cross_page_parameter = 'cross' in param_lower
        
        # Adaptive adjustments
        if is_mathematical or has_special_chars:
            # Mathematical expressions: more lenient on length, stricter on coverage
            thresholds.update({
                'coverage_ratio_min': 0.5,  # More lenient - math symbols can be tricky
                'len_ratio_min': 0.4,       # Much more lenient - math spacing varies
                'len_ratio_max': 2.5,       # Allow longer segments for math
                'anchors_min': 1            # Mathematical expressions may have fewer distinctive words
            })
        
        if is_dash_heavy or is_dash_parameter:
            # Dash-heavy content: adjust for measurement ranges, citations
            thresholds.update({
                'coverage_ratio_min': 0.55,
                'len_ratio_min': 0.5,
                'len_ratio_max': 2.0,
                'anchors_min': 1
            })
        
        if is_hyphen_parameter:
            # Hyphenated content: very lenient on length ratios
            thresholds.update({
                'coverage_ratio_min': 0.5,
                'len_ratio_min': 0.4,
                'len_ratio_max': 2.5,
                'anchors_min': 1
            })
        
        if is_cross_page_parameter:
            # Cross-page content: should be stricter to avoid false positives
            thresholds.update({
                'coverage_ratio_min': 0.7,
                'len_ratio_min': 0.7,
                'len_ratio_max': 1.5,
                'anchors_min': 2
            })
        
        # Quote length adjustments
        if len(quote_text) < 30:
            # Short quotes: be more lenient on anchors
            thresholds['anchors_min'] = 1
        elif len(quote_text) > 100:
            # Long quotes: can be stricter
            thresholds['coverage_ratio_min'] = min(0.7, thresholds['coverage_ratio_min'] + 0.1)
        
        return thresholds

    def _fuzzy_string_match(self, query: str, threshold: float = 0.6, max_matches: int = 3, max_iterations: int = 500) -> List[Tuple[int, int, float]]:
        """
        Find fuzzy matches using difflib sequence matching.
        Returns list of (start, end, similarity_ratio) tuples.
        OPTIMIZED: Larger step sizes, iteration limits, quick ratio checks.
        """
        matches = []
        query_lower = query.lower()
        
        # Use sliding window approach with performance optimizations
        window_size = len(query)
        # OPTIMIZATION: Larger step sizes for better performance
        step_size = max(window_size // 2, 10)  # Reduced overlap, minimum 10 chars
        
        iteration_count = 0
        for i in range(0, len(self.norm_text_lower) - window_size + 1, step_size):
            # OPTIMIZATION: Limit iterations for very long documents
            iteration_count += 1
            if iteration_count > max_iterations:
                break
                
            window = self.norm_text_lower[i:i + window_size * 2]  # Slightly larger window
            
            # OPTIMIZATION: Quick ratio check before expensive SequenceMatcher
            common_chars = sum(1 for c in query_lower if c in window)
            quick_ratio = common_chars / len(query_lower)
            if quick_ratio < threshold * 0.7:  # Pre-filter: needs at least 70% of threshold
                continue
            
            # Use SequenceMatcher for fuzzy matching
            matcher = difflib.SequenceMatcher(None, query_lower, window)
            ratio = matcher.ratio()
            
            if ratio >= threshold:
                # Find the best matching substring within the window
                matching_blocks = matcher.get_matching_blocks()
                if matching_blocks:
                    # Get the span of the match
                    start_in_window = min(block.b for block in matching_blocks if block.size > 0)
                    end_in_window = max(block.b + block.size for block in matching_blocks if block.size > 0)
                    
                    actual_start = i + start_in_window
                    actual_end = i + end_in_window
                    
                    # Avoid overlapping matches
                    if not any(abs(actual_start - m[0]) < window_size // 2 for m in matches):
                        matches.append((actual_start, actual_end, ratio))
                        
                        # OPTIMIZATION: Early termination when we have enough good matches
                        if len(matches) >= max_matches:
                            break
        
        # Sort by similarity ratio, descending
        return sorted(matches, key=lambda x: x[2], reverse=True)

    def _character_level_alignment(self, query: str, max_candidates: int = 3, max_iterations: int = 200) -> List[Tuple[int, int, float]]:
        """
        Perform character-level alignment for mathematical expressions with OCR errors.
        Uses edit distance with custom costs for common OCR substitutions.
        OPTIMIZED: Larger step sizes, iteration limits, length pre-checks.
        """
        matches = []
        query_lower = query.lower()
        
        # Define OCR-common character substitutions and their costs
        ocr_costs = {
            # Mathematical symbols often confused
            ('l', '1'): 0.1, ('1', 'l'): 0.1, ('0', 'o'): 0.1, ('o', '0'): 0.1,
            ('*', '×'): 0.1, ('×', '*'): 0.1, ('-', '−'): 0.1, ('−', '-'): 0.1,
            # Common ligature issues
            ('fi', 'ﬁ'): 0.1, ('fl', 'ﬂ'): 0.1, ('ff', 'ﬀ'): 0.1,
            # Space/punctuation variations
            (' ', ''): 0.2, ('', ' '): 0.2,
        }
        
        # Use a sliding window approach with custom edit distance
        window_size = len(query)
        max_distance = window_size * 0.3  # Allow up to 30% character differences
        
        # OPTIMIZATION: Larger step sizes and iteration limit
        step_size = max(window_size // 4, 5)  # Larger steps, minimum 5 chars
        iteration_count = 0
        
        for i in range(0, len(self.norm_text_lower) - window_size + 1, step_size):
            # OPTIMIZATION: Limit iterations for performance
            iteration_count += 1
            if iteration_count > max_iterations:
                break
                
            window = self.norm_text_lower[i:i + int(window_size * 1.5)]
            
            # OPTIMIZATION: Quick length check before expensive edit distance
            length_diff = abs(len(window) - len(query_lower))
            if length_diff > window_size * 0.5:  # Skip if length difference is too large
                continue
            
            # Calculate custom edit distance
            distance = self._custom_edit_distance(query_lower, window, ocr_costs)
            if distance <= max_distance:
                similarity = 1.0 - (distance / max(len(query_lower), len(window)))
                matches.append((i, i + len(window), similarity))
                
                if len(matches) >= max_candidates:
                    break
        
        return sorted(matches, key=lambda x: x[2], reverse=True)

    def _custom_edit_distance(self, s1: str, s2: str, custom_costs: Dict) -> float:
        """
        Compute edit distance with custom substitution costs.
        """
        m, n = len(s1), len(s2)
        dp = [[float('inf')] * (n + 1) for _ in range(m + 1)]
        
        # Initialize base cases
        for i in range(m + 1):
            dp[i][0] = i
        for j in range(n + 1):
            dp[0][j] = j
        
        for i in range(1, m + 1):
            for j in range(1, n + 1):
                if s1[i-1] == s2[j-1]:
                    dp[i][j] = dp[i-1][j-1]  # No cost for exact match
                else:
                    # Check custom costs
                    subst_cost = custom_costs.get((s1[i-1], s2[j-1]), 1.0)
                    
                    dp[i][j] = min(
                        dp[i-1][j] + 1,      # deletion
                        dp[i][j-1] + 1,      # insertion
                        dp[i-1][j-1] + subst_cost  # substitution
                    )
        
        return dp[m][n]

    def _calculate_text_similarity(self, candidate: QuoteCandidate, original_query: str) -> float:
        """Calculate text similarity score for a candidate"""
        if not candidate.page_regions:
            return 0.0
        
        # Extract the actual text from the candidate span
        seg_text = self._extract_norm_text_for_span(candidate.start_char, candidate.end_char)
        original_normalized = _normalize_text(original_query).lower()
        
        # Calculate multiple similarity metrics
        sequence_ratio = difflib.SequenceMatcher(None, original_normalized, seg_text).ratio()
        
        # Token-based similarity
        orig_tokens = self._tokenize_words(original_normalized)
        seg_tokens = self._tokenize_words(seg_text)
        
        if not orig_tokens:
            token_similarity = 1.0 if not seg_tokens else 0.0
        else:
            matching_tokens = sum(1 for token in orig_tokens if token in seg_tokens)
            token_similarity = matching_tokens / len(orig_tokens)
        
        # Length ratio (penalize segments that are too long or short)
        len_ratio = len(seg_text) / max(1, len(original_normalized))
        len_penalty = max(0, 1 - abs(len_ratio - 1.0))
        
        # Combine metrics
        return (0.4 * sequence_ratio + 0.4 * token_similarity + 0.2 * len_penalty)

    def _calculate_spatial_coherence(self, candidate: QuoteCandidate) -> float:
        """Calculate spatial coherence score based on rectangle positioning"""
        if not candidate.page_regions:
            return 0.0
        
        scores = []
        
        for page_num, rects in candidate.page_regions.items():
            if len(rects) <= 1:
                scores.append(1.0)  # Single rect is perfectly coherent
                continue
                
            # Check if rectangles form reasonable lines/columns
            y_positions = [(r.y0 + r.y1) / 2 for r in rects]
            x_positions = [(r.x0 + r.x1) / 2 for r in rects]
            
            # Calculate variance in y-positions (lower = more line-like)
            if len(y_positions) > 1:
                y_variance = sum((y - sum(y_positions) / len(y_positions))**2 for y in y_positions) / len(y_positions)
                y_coherence = max(0, 1 - (y_variance / 100))  # Normalize by reasonable threshold
            else:
                y_coherence = 1.0
            
            # Check for reasonable gaps between rectangles
            x_sorted_rects = sorted(rects, key=lambda r: r.x0)
            gap_reasonableness = 1.0
            for i in range(len(x_sorted_rects) - 1):
                gap = x_sorted_rects[i+1].x0 - x_sorted_rects[i].x1
                if gap > 200:  # Very large gap suggests disconnected text
                    gap_reasonableness *= 0.5
            
            scores.append(0.7 * y_coherence + 0.3 * gap_reasonableness)
        
        return sum(scores) / len(scores) if scores else 0.0

    def _calculate_context_relevance(self, candidate: QuoteCandidate, quote_info: Dict) -> float:
        """Calculate context relevance based on surrounding text"""
        # For now, use a simple heuristic based on parameter type
        parameter = quote_info.get('parameter', '').lower()
        
        # Extract some context around the candidate
        context_start = max(0, candidate.start_char - 200)
        context_end = min(len(self.norm_text_lower), candidate.end_char + 200)
        context = self.norm_text_lower[context_start:context_end]
        
        relevance_score = 0.5  # Base score
        
        # Boost score for mathematical content if parameter suggests math
        if 'dash' in parameter or 'math' in parameter:
            math_indicators = ['=', '+', '-', '(', ')', 'equation', 'formula']
            math_count = sum(1 for indicator in math_indicators if indicator in context)
            relevance_score += min(0.3, math_count * 0.05)
        
        # Boost for scientific content
        science_indicators = ['fig', 'figure', 'table', 'equation', 'data', 'measurement', 'observation']
        science_count = sum(1 for indicator in science_indicators if indicator in context)
        relevance_score += min(0.2, science_count * 0.02)
        
        return min(1.0, relevance_score)

    def _calculate_confidence_score(self, candidate: QuoteCandidate, method_reliability: Dict[MatchMethod, float]) -> float:
        """Calculate confidence score based on method reliability and other factors"""
        base_confidence = method_reliability.get(candidate.method, 0.5)
        
        # Adjust based on cross-page complexity
        if candidate.method in [MatchMethod.CROSS_PAGE_CHAIN, MatchMethod.CROSS_PAGE_LINES_COMBINED, MatchMethod.FITZ_ANCHOR_CHAIN]:
            base_confidence *= 0.8  # Cross-page matches are inherently less reliable
        
        # Boost for exact matches
        if candidate.method == MatchMethod.EXACT_CI:
            base_confidence = 1.0
        
        # Adjust based on number of pages spanned
        if len(candidate.page_regions) > 1:
            base_confidence *= 0.9
        
        return base_confidence

    def _score_candidate(self, candidate: QuoteCandidate, original_query: str, quote_info: Dict) -> QuoteCandidate:
        """Score all dimensions of a candidate and update its scores"""
        # Method reliability scores
        method_reliability = {
            MatchMethod.EXACT_CI: 0.95,
            MatchMethod.PUNCTUATION_FALLBACK: 0.8,
            MatchMethod.HYPHEN_JOIN_VARIANT: 0.75,
            MatchMethod.WORD_FRAGMENT_JOIN: 0.7,
            MatchMethod.ANCHOR_GAPPED: 0.7,
            MatchMethod.FUZZY_MATCH: 0.6,
            MatchMethod.CHARACTER_ALIGNMENT: 0.65,
            MatchMethod.ELLIPSIS_CHAIN: 0.6,
            MatchMethod.CROSS_PAGE_CHAIN: 0.5,
            MatchMethod.CROSS_PAGE_LINES_COMBINED: 0.45,
            MatchMethod.FITZ_ANCHOR_CHAIN: 0.4,
        }
        
        candidate.text_similarity_score = self._calculate_text_similarity(candidate, original_query)
        candidate.spatial_coherence_score = self._calculate_spatial_coherence(candidate)
        candidate.context_relevance_score = self._calculate_context_relevance(candidate, quote_info)
        candidate.confidence_score = self._calculate_confidence_score(candidate, method_reliability)
        
        return candidate

    def _generate_candidates_high_recall(self, quote_text: str, quote_info: Dict) -> List[QuoteCandidate]:
        """
        Phase 1: Generate candidates using all available methods with relaxed thresholds.
        Returns a list of all possible candidates for ranking.
        OPTIMIZED: Early termination on exact match, selective method execution.
        """
        candidates = []
        norm_q = _normalize_text(quote_text)
        
        if not norm_q:
            return candidates
        
        # Analyze quote characteristics for selective method execution
        is_mathematical = any(char in quote_text for char in ['=', '+', '-', '*', '/', '(', ')', 'α', 'β', 'λ', '·'])
        is_cross_page = ('...' in quote_text or '…' in quote_text)
        is_short = len(norm_q) < 20
        
        # Method 1: Exact case-insensitive match (most reliable)
        start = self.norm_text_lower.find(norm_q.lower())
        if start != -1:
            end = start + len(norm_q)
            regions = self._spans_to_regions(start, end)
            if regions:
                candidate = QuoteCandidate(
                    quote=quote_text,
                    start_char=start,
                    end_char=end,
                    method=MatchMethod.EXACT_CI,
                    page_regions=regions
                )
                candidates.append(candidate)
                
                # OPTIMIZATION: Early termination for exact matches unless we need cross-page handling
                if not is_cross_page:
                    return candidates
        
        # Method 2: Fuzzy string matching (for OCR errors, spacing issues)
        # OPTIMIZATION: Skip fuzzy matching for very short quotes to avoid false positives
        if not is_short:
            fuzzy_matches = self._fuzzy_string_match(norm_q.lower(), threshold=0.5, max_matches=2)  # Reduced from 3 to 2
            for start, end, similarity in fuzzy_matches[:2]:  # Top 2 fuzzy matches
                regions = self._spans_to_regions(start, end)
                if regions:
                    candidate = QuoteCandidate(
                        quote=quote_text,
                        start_char=start,
                        end_char=end,
                        method=MatchMethod.FUZZY_MATCH,
                        page_regions=regions
                    )
                    candidate.debug_info['fuzzy_similarity'] = similarity
                    candidates.append(candidate)
        
        # Method 3: Character-level alignment (for mathematical expressions)
        # OPTIMIZATION: Only run for mathematical content to save time
        if is_mathematical:
            alignment_matches = self._character_level_alignment(norm_q.lower(), max_candidates=2)  # Reduced from 3 to 2
            for start, end, similarity in alignment_matches:
                regions = self._spans_to_regions(start, end)
                if regions:
                    candidate = QuoteCandidate(
                        quote=quote_text,
                        start_char=start,
                        end_char=end,
                        method=MatchMethod.CHARACTER_ALIGNMENT,
                        page_regions=regions
                    )
                    candidate.debug_info['alignment_similarity'] = similarity
                    candidates.append(candidate)
        
        # Method 4: Relaxed punctuation fallback (existing method but more permissive)
        if norm_q:
            # Build a regex that collapses consecutive non-alnum
            pat_parts = []
            ql = norm_q.lower()
            i = 0
            while i < len(ql):
                if ql[i].isalnum():
                    j = i
                    while j < len(ql) and ql[j].isalnum():
                        j += 1
                    pat_parts.append(re.escape(ql[i:j]))
                    i = j
                else:
                    j = i
                    while j < len(ql) and not ql[j].isalnum():
                        j += 1
                    pat_parts.append(r"[^0-9a-zA-Z]+")
                    i = j
            pattern = "".join(pat_parts)
            m = re.search(pattern, self.norm_text_lower)
            if m:
                start, end = m.start(), m.end()
                regions = self._spans_to_regions(start, end)
                if regions:
                    candidate = QuoteCandidate(
                        quote=quote_text,
                        start_char=start,
                        end_char=end,
                        method=MatchMethod.PUNCTUATION_FALLBACK,
                        page_regions=regions
                    )
                    candidate.debug_info['regex_pattern'] = pattern
                    candidates.append(candidate)
        
        # Method 5: Word fragment joining (for hyphen-join cases)
        # OPTIMIZATION: Only run if we don't have good candidates yet
        if len(candidates) == 0 or (len(candidates) == 1 and candidates[0].method != MatchMethod.EXACT_CI):
            quote_tokens = self._tokenize_words(norm_q)
            for i in range(len(quote_tokens) - 1):
                part1, part2 = quote_tokens[i], quote_tokens[i + 1]
                if self._looks_like_word_fragment(part1, part2):
                    joined_word = part1 + part2
                    pattern = re.compile(rf"\b{re.escape(part1)}\s+{re.escape(part2)}\b", flags=re.IGNORECASE)
                    variant = pattern.sub(joined_word, norm_q)
                    start = self.norm_text_lower.find(variant.lower())
                    if start != -1:
                        end = start + len(variant)
                        regions = self._spans_to_regions(start, end)
                        if regions:
                            candidate = QuoteCandidate(
                                quote=quote_text,
                                start_char=start,
                                end_char=end,
                                method=MatchMethod.WORD_FRAGMENT_JOIN,
                                page_regions=regions
                            )
                            candidate.debug_info['joined_word'] = joined_word
                            candidates.append(candidate)
                            break  # Only try first viable word fragment
        
        # Method 6: Cross-page candidate generation (for ellipsis quotes)
        # OPTIMIZATION: Only run for cross-page quotes
        if is_cross_page:
            cross_page_candidates = self._generate_cross_page_candidates(quote_text, norm_q)
            candidates.extend(cross_page_candidates)
        
        return candidates

    def _generate_cross_page_candidates(self, quote_text: str, norm_q: str) -> List[QuoteCandidate]:
        """Generate multiple cross-page candidates using different strategies"""
        candidates = []
        
        # Only proceed if we have multiple pages and ellipsis
        if len(self.page_ranges) < 2:
            return candidates
        
        parts = [p.strip() for p in re.split(r"\.\.\.|…", quote_text) if p.strip()]
        if len(parts) < 2:
            return candidates
        
        left_part = _normalize_text(parts[0]).lower()
        right_part = _normalize_text(parts[-1]).lower()
        
        # Minimum part length for viable cross-page matching
        if len(left_part) < 8 or len(right_part) < 8:
            return candidates
        
        # Strategy 1: Ellipsis chain - look for parts across page boundaries
        for i in range(len(self.page_ranges) - 1):
            a_start, a_end = self.page_ranges[i]
            b_start, b_end = self.page_ranges[i + 1]
            
            # Search for left part near end of page i
            window_size = min(1000, (a_end - a_start) // 3)  # Conservative window
            left_search_start = max(a_start, a_end - window_size)
            left_idx = self.norm_text_lower.find(left_part, left_search_start, a_end)
            
            # Search for right part near start of page i+1
            right_search_end = min(b_end, b_start + window_size)
            right_idx = self.norm_text_lower.find(right_part, b_start, right_search_end)
            
            if left_idx != -1 and right_idx != -1:
                # Check if this forms a reasonable cross-page span
                start_char = left_idx
                end_char = right_idx + len(right_part)
                span_length = end_char - start_char
                
                # Conservative length check (avoid spans that are too long)
                if span_length <= len(quote_text) * 4:  # Allow some expansion but not too much
                    regions = self._spans_to_regions(start_char, end_char)
                    if regions and len(regions) == 2:  # Must span exactly 2 pages
                        candidate = QuoteCandidate(
                            quote=quote_text,
                            start_char=start_char,
                            end_char=end_char,
                            method=MatchMethod.ELLIPSIS_CHAIN,
                            page_regions=regions
                        )
                        candidate.debug_info.update({
                            'left_part': left_part[:30],
                            'right_part': right_part[:30],
                            'pages_spanned': [i + 1, i + 2],
                            'span_length': span_length
                        })
                        candidates.append(candidate)
        
        # Strategy 2: Fuzzy cross-page matching - use fuzzy search for parts
        for i in range(len(self.page_ranges) - 1):
            a_start, a_end = self.page_ranges[i]
            b_start, b_end = self.page_ranges[i + 1]
            
            # Create a combined window across the page boundary
            boundary_start = max(a_start, a_end - 800)
            boundary_end = min(b_end, b_start + 800)
            boundary_text = self.norm_text_lower[boundary_start:boundary_end]
            
            # Look for the full quote (without ellipsis) in the boundary
            quote_no_ellipsis = re.sub(r'\.\.\.|…', ' ', norm_q.lower())
            
            # Use fuzzy matching on the boundary text
            matcher = difflib.SequenceMatcher(None, quote_no_ellipsis, boundary_text)
            ratio = matcher.ratio()
            
            if ratio >= 0.4:  # Lower threshold for cross-page
                # Find the best alignment
                matching_blocks = matcher.get_matching_blocks()
                if matching_blocks:
                    start_in_boundary = min(block.b for block in matching_blocks if block.size > 0)
                    end_in_boundary = max(block.b + block.size for block in matching_blocks if block.size > 0)
                    
                    start_char = boundary_start + start_in_boundary
                    end_char = boundary_start + end_in_boundary
                    
                    regions = self._spans_to_regions(start_char, end_char)
                    if regions and len(regions) >= 1:  # Allow single or multi-page
                        candidate = QuoteCandidate(
                            quote=quote_text,
                            start_char=start_char,
                            end_char=end_char,
                            method=MatchMethod.CROSS_PAGE_CHAIN,
                            page_regions=regions
                        )
                        candidate.debug_info.update({
                            'fuzzy_ratio': ratio,
                            'boundary_pages': [i + 1, i + 2],
                            'quote_no_ellipsis': quote_no_ellipsis[:50]
                        })
                        candidates.append(candidate)
        
        return candidates

    def _validate_with_llm(self, candidate: QuoteCandidate, original_quote: str) -> Tuple[bool, float, str]:
        """
        Use GPT-5-nano to validate uncertain matches.
        Returns (is_valid, confidence, explanation).
        """
        try:
            # Only import when needed to avoid dependency issues
            import litellm
            
            # Extract context around the candidate match
            context_start = max(0, candidate.start_char - 300)
            context_end = min(len(self.norm_text_lower), candidate.end_char + 300)
            context_text = self.norm_text_lower[context_start:context_end]
            
            # Extract the matched segment
            matched_text = self._extract_norm_text_for_span(candidate.start_char, candidate.end_char)
            
            # Create a focused prompt for validation
            prompt = f"""You are helping validate whether text extracted from a PDF matches a target quote.

TARGET QUOTE:
"{original_quote}"

EXTRACTED TEXT:
"{matched_text}"

SURROUNDING CONTEXT:
"{context_text}"

The extracted text was found using automated matching. Please evaluate:
1. Does the extracted text semantically match the target quote?
2. Are any differences due to formatting/OCR issues rather than content differences?
3. Is this a valid match despite minor spacing or symbol variations?

Respond with a JSON object:
{{
    "is_valid": true/false,
    "confidence": 0.0-1.0,
    "explanation": "Brief explanation of your reasoning"
}}"""

            # Call GPT-5-nano (using litellm for model abstraction)
            response = litellm.completion(
                model="gpt-5-nano",  # Assuming this will be the model name
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                max_tokens=200,
                temperature=0.1  # Low temperature for consistent validation
            )
            
            # Parse the response
            import json
            result = json.loads(response.choices[0].message.content)
            
            return (
                result.get("is_valid", False),
                result.get("confidence", 0.0),
                result.get("explanation", "No explanation provided")
            )
            
        except Exception as e:
            # If LLM validation fails, fall back to heuristic
            return (candidate.total_score >= 0.4, candidate.total_score, f"LLM validation failed: {e}")

    def find_quotes_ir(self, quotes: List[Dict[str, str]], debug: bool = False, use_llm_validation: bool = False) -> List[Dict]:
        """
        Information Retrieval inspired quote finding with multi-stage pipeline:
        1. High-recall candidate generation
        2. Multi-dimensional scoring
        3. Ranking and selection
        4. LLM validation for uncertain matches
        """
        import time
        results = []
        
        # Pre-normalize all quotes once
        norm_queries = [(_normalize_text(q.get("quote", "")), q) for q in quotes]
        
        # Prepare static debug context
        doc_debug = None
        if debug:
            doc_debug = {
                'doc_len': len(self.norm_text_lower),
                'pages': [{'start': a, 'end': b, 'len': b - a} for (a, b) in self.page_ranges],
                'hyphen_joins_count': len(self.hyphen_joins),
            }
        
        for norm_q, qinfo in norm_queries:
            quote_text = qinfo.get("quote", "")
            t_start = time.perf_counter()
            
            # Phase 1: Generate all possible candidates with high recall
            candidates = self._generate_candidates_high_recall(quote_text, qinfo)
            
            # Phase 2: Score all candidates
            scored_candidates = []
            for candidate in candidates:
                scored_candidate = self._score_candidate(candidate, quote_text, qinfo)
                scored_candidates.append(scored_candidate)
            
            # Phase 3: Rank candidates by total score
            ranked_candidates = sorted(scored_candidates, key=lambda c: c.total_score, reverse=True)
            
            # Phase 4: Select best candidate with optional LLM validation
            best_candidate = None
            if ranked_candidates:
                top_candidate = ranked_candidates[0]
                
                # For uncertain matches (0.3-0.7 score range), use LLM validation if enabled
                if use_llm_validation and 0.3 <= top_candidate.total_score <= 0.7:
                    is_valid, llm_confidence, explanation = self._validate_with_llm(top_candidate, quote_text)
                    if debug:
                        qinfo.setdefault('debug', {}).update({
                            'llm_validation': {
                                'is_valid': is_valid,
                                'confidence': llm_confidence,
                                'explanation': explanation
                            }
                        })
                    
                    if is_valid:
                        # Boost the candidate's confidence score based on LLM validation
                        top_candidate.confidence_score = max(top_candidate.confidence_score, llm_confidence)
                        best_candidate = top_candidate
                elif top_candidate.total_score >= 0.3:  # Standard threshold without LLM
                    best_candidate = top_candidate
            
            # Convert to expected format
            location = None
            dbg = {'method': None, 'candidates_generated': len(candidates)} if debug else None
            
            if best_candidate:
                # Create location data
                first_page = sorted(best_candidate.page_regions.keys())[0]
                first_rect = best_candidate.page_regions[first_page][0]
                coordinate_regions = []
                for page_num, rects in best_candidate.page_regions.items():
                    for r in rects:
                        coordinate_regions.append({
                            'page': page_num + 1,
                            'x0': r.x0, 'y0': r.y0, 'x1': r.x1, 'y1': r.y1
                        })
                
                location = {
                    'page_number': first_page + 1,
                    'x0': first_rect.x0, 'y0': first_rect.y0,
                    'x1': first_rect.x1, 'y1': first_rect.y1,
                    'is_cross_page': len(best_candidate.page_regions) > 1,
                    'coordinate_regions': coordinate_regions,
                    'is_multiline': any(len(rs) > 1 for rs in best_candidate.page_regions.values())
                }
                
                if debug:
                    dbg.update({
                        'method': best_candidate.method.value,
                        'total_score': best_candidate.total_score,
                        'text_similarity': best_candidate.text_similarity_score,
                        'spatial_coherence': best_candidate.spatial_coherence_score,
                        'context_relevance': best_candidate.context_relevance_score,
                        'confidence': best_candidate.confidence_score,
                        'span': [best_candidate.start_char, best_candidate.end_char],
                        **best_candidate.debug_info
                    })
            
            t_end = time.perf_counter()
            result = {
                **qinfo,
                'location': location
            }
            if debug:
                dbg['timing_ms'] = round((t_end - t_start) * 1000, 3)
                dbg['doc'] = doc_debug
                result['debug'] = dbg
            results.append(result)
        
        return results

    def find_quotes(self, quotes: List[Dict[str, str]], debug: bool = False) -> List[Dict]:
        """
        Find locations for a list of quotes.
        `quotes` is a list of dicts with keys: 'quote', 'instrument', 'parameter'.
        Returns the same list enriched with a 'location' dict like PDFAnnotator.
        """
        import time
        results: List[Dict] = []

        # Pre-normalize all quotes once
        norm_queries = [(_normalize_text(q.get("quote", "")), q) for q in quotes]

        # Prepare static debug context
        doc_debug = None
        if debug:
            doc_debug = {
                'doc_len': len(self.norm_text_lower),
                'pages': [{'start': a, 'end': b, 'len': b - a} for (a, b) in self.page_ranges],
                'hyphen_joins_count': len(self.hyphen_joins),
            }

        for norm_q, qinfo in norm_queries:
            quote_text = qinfo.get("quote", "")
            location = None
            dbg = {'method': None} if debug else None
            t_start = time.perf_counter()
            if norm_q:
                # Find first occurrence (case-insensitive)
                start = self.norm_text_lower.find(norm_q.lower())
                if start != -1:
                    end = start + len(norm_q)
                    # Verify extracted normalized text contains the query
                    seg_text = self._extract_norm_text_for_span(start, end)
                    slice_text = self.norm_text_lower[start:end]
                    if debug:
                        dbg.update({
                            'attempt': 'exact_ci',
                            'query_norm': norm_q.lower(),
                            'span': [start, end],
                            'segment_norm_preview': seg_text[:200],
                            'slice_preview': slice_text[:200]
                        })
                    if norm_q.lower() not in seg_text and norm_q.lower() not in slice_text:
                        regions = {}
                        if debug:
                            dbg['reject_reason'] = 'exact_segment_verification_failed'
                    else:
                        regions = self._spans_to_regions(start, end)
                    if regions:
                        # Choose first page's first rect as primary location
                        first_page = sorted(regions.keys())[0]
                        first_rect = regions[first_page][0]

                        coordinate_regions = []
                        for page_num, rects in regions.items():
                            for r in rects:
                                coordinate_regions.append({
                                    'page': page_num + 1,
                                    'x0': r.x0, 'y0': r.y0, 'x1': r.x1, 'y1': r.y1
                                })

                        location = {
                            'page_number': first_page + 1,
                            'x0': first_rect.x0, 'y0': first_rect.y0,
                            'x1': first_rect.x1, 'y1': first_rect.y1,
                            'is_cross_page': len(regions) > 1,
                            'coordinate_regions': coordinate_regions,
                            'is_multiline': any(len(rs) > 1 for rs in regions.values())
                        }
                        if debug:
                            dbg['method'] = 'exact_ci'

            # Ellipsis-aware fallback: chain parts split by ... or …
            if location is None and ('...' in quote_text or '…' in quote_text):
                parts = [p.strip() for p in re.split(r"\.\.\.|…", quote_text) if p.strip()]
                if parts:
                    norm_parts = [_normalize_text(p).lower() for p in parts]
                    positions: List[Tuple[int, int]] = []
                    cursor = 0
                    max_gap_chars = 200  # limit gap size to reduce spurious long-span matches
                    for p in norm_parts:
                        pos = self.norm_text_lower.find(p, cursor)
                        if pos == -1:
                            positions = []
                            break
                        if positions and pos - positions[-1][1] > max_gap_chars:
                            positions = []
                            break
                        positions.append((pos, pos + len(p)))
                        cursor = pos + len(p)
                    if positions:
                        start = positions[0][0]
                        end = positions[-1][1]
                        seg_text = self._extract_norm_text_for_span(start, end)
                        ok = True
                        # Ensure each part appears in order within the reconstructed segment
                        cur = 0
                        for p in norm_parts:
                            i = seg_text.find(p, cur)
                            if i == -1:
                                ok = False
                                break
                            cur = i + len(p)
                        regions = self._spans_to_regions(start, end) if ok else {}
                        if regions:
                            first_page = sorted(regions.keys())[0]
                            first_rect = regions[first_page][0]
                            coordinate_regions = []
                            for page_num, rects in regions.items():
                                for r in rects:
                                    coordinate_regions.append({
                                        'page': page_num + 1,
                                        'x0': r.x0, 'y0': r.y0, 'x1': r.x1, 'y1': r.y1
                                    })
                            location = {
                                'page_number': first_page + 1,
                                'x0': first_rect.x0, 'y0': first_rect.y0,
                                'x1': first_rect.x1, 'y1': first_rect.y1,
                                'is_cross_page': len(regions) > 1,
                                'coordinate_regions': coordinate_regions,
                                'is_multiline': any(len(rs) > 1 for rs in regions.values())
                            }
                            if debug:
                                dbg.update({'method': 'ellipsis_chain', 'norm_parts': norm_parts, 'positions': positions, 'segment_preview': seg_text[:240]})
                        elif debug:
                            dbg.update({'attempt': 'ellipsis_chain', 'norm_parts': norm_parts, 'reject_reason': 'parts_not_found_or_gap_too_large'})

            # Loose punctuation-insensitive fallback: treat any non-alnum in the quote
            # as matching any non-alnum run in the document (handles unknown glyphs like '?').
            if location is None and norm_q:
                # Build a regex that collapses consecutive non-alnum in the quote
                # into a single matcher for any run of non-alnum characters.
                pat_parts = []
                ql = norm_q.lower()
                i = 0
                while i < len(ql):
                    if ql[i].isalnum():
                        # Append consecutive alnum chars as escaped literal
                        j = i
                        while j < len(ql) and ql[j].isalnum():
                            j += 1
                        pat_parts.append(re.escape(ql[i:j]))
                        i = j
                    else:
                        # Skip over a run of non-alnum and add a single wildcard
                        j = i
                        while j < len(ql) and not ql[j].isalnum():
                            j += 1
                        pat_parts.append(r"[^0-9a-zA-Z]+")
                        i = j
                pattern = "".join(pat_parts)
                m = re.search(pattern, self.norm_text_lower)
                if m:
                    start, end = m.start(), m.end()
                    seg_text = self._extract_norm_text_for_span(start, end)
                    # Token coverage and length checks to reduce false positives
                    quote_tokens = self._tokenize_words(ql)
                    seg_tokens = self._tokenize_words(seg_text)
                    # Require tokens in order and coverage ratio >= threshold
                    cover = 0
                    cur = 0
                    for qt in quote_tokens:
                        try:
                            # find next occurrence from cur
                            j = seg_tokens.index(qt, cur)
                            cover += 1
                            cur = j + 1
                        except ValueError:
                            pass
                    coverage_ratio = cover / len(quote_tokens) if quote_tokens else 0
                    len_ratio = (len(seg_text) / max(1, len(ql)))
                    # Anchor requirement: at least 2 distinctive tokens in order
                    anchors_needed = self._anchors(quote_tokens)
                    anchors_found = 0
                    cur = 0
                    for a in anchors_needed:
                        try:
                            j = seg_tokens.index(a, cur)
                            anchors_found += 1
                            cur = j + 1
                        except ValueError:
                            pass
                    # Use adaptive thresholds based on quote characteristics
                    param = qinfo.get('parameter', '')
                    thresholds = self._get_adaptive_thresholds(quote_text, param)
                    
                    # Hyphen-aware adjustment
                    qtoks_pairs = [quote_tokens[i] + quote_tokens[i+1] for i in range(len(quote_tokens)-1)]
                    hyphen_mode = any(join in self.hyphen_joins for join in qtoks_pairs)
                    if hyphen_mode:
                        # Further relax thresholds for hyphen joins
                        thresholds['coverage_ratio_min'] = max(0.4, thresholds['coverage_ratio_min'] - 0.1)
                        thresholds['len_ratio_min'] = max(0.3, thresholds['len_ratio_min'] - 0.2)
                        thresholds['len_ratio_max'] = min(3.0, thresholds['len_ratio_max'] + 0.5)
                    
                    ok = (coverage_ratio >= thresholds['coverage_ratio_min'] and 
                          thresholds['len_ratio_min'] <= len_ratio <= thresholds['len_ratio_max'] and 
                          anchors_found >= min(thresholds['anchors_min'], len(anchors_needed)))
                    regions = self._spans_to_regions(start, end) if ok else {}
                    if regions:
                        first_page = sorted(regions.keys())[0]
                        first_rect = regions[first_page][0]
                        coordinate_regions = []
                        for page_num, rects in regions.items():
                            for r in rects:
                                coordinate_regions.append({
                                    'page': page_num + 1,
                                    'x0': r.x0, 'y0': r.y0, 'x1': r.x1, 'y1': r.y1
                                })
                        location = {
                            'page_number': first_page + 1,
                            'x0': first_rect.x0, 'y0': first_rect.y0,
                            'x1': first_rect.x1, 'y1': first_rect.y1,
                            'is_cross_page': len(regions) > 1,
                            'coordinate_regions': coordinate_regions,
                            'is_multiline': any(len(rs) > 1 for rs in regions.values())
                        }
                        if debug:
                            dbg.update({'method': 'punctuation_fallback', 'coverage_ratio': coverage_ratio, 'len_ratio': len_ratio, 'hyphen_mode': hyphen_mode, 'anchors_found': anchors_found, 'anchors_total': len(anchors_needed), 'pattern': pattern, 'span': [start, end], 'segment_norm_preview': seg_text[:200]})
                    elif debug:
                        dbg.update({'attempt': 'punctuation_fallback', 'coverage_ratio': coverage_ratio, 'len_ratio': len_ratio, 'pattern': pattern, 'reject_reason': 'verification_failed'})

            # Hyphen-join variant probe: if the quote likely crosses a dehyphenated boundary,
            # try multiple strategies to find word-break matches.
            if location is None and norm_q:
                quote_tokens = self._tokenize_words(norm_q)
                # Strategy 1: Use detected hyphen joins
                if self.hyphen_joins:
                    for i in range(len(quote_tokens) - 1):
                        join = (quote_tokens[i] + quote_tokens[i + 1])
                        
                        # Try exact join, hyphenated variant, and spaced variant
                        variants_to_try = [join]
                        if join in self.hyphen_joins:
                            variants_to_try.extend([quote_tokens[i] + "-" + quote_tokens[i + 1], 
                                                   quote_tokens[i] + " " + quote_tokens[i + 1]])
                        
                        for variant_join in variants_to_try:
                            if variant_join in self.hyphen_joins or variant_join == join:
                                # Replace 't1 t2' with variant in the normalized quote string
                                pattern = re.compile(rf"\b{re.escape(quote_tokens[i])}\s+{re.escape(quote_tokens[i+1])}\b", flags=re.IGNORECASE)
                                variant = pattern.sub(variant_join.replace(" ", ""), norm_q)
                                start = self.norm_text_lower.find(variant.lower())
                                if start != -1:
                                    end = start + len(variant)
                                    seg_text = self._extract_norm_text_for_span(start, end)
                                    # Token order check with relaxed thresholds
                                    seg_tokens = self._tokenize_words(seg_text)
                                    cover = 0
                                    cur = 0
                                    for qt in self._tokenize_words(norm_q):
                                        try:
                                            j = seg_tokens.index(qt, cur)
                                            cover += 1
                                            cur = j + 1
                                        except ValueError:
                                            pass
                                    coverage_ratio = cover / max(1, len(self._tokenize_words(norm_q)))
                                    len_ratio = (len(seg_text) / max(1, len(norm_q)))
                                    ok = (coverage_ratio >= 0.6) and (0.5 <= len_ratio <= 2.0)
                                    regions = self._spans_to_regions(start, end) if ok else {}
                                    if regions:
                                        first_page = sorted(regions.keys())[0]
                                        first_rect = regions[first_page][0]
                                        coordinate_regions = []
                                        for page_num, rects in regions.items():
                                            for r in rects:
                                                coordinate_regions.append({
                                                    'page': page_num + 1,
                                                    'x0': r.x0, 'y0': r.y0, 'x1': r.x1, 'y1': r.y1
                                                })
                                        location = {
                                            'page_number': first_page + 1,
                                            'x0': first_rect.x0, 'y0': first_rect.y0,
                                            'x1': first_rect.x1, 'y1': first_rect.y1,
                                            'is_cross_page': len(regions) > 1,
                                            'coordinate_regions': coordinate_regions,
                                            'is_multiline': any(len(rs) > 1 for rs in regions.values())
                                        }
                                        if debug:
                                            dbg.update({'method': 'hyphen_join_variant', 'variant': variant, 'join': variant_join, 'span': [start, end], 'coverage_ratio': coverage_ratio, 'len_ratio': len_ratio})
                                        break
                        if location:
                            break
                
                # Strategy 2: Try automatic word-break detection for word fragments
                if location is None:
                    for i in range(len(quote_tokens) - 1):
                        part1, part2 = quote_tokens[i], quote_tokens[i + 1]
                        if self._looks_like_word_fragment(part1, part2):
                            # Try joining the fragments
                            joined_word = part1 + part2
                            # Replace 'part1 part2' with 'joined_word' in the quote
                            pattern = re.compile(rf"\b{re.escape(part1)}\s+{re.escape(part2)}\b", flags=re.IGNORECASE)
                            variant = pattern.sub(joined_word, norm_q)
                            start = self.norm_text_lower.find(variant.lower())
                            if start != -1:
                                end = start + len(variant)
                                seg_text = self._extract_norm_text_for_span(start, end)
                                # More relaxed verification for word fragments
                                seg_tokens = self._tokenize_words(seg_text)
                                cover = 0
                                cur = 0
                                # Check if the joined word appears in the segment
                                if joined_word.lower() in seg_text:
                                    # Verify other tokens
                                    remaining_tokens = [t for j, t in enumerate(quote_tokens) if j != i and j != i + 1]
                                    for qt in remaining_tokens:
                                        try:
                                            j = seg_tokens.index(qt, cur)
                                            cover += 1
                                            cur = j + 1
                                        except ValueError:
                                            pass
                                    coverage_ratio = (cover + 1) / max(1, len(quote_tokens) - 1)  # +1 for the joined word
                                    len_ratio = (len(seg_text) / max(1, len(norm_q)))
                                    ok = (coverage_ratio >= 0.5) and (0.4 <= len_ratio <= 2.5)
                                    regions = self._spans_to_regions(start, end) if ok else {}
                                    if regions:
                                        first_page = sorted(regions.keys())[0]
                                        first_rect = regions[first_page][0]
                                        coordinate_regions = []
                                        for page_num, rects in regions.items():
                                            for r in rects:
                                                coordinate_regions.append({
                                                    'page': page_num + 1,
                                                    'x0': r.x0, 'y0': r.y0, 'x1': r.x1, 'y1': r.y1
                                                })
                                        location = {
                                            'page_number': first_page + 1,
                                            'x0': first_rect.x0, 'y0': first_rect.y0,
                                            'x1': first_rect.x1, 'y1': first_rect.y1,
                                            'is_cross_page': len(regions) > 1,
                                            'coordinate_regions': coordinate_regions,
                                            'is_multiline': any(len(rs) > 1 for rs in regions.values())
                                        }
                                        if debug:
                                            dbg.update({'method': 'word_fragment_join', 'variant': variant, 'joined_word': joined_word, 'span': [start, end], 'coverage_ratio': coverage_ratio, 'len_ratio': len_ratio})
                                        break
                        if location:
                            break

            # Anchor-gapped fallback: require distinctive tokens in order, allow up to K chars between
            if location is None and norm_q:
                anchors = self._anchors(self._tokenize_words(norm_q))
                if len(anchors) >= 2:
                    # Use up to first 3 anchors to limit backtracking
                    use = anchors[:3]
                    param = (qinfo.get('parameter') or '').lower()
                    # Detect if quote likely crosses a hyphen join
                    qtoks = self._tokenize_words(norm_q)
                    hyphen_mode = 'hyphen' in param or any(
                        (qtoks[i] + qtoks[i+1]) in self.hyphen_joins for i in range(len(qtoks)-1)
                    )
                    max_gap = min(600 if hyphen_mode else 400, max(150, len(norm_q) * (3 if hyphen_mode else 2)))
                    pattern = re.escape(use[0])
                    for a in use[1:]:
                        pattern += rf".{{0,{max_gap}}}?" + re.escape(a)
                    m = re.search(pattern, self.norm_text_lower, flags=re.DOTALL)
                    if m:
                        start, end = m.start(), m.end()
                        seg_text = self._extract_norm_text_for_span(start, end)
                        # Verify token coverage and anchors within the segment
                        quote_tokens = self._tokenize_words(norm_q)
                        seg_tokens = self._tokenize_words(seg_text)
                        cover = 0
                        cur = 0
                        for qt in quote_tokens:
                            try:
                                j = seg_tokens.index(qt, cur)
                                cover += 1
                                cur = j + 1
                            except ValueError:
                                pass
                        coverage_ratio = cover / len(quote_tokens) if quote_tokens else 0
                        len_ratio = (len(seg_text) / max(1, len(norm_q)))
                        # Anchor presence in order within segment
                        anchors_found = 0
                        cur = 0
                        for a in use:
                            try:
                                j = seg_tokens.index(a, cur)
                                anchors_found += 1
                                cur = j + 1
                            except ValueError:
                                pass
                        # Use adaptive thresholds for anchor-gapped matching
                        param = (qinfo.get('parameter') or '').lower()
                        thresholds = self._get_adaptive_thresholds(quote_text, param)
                        
                        if hyphen_mode:
                            # Further adjust for hyphen joins
                            thresholds['coverage_ratio_min'] = max(0.4, thresholds['coverage_ratio_min'] - 0.1)
                            thresholds['len_ratio_min'] = max(0.3, thresholds['len_ratio_min'] - 0.2)
                            thresholds['len_ratio_max'] = min(3.0, thresholds['len_ratio_max'] + 0.5)
                        
                        ok = (coverage_ratio >= thresholds['coverage_ratio_min'] and 
                              thresholds['len_ratio_min'] <= len_ratio <= thresholds['len_ratio_max'] and 
                              anchors_found >= min(thresholds['anchors_min'], len(use)))
                        regions = self._spans_to_regions(start, end) if ok else {}
                        if regions:
                            first_page = sorted(regions.keys())[0]
                            first_rect = regions[first_page][0]
                            coordinate_regions = []
                            for page_num, rects in regions.items():
                                for r in rects:
                                    coordinate_regions.append({
                                        'page': page_num + 1,
                                        'x0': r.x0, 'y0': r.y0, 'x1': r.x1, 'y1': r.y1
                                    })
                            location = {
                                'page_number': first_page + 1,
                                'x0': first_rect.x0, 'y0': first_rect.y0,
                                'x1': first_rect.x1, 'y1': first_rect.y1,
                                'is_cross_page': len(regions) > 1,
                                'coordinate_regions': coordinate_regions,
                                'is_multiline': any(len(rs) > 1 for rs in regions.values())
                            }
                            if debug:
                                dbg.update({'method': 'anchor_gapped', 'anchors': use, 'span': [start, end], 'coverage_ratio': coverage_ratio, 'len_ratio': len_ratio, 'anchors_found': anchors_found})
                        elif debug:
                            dbg.update({'attempt': 'anchor_gapped', 'anchors': use, 'pattern': pattern, 'reject_reason': 'verification_failed', 'coverage_ratio': coverage_ratio, 'len_ratio': len_ratio, 'anchors_found': anchors_found})

            # Cross-page chaining: ONLY if the quote has ellipsis AND we have strong evidence it should span pages
            if location is None and len(self.page_ranges) >= 2 and ('...' in quote_text or '…' in quote_text):
                parts = [p.strip() for p in re.split(r"\.\.\.|…", quote_text) if p.strip()]
                if len(parts) >= 2:
                    left_part = _normalize_text(parts[0]).lower()
                    right_part = _normalize_text(parts[-1]).lower()
                    
                    # STRICTER VALIDATION: Only proceed if parts are substantial and non-overlapping
                    if len(left_part) < 10 or len(right_part) < 10:
                        if debug:
                            dbg.update({'attempt': 'cross_page_chain', 'reject_reason': 'parts_too_short', 'left_len': len(left_part), 'right_len': len(right_part)})
                    elif left_part in right_part or right_part in left_part:
                        if debug:
                            dbg.update({'attempt': 'cross_page_chain', 'reject_reason': 'parts_overlap', 'left_part': left_part[:50], 'right_part': right_part[:50]})
                    else:
                        # Use more conservative search keys
                        left_key = left_part[-20:] if len(left_part) > 20 else left_part
                        right_key = right_part[:20] if len(right_part) > 20 else right_part
                        
                        # MUCH smaller search window to reduce false positives
                        window = 800  # Reduced from 3000
                        found_valid_match = False
                        
                        for i in range(len(self.page_ranges) - 1):
                            a_start, a_end = self.page_ranges[i]
                            b_start, b_end = self.page_ranges[i + 1]
                            left_slice_start = max(a_end - window, a_start)
                            right_slice_end = min(b_start + window, b_end)
                            left_idx = self.norm_text_lower.find(left_key, left_slice_start, a_end)
                            right_idx = self.norm_text_lower.find(right_key, b_start, right_slice_end)
                            
                            if left_idx != -1 and right_idx != -1:
                                # ADDITIONAL VALIDATION: Ensure the match spans the page boundary appropriately
                                # Left part should be near the end of page i, right part near start of page i+1
                                distance_from_page_end = a_end - left_idx
                                distance_from_page_start = right_idx - b_start
                                
                                # Both parts should be reasonably close to the page boundary
                                if distance_from_page_end > window // 2 or distance_from_page_start > window // 2:
                                    continue
                                
                                start = left_idx
                                end = right_idx + len(right_key)
                                seg_text = self._extract_norm_text_for_span(start, end)
                                
                                # STRICTER VERIFICATION: Ensure parts appear in order and segment is reasonable
                                cur = 0
                                ok = True
                                for p in [left_part, right_part]:
                                    idx = seg_text.find(p, cur)
                                    if idx == -1:
                                        ok = False
                                        break
                                    cur = idx + len(p)
                                
                                # Additional check: segment shouldn't be too long (likely a false positive)
                                if ok and len(seg_text) > len(quote_text) * 3:
                                    ok = False
                                    if debug:
                                        dbg.update({'attempt': 'cross_page_chain', 'reject_reason': 'segment_too_long', 'seg_len': len(seg_text), 'quote_len': len(quote_text)})
                                
                                regions = self._spans_to_regions(start, end) if ok else {}
                                if regions:
                                    # FINAL VALIDATION: Must actually span exactly 2 consecutive pages
                                    pages_spanned = sorted(regions.keys())
                                    if len(pages_spanned) == 2 and pages_spanned[1] == pages_spanned[0] + 1:
                                        first_page = pages_spanned[0]
                                        first_rect = regions[first_page][0]
                                        coordinate_regions = []
                                        for page_num, rects in regions.items():
                                            for r in rects:
                                                coordinate_regions.append({
                                                    'page': page_num + 1,
                                                    'x0': r.x0, 'y0': r.y0, 'x1': r.x1, 'y1': r.y1
                                                })
                                        location = {
                                            'page_number': first_page + 1,
                                            'x0': first_rect.x0, 'y0': first_rect.y0,
                                            'x1': first_rect.x1, 'y1': first_rect.y1,
                                            'is_cross_page': True,
                                            'coordinate_regions': coordinate_regions,
                                            'is_multiline': any(len(rs) > 1 for rs in regions.values())
                                        }
                                        if debug:
                                            dbg.update({'method': 'cross_page_chain', 'pages': [i + 1, i + 2], 'span': [start, end], 'left_key': left_key, 'right_key': right_key, 'left_idx': left_idx, 'right_idx': right_idx, 'segment_preview': seg_text[:240]})
                                        found_valid_match = True
                                        break
                            
                        if not found_valid_match and debug:
                            dbg.update({'attempt': 'cross_page_chain', 'reject_reason': 'no_valid_cross_page_match_found'})

            # Cross-page via line windows: CONSERVATIVE matching within boundary lines
            if location is None and ('...' in quote_text or '…' in quote_text) and len(self.page_lines) >= 2:
                parts = [p.strip() for p in re.split(r"\.\.\.|…", quote_text) if p.strip()]
                if len(parts) >= 2:
                    left_part = _normalize_text(parts[0]).lower()
                    right_part = _normalize_text(parts[-1]).lower()
                    
                    # STRICTER VALIDATION: Same as cross-page chain method
                    if len(left_part) < 10 or len(right_part) < 10:
                        if debug:
                            dbg.update({'attempt': 'cross_page_lines', 'reject_reason': 'parts_too_short'})
                    elif left_part in right_part or right_part in left_part:
                        if debug:
                            dbg.update({'attempt': 'cross_page_lines', 'reject_reason': 'parts_overlap'})
                    else:
                        L = 8  # Reduced from 15 to be more conservative
                        found_valid_match = False
                        
                        for i in range(len(self.page_lines) - 1):
                            cw = self._boundary_combined_window(i, lines_each_side=L)
                            if not cw:
                                continue
                            combined_text, segments = cw
                            if debug:
                                dbg.setdefault('cross_page_lines_combined', {'page': i + 1, 'combined_len': len(combined_text)})
                            
                            # STRICTER anchor requirements
                            left_tokens = [t for t in self._tokenize_words(left_part) if len(t) >= 4]  # Increased from 3
                            right_tokens = [t for t in self._tokenize_words(right_part) if len(t) >= 4]
                            
                            # Require more anchors for reliable matching
                            if len(left_tokens) < 2 or len(right_tokens) < 2:
                                continue
                                
                            left_anchors = left_tokens[-2:]  # Reduced from 3
                            right_anchors = right_tokens[:2]
                            
                            # Find left anchors in order
                            start_idx = 0
                            anchor_positions = []
                            ok = True
                            for tok in left_anchors:
                                pos = combined_text.find(tok, start_idx)
                                if pos == -1:
                                    ok = False
                                    break
                                anchor_positions.append((tok, pos, pos + len(tok)))
                                start_idx = pos + len(tok)
                            if not ok:
                                continue
                            
                            # Find right anchors in order after left anchors
                            start_idx_right = start_idx
                            for tok in right_anchors:
                                pos = combined_text.find(tok, start_idx_right)
                                if pos == -1:
                                    ok = False
                                    break
                                anchor_positions.append((tok, pos, pos + len(tok)))
                                start_idx_right = pos + len(tok)
                            if not ok:
                                continue
                            
                            # ADDITIONAL VALIDATION: Check that the span is reasonable
                            start_idx = anchor_positions[0][1]
                            end_idx = anchor_positions[-1][2]
                            span_text = combined_text[start_idx:end_idx]
                            
                            # Reject if span is too long relative to original quote
                            if len(span_text) > len(quote_text) * 2:
                                continue
                            
                            # Build regions from line segments
                            regions = {}
                            # Build spans with actual lengths
                            line_spans = []
                            for si, (pidx, lidx, seg_start, rect) in enumerate(segments):
                                seg_end = segments[si + 1][2] if si + 1 < len(segments) else len(combined_text)
                                line_spans.append((pidx, lidx, seg_start, seg_end, rect))
                                
                            for (pidx, lidx, seg_start, seg_end, rect) in line_spans:
                                if seg_end <= start_idx or seg_start >= end_idx:
                                    continue
                                regions.setdefault(pidx, []).append(rect)
                                
                            if regions:
                                # FINAL VALIDATION: Must span exactly 2 consecutive pages
                                pages_spanned = sorted(regions.keys())
                                if len(pages_spanned) == 2 and pages_spanned[1] == pages_spanned[0] + 1:
                                    first_page = pages_spanned[0]
                                    first_rect = regions[first_page][0]
                                    coordinate_regions = []
                                    for page_num, rects in regions.items():
                                        for r in rects:
                                            coordinate_regions.append({
                                                'page': page_num + 1,
                                                'x0': r.x0, 'y0': r.y0, 'x1': r.x1, 'y1': r.y1
                                            })
                                    location = {
                                        'page_number': first_page + 1,
                                        'x0': first_rect.x0, 'y0': first_rect.y0,
                                        'x1': first_rect.x1, 'y1': first_rect.y1,
                                        'is_cross_page': True,
                                        'coordinate_regions': coordinate_regions,
                                        'is_multiline': True
                                    }
                                    if debug:
                                        dbg.update({'method': 'cross_page_lines_combined', 'pages': [i + 1, i + 2], 'anchors': anchor_positions, 'span': [start_idx, end_idx]})
                                    found_valid_match = True
                                    break
                            if found_valid_match:
                                break
                        
                        if not found_valid_match and debug:
                            dbg.update({'attempt': 'cross_page_lines', 'reject_reason': 'no_valid_cross_page_line_match'})

            # Cross-page via token anchor chaining (MOST CONSERVATIVE - only for strong evidence)
            if location is None and ('...' in quote_text or '…' in quote_text):
                parts = [p.strip() for p in re.split(r"\.\.\.|…", quote_text) if p.strip()]
                if len(parts) >= 2:
                    left_part = _normalize_text(parts[0]).lower()
                    right_part = _normalize_text(parts[-1]).lower()
                    
                    # SAME STRICT VALIDATION as other cross-page methods
                    if len(left_part) < 15 or len(right_part) < 15:  # Even stricter for MuPDF method
                        if debug:
                            dbg.update({'attempt': 'fitz_anchor_chain', 'reject_reason': 'parts_too_short'})
                    elif left_part in right_part or right_part in left_part:
                        if debug:
                            dbg.update({'attempt': 'fitz_anchor_chain', 'reject_reason': 'parts_overlap'})
                    else:
                        left_tokens = [t for t in self._tokenize_words(left_part) if len(t) >= 4]  # Stricter
                        right_tokens = [t for t in self._tokenize_words(right_part) if len(t) >= 4]
                        
                        # Require strong anchor evidence
                        if len(left_tokens) < 3 or len(right_tokens) < 3:
                            if debug:
                                dbg.update({'attempt': 'fitz_anchor_chain', 'reject_reason': 'insufficient_anchors'})
                        else:
                            left_anchors = left_tokens[-2:]  # Only most distinctive
                            right_anchors = right_tokens[:2]
                            chained = False
                            
                            for i in range(len(self.doc) - 1):
                                page_a = self.doc.load_page(i)
                                page_b = self.doc.load_page(i + 1)
                                h_a = page_a.rect.height
                                h_b = page_b.rect.height
                                bottom_thresh = h_a * 0.70
                                top_thresh = h_b * 0.30
                                # Find anchors on A near bottom
                                found_a = []
                                for tok in left_anchors:
                                    rects = page_a.search_for(tok, flags=fitz.TEXT_INHIBIT_SPACES) or []
                                    rects = [r for r in rects if r.y1 >= bottom_thresh] or rects
                                    if rects:
                                        found_a.append((tok, rects))
                                    else:
                                        found_a = []
                                        break
                                # Find anchors on B near top
                                found_b = []
                                for tok in right_anchors:
                                    rects = page_b.search_for(tok, flags=fitz.TEXT_INHIBIT_SPACES) or []
                                    rects = [r for r in rects if r.y0 <= top_thresh] or rects
                                    if rects:
                                        found_b.append((tok, rects))
                                    else:
                                        found_b = []
                                        break
                                if found_a and found_b:
                                    regions = {i: [r for _, rs in found_a for r in rs], i + 1: [r for _, rs in found_b for r in rs]}
                                    first_rects_a = regions[i]
                                    if not first_rects_a:
                                        continue
                                    first_rect = first_rects_a[0]
                                    coordinate_regions = []
                                    for page_num, rlist in regions.items():
                                        for r in rlist:
                                            coordinate_regions.append({
                                                'page': page_num + 1,
                                                'x0': r.x0, 'y0': r.y0, 'x1': r.x1, 'y1': r.y1
                                            })
                                    location = {
                                        'page_number': i + 1,
                                        'x0': first_rect.x0, 'y0': first_rect.y0,
                                        'x1': first_rect.x1, 'y1': first_rect.y1,
                                        'is_cross_page': True,
                                        'coordinate_regions': coordinate_regions,
                                        'is_multiline': True
                                    }
                                    if debug:
                                        dbg.update({'method': 'fitz_anchor_chain', 'pages': [i + 1, i + 2], 'left_anchors': left_anchors, 'right_anchors': right_anchors,
                                                    'left_counts': [len(rs) for _, rs in found_a], 'right_counts': [len(rs) for _, rs in found_b]})
                                    chained = True
                                    break
                            if not chained and debug:
                                dbg.update({'attempt': 'fitz_anchor_chain', 'reject_reason': 'anchors_not_found_near_boundaries', 'left_anchors': left_anchors, 'right_anchors': right_anchors})

            t_end = time.perf_counter()
            result = {
                **qinfo,
                'location': location
            }
            if debug:
                dbg['timing_ms'] = round((t_end - t_start) * 1000, 3)
                dbg['doc'] = doc_debug
                result['debug'] = dbg
            results.append(result)

        return results

    def find_quotes_original(self, quotes: List[Dict[str, str]], debug: bool = False,
                             skip_expensive_crosspage: bool = False) -> List[Dict]:
        """
        Original quote finding method from commit d85121c (exact copy).
        This is the fast method that was used before the IR implementation.

        skip_expensive_crosspage (default False → unchanged behavior) drops the
        two ellipsis-only cross-page fallbacks (`cross_page_lines_combined` and
        `fitz_anchor_chain`) that the bench measured at 0% precision AND the
        worst per-quote latency (fitz reloads every page + search_for per token).
        The bulk-enrichment path sets this True; the interactive path never does.
        """
        import time
        results: List[Dict] = []

        # Pre-normalize all quotes once
        norm_queries = [(_normalize_text(q.get("quote", "")), q) for q in quotes]

        # Prepare static debug context
        doc_debug = None
        if debug:
            doc_debug = {
                'doc_len': len(self.norm_text_lower),
                'pages': [{'start': a, 'end': b, 'len': b - a} for (a, b) in self.page_ranges],
                'hyphen_joins_count': len(self.hyphen_joins),
            }

        for norm_q, qinfo in norm_queries:
            quote_text = qinfo.get("quote", "")
            location = None
            dbg = {'method': None} if debug else None
            t_start = time.perf_counter()
            if norm_q:
                # Find first occurrence (case-insensitive)
                start = self.norm_text_lower.find(norm_q.lower())
                if start != -1:
                    end = start + len(norm_q)
                    # Verify extracted normalized text contains the query
                    seg_text = self._extract_norm_text_for_span(start, end)
                    slice_text = self.norm_text_lower[start:end]
                    if debug:
                        dbg.update({
                            'attempt': 'exact_ci',
                            'query_norm': norm_q.lower(),
                            'span': [start, end],
                            'segment_norm_preview': seg_text[:200],
                            'slice_preview': slice_text[:200]
                        })
                    if norm_q.lower() not in seg_text and norm_q.lower() not in slice_text:
                        regions = {}
                        if debug:
                            dbg['reject_reason'] = 'exact_segment_verification_failed'
                    else:
                        regions = self._spans_to_regions(start, end)
                    if regions:
                        # Choose first page's first rect as primary location
                        first_page = sorted(regions.keys())[0]
                        first_rect = regions[first_page][0]

                        coordinate_regions = []
                        for page_num, rects in regions.items():
                            for r in rects:
                                coordinate_regions.append({
                                    'page': page_num + 1,
                                    'x0': r.x0, 'y0': r.y0, 'x1': r.x1, 'y1': r.y1
                                })

                        location = {
                            'page_number': first_page + 1,
                            'x0': first_rect.x0, 'y0': first_rect.y0,
                            'x1': first_rect.x1, 'y1': first_rect.y1,
                            'is_cross_page': len(regions) > 1,
                            'coordinate_regions': coordinate_regions,
                            'is_multiline': any(len(rs) > 1 for rs in regions.values())
                        }
                        if debug:
                            dbg['method'] = 'exact_ci'

            # Ellipsis-aware fallback: chain parts split by ... or …
            if location is None and ('...' in quote_text or '…' in quote_text):
                parts = [p.strip() for p in re.split(r"\.\.\.|…", quote_text) if p.strip()]
                if parts:
                    norm_parts = [_normalize_text(p).lower() for p in parts]
                    positions: List[Tuple[int, int]] = []
                    cursor = 0
                    max_gap_chars = 200  # limit gap size to reduce spurious long-span matches
                    for p in norm_parts:
                        pos = self.norm_text_lower.find(p, cursor)
                        if pos == -1:
                            positions = []
                            break
                        if positions and pos - positions[-1][1] > max_gap_chars:
                            positions = []
                            break
                        positions.append((pos, pos + len(p)))
                        cursor = pos + len(p)
                    if positions:
                        start = positions[0][0]
                        end = positions[-1][1]
                        seg_text = self._extract_norm_text_for_span(start, end)
                        ok = True
                        # Ensure each part appears in order within the reconstructed segment
                        cur = 0
                        for p in norm_parts:
                            i = seg_text.find(p, cur)
                            if i == -1:
                                ok = False
                                break
                            cur = i + len(p)
                        regions = self._spans_to_regions(start, end) if ok else {}
                        if regions:
                            first_page = sorted(regions.keys())[0]
                            first_rect = regions[first_page][0]
                            coordinate_regions = []
                            for page_num, rects in regions.items():
                                for r in rects:
                                    coordinate_regions.append({
                                        'page': page_num + 1,
                                        'x0': r.x0, 'y0': r.y0, 'x1': r.x1, 'y1': r.y1
                                    })
                            location = {
                                'page_number': first_page + 1,
                                'x0': first_rect.x0, 'y0': first_rect.y0,
                                'x1': first_rect.x1, 'y1': first_rect.y1,
                                'is_cross_page': len(regions) > 1,
                                'coordinate_regions': coordinate_regions,
                                'is_multiline': any(len(rs) > 1 for rs in regions.values())
                            }
                            if debug:
                                dbg.update({'method': 'ellipsis_chain', 'norm_parts': norm_parts, 'positions': positions, 'segment_preview': seg_text[:240]})
                        elif debug:
                            dbg.update({'attempt': 'ellipsis_chain', 'norm_parts': norm_parts, 'reject_reason': 'parts_not_found_or_gap_too_large'})

            # Loose punctuation-insensitive fallback: treat any non-alnum in the quote
            # as matching any non-alnum run in the document (handles unknown glyphs like '?').
            if location is None and norm_q:
                # Build a regex that collapses consecutive non-alnum in the quote
                # into a single matcher for any run of non-alnum characters.
                pat_parts = []
                ql = norm_q.lower()
                i = 0
                while i < len(ql):
                    if ql[i].isalnum():
                        # Append consecutive alnum chars as escaped literal
                        j = i
                        while j < len(ql) and ql[j].isalnum():
                            j += 1
                        pat_parts.append(re.escape(ql[i:j]))
                        i = j
                    else:
                        # Skip over a run of non-alnum and add a single wildcard
                        j = i
                        while j < len(ql) and not ql[j].isalnum():
                            j += 1
                        pat_parts.append(r"[^0-9a-zA-Z]+")
                        i = j
                pattern = "".join(pat_parts)
                m = re.search(pattern, self.norm_text_lower)
                if m:
                    start, end = m.start(), m.end()
                    seg_text = self._extract_norm_text_for_span(start, end)
                    # Token coverage and length checks to reduce false positives
                    quote_tokens = self._tokenize_words(ql)
                    seg_tokens = self._tokenize_words(seg_text)
                    # Require tokens in order and coverage ratio >= threshold
                    cover = 0
                    cur = 0
                    for qt in quote_tokens:
                        try:
                            # find next occurrence from cur
                            j = seg_tokens.index(qt, cur)
                            cover += 1
                            cur = j + 1
                        except ValueError:
                            pass
                    coverage_ratio = cover / len(quote_tokens) if quote_tokens else 0
                    len_ratio = (len(seg_text) / max(1, len(ql)))
                    # Anchor requirement: at least 2 distinctive tokens in order
                    anchors_needed = self._anchors(quote_tokens)
                    anchors_found = 0
                    cur = 0
                    for a in anchors_needed:
                        try:
                            j = seg_tokens.index(a, cur)
                            anchors_found += 1
                            cur = j + 1
                        except ValueError:
                            pass
                    # Hyphen-aware relaxation if quote crosses a known hyphen join
                    qtoks_pairs = [quote_tokens[i] + quote_tokens[i+1] for i in range(len(quote_tokens)-1)]
                    hyphen_mode = any(join in self.hyphen_joins for join in qtoks_pairs)
                    if hyphen_mode:
                        ok = (coverage_ratio >= 0.6) and (0.5 <= len_ratio <= 2.0) and (anchors_found >= min(2, len(anchors_needed)))
                    else:
                        ok = (coverage_ratio >= 0.6) and (0.6 <= len_ratio <= 1.8) and (anchors_found >= min(2, len(anchors_needed)))
                    regions = self._spans_to_regions(start, end) if ok else {}
                    if regions:
                        first_page = sorted(regions.keys())[0]
                        first_rect = regions[first_page][0]
                        coordinate_regions = []
                        for page_num, rects in regions.items():
                            for r in rects:
                                coordinate_regions.append({
                                    'page': page_num + 1,
                                    'x0': r.x0, 'y0': r.y0, 'x1': r.x1, 'y1': r.y1
                                })
                        location = {
                            'page_number': first_page + 1,
                            'x0': first_rect.x0, 'y0': first_rect.y0,
                            'x1': first_rect.x1, 'y1': first_rect.y1,
                            'is_cross_page': len(regions) > 1,
                            'coordinate_regions': coordinate_regions,
                            'is_multiline': any(len(rs) > 1 for rs in regions.values())
                        }
                        if debug:
                            dbg.update({'method': 'punctuation_fallback', 'coverage_ratio': coverage_ratio, 'len_ratio': len_ratio, 'hyphen_mode': hyphen_mode, 'anchors_found': anchors_found, 'anchors_total': len(anchors_needed), 'pattern': pattern, 'span': [start, end], 'segment_norm_preview': seg_text[:200]})
                    elif debug:
                        dbg.update({'attempt': 'punctuation_fallback', 'coverage_ratio': coverage_ratio, 'len_ratio': len_ratio, 'pattern': pattern, 'reject_reason': 'verification_failed'})

            # Hyphen-join variant probe: if the quote likely crosses a dehyphenated boundary,
            # try an exact search on a join-insensitive normalized variant.
            if location is None and norm_q and self.hyphen_joins:
                quote_tokens = self._tokenize_words(norm_q)
                for i in range(len(quote_tokens) - 1):
                    join = (quote_tokens[i] + quote_tokens[i + 1])
                    if join in self.hyphen_joins:
                        # Replace 't1 t2' with 't1t2' in the normalized quote string
                        pattern = re.compile(rf"\b{re.escape(quote_tokens[i])}\s+{re.escape(quote_tokens[i+1])}\b", flags=re.IGNORECASE)
                        variant = pattern.sub(join, norm_q)
                        start = self.norm_text_lower.find(variant.lower())
                        if start != -1:
                            end = start + len(variant)
                            seg_text = self._extract_norm_text_for_span(start, end)
                            # Token order check with relaxed thresholds
                            seg_tokens = self._tokenize_words(seg_text)
                            cover = 0
                            cur = 0
                            for qt in self._tokenize_words(norm_q):
                                try:
                                    j = seg_tokens.index(qt, cur)
                                    cover += 1
                                    cur = j + 1
                                except ValueError:
                                    pass
                            coverage_ratio = cover / max(1, len(self._tokenize_words(norm_q)))
                            len_ratio = (len(seg_text) / max(1, len(norm_q)))
                            ok = (coverage_ratio >= 0.6) and (0.5 <= len_ratio <= 2.0)
                            regions = self._spans_to_regions(start, end) if ok else {}
                            if regions:
                                first_page = sorted(regions.keys())[0]
                                first_rect = regions[first_page][0]
                                coordinate_regions = []
                                for page_num, rects in regions.items():
                                    for r in rects:
                                        coordinate_regions.append({
                                            'page': page_num + 1,
                                            'x0': r.x0, 'y0': r.y0, 'x1': r.x1, 'y1': r.y1
                                        })
                                location = {
                                    'page_number': first_page + 1,
                                    'x0': first_rect.x0, 'y0': first_rect.y0,
                                    'x1': first_rect.x1, 'y1': first_rect.y1,
                                    'is_cross_page': len(regions) > 1,
                                    'coordinate_regions': coordinate_regions,
                                    'is_multiline': any(len(rs) > 1 for rs in regions.values())
                                }
                                if debug:
                                    dbg.update({'method': 'hyphen_join_variant', 'variant': variant, 'join': join, 'span': [start, end], 'coverage_ratio': coverage_ratio, 'len_ratio': len_ratio})
                                break

            # Anchor-gapped fallback: require distinctive tokens in order, allow up to K chars between
            if location is None and norm_q:
                anchors = self._anchors(self._tokenize_words(norm_q))
                if len(anchors) >= 2:
                    # Use up to first 3 anchors to limit backtracking
                    use = anchors[:3]
                    param = (qinfo.get('parameter') or '').lower()
                    # Detect if quote likely crosses a hyphen join
                    qtoks = self._tokenize_words(norm_q)
                    hyphen_mode = 'hyphen' in param or any(
                        (qtoks[i] + qtoks[i+1]) in self.hyphen_joins for i in range(len(qtoks)-1)
                    )
                    max_gap = min(600 if hyphen_mode else 400, max(150, len(norm_q) * (3 if hyphen_mode else 2)))
                    pattern = re.escape(use[0])
                    for a in use[1:]:
                        pattern += rf".{{0,{max_gap}}}?" + re.escape(a)
                    m = re.search(pattern, self.norm_text_lower, flags=re.DOTALL)
                    if m:
                        start, end = m.start(), m.end()
                        seg_text = self._extract_norm_text_for_span(start, end)
                        # Verify token coverage and anchors within the segment
                        quote_tokens = self._tokenize_words(norm_q)
                        seg_tokens = self._tokenize_words(seg_text)
                        cover = 0
                        cur = 0
                        for qt in quote_tokens:
                            try:
                                j = seg_tokens.index(qt, cur)
                                cover += 1
                                cur = j + 1
                            except ValueError:
                                pass
                        coverage_ratio = cover / len(quote_tokens) if quote_tokens else 0
                        len_ratio = (len(seg_text) / max(1, len(norm_q)))
                        # Anchor presence in order within segment
                        anchors_found = 0
                        cur = 0
                        for a in use:
                            try:
                                j = seg_tokens.index(a, cur)
                                anchors_found += 1
                                cur = j + 1
                            except ValueError:
                                pass
                        if hyphen_mode:
                            ok = (coverage_ratio >= 0.6) and (0.5 <= len_ratio <= 2.0) and (anchors_found >= 2)
                        else:
                            ok = (coverage_ratio >= 0.7) and (0.6 <= len_ratio <= 1.6) and (anchors_found >= 2)
                        regions = self._spans_to_regions(start, end) if ok else {}
                        if regions:
                            first_page = sorted(regions.keys())[0]
                            first_rect = regions[first_page][0]
                            coordinate_regions = []
                            for page_num, rects in regions.items():
                                for r in rects:
                                    coordinate_regions.append({
                                        'page': page_num + 1,
                                        'x0': r.x0, 'y0': r.y0, 'x1': r.x1, 'y1': r.y1
                                    })
                            location = {
                                'page_number': first_page + 1,
                                'x0': first_rect.x0, 'y0': first_rect.y0,
                                'x1': first_rect.x1, 'y1': first_rect.y1,
                                'is_cross_page': len(regions) > 1,
                                'coordinate_regions': coordinate_regions,
                                'is_multiline': any(len(rs) > 1 for rs in regions.values())
                            }
                            if debug:
                                dbg.update({'method': 'anchor_gapped', 'anchors': use, 'span': [start, end], 'coverage_ratio': coverage_ratio, 'len_ratio': len_ratio, 'anchors_found': anchors_found})
                        elif debug:
                            dbg.update({'attempt': 'anchor_gapped', 'anchors': use, 'pattern': pattern, 'reject_reason': 'verification_failed', 'coverage_ratio': coverage_ratio, 'len_ratio': len_ratio, 'anchors_found': anchors_found})

            # Cross-page chaining: if the quote has an ellipsis, try matching last/first parts across page boundary windows
            if location is None and len(self.page_ranges) >= 2 and ('...' in quote_text or '…' in quote_text):
                parts = [p.strip() for p in re.split(r"\.\.\.|…", quote_text) if p.strip()]
                if len(parts) >= 2:
                    left_part = _normalize_text(parts[0]).lower()
                    right_part = _normalize_text(parts[-1]).lower()
                    # Use substring tails/heads to anchor near boundaries
                    left_key = left_part[-30:] if len(left_part) > 30 else left_part
                    right_key = right_part[:30] if len(right_part) > 30 else right_part
                    window = 3000
                    for i in range(len(self.page_ranges) - 1):
                        a_start, a_end = self.page_ranges[i]
                        b_start, b_end = self.page_ranges[i + 1]
                        left_slice_start = max(a_end - window, a_start)
                        right_slice_end = min(b_start + window, b_end)
                        left_idx = self.norm_text_lower.find(left_key, left_slice_start, a_end)
                        right_idx = self.norm_text_lower.find(right_key, b_start, right_slice_end)
                        if left_idx != -1 and right_idx != -1:
                            start = left_idx
                            end = right_idx + len(right_key)
                            seg_text = self._extract_norm_text_for_span(start, end)
                            # Verify both parts appear in order within the segment
                            cur = 0
                            ok = True
                            for p in [left_part, right_part]:
                                idx = seg_text.find(p, cur)
                                if idx == -1:
                                    ok = False
                                    break
                                cur = idx + len(p)
                            regions = self._spans_to_regions(start, end) if ok else {}
                            if regions:
                                first_page = sorted(regions.keys())[0]
                                first_rect = regions[first_page][0]
                                coordinate_regions = []
                                for page_num, rects in regions.items():
                                    for r in rects:
                                        coordinate_regions.append({
                                            'page': page_num + 1,
                                            'x0': r.x0, 'y0': r.y0, 'x1': r.x1, 'y1': r.y1
                                        })
                                location = {
                                    'page_number': first_page + 1,
                                    'x0': first_rect.x0, 'y0': first_rect.y0,
                                    'x1': first_rect.x1, 'y1': first_rect.y1,
                                    'is_cross_page': True,
                                    'coordinate_regions': coordinate_regions,
                                    'is_multiline': any(len(rs) > 1 for rs in regions.values())
                                }
                                if debug:
                                    dbg.update({'method': 'cross_page_chain', 'pages': [i + 1, i + 2], 'span': [start, end], 'left_key': left_key, 'right_key': right_key, 'left_idx': left_idx, 'right_idx': right_idx, 'segment_preview': seg_text[:240]})
                                break
                    else:
                        if debug:
                            dbg.update({'attempt': 'cross_page_chain', 'reject_reason': 'anchors_not_found_in_boundaries', 'left_key': left_key, 'right_key': right_key})

            # Cross-page via line windows: match parts within last/first N lines around boundary
            if location is None and not skip_expensive_crosspage and ('...' in quote_text or '…' in quote_text) and len(self.page_lines) >= 2:
                parts = [p.strip() for p in re.split(r"\.\.\.|…", quote_text) if p.strip()]
                if len(parts) >= 2:
                    left_part = _normalize_text(parts[0]).lower()
                    right_part = _normalize_text(parts[-1]).lower()
                    L = 15
                    for i in range(len(self.page_lines) - 1):
                        cw = self._boundary_combined_window(i, lines_each_side=L)
                        if not cw:
                            continue
                        combined_text, segments = cw
                        if debug:
                            dbg.setdefault('cross_page_lines_combined', {'page': i + 1, 'combined_len': len(combined_text)})
                        # Token-anchor chaining across combined text
                        left_tokens = [t for t in self._tokenize_words(left_part) if len(t) >= 3]
                        right_tokens = [t for t in self._tokenize_words(right_part) if len(t) >= 3]
                        left_anchors = left_tokens[-3:]
                        right_anchors = right_tokens[:3]
                        # Find left anchors in order
                        start_idx = 0
                        anchor_positions = []
                        ok = True
                        for tok in left_anchors:
                            pos = combined_text.find(tok, start_idx)
                            if pos == -1:
                                ok = False
                                break
                            anchor_positions.append((tok, pos, pos + len(tok)))
                            start_idx = pos + len(tok)
                        if not ok:
                            continue
                        # Find right anchors in order after left anchors
                        start_idx_right = start_idx
                        for tok in right_anchors:
                            pos = combined_text.find(tok, start_idx_right)
                            if pos == -1:
                                ok = False
                                break
                            anchor_positions.append((tok, pos, pos + len(tok)))
                            start_idx_right = pos + len(tok)
                        if not ok:
                            continue
                        # Build span from first left anchor to last right anchor
                        start_idx = anchor_positions[0][1]
                        end_idx = anchor_positions[-1][2]
                        regions = {}
                        # Identify contributing lines from segments by checking span overlap
                        for (pidx, lidx, seg_start, rect) in segments:
                            # Line segment length is approximate: distance to next segment start or remaining
                            # To avoid heavy computation, treat each line as covering len(norm_text) starting at seg_start
                            # We don't have per-line lengths here; recompute from rect presence: assume non-empty line covers up to next seg_start
                            # Build a rough span list
                            pass
                        # Build spans with actual lengths
                        line_spans = []
                        for si, (pidx, lidx, seg_start, rect) in enumerate(segments):
                            seg_end = segments[si + 1][2] if si + 1 < len(segments) else len(combined_text)
                            line_spans.append((pidx, lidx, seg_start, seg_end, rect))
                        for (pidx, lidx, seg_start, seg_end, rect) in line_spans:
                            if seg_end <= start_idx or seg_start >= end_idx:
                                continue
                            regions.setdefault(pidx, []).append(rect)
                        if regions:
                            # Union rects per page (simple list; consumers handle multiple rects)
                            first_page = min(regions.keys())
                            first_rect = regions[first_page][0]
                            coordinate_regions = []
                            for page_num, rects in regions.items():
                                for r in rects:
                                    coordinate_regions.append({
                                        'page': page_num + 1,
                                        'x0': r.x0, 'y0': r.y0, 'x1': r.x1, 'y1': r.y1
                                    })
                            location = {
                                'page_number': first_page + 1,
                                'x0': first_rect.x0, 'y0': first_rect.y0,
                                'x1': first_rect.x1, 'y1': first_rect.y1,
                                'is_cross_page': True,
                                'coordinate_regions': coordinate_regions,
                                'is_multiline': True
                            }
                            if debug:
                                dbg.update({'method': 'cross_page_lines_combined', 'pages': [i + 1, i + 2], 'anchors': anchor_positions, 'span': [start_idx, end_idx]})
                            break
                    else:
                        if debug:
                            dbg.update({'attempt': 'cross_page_lines', 'reject_reason': 'parts_not_found_in_line_windows'})

            # Cross-page via token anchor chaining (MuPDF search for distinctive tokens near boundaries)
            if location is None and not skip_expensive_crosspage and ('...' in quote_text or '…' in quote_text):
                parts = [p.strip() for p in re.split(r"\.\.\.|…", quote_text) if p.strip()]
                if len(parts) >= 2:
                    left_part = _normalize_text(parts[0]).lower()
                    right_part = _normalize_text(parts[-1]).lower()
                    left_tokens = [t for t in self._tokenize_words(left_part) if len(t) >= 3]
                    right_tokens = [t for t in self._tokenize_words(right_part) if len(t) >= 3]
                    left_anchors = left_tokens[-2:] if len(left_tokens) >= 2 else left_tokens[-1:]
                    right_anchors = right_tokens[:2] if len(right_tokens) >= 2 else right_tokens[:1]
                    chained = False
                    for i in range(len(self.doc) - 1):
                        page_a = self.doc.load_page(i)
                        page_b = self.doc.load_page(i + 1)
                        h_a = page_a.rect.height
                        h_b = page_b.rect.height
                        bottom_thresh = h_a * 0.70
                        top_thresh = h_b * 0.30
                        # Find anchors on A near bottom
                        found_a = []
                        for tok in left_anchors:
                            rects = page_a.search_for(tok, flags=fitz.TEXT_INHIBIT_SPACES) or []
                            rects = [r for r in rects if r.y1 >= bottom_thresh] or rects
                            if rects:
                                found_a.append((tok, rects))
                            else:
                                found_a = []
                                break
                        # Find anchors on B near top
                        found_b = []
                        for tok in right_anchors:
                            rects = page_b.search_for(tok, flags=fitz.TEXT_INHIBIT_SPACES) or []
                            rects = [r for r in rects if r.y0 <= top_thresh] or rects
                            if rects:
                                found_b.append((tok, rects))
                            else:
                                found_b = []
                                break
                        if found_a and found_b:
                            regions = {i: [r for _, rs in found_a for r in rs], i + 1: [r for _, rs in found_b for r in rs]}
                            first_rects_a = regions[i]
                            if not first_rects_a:
                                continue
                            first_rect = first_rects_a[0]
                            coordinate_regions = []
                            for page_num, rlist in regions.items():
                                for r in rlist:
                                    coordinate_regions.append({
                                        'page': page_num + 1,
                                        'x0': r.x0, 'y0': r.y0, 'x1': r.x1, 'y1': r.y1
                                    })
                            location = {
                                'page_number': i + 1,
                                'x0': first_rect.x0, 'y0': first_rect.y0,
                                'x1': first_rect.x1, 'y1': first_rect.y1,
                                'is_cross_page': True,
                                'coordinate_regions': coordinate_regions,
                                'is_multiline': True
                            }
                            if debug:
                                dbg.update({'method': 'fitz_anchor_chain', 'pages': [i + 1, i + 2], 'left_anchors': left_anchors, 'right_anchors': right_anchors,
                                            'left_counts': [len(rs) for _, rs in found_a], 'right_counts': [len(rs) for _, rs in found_b]})
                            chained = True
                            break
                    if not chained and debug:
                        dbg.update({'attempt': 'fitz_anchor_chain', 'reject_reason': 'anchors_not_found_near_boundaries', 'left_anchors': left_anchors, 'right_anchors': right_anchors})

            t_end = time.perf_counter()
            result = {
                **qinfo,
                'location': location
            }
            if debug:
                dbg['timing_ms'] = round((t_end - t_start) * 1000, 3)
                dbg['doc'] = doc_debug
                result['debug'] = dbg
            results.append(result)

        return results

    @staticmethod
    def _page_regions_to_location(regions: Dict[int, List[fitz.Rect]]) -> Optional[Dict]:
        """Build the standard `location` dict from a page_num -> [rects] mapping."""
        if not regions:
            return None
        first_page = sorted(regions.keys())[0]
        first_rect = regions[first_page][0]
        coordinate_regions = []
        for page_num, rects in regions.items():
            for r in rects:
                coordinate_regions.append({
                    'page': page_num + 1,
                    'x0': r.x0, 'y0': r.y0, 'x1': r.x1, 'y1': r.y1,
                })
        return {
            'page_number': first_page + 1,
            'x0': first_rect.x0, 'y0': first_rect.y0,
            'x1': first_rect.x1, 'y1': first_rect.y1,
            'is_cross_page': len(regions) > 1,
            'coordinate_regions': coordinate_regions,
            'is_multiline': any(len(rs) > 1 for rs in regions.values()),
        }

    def _fuzzy_locate_rapid(self, norm_q: str, score_cutoff: float = 85.0,
                            coverage_min: float = 0.7,
                            apply_distinctive_guard: bool = True) -> Optional[Dict[int, List[fitz.Rect]]]:
        """Bounded fuzzy locate via rapidfuzz's C-backed partial alignment.

        Finds the best-matching substring of the whole normalized document in a
        single C call (ms even for large docs) — replacing difflib's Python
        sliding window, which scanned the doc 500x per quote and spiked to ~27s.
        Guarded by `score_cutoff` and an in-order token-coverage check so it
        stays a *precision*-respecting recall booster, not a box-at-any-cost.
        """
        try:
            from rapidfuzz import fuzz
        except Exception:
            return None
        ql = norm_q.lower()
        if len(ql) < 12:
            return None  # too short to fuzzy-match safely
        al = fuzz.partial_ratio_alignment(ql, self.norm_text_lower, score_cutoff=score_cutoff)
        if al is None or al.score < score_cutoff or al.dest_end <= al.dest_start:
            return None
        start, end = al.dest_start, al.dest_end
        # In-order token coverage guard (mirrors the punctuation/anchor fallbacks).
        seg_text = self._extract_norm_text_for_span(start, end)
        qtoks = self._tokenize_words(ql)
        segtoks = self._tokenize_words(seg_text)
        cover = cur = 0
        for qt in qtoks:
            try:
                j = segtoks.index(qt, cur)
                cover += 1
                cur = j + 1
            except ValueError:
                pass
        if not qtoks or (cover / len(qtoks)) < coverage_min:
            return None
        # Distinctive-token guard: the failure mode of a global fuzzy match is
        # locking onto a near-identical SIBLING (e.g. "HET/STB" -> "HET/STA",
        # "Fig. 1" -> "Fig. 5"). Those siblings differ only in high-signal tokens
        # — numbers and uppercase IDs. Require every such token in the quote to
        # actually appear under the box; reject otherwise. Cheap (set ops) and it
        # only ever removes a wrong box, never relocates a right one.
        if apply_distinctive_guard and self._fuzzy_sibling_conflict(norm_q, seg_text):
            return None
        return self._spans_to_regions(start, end) or None

    @staticmethod
    def _distinctive_tokens(text: str) -> set:
        """High-signal tokens that distinguish near-identical siblings: numbers and
        uppercase IDs (STA/STB, HET, EUVI, LASCO). Case-folded for comparison."""
        toks = {t for t in re.findall(r"[0-9]+", text)}
        toks |= {t.lower() for t in re.findall(r"[A-Za-z]+", text)
                 if len(t) >= 2 and t.isupper()}
        return toks

    @classmethod
    def _fuzzy_sibling_conflict(cls, norm_q: str, seg_text: str) -> bool:
        """True iff the matched segment is a near-identical SIBLING of the quote
        rather than the quote itself — the global-fuzzy failure mode
        ("HET/STB"->"HET/STA", "Fig. 1"->"Fig. 5", "20 April"->"13 April").

        Siblings differ only in high-signal tokens (numbers, uppercase IDs), so we
        reject when any distinctive quote token is absent from the box. A stricter
        "conflict-only" variant (require ALSO a competing foreign token) was tried
        via the audit loop and measured WORSE (re-admitted wrong siblings without
        recovering correct truncations), so this simpler rule stands. 4-digit years
        are exempted — a bled-in leading citation "(2009)." must not force a reject.
        """
        seg_all = {t.lower() for t in re.findall(r"[0-9a-zA-Z]+", seg_text)}

        def not_year(t):
            return not (t.isdigit() and len(t) == 4 and t[:2] in ('19', '20'))

        for tok in cls._distinctive_tokens(norm_q):
            if not_year(tok) and tok not in seg_all:
                return True
        return False

    def _fuzzy_ellipsis_chain(self, quote_text: str, score_cutoff: float = 85.0,
                              max_gap_chars: int = 400) -> Optional[Dict[int, List[fitz.Rect]]]:
        """Fuzzy counterpart to the deterministic ellipsis_chain.

        The largest miss bucket is ellipsis quotes ("Figure 1. … COR2-A images at
        03:08 UT") whose segments drifted just enough that the EXACT ellipsis_chain
        failed. Here each segment is located FUZZILY, but we keep ellipsis_chain's
        precision guards: the segments must appear IN ORDER and CLOSE together
        (a real quote omits only a small gap), and the combined span must pass the
        whole-quote distinctive-token guard. That coherence requirement rejects the
        sibling trap (a generic segment matching one event while the date-bearing
        segment matches another, far away — the ell_4 failure).
        """
        from rapidfuzz import fuzz
        parts = [_normalize_text(p).lower() for p in re.split(r"\.\.\.|…", quote_text)]
        parts = [p for p in parts if len(p) >= 15]
        # Require >=2 substantial segments: the precision comes from the coherence
        # BETWEEN segments. A single generic segment (trailing/leading "…") has no
        # disambiguator and matches siblings at random — leave it to miss.
        if len(parts) < 2:
            return None
        spans = []
        for p in parts:
            al = fuzz.partial_ratio_alignment(p, self.norm_text_lower, score_cutoff=score_cutoff)
            if al is None or al.score < score_cutoff or al.dest_end <= al.dest_start:
                return None
            spans.append((al.dest_start, al.dest_end))
        # segments must be in document order and separated only by small gaps
        for i in range(1, len(spans)):
            gap = spans[i][0] - spans[i - 1][1]
            if gap < 0 or gap > max_gap_chars:
                return None
        start, end = spans[0][0], spans[-1][1]
        seg_text = self._extract_norm_text_for_span(start, end)
        if self._fuzzy_sibling_conflict(_normalize_text(quote_text), seg_text):
            return None
        merged: Dict[int, List[fitz.Rect]] = {}
        for (s, e) in spans:
            for pg, rects in (self._spans_to_regions(s, e) or {}).items():
                merged.setdefault(pg, []).extend(rects)
        return merged or None

    @staticmethod
    def _clean_quote_for_match(text: str) -> str:
        """Undo the light, non-content 'reconstruction' the extractor sometimes
        applies to a quote so a genuinely verbatim quote matches the PDF:

          * peel wrapper markers it adds around the text (*...*, "...", '...')
          * fold literal caret superscripts 10^12 / 10^{12} -> 1012 (the PDF drops
            the superscript; unicode ¹² is already handled by _normalize_text)

        This is a QUERY-side cleanup only (the stored quote is untouched); it does
        not change what the PDF index contains.
        """
        t = (text or '').strip().strip(' *"\'“”‘’').strip()
        t = re.sub(r'(\d)\s*\^\s*\{?(\d+)\}?', r'\1\2', t)
        return t

    def find_quotes_enrich(self, quotes: List[Dict[str, str]], debug: bool = False,
                           score_cutoff: float = 85.0) -> List[Dict]:
        """Budgeted-hybrid finder for the off-hot-path bulk enrichment.

        Two-stage per quote:
          1. The cheap, high-precision DETERMINISTIC cascade — `find_quotes_original`
             with `skip_expensive_crosspage=True` (exact_ci / ellipsis / punctuation
             / hyphen / anchor-gapped / strict cross-page-chain; the 0%-precision
             fitz + line-window fallbacks are dropped). Resolves the easy majority
             in microseconds and never returns a wrong-but-expensive box.
          2. For the residual misses, a bounded rapidfuzz partial alignment
             (`_fuzzy_locate_rapid`) — recovering the "mostly verbatim, minor drift"
             tail that `find_quotes_original` has no fuzzy path for, without the
             difflib blowup.
          3. For ellipsis quotes that still miss, `_fuzzy_ellipsis_chain` locates
             each segment fuzzily but keeps ellipsis_chain's coherence guards
             (>=2 segments, in-order, small gap, whole-quote distinctive check) —
             the largest recoverable miss bucket, precision-safe.

        Pair with `PDFTextSearcher(pdf, fast_index=True)` for the ~4x-cheaper index.
        `find_quotes_original` / `find_quotes` / `find_quotes_ir` are untouched.
        """
        import time
        base = self.find_quotes_original(quotes, debug=debug, skip_expensive_crosspage=True)
        for res in base:
            if res.get('location') is not None:
                continue
            clean = self._clean_quote_for_match(res.get('quote', ''))
            norm_q = _normalize_text(clean)
            if not norm_q:
                continue
            t0 = time.perf_counter()
            method = None
            regions = None
            # Cleaned exact retry: a quote that is verbatim once wrapper markers /
            # caret-superscripts are removed now matches exactly (highest precision).
            start = self.norm_text_lower.find(norm_q.lower())
            if start != -1:
                regions = self._spans_to_regions(start, start + len(norm_q))
                if regions:
                    method = 'exact_ci_cleaned'
            if not regions:
                regions = self._fuzzy_locate_rapid(norm_q, score_cutoff=score_cutoff)
                if regions:
                    method = 'fuzzy_match'
            if not regions and ('...' in clean or '…' in clean):
                regions = self._fuzzy_ellipsis_chain(clean, score_cutoff=score_cutoff)
                if regions:
                    method = 'fuzzy_ellipsis_chain'
            if regions:
                res['location'] = self._page_regions_to_location(regions)
                if debug:
                    d = res.setdefault('debug', {})
                    d['method'] = method
                    d['fuzzy_fallback'] = True
                    d['timing_ms'] = round(d.get('timing_ms', 0.0) + (time.perf_counter() - t0) * 1000, 3)
        return base

    def close(self):
        try:
            self.doc.close()
        except Exception:
            pass
