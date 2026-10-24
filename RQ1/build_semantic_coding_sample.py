#!/usr/bin/env python3
"""Create a reproducible stratified sample for manual semantic coding."""

import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DISCORDANCE = ROOT / "RQ1" / "discordance"
SAMPLE_SIZE = 12
SEED = "rq1-discordance-v1"


def stable_rank(row):
    value = "|".join(
        [
            SEED,
            row["subtask_code"],
            row["discordance_cell"],
            row["agent"],
            row["instance_id"],
        ]
    )
    return hashlib.sha256(value.encode()).hexdigest()


def read_rows():
    with (DISCORDANCE / "discordant_anchor_cases.csv").open(
        newline="", encoding="utf-8"
    ) as handle:
        return list(csv.DictReader(handle))


def allocate(items, size):
    grouped = defaultdict(list)
    for item in items:
        grouped[item["agent"]].append(item)
    selected = []
    per_agent = size // 3
    for agent in ("lingxi", "moatless", "openhands"):
        candidates = sorted(grouped[agent], key=stable_rank)
        selected.extend(candidates[:per_agent])
    remaining = sorted(
        [item for item in items if item not in selected], key=stable_rank
    )
    selected.extend(remaining[: size - len(selected)])
    return selected


def main():
    rows = read_rows()
    sampled = []
    for key in sorted({(row["subtask_code"], row["discordance_cell"]) for row in rows}):
        candidates = [
            row
            for row in rows
            if (row["subtask_code"], row["discordance_cell"]) == key
        ]
        for row in allocate(candidates, min(SAMPLE_SIZE, len(candidates))):
            patch = (
                DISCORDANCE
                / "final_patches"
                / row["agent"]
                / f"{row['instance_id']}.patch"
            )
            sampled.append(
                {
                    "subtask_code": row["subtask_code"],
                    "discordance_cell": row["discordance_cell"],
                    "agent": row["agent"],
                    "instance_id": row["instance_id"],
                    "anchor": row["anchor"],
                    "local_outcome_basis": row["local_outcome_basis"],
                    "action_sequence": row["action_sequence"],
                    "raw_trajectory": row["raw_trajectory"],
                    "final_patch": str(patch) if patch.exists() else "",
                    "primary_mechanism": "",
                    "secondary_mechanism": "",
                    "coder_evidence": "",
                    "coder_id": "",
                }
            )
    path = DISCORDANCE / "semantic_coding_sample.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=sampled[0].keys())
        writer.writeheader()
        writer.writerows(sampled)
    manifest = {
        "seed": SEED,
        "per_cell": SAMPLE_SIZE,
        "cells": len({(row["subtask_code"], row["discordance_cell"]) for row in sampled}),
        "sampled_anchors": len(sampled),
        "allocation": "four per agent when available, then deterministic top-up",
    }
    (DISCORDANCE / "semantic_coding_sample.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False))


if __name__ == "__main__":
    main()
