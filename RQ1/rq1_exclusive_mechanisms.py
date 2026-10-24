#!/usr/bin/env python3
"""Build mutually exclusive evidence profiles for RQ1.1 discordance cells."""

import csv
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TRAJ_ROOT = ROOT / "swe_verified_claude4_traj"
OUT_DIR = ROOT / "RQ1" / "discordance"
PATCH_ROOT = OUT_DIR / "final_patches"
SUBTASKS = Path(
    os.environ.get(
        "PRE12_SUBTASKS",
        ROOT / "pre" / "pre-12" / "dataset" / "pre12_subtasks.csv",
    )
)
sys.path.insert(0, str(TRAJ_ROOT))
sys.path.insert(0, str(ROOT / "RQ1"))

from scripts import pre12_recompute as pre  # noqa: E402
import rq1_discordance_mechanisms as mech  # noqa: E402
import rq1_patch_mechanisms as patch_mech  # noqa: E402


CRITERIA = {
    "text_only_target_evidence": (
        "FR+ mentions an oracle test but contains no executable run"
    ),
    "non_target_failure": "FR+ observes only a failure unrelated to oracle tests",
    "target_run_unknown": "FR+ executes a target-related run with no decisive result",
    "target_run_passed": "FR+ executes a target-related run that passes",
    "related_target_failure": (
        "FR+ executes a reference-test-file run that fails without an exact target match"
    ),
    "exact_target_failure": "FR+ executes an exact FAIL_TO_PASS test that fails",
    "reproduction_not_executed": "FR- contains no executable reproduction run",
    "reproduction_inconclusive": "FR- contains runs but no decisive result",
    "reproduction_passed": "FR- contains a passing run and no target failure",
    "partial_reference_localization": (
        "FL+ reaches only a subset of files in a multi-file reference patch"
    ),
    "file_only_localization": (
        "FL+ reaches reference files without changed-hunk token evidence"
    ),
    "file_and_hunk_localization": (
        "FL+ reaches all reference files and includes changed-hunk token evidence"
    ),
    "implicit_localization_at_patch": "FL- is followed by a first patch on reference files",
    "delayed_reference_redirection": "a later refinement first reaches reference files",
    "alternative_nonreference_implementation": (
        "the officially resolved final patch does not edit reference-patch files"
    ),
    "no_reference_file": "the final patch contains none of the reference-patch files",
    "partial_reference_file_coverage": (
        "the final patch contains only a subset of reference-patch files"
    ),
    "all_files_exact_lines_lt20": (
        "the final patch reaches all reference files but covers <20% of exact changed lines"
    ),
    "all_files_exact_lines_20_79": (
        "the final patch reaches all reference files and covers 20-79% of exact changed lines"
    ),
    "all_files_exact_lines_ge80": (
        "the final patch reaches all reference files and covers >=80% of exact changed lines"
    ),
    "exact_target_pass": "PV+ ends with an exact FAIL_TO_PASS test passing",
    "exact_target_fail": "PV+ ends with an exact FAIL_TO_PASS test failing",
    "exact_target_unknown": "PV+ runs an exact FAIL_TO_PASS test without a decisive result",
    "related_scope_pass": "PV+ passes a related scope but does not run an exact target test",
    "related_scope_fail": "PV+ fails a related scope but does not run an exact target test",
    "related_scope_unknown": "PV+ has target-related activity without a decisive result",
    "proxy_pass": "PV- ends with a passing non-target run",
    "proxy_fail": "PV- ends with a failing non-target run",
    "proxy_unknown": "PV- has no decisive run result",
}


FAMILY = {
    "text_only_target_evidence": "measurement_false_positive",
    "non_target_failure": "measurement_false_positive",
    "target_run_unknown": "insufficient_observability",
    "target_run_passed": "measurement_false_positive",
    "related_target_failure": "coarse_reproduction",
    "exact_target_failure": "genuine_local_success",
    "reproduction_not_executed": "reproduction_bypassed",
    "reproduction_inconclusive": "insufficient_observability",
    "reproduction_passed": "failure_not_observed",
    "partial_reference_localization": "local_scope_undercoverage",
    "file_only_localization": "local_granularity_undercoverage",
    "file_and_hunk_localization": "genuine_local_success",
    "implicit_localization_at_patch": "measurement_false_negative",
    "delayed_reference_redirection": "later_recovery",
    "alternative_nonreference_implementation": "nonunique_solution",
    "no_reference_file": "oracle_direction_abandoned",
    "partial_reference_file_coverage": "patch_scope_undercoverage",
    "all_files_exact_lines_lt20": "patch_content_undercoverage",
    "all_files_exact_lines_20_79": "partial_or_alternative_patch_content",
    "all_files_exact_lines_ge80": "near_reference_patch_but_unresolved",
    "exact_target_pass": "genuine_local_success",
    "exact_target_fail": "measurement_false_positive",
    "exact_target_unknown": "insufficient_observability",
    "related_scope_pass": "validation_scope_undercoverage",
    "related_scope_fail": "measurement_false_positive",
    "related_scope_unknown": "insufficient_observability",
    "proxy_pass": "measurement_false_negative",
    "proxy_fail": "proxy_evidence_contradicts_evaluator",
    "proxy_unknown": "insufficient_observability",
}


def read_csv(path):
    with Path(path).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path, rows):
    fields = [
        "subtask_code",
        "discordance_cell",
        "mechanism",
        "mechanism_family",
        "criterion",
        "n",
        "cell_n",
        "share",
        "lingxi",
        "moatless",
        "openhands",
        "representative_instances",
    ]
    with Path(path).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def classify_fr(cell, events, ref):
    profile = mech.run_profile(events, ref)
    if cell == "positive_unresolved":
        if profile["exact_target_fail"]:
            return "exact_target_failure"
        if profile["related_fail"]:
            return "related_target_failure"
        if profile["any_fail"]:
            return "non_target_failure"
        if profile["related_pass"]:
            return "target_run_passed"
        if profile["related_run_count"]:
            return "target_run_unknown"
        return "text_only_target_evidence"
    if profile["any_pass"]:
        return "reproduction_passed"
    if profile["run_count"]:
        return "reproduction_inconclusive"
    return "reproduction_not_executed"


def classify_fl(cell, events, later_events, first_pc, ref):
    if cell == "positive_unresolved":
        profile = mech.path_profile(events, ref)
        if profile["reference_path_count"] > 1 and profile["reference_path_coverage"] < 1:
            return "partial_reference_localization"
        if profile["oracle_hunk_token_hits"] < 2:
            return "file_only_localization"
        return "file_and_hunk_localization"
    if first_pc and first_pc["local_outcome"] == "+":
        return "implicit_localization_at_patch"
    if mech.edit_profile(later_events, ref)["reference_file_coverage"] > 0:
        return "delayed_reference_redirection"
    return "alternative_nonreference_implementation"


def last_outcome(events):
    outcomes = [
        event.get("outcome")
        for event in events
        if (event["action"] == "Run" or event.get("executes"))
        and event.get("outcome") in {"pass", "fail"}
    ]
    return outcomes[-1] if outcomes else "unknown"


def classify_pv(cell, events, ref):
    runs = [
        event
        for event in events
        if event["action"] == "Run" or event.get("executes")
    ]
    if cell == "positive_unresolved":
        exact = [event for event in runs if mech.mentions_exact_target(event, ref)]
        related = [event for event in runs if pre.event_relevant_to_tests(event, ref)]
        exact_state = last_outcome(exact)
        related_state = last_outcome(related)
        if exact and exact_state == "pass":
            return "exact_target_pass"
        if exact and exact_state == "fail":
            return "exact_target_fail"
        if exact:
            return "exact_target_unknown"
        if related_state == "pass":
            return "related_scope_pass"
        if related_state == "fail":
            return "related_scope_fail"
        return "related_scope_unknown"
    state = last_outcome(runs)
    if state == "pass":
        return "proxy_pass"
    if state == "fail":
        return "proxy_fail"
    return "proxy_unknown"


def patch_profile(agent, instance_id, ref_patch, manifest):
    item = manifest.get((agent, instance_id))
    if not item or item["available"] != "1":
        return None
    path = PATCH_ROOT / agent / f"{instance_id}.patch"
    candidate = path.read_text(encoding="utf-8", errors="replace")
    candidate_added, candidate_removed = map(set, patch_mech.changed_lines(candidate))
    reference_added, reference_removed = map(set, patch_mech.changed_lines(ref_patch))
    overlap = len(candidate_added & reference_added) + len(candidate_removed & reference_removed)
    oracle_size = len(reference_added) + len(reference_removed)
    exact_line_recall = overlap / oracle_size if oracle_size else 0.0
    candidate_files = set(filter(None, item["patch_files"].split(";")))
    reference_files = set(filter(None, item["reference_files"].split(";")))
    file_recall = (
        len(candidate_files & reference_files) / len(reference_files)
        if reference_files
        else 0.0
    )
    if file_recall == 0:
        return "no_reference_file"
    if file_recall < 1:
        return "partial_reference_file_coverage"
    if exact_line_recall < 0.20:
        return "all_files_exact_lines_lt20"
    if exact_line_recall < 0.80:
        return "all_files_exact_lines_20_79"
    return "all_files_exact_lines_ge80"


def select(segments, code, first=False):
    matches = [segment for segment in segments if segment["subtask_code"] == code]
    if not matches:
        return None
    return matches[0] if first else matches[-1]


def build_cases():
    refs = pre.load_reference(TRAJ_ROOT, Path("/tmp/rq1_exclusive_mechanisms"))
    references = patch_mech.parse_reference_patch()
    manifest = {
        (row["agent"], row["instance_id"]): row
        for row in read_csv(PATCH_ROOT / "manifest.csv")
    }
    cases = []
    for agent, instance_id, resolved, events, segments in pre.load_all(TRAJ_ROOT, refs):
        for code in ("FR", "FL", "PC", "PR", "PV"):
            segment = select(segments, code, first=code == "PC")
            if not segment or segment["local_outcome"] not in {"+", "-"}:
                continue
            positive = segment["local_outcome"] == "+"
            if int(resolved) == int(positive):
                continue
            cell = "positive_unresolved" if positive else "negative_resolved"
            segment_events = events[segment["start_event"] : segment["end_event"] + 1]
            later_events = events[segment["end_event"] + 1 :]
            if code == "FR":
                label = classify_fr(cell, segment_events, refs[instance_id])
            elif code == "FL":
                label = classify_fl(
                    cell,
                    segment_events,
                    later_events,
                    select(segments, "PC", first=True),
                    refs[instance_id],
                )
            elif code in {"PC", "PR"}:
                label = patch_profile(
                    agent, instance_id, references[instance_id], manifest
                )
                if label is None:
                    continue
            else:
                label = classify_pv(cell, segment_events, refs[instance_id])
            cases.append(
                {
                    "agent": agent,
                    "instance_id": instance_id,
                    "subtask_code": code,
                    "discordance_cell": cell,
                    "mechanism": label,
                }
            )
    return cases


def summarize(cases):
    cells = Counter(
        (case["subtask_code"], case["discordance_cell"]) for case in cases
    )
    grouped = defaultdict(list)
    for case in cases:
        grouped[
            (case["subtask_code"], case["discordance_cell"], case["mechanism"])
        ].append(case)
    rows = []
    for (code, cell, label), items in sorted(grouped.items()):
        agents = Counter(item["agent"] for item in items)
        examples = list(dict.fromkeys(item["instance_id"] for item in items))[:5]
        total = cells[(code, cell)]
        rows.append(
            {
                "subtask_code": code,
                "discordance_cell": cell,
                "mechanism": label,
                "mechanism_family": FAMILY[label],
                "criterion": CRITERIA[label],
                "n": len(items),
                "cell_n": total,
                "share": f"{len(items) / total:.3f}",
                "lingxi": agents["lingxi"],
                "moatless": agents["moatless"],
                "openhands": agents["openhands"],
                "representative_instances": ";".join(examples),
            }
        )
    return rows


def main():
    cases = build_cases()
    rows = summarize(cases)
    write_csv(OUT_DIR / "exclusive_mechanism_summary.csv", rows)
    for row in rows:
        print(row)


if __name__ == "__main__":
    main()
