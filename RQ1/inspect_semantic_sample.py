#!/usr/bin/env python3
"""Print compact raw-evidence packets for the stratified coding sample."""

import argparse
import csv
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TRAJ_ROOT = ROOT / "swe_verified_claude4_traj"
DISCORDANCE = ROOT / "RQ1" / "discordance"
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


def compact(value, limit):
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 3] + "..."


def sample_rows(code, cell, instance_id):
    path = DISCORDANCE / "semantic_coding_sample.csv"
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    return [
        row
        for row in rows
        if row["subtask_code"] == code
        and row["discordance_cell"] == cell
        and (not instance_id or row["instance_id"] == instance_id)
    ]


def raw_events(row):
    path = Path(row["raw_trajectory"])
    extractor = {
        "lingxi": pre.extract_lingxi,
        "moatless": pre.extract_moatless,
        "openhands": pre.extract_openhands,
    }[row["agent"]]
    return extractor(path)


def select_segment(segments, code):
    matches = [segment for segment in segments if segment["subtask_code"] == code]
    if not matches:
        return None
    return matches[0] if ANCHOR[code] == "first" else matches[-1]


def reference_changes(ref):
    lines = []
    for path in sorted(ref["patch_files"]):
        lines.append(f"FILE {path}")
        for line in sorted(ref["removed"].get(path, set()))[:24]:
            lines.append(f"- {line}")
        for line in sorted(ref["added"].get(path, set()))[:24]:
            lines.append(f"+ {line}")
    return "\n".join(lines)


def event_line(event):
    evidence = event.get("text") or event.get("command") or ""
    old = compact(event.get("old_str"), 500)
    new = compact(event.get("new_str"), 500)
    edit = f" OLD={old} NEW={new}" if old or new else ""
    return (
        f"[{event['event_index']}] {event['action']} "
        f"path={event.get('path', '')} outcome={event.get('outcome', '')} "
        f"cue={event.get('cue', '')}: {compact(evidence, 1800)}{edit}"
    )


def print_case(row, ref):
    events = raw_events(row)
    for index, event in enumerate(events):
        event["event_index"] = index
    pre.annotate_event_provenance(events, ref)
    labels = pre.assign_subtasks(events, ref)
    segments = pre.build_segments(events, labels, ref)
    segment = select_segment(segments, row["subtask_code"])
    if not segment:
        return

    start, end = segment["start_event"], segment["end_event"]
    anchor_events = events[start : end + 1]
    later_key = [
        event
        for event in events[end + 1 :]
        if event["action"] == "Run" or pre.is_patch_edit(event, ref)
    ]
    patch_path = Path(row["final_patch"]) if row["final_patch"] else None
    final_patch = (
        patch_path.read_text(encoding="utf-8", errors="replace")
        if patch_path and patch_path.exists()
        else "<unavailable>"
    )

    print(f"\n## {row['agent']} / {row['instance_id']}")
    print(f"anchor={row['anchor']} outcome_basis={row['local_outcome_basis'] or '<empty>'}")
    print(f"actions={row['action_sequence']}")
    print("\nISSUE:")
    print(compact(ref["problem_statement"], 2200))
    print("\nREFERENCE:")
    print(reference_changes(ref))
    print("\nANCHOR EVENTS:")
    for event in anchor_events:
        print(event_line(event))
    print("\nLATER EDIT/RUN EVENTS:")
    for event in later_key[-24:]:
        print(event_line(event))
    print("\nFINAL PATCH:")
    print(compact(final_patch, 5000))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("code", choices=ANCHOR)
    parser.add_argument(
        "cell", choices=("positive_unresolved", "negative_resolved")
    )
    parser.add_argument("--instance")
    args = parser.parse_args()

    rows = sample_rows(args.code, args.cell, args.instance)
    refs = pre.load_reference(TRAJ_ROOT, Path("/tmp/pre12_semantic_inspection"))
    for row in rows:
        print_case(row, refs[row["instance_id"]])


if __name__ == "__main__":
    main()
