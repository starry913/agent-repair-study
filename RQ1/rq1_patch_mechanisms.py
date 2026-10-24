#!/usr/bin/env python3
"""Measure patch-level mechanisms behind PC/PR local/final discordance."""

import csv
import math
import os
import re
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATCH_ROOT = ROOT / "RQ1" / "discordance" / "final_patches"
SUBTASKS = Path(
    os.environ.get(
        "PRE12_SUBTASKS",
        ROOT / "pre" / "pre-12" / "dataset" / "pre12_subtasks.csv",
    )
)


def read_csv(path):
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def changed_lines(patch):
    added = []
    removed = []
    for line in patch.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            added.append(line[1:].strip())
        elif line.startswith("-") and not line.startswith("---"):
            removed.append(line[1:].strip())
    return added, removed


def tokens(lines):
    ignored = {
        "self", "return", "true", "false", "none", "class", "def", "import",
        "from", "with", "value", "name", "type", "else", "elif", "raise",
    }
    return {
        token.lower()
        for line in lines
        for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", line)
        if token.lower() not in ignored
    }


def parse_reference_patch():
    import duckdb

    candidates = sorted(
        Path.home().glob(
            ".cache/huggingface/hub/datasets--princeton-nlp--SWE-bench_Verified/blobs/*"
        ),
        key=lambda path: path.stat().st_size,
        reverse=True,
    )
    explicit = os.environ.get("SWE_BENCH_VERIFIED_PARQUET")
    parquet = Path(explicit).expanduser() if explicit else next((path for path in candidates if path.stat().st_size > 100000), None)
    if parquet is None:
        raise FileNotFoundError("Set SWE_BENCH_VERIFIED_PARQUET to the reference Parquet file, or populate the SWE-bench Verified Hugging Face cache")
    con = duckdb.connect()
    rows = con.execute(
        "select instance_id, patch from read_parquet(?)", [str(parquet)]
    ).fetchall()
    return dict(rows)


def patch_features(candidate, reference):
    cand_add, cand_remove = changed_lines(candidate)
    ref_add, ref_remove = changed_lines(reference)
    cand_add_tokens = tokens(cand_add)
    cand_remove_tokens = tokens(cand_remove)
    ref_add_tokens = tokens(ref_add)
    ref_remove_tokens = tokens(ref_remove)
    correct = len(cand_add_tokens & ref_add_tokens) + len(cand_remove_tokens & ref_remove_tokens)
    reverse = len(cand_add_tokens & ref_remove_tokens) + len(cand_remove_tokens & ref_add_tokens)
    oracle = len(ref_add_tokens) + len(ref_remove_tokens)
    candidate_size = len(cand_add_tokens) + len(cand_remove_tokens)
    return {
        "direction_recall": correct / oracle if oracle else 0.0,
        "direction_precision": correct / candidate_size if candidate_size else 0.0,
        "reverse_overlap": reverse / oracle if oracle else 0.0,
        "candidate_changed_lines": len(cand_add) + len(cand_remove),
        "reference_changed_lines": len(ref_add) + len(ref_remove),
    }


def select_anchors(rows):
    grouped = defaultdict(list)
    for row in rows:
        if row["subtask_code"] in {"PC", "PR"}:
            grouped[(row["agent"], row["instance_id"], row["subtask_code"])].append(row)
    selected = {}
    for key, items in grouped.items():
        selected[key] = items[0] if key[2] == "PC" else items[-1]
    return selected


def write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def sign_test_p(positive, negative):
    n = positive + negative
    if not n:
        return 1.0
    tail = sum(math.comb(n, index) for index in range(min(positive, negative) + 1))
    return min(1.0, 2 * tail / (2**n))


def main():
    manifest = read_csv(PATCH_ROOT / "manifest.csv")
    anchors = select_anchors(read_csv(SUBTASKS))
    references = parse_reference_patch()
    rows = []
    for item in manifest:
        if item["available"] != "1":
            continue
        key_base = (item["agent"], item["instance_id"])
        patch_path = PATCH_ROOT / item["agent"] / f"{item['instance_id']}.patch"
        candidate = patch_path.read_text(encoding="utf-8")
        features = patch_features(candidate, references[item["instance_id"]])
        candidate_files = set(filter(None, item["patch_files"].split(";")))
        reference_files = set(filter(None, item["reference_files"].split(";")))
        file_precision = (
            len(candidate_files & reference_files) / len(candidate_files)
            if candidate_files
            else 0.0
        )
        file_recall = (
            len(candidate_files & reference_files) / len(reference_files)
            if reference_files
            else 0.0
        )
        for code in ("PC", "PR"):
            anchor = anchors.get((*key_base, code))
            if not anchor or anchor["local_outcome"] not in {"+", "-"}:
                continue
            resolved = int(anchor["resolved"])
            local_positive = anchor["local_outcome"] == "+"
            if resolved == local_positive:
                continue
            rows.append(
                {
                    "agent": item["agent"],
                    "instance_id": item["instance_id"],
                    "subtask_code": code,
                    "discordance_cell": (
                        "positive_unresolved" if local_positive else "negative_resolved"
                    ),
                    "local_outcome_basis": anchor["local_outcome_basis"],
                    "patch_method": item["method"],
                    "file_precision": f"{file_precision:.4f}",
                    "file_recall": f"{file_recall:.4f}",
                    **{key: f"{value:.4f}" for key, value in features.items()},
                }
            )
    write_csv(ROOT / "RQ1" / "discordance" / "patch_mechanism_cases.csv", rows)

    summary = []
    for key in sorted({(row["subtask_code"], row["discordance_cell"]) for row in rows}):
        items = [row for row in rows if (row["subtask_code"], row["discordance_cell"]) == key]
        bins = Counter()
        for row in items:
            file_recall = float(row["file_recall"])
            direction_recall = float(row["direction_recall"])
            if file_recall == 0:
                label = "alternative_file"
            elif file_recall < 1:
                label = "partial_file_coverage"
            elif direction_recall < 0.10:
                label = "same_files_low_semantic_overlap"
            elif direction_recall < 0.50:
                label = "partial_semantic_overlap"
            else:
                label = "high_reference_overlap"
            bins[label] += 1
        for label, n in bins.most_common():
            agents = Counter(row["agent"] for row in items if (
                ("alternative_file" if float(row["file_recall"]) == 0 else
                 "partial_file_coverage" if float(row["file_recall"]) < 1 else
                 "same_files_low_semantic_overlap" if float(row["direction_recall"]) < 0.10 else
                 "partial_semantic_overlap" if float(row["direction_recall"]) < 0.50 else
                 "high_reference_overlap") == label
            ))
            summary.append(
                {
                    "subtask_code": key[0],
                    "discordance_cell": key[1],
                    "patch_profile": label,
                    "n": n,
                    "cell_n": len(items),
                    "share": f"{n / len(items):.3f}",
                    "lingxi": agents["lingxi"],
                    "moatless": agents["moatless"],
                    "openhands": agents["openhands"],
                }
            )
    write_csv(ROOT / "RQ1" / "discordance" / "patch_mechanism_summary.csv", summary)

    matched = []
    by_instance = defaultdict(list)
    for item in manifest:
        if item["available"] != "1":
            continue
        by_instance[item["instance_id"]].append(item)
    for instance_id, items in by_instance.items():
        resolved_items = [item for item in items if item["resolved"] == "1"]
        unresolved_items = [item for item in items if item["resolved"] == "0"]
        if not resolved_items or not unresolved_items:
            continue
        profiles = []
        for item in items:
            patch_path = PATCH_ROOT / item["agent"] / f"{instance_id}.patch"
            features = patch_features(
                patch_path.read_text(encoding="utf-8"), references[instance_id]
            )
            candidate_files = set(filter(None, item["patch_files"].split(";")))
            reference_files = set(filter(None, item["reference_files"].split(";")))
            features["file_recall"] = (
                len(candidate_files & reference_files) / len(reference_files)
                if reference_files
                else 0.0
            )
            profiles.append((item, features))
        for feature in ("file_recall", "direction_recall", "direction_precision", "reverse_overlap"):
            resolved_mean = sum(
                profile[feature] for item, profile in profiles if item["resolved"] == "1"
            ) / len(resolved_items)
            unresolved_mean = sum(
                profile[feature] for item, profile in profiles if item["resolved"] == "0"
            ) / len(unresolved_items)
            matched.append(
                {
                    "instance_id": instance_id,
                    "feature": feature,
                    "resolved_agents": ";".join(item["agent"] for item in resolved_items),
                    "unresolved_agents": ";".join(item["agent"] for item in unresolved_items),
                    "resolved_mean": f"{resolved_mean:.4f}",
                    "unresolved_mean": f"{unresolved_mean:.4f}",
                    "delta": f"{resolved_mean - unresolved_mean:.4f}",
                }
            )
    write_csv(ROOT / "RQ1" / "discordance" / "matched_final_patch_differences.csv", matched)

    matched_summary = []
    for feature in sorted({row["feature"] for row in matched}):
        items = [row for row in matched if row["feature"] == feature]
        deltas = [float(row["delta"]) for row in items]
        positive = sum(value > 0 for value in deltas)
        negative = sum(value < 0 for value in deltas)
        matched_summary.append(
            {
                "feature": feature,
                "matched_instances": len(items),
                "mean_delta": f"{sum(deltas) / len(deltas):.4f}",
                "resolved_higher": positive,
                "unresolved_higher": negative,
                "ties": len(items) - positive - negative,
                "sign_test_p": f"{sign_test_p(positive, negative):.4f}",
            }
        )
    write_csv(ROOT / "RQ1" / "discordance" / "matched_final_patch_summary.csv", matched_summary)
    for row in summary:
        print(row)
    print("matched_final_patch_summary")
    for row in matched_summary:
        print(row)


if __name__ == "__main__":
    main()
