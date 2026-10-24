#!/usr/bin/env python3
"""Build auditable evidence profiles for local/final outcome discordance.

This script does not infer causal labels. It selects one stage anchor per
trajectory and exports observable evidence used for subsequent qualitative
coding against the raw trajectory.
"""

import csv
import sys
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TRAJ_ROOT = ROOT / "swe_verified_claude4_traj"
OUT_DIR = ROOT / "RQ1" / "discordance"
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


def write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def run_events(events):
    return [event for event in events if event["action"] == "Run" or event.get("executes")]


def last_decisive_outcome(events):
    outcomes = [event.get("outcome") for event in run_events(events)]
    outcomes = [outcome for outcome in outcomes if outcome in {"pass", "fail"}]
    return outcomes[-1] if outcomes else "unknown"


def validation_profile(events, ref):
    runs = run_events(events)
    relevant = [event for event in runs if pre.event_relevant_to_tests(event, ref)]
    relevant_outcomes = [event.get("outcome") or "unknown" for event in relevant]
    return {
        "run_count": len(runs),
        "relevant_run_count": len(relevant),
        "last_run_outcome": last_decisive_outcome(events),
        "last_relevant_outcome": last_decisive_outcome(relevant),
        "has_relevant_pass": int("pass" in relevant_outcomes),
        "has_relevant_fail": int("fail" in relevant_outcomes),
        "has_relevant_unknown": int("unknown" in relevant_outcomes),
    }


def edit_profile(events, ref):
    edits = [event for event in events if pre.is_patch_edit(event, ref)]
    alignments = [pre.edit_alignment(event, ref) for event in edits]
    reference_paths = {pre.norm_path(path) for path in ref["patch_files"]}
    edited_paths = {pre.norm_path(event.get("path", "")) for event in edits}
    positive = sum(item["positive"] for item in alignments)
    negative = sum(item["negative"] for item in alignments)
    positive_score = sum(item["positive_score"] for item in alignments)
    negative_score = sum(item["negative_score"] for item in alignments)
    return {
        "source_edit_count": len(edits),
        "reference_source_edit_count": sum(item["path"] for item in alignments),
        "nonreference_source_edit_count": sum(not item["path"] for item in alignments),
        "edited_reference_file_count": len(edited_paths & reference_paths),
        "reference_file_count": len(reference_paths),
        "reference_file_coverage": (
            len(edited_paths & reference_paths) / len(reference_paths) if reference_paths else 0.0
        ),
        "has_reference_direction_signal": int(positive > 0 or positive_score > 0.05),
        "has_opposing_direction_signal": int(negative > 0 or negative_score > 0.05),
        "first_edit_reference_file": int(
            bool(edits) and pre.norm_path(edits[0].get("path", "")) in reference_paths
        ),
        "edited_paths": ";".join(sorted(edited_paths)),
        "reference_paths": ";".join(sorted(reference_paths)),
    }


def previous_outcome(segments, index, code):
    matches = [segment["local_outcome"] for segment in segments[:index] if segment["subtask_code"] == code]
    return matches[-1] if matches else "none"


def later_outcome(segments, index, code):
    matches = [segment["local_outcome"] for segment in segments[index + 1 :] if segment["subtask_code"] == code]
    return matches[0] if matches else "none"


def select_anchor(segments, code):
    matches = [(index, segment) for index, segment in enumerate(segments) if segment["subtask_code"] == code]
    if not matches:
        return None
    return matches[0] if ANCHOR[code] == "first" else matches[-1]


def raw_path(agent, instance_id):
    suffix = ".traj" if agent == "lingxi" else ".json"
    return TRAJ_ROOT / "data" / "raw" / agent / f"{instance_id}{suffix}"


def build_rows():
    refs = pre.load_reference(TRAJ_ROOT, TRAJ_ROOT / "data" / "processed" / "pre12")
    rows = []
    for agent, instance_id, resolved, events, segments in pre.load_all(TRAJ_ROOT, refs):
        if not segments:
            continue
        ref = refs[instance_id]
        anchors = {code: select_anchor(segments, code) for code in ANCHOR}
        all_validation = validation_profile(events, ref)
        all_edits = edit_profile(events, ref)
        codes = [segment["subtask_code"] for segment in segments]
        loop_count = sum(left == "PV" and right == "PR" for left, right in zip(codes, codes[1:]))

        anchor_evidence = {}
        for anchor_code, selected in anchors.items():
            if selected is None:
                anchor_evidence[f"anchor_{anchor_code}_outcome"] = "absent"
                anchor_evidence[f"anchor_{anchor_code}_basis"] = ""
                continue
            _, anchor_segment = selected
            anchor_events = events[anchor_segment["start_event"] : anchor_segment["end_event"] + 1]
            anchor_evidence[f"anchor_{anchor_code}_outcome"] = anchor_segment["local_outcome"]
            anchor_evidence[f"anchor_{anchor_code}_basis"] = anchor_segment.get("local_outcome_basis", "")
            for key, value in validation_profile(anchor_events, ref).items():
                anchor_evidence[f"anchor_{anchor_code}_{key}"] = value
            for key, value in edit_profile(anchor_events, ref).items():
                anchor_evidence[f"anchor_{anchor_code}_{key}"] = value

        for code in ANCHOR:
            selected = anchors[code]
            if selected is None:
                continue
            index, segment = selected
            outcome = segment["local_outcome"]
            resolved_int = int(resolved)
            if outcome not in {"+", "-"} or resolved_int == int(outcome == "+"):
                continue

            segment_events = events[segment["start_event"] : segment["end_event"] + 1]
            later_events = events[segment["end_event"] + 1 :]
            segment_validation = validation_profile(segment_events, ref)
            later_validation = validation_profile(later_events, ref)
            segment_edits = edit_profile(segment_events, ref)
            later_edits = edit_profile(later_events, ref)
            cell = "positive_unresolved" if outcome == "+" else "negative_resolved"
            rows.append(
                {
                    "agent": agent,
                    "instance_id": instance_id,
                    "subtask_code": code,
                    "anchor": ANCHOR[code],
                    "local_outcome": outcome,
                    "resolved": resolved_int,
                    "discordance_cell": cell,
                    "subtask_index": segment["subtask_index"],
                    "action_sequence": segment["action_sequence"],
                    "local_outcome_basis": segment.get("local_outcome_basis", ""),
                    "previous_same_subtask_outcome": previous_outcome(segments, index, code),
                    "later_same_subtask_outcome": later_outcome(segments, index, code),
                    "previous_subtask": codes[index - 1] if index else "START",
                    "next_subtask": codes[index + 1] if index + 1 < len(codes) else "END",
                    "has_later_pr": int("PR" in codes[index + 1 :]),
                    "pv_pr_loops": loop_count,
                    "raw_trajectory": str(raw_path(agent, instance_id)),
                    **anchor_evidence,
                    **{f"segment_{key}": value for key, value in segment_validation.items()},
                    **{f"later_{key}": value for key, value in later_validation.items()},
                    **{f"trajectory_{key}": value for key, value in all_validation.items()},
                    **{f"segment_{key}": value for key, value in segment_edits.items()},
                    **{f"later_{key}": value for key, value in later_edits.items()},
                    **{f"trajectory_{key}": value for key, value in all_edits.items()},
                }
            )
    return rows


def summarize(rows):
    counts = Counter((row["subtask_code"], row["discordance_cell"]) for row in rows)
    agent_counts = Counter(
        (row["subtask_code"], row["discordance_cell"], row["agent"]) for row in rows
    )
    summary = []
    for (code, cell), count in sorted(counts.items()):
        summary.append(
            {
                "subtask_code": code,
                "discordance_cell": cell,
                "n": count,
                "lingxi": agent_counts[(code, cell, "lingxi")],
                "moatless": agent_counts[(code, cell, "moatless")],
                "openhands": agent_counts[(code, cell, "openhands")],
            }
        )
    return summary


def main():
    rows = build_rows()
    write_csv(OUT_DIR / "discordant_anchor_cases.csv", rows)
    write_csv(OUT_DIR / "discordant_anchor_summary.csv", summarize(rows))
    print(f"Wrote {len(rows)} auditable discordant anchor cases to {OUT_DIR}")


if __name__ == "__main__":
    main()
