#!/usr/bin/env python3
"""Extract auditable mechanisms behind local/final outcome discordance.

The exported mechanisms are evidence profiles, not causal claims. A trajectory
may exhibit more than one mechanism, so mechanism shares are not additive.
Semantic claims about problem understanding remain explicitly uncoded until a
human coding pass is completed.
"""

import csv
import re
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

AGENTS = ("lingxi", "moatless", "openhands")

CRITERIA = {
    "semantic_review_required": "PU correctness cannot be inferred from lexical oracle overlap alone",
    "exact_target_failure_observed": "an executed run mentions a FAIL_TO_PASS test and ends in failure",
    "related_target_failure_observed": "an executed run mentions a reference test file and ends in failure",
    "non_target_failure_counted_positive": "FR+ is supported only by a failing run unrelated to oracle tests",
    "target_run_passed_but_fr_positive": "a target-related run passes, but the FR anchor is labeled positive",
    "text_only_target_evidence": "FR+ has oracle-test text evidence but no executable run",
    "target_run_outcome_unknown": "a target-related run exists but has no decisive pass/fail result",
    "reproduction_attempt_passed": "FR- contains a passing run and no target failure evidence",
    "reproduction_attempt_inconclusive": "FR- contains runs but no decisive result",
    "reproduction_not_executed": "FR- contains only diagnostic material or reasoning, without a run",
    "partial_reference_file_localization": "FL+ reaches only a subset of a multi-file reference patch",
    "file_only_localization": "FL+ reaches reference files but has no changed-hunk token signal",
    "file_and_hunk_localization": "FL+ reaches all reference files and contains changed-hunk token evidence",
    "implicit_localization_at_patch": "FL- is followed by a first patch on reference files",
    "delayed_reference_redirection": "later refinement reaches reference files after an oracle-misaligned anchor",
    "alternative_nonreference_implementation": "officially resolved trajectory never edits reference-patch files",
    "partial_reference_patch_coverage": "PC+ edits only a subset of reference-patch files",
    "reference_file_without_direction_evidence": "PC+ reaches reference files without positive changed-content evidence",
    "negative_post_patch_refinement": "the last refinement is oracle-negative after PC+",
    "target_validation_still_fails": "the last target-related validation fails",
    "target_validation_passes_but_evaluator_fails": "target-related local validation passes but official evaluation is unresolved",
    "no_decisive_target_validation": "no decisive target-related validation result is observable",
    "first_patch_redirected_later": "PC- is followed by an edit of reference-patch files",
    "reference_direction_not_unique": "officially resolved last refinement opposes the reference-patch direction",
    "local_validation_contradicts_evaluator": "negative local validation evidence is followed by official resolution",
    "proxy_validation_passes": "PV- ends with a passing non-target run and official resolution",
    "proxy_validation_fails_but_evaluator_passes": "PV- ends with a failing non-target run but official evaluation resolves",
    "no_decisive_proxy_validation": "PV- has no decisive target or proxy result, but official evaluation resolves",
}


def write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def select_anchor(segments, code):
    matches = [(index, segment) for index, segment in enumerate(segments) if segment["subtask_code"] == code]
    if not matches:
        return None
    return matches[0] if ANCHOR[code] == "first" else matches[-1]


def event_text(event):
    return " ".join(
        str(event.get(key, "")) for key in ("command", "text", "path", "cue")
    ).lower()


def test_identifier_parts(test):
    value = str(test or "").lower().strip()
    if not value:
        return []
    parts = [value]
    if "::" in value:
        path, *nodes = value.split("::")
        parts.extend([path.rsplit("/", 1)[-1], *nodes])
    else:
        match = re.match(r"([^\s(]+)\s*\(([^)]+)\)", value)
        if match:
            parts.extend([match.group(1), *match.group(2).split(".")[-2:]])
    return [part for part in parts if len(part) >= 4]


def mentions_exact_target(event, ref):
    text = event_text(event)
    for test in ref.get("fail_tests", []):
        parts = test_identifier_parts(test)
        if parts and (parts[0] in text or sum(part in text for part in parts[1:]) >= 2):
            return True
    return False


def mentions_reference_test_file(event, ref):
    text = event_text(event)
    for path in ref.get("test_files", set()):
        path = pre.norm_path(path).lower()
        if path and (path in text or path.rsplit("/", 1)[-1] in text):
            return True
    return False


def run_profile(events, ref):
    runs = [event for event in events if event["action"] == "Run" or event.get("executes")]
    exact = [event for event in runs if mentions_exact_target(event, ref)]
    related = [event for event in runs if pre.event_relevant_to_tests(event, ref)]
    file_related = [event for event in runs if mentions_reference_test_file(event, ref)]
    return {
        "run_count": len(runs),
        "exact_target_run_count": len(exact),
        "related_run_count": len(related),
        "reference_file_run_count": len(file_related),
        "exact_target_fail": int(any(event.get("outcome") == "fail" for event in exact)),
        "exact_target_pass": int(any(event.get("outcome") == "pass" for event in exact)),
        "related_fail": int(any(event.get("outcome") == "fail" for event in related)),
        "related_pass": int(any(event.get("outcome") == "pass" for event in related)),
        "any_fail": int(any(event.get("outcome") == "fail" for event in runs)),
        "any_pass": int(any(event.get("outcome") == "pass" for event in runs)),
        "any_blocked": int(any(event.get("blocked") for event in runs)),
    }


def path_profile(events, ref):
    reference_paths = {pre.norm_path(path) for path in ref.get("patch_files", set())}
    source_paths = {
        pre.norm_path(event.get("path", ""))
        for event in events
        if event.get("path") and pre.is_source_like(event.get("path", ""), ref)
    }
    hits = source_paths & reference_paths
    oracle_tokens = pre.meaningful_tokens(
        set().union(*ref.get("added", {}).values(), *ref.get("removed", {}).values())
        if ref.get("added") or ref.get("removed")
        else set()
    )
    observed_tokens = pre.meaningful_tokens(["\n".join(event_text(event) for event in events)])
    return {
        "source_paths": ";".join(sorted(source_paths)),
        "reference_paths": ";".join(sorted(reference_paths)),
        "reference_path_count": len(reference_paths),
        "reference_path_hit_count": len(hits),
        "reference_path_coverage": len(hits) / len(reference_paths) if reference_paths else 0.0,
        "oracle_hunk_token_hits": len(oracle_tokens & observed_tokens),
    }


def edit_profile(events, ref):
    edits = [event for event in events if pre.is_patch_edit(event, ref)]
    alignments = [pre.edit_alignment(event, ref) for event in edits]
    reference_paths = {pre.norm_path(path) for path in ref.get("patch_files", set())}
    edited_paths = {pre.norm_path(event.get("path", "")) for event in edits}
    return {
        "source_edit_count": len(edits),
        "edited_paths": ";".join(sorted(edited_paths)),
        "reference_edit_count": sum(item["path"] for item in alignments),
        "reference_file_coverage": (
            len(edited_paths & reference_paths) / len(reference_paths) if reference_paths else 0.0
        ),
        "positive_direction": int(
            any(item["positive"] or item["positive_score"] > 0.05 for item in alignments)
        ),
        "opposing_direction": int(
            any(item["negative"] or item["negative_score"] > 0.05 for item in alignments)
        ),
    }


def last_decisive(events, ref, target_only=False):
    state = "unknown"
    for event in events:
        if event["action"] != "Run" and not event.get("executes"):
            continue
        if target_only and not pre.event_relevant_to_tests(event, ref):
            continue
        if event.get("outcome") in {"pass", "fail"}:
            state = event["outcome"]
    return state


def validation_mechanism(events, ref, positive_unresolved):
    state = last_decisive(events, ref, target_only=True)
    if positive_unresolved:
        if state == "fail":
            return "target_validation_still_fails"
        if state == "pass":
            return "target_validation_passes_but_evaluator_fails"
        return "no_decisive_target_validation"
    state = last_decisive(events, ref, target_only=False)
    if state == "pass":
        return "proxy_validation_passes"
    if state == "fail":
        return "proxy_validation_fails_but_evaluator_passes"
    return "no_decisive_proxy_validation"


def mechanisms_for(code, cell, context):
    segment_runs = context["segment_runs"]
    segment_paths = context["segment_paths"]
    segment_edits = context["segment_edits"]
    trajectory_edits = context["trajectory_edits"]
    later_edits = context["later_edits"]
    anchor_outcomes = context["anchor_outcomes"]
    segment_events = context["segment_events"]
    ref = context["ref"]
    mechanisms = []

    if code == "PU":
        return ["semantic_review_required"]

    if code == "FR" and cell == "positive_unresolved":
        if segment_runs["exact_target_fail"]:
            mechanisms.append("exact_target_failure_observed")
        elif segment_runs["related_fail"]:
            mechanisms.append("related_target_failure_observed")
        elif segment_runs["any_fail"]:
            mechanisms.append("non_target_failure_counted_positive")
        elif segment_runs["related_pass"]:
            mechanisms.append("target_run_passed_but_fr_positive")
        elif segment_runs["related_run_count"]:
            mechanisms.append("target_run_outcome_unknown")
        else:
            mechanisms.append("text_only_target_evidence")
        return mechanisms

    if code == "FR" and cell == "negative_resolved":
        if segment_runs["any_pass"]:
            return ["reproduction_attempt_passed"]
        if segment_runs["run_count"]:
            return ["reproduction_attempt_inconclusive"]
        return ["reproduction_not_executed"]

    if code == "FL" and cell == "positive_unresolved":
        if (
            segment_paths["reference_path_count"] > 1
            and segment_paths["reference_path_coverage"] < 1.0
        ):
            mechanisms.append("partial_reference_file_localization")
        elif segment_paths["oracle_hunk_token_hits"] < 2:
            mechanisms.append("file_only_localization")
        else:
            mechanisms.append("file_and_hunk_localization")
        return mechanisms

    if code == "FL" and cell == "negative_resolved":
        if anchor_outcomes.get("PC") == "+":
            return ["implicit_localization_at_patch"]
        if later_edits["reference_file_coverage"] > 0:
            return ["delayed_reference_redirection"]
        return ["alternative_nonreference_implementation"]

    if code == "PC" and cell == "positive_unresolved":
        if segment_edits["reference_file_coverage"] < 1.0:
            mechanisms.append("partial_reference_patch_coverage")
        if not segment_edits["positive_direction"]:
            mechanisms.append("reference_file_without_direction_evidence")
        if anchor_outcomes.get("PR") == "-":
            mechanisms.append("negative_post_patch_refinement")
        mechanisms.append(validation_mechanism(context["anchor_pv_events"], ref, True))
        return mechanisms

    if code == "PC" and cell == "negative_resolved":
        if later_edits["reference_file_coverage"] > 0:
            return ["first_patch_redirected_later"]
        return ["alternative_nonreference_implementation"]

    if code == "PR" and cell == "positive_unresolved":
        return [validation_mechanism(context["anchor_pv_events"], ref, True)]

    if code == "PR" and cell == "negative_resolved":
        basis = context["segment"]["local_outcome_basis"]
        if basis == "edit opposes reference direction":
            return ["reference_direction_not_unique"]
        return ["local_validation_contradicts_evaluator"]

    if code == "PV" and cell == "positive_unresolved":
        return [validation_mechanism(segment_events, ref, True)]

    if code == "PV" and cell == "negative_resolved":
        return [validation_mechanism(segment_events, ref, False)]

    return []


def raw_path(agent, instance_id):
    suffix = ".traj" if agent == "lingxi" else ".json"
    return TRAJ_ROOT / "data" / "raw" / agent / f"{instance_id}{suffix}"


def build_rows():
    refs = pre.load_reference(TRAJ_ROOT, TRAJ_ROOT / "data" / "processed" / "pre12")
    rows = []
    cell_totals = Counter()
    for agent, instance_id, resolved, events, segments in pre.load_all(TRAJ_ROOT, refs):
        if not segments:
            continue
        ref = refs[instance_id]
        anchors = {code: select_anchor(segments, code) for code in ANCHOR}
        anchor_outcomes = {
            code: selected[1]["local_outcome"] if selected else "absent"
            for code, selected in anchors.items()
        }
        anchor_pv_events = []
        if anchors["PV"]:
            pv = anchors["PV"][1]
            anchor_pv_events = events[pv["start_event"] : pv["end_event"] + 1]

        for code, selected in anchors.items():
            if not selected:
                continue
            _, segment = selected
            outcome = segment["local_outcome"]
            if outcome not in {"+", "-"} or int(resolved) == int(outcome == "+"):
                continue
            cell = "positive_unresolved" if outcome == "+" else "negative_resolved"
            segment_events = events[segment["start_event"] : segment["end_event"] + 1]
            later_events = events[segment["end_event"] + 1 :]
            context = {
                "segment": segment,
                "segment_events": segment_events,
                "ref": ref,
                "segment_runs": run_profile(segment_events, ref),
                "segment_paths": path_profile(segment_events, ref),
                "segment_edits": edit_profile(segment_events, ref),
                "later_edits": edit_profile(later_events, ref),
                "trajectory_edits": edit_profile(events, ref),
                "anchor_outcomes": anchor_outcomes,
                "anchor_pv_events": anchor_pv_events,
            }
            cell_totals[(code, cell)] += 1
            for mechanism in mechanisms_for(code, cell, context):
                rows.append(
                    {
                        "agent": agent,
                        "instance_id": instance_id,
                        "subtask_code": code,
                        "discordance_cell": cell,
                        "mechanism": mechanism,
                        "criterion": CRITERIA[mechanism],
                        "anchor": ANCHOR[code],
                        "local_outcome_basis": segment.get("local_outcome_basis", ""),
                        "action_sequence": segment["action_sequence"],
                        "raw_trajectory": str(raw_path(agent, instance_id)),
                        **{f"segment_run_{key}": value for key, value in context["segment_runs"].items()},
                        **{f"segment_path_{key}": value for key, value in context["segment_paths"].items()},
                        **{f"segment_edit_{key}": value for key, value in context["segment_edits"].items()},
                        **{f"later_edit_{key}": value for key, value in context["later_edits"].items()},
                        **{f"anchor_{key}_outcome": value for key, value in anchor_outcomes.items()},
                    }
                )
    return rows, cell_totals


def summarize(rows, cell_totals):
    grouped = defaultdict(list)
    for row in rows:
        grouped[(row["subtask_code"], row["discordance_cell"], row["mechanism"])].append(row)
    summary = []
    for (code, cell, mechanism), items in sorted(grouped.items()):
        total = cell_totals[(code, cell)]
        agents = Counter(item["agent"] for item in items)
        examples = []
        for item in items:
            if item["instance_id"] not in examples:
                examples.append(item["instance_id"])
        summary.append(
            {
                "subtask_code": code,
                "discordance_cell": cell,
                "mechanism": mechanism,
                "criterion": CRITERIA[mechanism],
                "n": len(items),
                "cell_n": total,
                "share": f"{len(items) / total:.3f}",
                **{agent: agents[agent] for agent in AGENTS},
                "representative_instances": ";".join(examples[:5]),
            }
        )
    return summary


def main():
    rows, cell_totals = build_rows()
    summary = summarize(rows, cell_totals)
    write_csv(OUT_DIR / "discordance_mechanism_cases.csv", rows)
    write_csv(OUT_DIR / "discordance_mechanism_summary.csv", summary)
    print(f"Wrote {len(rows)} mechanism-case links and {len(summary)} summary rows")


if __name__ == "__main__":
    main()
