#!/usr/bin/env python3
"""Export compact raw-evidence packets for manual mechanism verification."""

import csv
import json
import sys
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TRAJ_ROOT = ROOT / "swe_verified_claude4_traj"
DISCORDANCE_DIR = ROOT / "RQ1" / "discordance"
sys.path.insert(0, str(TRAJ_ROOT))

from scripts import pre12_recompute as pre  # noqa: E402


ANCHOR = {
    "PU": "first",
    "FR": "last",
    "FL": "last",
    "PC": "first",
    "PR": "last",
    "PV": "last",
}


def compact(value, limit=1200):
    return " ".join(str(value or "").split())[:limit]


def select_anchor(segments, code):
    matches = [segment for segment in segments if segment["subtask_code"] == code]
    if not matches:
        return None
    return matches[0] if ANCHOR[code] == "first" else matches[-1]


def event_packet(event):
    return {
        "event_index": event["event_index"],
        "action": event["action"],
        "cue": event.get("cue", ""),
        "path": event.get("path", ""),
        "outcome": event.get("outcome", ""),
        "command": compact(event.get("command", ""), 500),
        "old_str": compact(event.get("old_str", ""), 700),
        "new_str": compact(event.get("new_str", ""), 700),
        "text": compact(event.get("text", "")),
    }


def reference_packet(ref):
    return {
        "patch_files": sorted(ref.get("patch_files", set())),
        "test_files": sorted(ref.get("test_files", set())),
        "fail_tests": ref.get("fail_tests", []),
        "removed": {
            path: sorted(lines)[:20] for path, lines in ref.get("removed", {}).items()
        },
        "added": {
            path: sorted(lines)[:20] for path, lines in ref.get("added", {}).items()
        },
    }


def selected_mechanisms(limit=3):
    path = DISCORDANCE_DIR / "discordance_mechanism_cases.csv"
    grouped = defaultdict(list)
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            key = (row["subtask_code"], row["discordance_cell"], row["mechanism"])
            existing = grouped[key]
            if len(existing) >= limit:
                continue
            if row["instance_id"] not in {item[1] for item in existing}:
                existing.append((row["agent"], row["instance_id"]))
    selected = defaultdict(list)
    for key, agent_instances in grouped.items():
        for agent_instance in agent_instances:
            selected[agent_instance].append(key)
    return selected


def main():
    refs = pre.load_reference(TRAJ_ROOT, Path("/tmp/pre12_casebook"))
    selected = selected_mechanisms()
    packets = []
    for agent, instance_id, resolved, events, segments in pre.load_all(TRAJ_ROOT, refs):
        keys = selected.get((agent, instance_id), [])
        for code, cell, mechanism in keys:
            segment = select_anchor(segments, code)
            if not segment:
                continue
            segment_events = events[segment["start_event"] : segment["end_event"] + 1]
            later_events = events[segment["end_event"] + 1 :]
            packets.append(
                {
                    "agent": agent,
                    "instance_id": instance_id,
                    "resolved": int(resolved),
                    "subtask_code": code,
                    "discordance_cell": cell,
                    "mechanism": mechanism,
                    "anchor": ANCHOR[code],
                    "local_outcome": segment["local_outcome"],
                    "local_outcome_basis": segment.get("local_outcome_basis", ""),
                    "problem_statement": compact(refs[instance_id]["problem_statement"], 1800),
                    "reference": reference_packet(refs[instance_id]),
                    "segment_events": [event_packet(event) for event in segment_events],
                    "later_edits": [
                        event_packet(event)
                        for event in later_events
                        if pre.is_patch_edit(event, refs[instance_id])
                    ][:20],
                }
            )

    out = DISCORDANCE_DIR / "mechanism_casebook.jsonl"
    with out.open("w", encoding="utf-8") as handle:
        for packet in packets:
            handle.write(json.dumps(packet, ensure_ascii=False) + "\n")
    print(f"Wrote {len(packets)} evidence packets to {out}")


if __name__ == "__main__":
    main()
