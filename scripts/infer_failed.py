"""Infer previously-failed bibcodes by comparing manifest against S3.

Logic: all downloadable bibcodes in the manifest that appear *before* the
last successfully-uploaded bibcode (by manifest order) but are NOT in S3
must have been attempted and failed.

Writes a JSONL file compatible with --failed-log.
"""

import json
import sys
import time
from pathlib import Path

import boto3

from bibcode_collection.pdf_downloader import sanitize_bibcode


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Infer failed downloads from S3 vs manifest")
    parser.add_argument("manifest", type=Path, help="JSONL manifest file")
    parser.add_argument("--s3-bucket", default=None, help="S3 bucket name (omit if using --s3-keys-file)")
    parser.add_argument("--s3-prefix", default="papers", help="S3 key prefix")
    parser.add_argument("--s3-keys-file", type=Path, default=None, help="Pre-fetched S3 keys file (one key per line)")
    parser.add_argument("--output", "-o", type=Path, required=True, help="Output failed-log JSONL file")
    parser.add_argument("--exclude-bibcodes", type=Path, default=None, help="Bibcodes to exclude")
    args = parser.parse_args()

    # Load manifest (ordered)
    records = []
    with open(args.manifest) as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))

    downloadable = [r for r in records if r.get("pdf_url") or r.get("arxiv_id")]

    # Apply exclusions
    if args.exclude_bibcodes:
        exclude = {l.strip() for l in args.exclude_bibcodes.read_text().splitlines() if l.strip()}
        downloadable = [r for r in downloadable if r["bibcode"] not in exclude]

    print(f"Manifest: {len(downloadable):,} downloadable bibcodes")

    # Load S3 keys
    if args.s3_keys_file:
        print(f"Loading S3 keys from {args.s3_keys_file}...")
        s3_keys = {line.strip() for line in args.s3_keys_file.read_text().splitlines() if line.strip()}
    elif args.s3_bucket:
        s3 = boto3.client("s3")
        print(f"Listing s3://{args.s3_bucket}/{args.s3_prefix}/...")
        s3_keys = set()
        paginator = s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=args.s3_bucket, Prefix=args.s3_prefix + "/"):
            for obj in page.get("Contents", []):
                s3_keys.add(obj["Key"])
    else:
        print("ERROR: Must provide --s3-bucket or --s3-keys-file")
        sys.exit(1)
    print(f"  Found {len(s3_keys):,} objects in S3")

    # Build bibcode → manifest index and check which are in S3
    bibcode_to_idx = {}
    in_s3 = set()
    for i, r in enumerate(downloadable):
        bib = r["bibcode"]
        bibcode_to_idx[bib] = i
        s3_key = f"{args.s3_prefix}/{sanitize_bibcode(bib)}.pdf"
        if s3_key in s3_keys:
            in_s3.add(bib)

    print(f"  {len(in_s3):,} of {len(downloadable):,} downloadable bibcodes are in S3")

    # Find the highest manifest index that has a successful S3 upload
    max_success_idx = -1
    for bib in in_s3:
        idx = bibcode_to_idx[bib]
        if idx > max_success_idx:
            max_success_idx = idx

    print(f"  Last successful upload at manifest index {max_success_idx:,} "
          f"(bibcode: {downloadable[max_success_idx]['bibcode']})")

    # Everything before that index that's NOT in S3 = inferred failure
    inferred_failed = []
    for i in range(max_success_idx + 1):
        bib = downloadable[i]["bibcode"]
        if bib not in in_s3:
            inferred_failed.append(bib)

    print(f"\nInferred {len(inferred_failed):,} failed bibcodes "
          f"(before index {max_success_idx:,}, not in S3)")

    # Write output
    ts = time.strftime("%Y-%m-%dT%H:%M:%S")
    with open(args.output, "w") as f:
        for bib in inferred_failed:
            f.write(json.dumps({"bibcode": bib, "ts": ts, "source": "inferred"}) + "\n")

    print(f"Written to: {args.output}")


if __name__ == "__main__":
    main()
