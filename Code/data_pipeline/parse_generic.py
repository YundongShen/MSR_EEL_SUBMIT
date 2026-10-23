"""raw instances (source_files / test_files / patches) -> parsed instances (REQ / TEST / ORIG).

    python data_pipeline/parse_generic.py --input raw_instances.jsonl --output instances.jsonl
"""
import argparse
import gzip
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common_parse import process_instance  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--input", required=True)
ap.add_argument("--output", required=True)
args = ap.parse_args()
opener = gzip.open if args.input.endswith(".gz") else open
stats = Counter()
with opener(args.input, "rt") as fin, open(args.output, "w") as fout:
    for line in fin:
        rec = process_instance(json.loads(line))
        fout.write(json.dumps(rec, ensure_ascii=False) + "\n")
        stats["instances"] += 1
        stats["without source units"] += not rec["source_units"]
        stats["without test units"] += not rec["test_functions"]
        stats["test units"] += len(rec["test_functions"])
        stats["test units from hunk text"] += sum(t["function_name"].startswith("hunk_") for t in rec["test_functions"])
        stats["source units"] += len(rec["source_units"])
print(dict(stats))
