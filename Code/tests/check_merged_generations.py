"""Offline checks for compact sampling and dataset construction."""

from __future__ import annotations

import copy
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
package = types.ModuleType("data")
package.__path__ = [str(ROOT / "data")]
sys.modules["data"] = package

from data_pipeline.merged_generations import candidate_hunks, diff_hunks, read_jsonl
from data_pipeline import sample_haiku_merge as sampler
from data_pipeline import build_dataset
from data.llm_client import LLMClient


def diff(start=1, value="fixed", new_start=None, file="a.py"):
    return f"--- a/{file}\n+++ b/{file}\n@@ -{start},1 +{new_start or start},1 @@\n-line{start - 1}\n+{value}\n"


def inst():
    return {
        "instance_id": "owner__repo-1", "repo": "owner/repo", "base_commit": "base",
        "patch": diff(), "problem_statement": "Fix line0",
        "source_files": {"a.py": "".join(f"line{i}\n" for i in range(60))},
    }


def result(patch_text, raw="first response"):
    return {"extracted_diff": patch_text, "raw_response": raw, "sr_blocks_found": 1,
            "sr_blocks_applied": 1, "modified_files": {"a.py": "not retained"}}


def merge(record, data, generation, sample=0, run_id="round"):
    return sampler.merge_sample(record, data, generation, sample=sample, run_id=run_id,
        model="claude-haiku-4-5-20251001", temperature=0.7, max_tokens=4096,
        system_prompt="system", user_prompt="user")


class SamplingChecks(unittest.TestCase):
    def test_dedup_preserves_first_response_and_sample_tags(self):
        data = inst()
        record, count = merge(None, data, result(diff()))
        self.assertEqual(count, 1)
        original = copy.deepcopy(record["generation"])
        record, count = merge(record, data, result(diff(new_start=4) + diff(30), "later response"), 1)
        self.assertEqual(count, 1)
        self.assertEqual(record["generation"], original)
        self.assertNotIn("later response", json.dumps(record))
        self.assertNotIn("modified_files", record["generation"])
        self.assertEqual([h["sample"] for h in candidate_hunks(record)], [0, 1])
        self.assertEqual(sampler.next_sample(record), 2)
        record, count = merge(record, data, result(diff(30), "duplicate"), 2)
        self.assertEqual(count, 0)
        self.assertEqual(len(record["merged_hunks"]), 2)
        self.assertEqual(sampler.next_sample(record), 3)

    def test_legacy_merged_hunks_preserve_raw_negatives(self):
        record = {"generation": {"extracted_diff": diff(30)},
                  "merged_hunks": [{"file": "a.py", "text": diff_hunks(diff())[0]["text"]}]}
        hunks = candidate_hunks(record)
        self.assertEqual([(h["old_start"], h["sample"]) for h in hunks], [(30, 0), (1, 1)])
        self.assertEqual(sampler.next_sample(record), 2)

    def test_file_boundaries_and_new_files(self):
        text = diff(file="a.py") + "diff --git a/b.py b/b.py\nindex 1..2 100644\n" + diff(file="b.py")
        hunks = diff_hunks(text)
        self.assertEqual([h["file"] for h in hunks], ["a.py", "b.py"])
        self.assertNotIn("diff --git", hunks[0]["text"])
        added = diff_hunks("--- /dev/null\n+++ b/new.py\n@@ -0,0 +1,1 @@\n+hello\n")
        self.assertEqual((added[0]["file"], added[0]["old_len"]), ("new.py", 0))
        header_like = diff_hunks("--- a/a.py\n+++ b/a.py\n@@ -1,1 +1,1 @@\n--- old divider\n+++ new divider\n")
        self.assertEqual(header_like[0]["file"], "a.py")
        self.assertIn("--- old divider", header_like[0]["text"])
        with self.assertRaises(ValueError):
            diff_hunks("--- a/a.py\n+++ b/a.py\n@@ -1,2 +1,2 @@\n-a\n+b\n")

    def test_plain_gzip_and_atomic_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            for suffix in (".jsonl", ".jsonl.gz"):
                path = Path(temp) / ("records" + suffix)
                records = {"i": {"instance_id": "i", "value": "文本"}}
                sampler.save_records(path, records)
                self.assertEqual(sampler.load_records(path), records)
                before = path.read_bytes()
                with patch.object(sampler.os, "replace", side_effect=OSError("interrupted")):
                    with self.assertRaises(OSError):
                        sampler.save_records(path, {"i": {"instance_id": "i", "value": "new"}})
                self.assertEqual(path.read_bytes(), before)
                self.assertEqual(sorted(p.name for p in Path(temp).iterdir()),
                    sorted(["records.jsonl"] if suffix == ".jsonl" else ["records.jsonl", "records.jsonl.gz"]))

    def test_changed_reference_is_rejected(self):
        data = inst()
        record, _ = merge(None, data, result(diff()))
        data["patch"] = diff(value="different reference")
        with self.assertRaises(ValueError):
            merge(record, data, result(diff(30)), 1)

    def test_sampler_api_resume_and_dataset_build(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            data = inst()
            input_path, output = folder / "input.jsonl.gz", folder / "generations.jsonl.gz"
            sampler.save_records(input_path, {data["instance_id"]: data})
            requests = []
            responses = [
                "<<<<<<< SEARCH\nFILE: a.py\nline0\n=======\nfixed\n>>>>>>> REPLACE",
                "<<<<<<< SEARCH\nFILE: a.py\nline29\n=======\nextra\n>>>>>>> REPLACE",
            ]

            def create(**kwargs):
                requests.append(kwargs)
                return types.SimpleNamespace(content=[types.SimpleNamespace(text=responses.pop(0))])

            fake = types.SimpleNamespace(messages=types.SimpleNamespace(create=create))
            args = ["sample_haiku_merge.py", "--input", str(input_path), "--generations", str(output),
                    "--samples", "2", "--run-id", "round-1", "--sleep", "0"]
            with patch.object(LLMClient, "_ensure_client", lambda self: setattr(self, "_client", fake)), \
                    patch.dict(sampler.os.environ, {"ANTHROPIC_API_KEY": "test"}), patch.object(sys, "argv", args):
                sampler.main()
                sampler.main()
            self.assertEqual(len(requests), 2)
            self.assertTrue(all(r["temperature"] == 0.7 and r["max_tokens"] == 4096 for r in requests))
            record = sampler.load_records(output)[data["instance_id"]]
            self.assertEqual([h["sample"] for h in candidate_hunks(record)], [0, 1])
            self.assertNotIn("line29\n=======", record["generation"]["raw_response"])
            self.assertEqual(len(record["sampling"]["runs"]), 2)

            splits = folder / "splits.json"
            splits.write_text(json.dumps({"train_ids": [data["instance_id"]], "val_ids": [], "test_ids": []}))
            instances = folder / "instances.jsonl.gz"
            sampler.save_records(instances, {data["instance_id"]: {"instance_id": data["instance_id"], "fail_to_pass_ids": []}})
            retained, tier3 = folder / "retained.jsonl", folder / "tier3.jsonl"
            args = ["build_dataset.py", "--generations", str(output), "--instances", str(instances),
                    "--splits", str(splits), "--retained-out", str(retained), "--tier3-out", str(tier3),
                    "--manifest", str(folder / "manifest.json")]
            with patch.object(sys, "argv", args):
                build_dataset.main()
            self.assertEqual(list(read_jsonl(retained))[0]["llm_t12_hunks"][0]["sample"], 0)
            self.assertEqual(list(read_jsonl(tier3))[0]["tier3_hunks"][0]["sample"], 1)
            before = output.read_bytes()
            with patch.object(sys, "argv", ["sample_haiku_merge.py", "--input", str(input_path),
                    "--generations", str(output), "--dry-run", "--max", "1"]):
                sampler.main()
            self.assertEqual(output.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
