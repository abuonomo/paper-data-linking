import json, random, sys
src, dst, n, seed = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
# Only keep valid JSON lines without null bytes
valid_lines = []
with open(src, errors='replace') as f:
    for line in f:
        line = line.strip()
        if not line or '\x00' in line:
            continue
        try:
            json.loads(line)
            valid_lines.append(line + '\n')
        except json.JSONDecodeError:
            pass
random.Random(seed).shuffle(valid_lines)
with open(dst, 'w') as f:
    f.writelines(valid_lines[:n])
print(f"Sampled {min(n, len(valid_lines))} from {len(valid_lines)} valid lines")
