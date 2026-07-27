from collections import Counter


def is_junk_pdf(content, line_to_char_ratio_threshold=0.10, similarity_threshold=0.8):
    lines = content.strip().split("\n")
    num_lines = len(lines)
    num_chars = sum(len(line) for line in lines)

    if num_chars == 0:
        return True

    line_to_char_ratio = num_lines / num_chars
    if line_to_char_ratio > line_to_char_ratio_threshold:
        return True

    # Check similarity between lines using Counter
    line_counts = Counter(lines)
    most_common_line_count = line_counts.most_common(1)[0][1]
    similarity_ratio = most_common_line_count / num_lines

    if similarity_ratio > similarity_threshold:
        return True

    return False
