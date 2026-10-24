#!/usr/bin/env python3
import argparse
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path


ROOT_HINT = Path(__file__).resolve().parents[1]
if str(ROOT_HINT) not in sys.path:
    sys.path.insert(0, str(ROOT_HINT))

from scripts import profile_taxonomy_coverage as prof


SUBTASKS = [
    "Problem Understanding",
    "Failure Reproduction",
    "Fault Localization",
    "Patch Construction",
    "Patch Refinement",
    "Patch Validation",
]

ACTIONS = prof.ACTIONS
EDIT_ACTIONS = prof.EDIT_ACTIONS
SOURCE_SUFFIXES = (
    ".py",
    ".pyi",
    ".rst",
    ".md",
    ".txt",
    ".toml",
    ".yaml",
    ".yml",
    ".json",
    ".ini",
    ".cfg",
    ".c",
    ".h",
    ".cpp",
    ".java",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
)

UNDERSTAND_CUES = {
    "problem_decoder",
    "issue_analysis",
    "current_behavior",
    "expected_behavior",
    "root_cause",
    "solution_mapper",
    "code_change_plan",
    "problem_solver",
    "think",
    "thinking_blocks",
    "thoughts",
}

UNDERSTAND_PATTERNS = [
    r"\b(root cause|cause|caused by|because|therefore|this means|indicates|suggests)\b",
    r"\b(issue|problem|bug|failure|failing|error|traceback|assertion|regression)\b",
    r"\b(expected|actual|current behavior|observed behavior)\b",
    r"\b(hypothesis|likely|probably|seems|appears|diagnos|analysis|reason)\b",
    r"\b(fix|patch|solution|approach|need to|should|must|modify|change|implement)\b",
    r"\b(target|relevant|related|call chain|inheritance|operator|method|function|class)\b",
]

WEAK_UNDERSTAND_PATTERNS = [
    r"^\s*(let me|i(?:'ll| will)|now let me|next,? i|great!?|perfect!?|ok(?:ay)?)[\s,.:!-]",
    r"^\s*(we need|i need) to (look|check|inspect|open|read|run|search|find)\b",
    r"^\s*(done|finished|completed|all tests pass|the fix is complete)\b",
]

BLOCKED_PATTERNS = [
    r"no module named",
    r"modulenotfounderror",
    r"importerror",
    r"permission denied",
    r"command not found",
    r"no such file or directory",
    r"not installed",
    r"could not install",
    r"dependency",
    r"environment",
    r"timeout",
]


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def pct(n, d):
    return 0.0 if d == 0 else 100.0 * n / d


def rr(resolved, n):
    return 0.0 if n == 0 else resolved / n


def bool_str(value):
    return "1" if value else "0"


def infer_path_extended(text):
    if not text:
        return ""
    for pat in [
        r"'(?:path|file_path|file_name)'\s*:\s*'([^']+)'",
        r'"(?:path|file_path|file_name)"\s*:\s*"([^"]+)"',
    ]:
        m = re.search(pat, text)
        if m:
            return m.group(1)
    return ""


def normalize_path(path):
    if not path:
        return ""
    p = str(path).replace("\\", "/")
    p = re.sub(r"^/workspace/[^/]+/", "", p)
    p = re.sub(r"^\./", "", p)
    return p


def is_source_like_path(path):
    p = normalize_path(path).lower()
    if not p:
        return False
    if prof.is_temp_or_test_path(p):
        return False
    base = p.rsplit("/", 1)[-1]
    if "." not in base:
        return False
    return base.endswith(SOURCE_SUFFIXES)


def is_blocked_text(text):
    low = (text or "").lower()
    return any(re.search(p, low) for p in BLOCKED_PATTERNS)


def strict_understand(event):
    cue = str(event.get("cue") or "")
    text = str(event.get("text") or "")
    low = text.lower()
    if cue in {
        "problem_decoder",
        "issue_analysis",
        "current_behavior",
        "expected_behavior",
        "root_cause",
        "solution_mapper",
        "code_change_plan",
        "problem_solver",
    }:
        return True
    if cue not in UNDERSTAND_CUES and len(text.strip()) < 120:
        return False
    if any(re.search(p, low) for p in WEAK_UNDERSTAND_PATTERNS) and len(text.strip()) < 220:
        return False
    hits = sum(1 for p in UNDERSTAND_PATTERNS if re.search(p, low))
    if cue in {"think", "thinking_blocks", "thoughts"}:
        return hits >= 1 and len(text.strip()) >= 60
    return hits >= 2 and len(text.strip()) >= 120


def enrich_events(events):
    enriched = []
    for idx, event in enumerate(events):
        e = dict(event)
        e["event_index"] = idx
        e["path"] = normalize_path(e.get("path") or infer_path_extended(e.get("text", "")))
        e["is_temp_or_test"] = prof.is_temp_or_test_path(e.get("path", ""))
        e["is_source_path"] = is_source_like_path(e.get("path", ""))
        e["is_patch_edit"] = is_patch_edit_event(e)
        e["blocked"] = is_blocked_text(e.get("text", ""))
        if e["action"] == "Understand" and not strict_understand(e):
            continue
        enriched.append(e)
    return enriched


def is_patch_edit_event(event):
    action = event.get("action")
    if action not in EDIT_ACTIONS:
        return False
    path = event.get("path") or ""
    if prof.is_temp_or_test_path(path):
        return False
    if path:
        return True
    return action in {"Modify", "Delete"}


def nearest_before(indices, i):
    vals = [x for x in indices if x < i]
    return vals[-1] if vals else None


def nearest_after(indices, i):
    for x in indices:
        if x > i:
            return x
    return None


def assign_subtasks(events):
    if not events:
        return []

    patch_indices = [i for i, e in enumerate(events) if e.get("is_patch_edit")]
    first_patch = patch_indices[0] if patch_indices else None
    exec_indices = [i for i, e in enumerate(events) if e["action"] == "Execute" or e.get("executes")]
    pre_patch_end = first_patch if first_patch is not None else len(events)
    pre_repro_indices = [
        i
        for i, e in enumerate(events[:pre_patch_end])
        if e["action"] == "Execute"
        or e.get("executes")
        or (e["action"] in {"Create", "Modify"} and e.get("is_temp_or_test"))
    ]
    first_repro = pre_repro_indices[0] if pre_repro_indices else None
    labels = []
    current = "Problem Understanding"

    for i, e in enumerate(events):
        action = e["action"]
        if first_patch is None or i < first_patch:
            if action == "Execute" or e.get("executes") or (action in {"Create", "Modify"} and e.get("is_temp_or_test")):
                label = "Failure Reproduction"
            elif i < first_repro if first_repro is not None else True:
                # Before any observable reproduction, only target-seeking operations count
                # as static fault localization. Generic browsing stays in PU.
                if action == "Search" or (action == "Read" and e.get("is_source_path")):
                    label = "Fault Localization"
                elif current == "Fault Localization" and action in {"Read", "Understand", "Setup"}:
                    label = "Fault Localization"
                else:
                    label = "Problem Understanding"
            elif action in {"Read", "Search", "Understand"}:
                label = "Fault Localization"
            elif action in {"Read", "Search"}:
                label = "Fault Localization"
            elif action == "Setup":
                label = current
            elif e.get("is_patch_edit"):
                label = "Patch Construction"
            else:
                label = current
        else:
            prev_exec = nearest_before(exec_indices, i)
            next_exec = nearest_after(exec_indices, i)
            next_patch = nearest_after(patch_indices, i)
            has_validated = prev_exec is not None and prev_exec > first_patch

            if e.get("is_patch_edit"):
                label = "Patch Refinement" if has_validated else "Patch Construction"
            elif action == "Execute" or e.get("executes"):
                label = "Patch Validation"
            elif not has_validated:
                label = "Patch Construction"
            elif action in {"Create", "Modify"} and e.get("is_temp_or_test"):
                label = "Patch Validation"
            elif action in {"Read", "Search", "Understand"}:
                if has_validated and next_patch is not None and (next_exec is None or next_patch < next_exec):
                    label = "Patch Refinement"
                else:
                    label = "Patch Validation"
            elif action == "Setup":
                label = current
            else:
                label = current

        labels.append(label)
        current = label

    labels = absorb_patch_context(events, labels)
    return labels


def absorb_patch_context(events, labels):
    labels = list(labels)
    for i, e in enumerate(events):
        if e.get("is_patch_edit") and labels[i] in {"Patch Construction", "Patch Refinement"}:
            target = labels[i]
            j = i - 1
            absorbed = 0
            while j >= 0 and absorbed < 2:
                if labels[j] in {"Fault Localization", "Problem Understanding"} and events[j]["action"] in {"Read", "Search", "Understand"}:
                    labels[j] = target
                    absorbed += 1
                    j -= 1
                else:
                    break
    return labels


def compress_actions(actions):
    out = []
    for action in actions:
        if out and out[-1].rstrip("+") == action:
            if not out[-1].endswith("+"):
                out[-1] += "+"
        else:
            out.append(action)
    return " -> ".join(out)


def build_segments(events, labels):
    segments = []
    if not events:
        return segments
    start = 0
    for i in range(1, len(events)):
        if labels[i] != labels[i - 1]:
            segments.append(make_segment(events[start:i], labels[i - 1], len(segments) + 1))
            start = i
    segments.append(make_segment(events[start:], labels[-1], len(segments) + 1))
    return segments


def make_segment(events, subtask, index):
    actions = [e["action"] for e in events]
    outcomes = [e.get("outcome") or "" for e in events]
    paths = sorted({e.get("path") for e in events if e.get("path")})
    return {
        "subtask_index": index,
        "subtask_type": subtask,
        "start_event": events[0]["event_index"],
        "end_event": events[-1]["event_index"],
        "n_events": len(events),
        "action_sequence": compress_actions(actions),
        "actions_raw": " -> ".join(actions),
        "local_outcome": infer_local_outcome(subtask, events, outcomes),
        "has_understand": any(e["action"] == "Understand" for e in events),
        "has_read": any(e["action"] == "Read" for e in events),
        "has_search": any(e["action"] == "Search" for e in events),
        "has_execute": any(e["action"] == "Execute" or e.get("executes") for e in events),
        "has_patch_edit": any(e.get("is_patch_edit") for e in events),
        "paths": ";".join(paths[:12]),
    }


def infer_local_outcome(subtask, events, outcomes):
    if any(e.get("blocked") for e in events):
        if subtask in {"Failure Reproduction", "Patch Validation"}:
            return "blocked"

    if subtask == "Problem Understanding":
        return "scope-formed" if any(e["action"] == "Understand" for e in events) else "no-scope"

    if subtask == "Failure Reproduction":
        known = [o for o in outcomes if o in {"pass", "fail"}]
        if any(o == "fail" for o in known):
            return "failure-reproduced"
        if any(o == "pass" for o in known):
            return "not-reproduced"
        return "inconclusive"

    if subtask == "Fault Localization":
        if any(e.get("is_source_path") for e in events):
            return "target-located"
        if any(e["action"] in {"Read", "Search"} for e in events):
            return "target-located"
        return "no-target"

    if subtask in {"Patch Construction", "Patch Refinement"}:
        return "patch-applied" if any(e.get("is_patch_edit") for e in events) else "edit-blocked"

    if subtask == "Patch Validation":
        known = [o for o in outcomes if o in {"pass", "fail"}]
        if not known:
            return "inconclusive"
        return known[-1]

    return "inconclusive"


def canonical_path(segments):
    return " -> ".join(s["subtask_type"] for s in segments)


def composition(segments):
    return " + ".join(s for s in SUBTASKS if any(x["subtask_type"] == s for x in segments))


def count_validation_refinement_loops(segments):
    loops = 0
    prev = None
    for seg in segments:
        cur = seg["subtask_type"]
        if prev == "Patch Validation" and cur == "Patch Refinement":
            loops += 1
        prev = cur
    return loops


def load_all(root):
    outcomes = prof.load_outcomes(root)
    extractors = {
        "lingxi": (root / "data/raw/lingxi", "*.traj", prof.extract_lingxi),
        "moatless": (root / "data/raw/moatless", "*.json", prof.extract_moatless),
        "openhands": (root / "data/raw/openhands", "*.json", prof.extract_openhands),
    }
    for agent, (directory, pattern, extractor) in extractors.items():
        for path in sorted(directory.glob(pattern)):
            instance_id = path.stem
            raw_events, _, meta = extractor(path)
            events = enrich_events(raw_events)
            labels = assign_subtasks(events)
            segments = build_segments(events, labels) if events else []
            yield agent, instance_id, instance_id in outcomes[agent], events, segments, meta


def write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    keys = sorted({k for row in rows for k in row.keys()})
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)


def summarize_rows(rows, group_keys):
    acc = defaultdict(lambda: {"n": 0, "resolved": 0})
    for row in rows:
        key = tuple(row[k] for k in group_keys)
        acc[key]["n"] += 1
        acc[key]["resolved"] += int(row["resolved"])
    out = []
    for key, vals in sorted(acc.items(), key=lambda kv: kv[0]):
        item = {k: v for k, v in zip(group_keys, key)}
        item.update(vals)
        item["resolved_rate"] = f"{rr(vals['resolved'], vals['n']):.3f}"
        out.append(item)
    return out


def distribution_rows(rows, group_keys, total_key=None):
    acc = Counter(tuple(row[k] for k in group_keys) for row in rows)
    totals = Counter()
    if total_key:
        for key, n in acc.items():
            total_group = key[group_keys.index(total_key)]
            totals[total_group] += n
    else:
        totals[None] = sum(acc.values())
    out = []
    for key, n in sorted(acc.items(), key=lambda kv: kv[0]):
        item = {k: v for k, v in zip(group_keys, key)}
        denom = totals[key[group_keys.index(total_key)]] if total_key else totals[None]
        item["n"] = n
        item["share"] = f"{pct(n, denom):.1f}%"
        out.append(item)
    return out


def top_by_group(rows, group_key, item_key, min_n=1, limit=20):
    buckets = defaultdict(Counter)
    resolved = defaultdict(Counter)
    for row in rows:
        g = row[group_key]
        item = row[item_key]
        buckets[g][item] += 1
        if row["resolved"]:
            resolved[g][item] += 1
    out = []
    for g in sorted(buckets):
        for item, n in buckets[g].most_common():
            if n < min_n:
                continue
            r = resolved[g][item]
            out.append(
                {
                    group_key: g,
                    item_key: item,
                    "n": n,
                    "resolved": r,
                    "resolved_rate": f"{rr(r, n):.3f}",
                }
            )
            if sum(1 for x in out if x[group_key] == g) >= limit:
                break
    return out


def md_table(rows, columns, headers=None):
    if headers is None:
        headers = columns
    lines = ["| " + " | ".join(headers) + " |"]
    lines.append("| " + " | ".join(["---"] * len(columns)) + " |")
    for row in rows:
        lines.append("| " + " | ".join(str(row.get(col, "")) for col in columns) + " |")
    return lines


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--out-dir", default="data/processed/rq1")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    out = root / args.out_dir
    out.mkdir(parents=True, exist_ok=True)

    subtask_rows = []
    traj_rows = []
    action_rows = []

    for agent, instance_id, resolved, events, segments, meta in load_all(root):
        action_counts = Counter(e["action"] for e in events)
        for e in events:
            action_rows.append(
                {
                    "agent": agent,
                    "instance_id": instance_id,
                    "resolved": int(resolved),
                    "event_index": e["event_index"],
                    "action": e["action"],
                    "cue": e.get("cue", ""),
                    "outcome": e.get("outcome", ""),
                    "path": e.get("path", ""),
                    "is_patch_edit": bool_str(e.get("is_patch_edit")),
                    "is_temp_or_test": bool_str(e.get("is_temp_or_test")),
                }
            )

        for seg in segments:
            row = {
                "agent": agent,
                "instance_id": instance_id,
                "resolved": int(resolved),
                **seg,
            }
            subtask_rows.append(row)

        seq = canonical_path(segments)
        comp = composition(segments)
        has_pc = any(s["subtask_type"] == "Patch Construction" for s in segments)
        has_pv = any(s["subtask_type"] == "Patch Validation" for s in segments)
        distinct = len({s["subtask_type"] for s in segments})
        loops = count_validation_refinement_loops(segments)
        traj_rows.append(
            {
                "agent": agent,
                "instance_id": instance_id,
                "resolved": int(resolved),
                "n_events": len(events),
                "n_subtasks": len(segments),
                "distinct_subtask_types": distinct,
                "complete_repair": int(has_pc and has_pv),
                "has_patch_construction": int(has_pc),
                "has_patch_validation": int(has_pv),
                "validation_refinement_loops": loops,
                "composition": comp,
                "canonical_path": seq,
                **{f"action_count_{a.lower()}": action_counts[a] for a in ACTIONS},
                **{f"has_{s.lower().replace(' ', '_')}": int(any(x["subtask_type"] == s for x in segments)) for s in SUBTASKS},
            }
        )

    complete_rows = [r for r in traj_rows if r["complete_repair"]]

    local_rows = summarize_rows(subtask_rows, ["subtask_type", "local_outcome"])
    distinct_rows = summarize_rows(complete_rows, ["distinct_subtask_types"])
    composition_rows = top_by_group(complete_rows, "distinct_subtask_types", "composition", min_n=1, limit=15)
    pathway_rows = top_by_group(complete_rows, "distinct_subtask_types", "canonical_path", min_n=3, limit=10)
    loop_rows = summarize_rows(complete_rows, ["validation_refinement_loops"])
    agent_loop_rows = summarize_rows(complete_rows, ["agent", "validation_refinement_loops"])
    agent_subtask_rows = distribution_rows(subtask_rows, ["agent", "subtask_type"], total_key="agent")
    agent_action_rows = distribution_rows(action_rows, ["agent", "action"], total_key="agent")

    understand_feature_rows = []
    for row in complete_rows:
        instance_subtasks = [s for s in subtask_rows if s["agent"] == row["agent"] and s["instance_id"] == row["instance_id"]]
        first_pc = next((s for s in instance_subtasks if s["subtask_type"] == "Patch Construction"), None)
        first_pr = next((s for s in instance_subtasks if s["subtask_type"] == "Patch Refinement"), None)
        pv_after_fail = any(s["subtask_type"] == "Patch Validation" and s["local_outcome"] == "fail" for s in instance_subtasks)
        understand_feature_rows.append(
            {
                "agent": row["agent"],
                "instance_id": row["instance_id"],
                "resolved": row["resolved"],
                "understand_before_or_in_first_patch": int(bool(first_pc and first_pc["has_understand"])),
                "understand_in_first_refinement": int(bool(first_pr and first_pr["has_understand"])),
                "has_failed_validation": int(pv_after_fail),
                "loops": row["validation_refinement_loops"],
            }
        )

    understand_tables = []
    for feature in [
        "understand_before_or_in_first_patch",
        "understand_in_first_refinement",
        "has_failed_validation",
    ]:
        for value in [0, 1]:
            subset = [r for r in understand_feature_rows if r[feature] == value]
            n = len(subset)
            resolved_n = sum(r["resolved"] for r in subset)
            understand_tables.append(
                {
                    "feature": feature,
                    "value": value,
                    "n": n,
                    "resolved": resolved_n,
                    "resolved_rate": f"{rr(resolved_n, n):.3f}",
                }
            )

    write_csv(out / "rq1_actions.csv", action_rows)
    write_csv(out / "rq1_subtasks.csv", subtask_rows)
    write_csv(out / "rq1_trajectories.csv", traj_rows)
    write_csv(out / "rq1_local_outcomes.csv", local_rows)
    write_csv(out / "rq1_distinct_subtasks.csv", distinct_rows)
    write_csv(out / "rq1_compositions_by_distinct.csv", composition_rows)
    write_csv(out / "rq1_pathways_by_distinct.csv", pathway_rows)
    write_csv(out / "rq1_validation_refinement_loops.csv", loop_rows)
    write_csv(out / "rq1_validation_refinement_loops_by_agent.csv", agent_loop_rows)
    write_csv(out / "rq1_agent_subtask_distribution.csv", agent_subtask_rows)
    write_csv(out / "rq1_agent_action_distribution.csv", agent_action_rows)
    write_csv(out / "rq1_understand_features.csv", understand_tables)

    report = []
    total_resolved = sum(r["resolved"] for r in traj_rows)
    complete_resolved = sum(r["resolved"] for r in complete_rows)
    report.append("# RQ1 Pre-experiment\n")
    report.append(f"Trajectories: {len(traj_rows)}; resolved: {total_resolved}; resolved rate: {rr(total_resolved, len(traj_rows)):.3f}\n")
    report.append(f"Complete repair trajectories (Patch Construction + Patch Validation): {len(complete_rows)}; resolved: {complete_resolved}; resolved rate: {rr(complete_resolved, len(complete_rows)):.3f}\n")

    report.append("## Agent + Subtask Distribution\n")
    report.extend(md_table(agent_subtask_rows, ["agent", "subtask_type", "n", "share"]))
    report.append("")

    report.append("## Agent + Action Distribution\n")
    report.extend(md_table(agent_action_rows, ["agent", "action", "n", "share"]))
    report.append("")

    report.append("## RQ1.1 Local Outcome vs Final Resolved\n")
    report.extend(md_table(local_rows, ["subtask_type", "local_outcome", "n", "resolved", "resolved_rate"]))
    report.append("")

    report.append("## RQ1.2 Distinct Subtask Types among Complete Repairs\n")
    report.extend(md_table(distinct_rows, ["distinct_subtask_types", "n", "resolved", "resolved_rate"]))
    report.append("")

    report.append("## RQ1.2 Composition Expansion\n")
    report.extend(md_table(composition_rows, ["distinct_subtask_types", "composition", "n", "resolved", "resolved_rate"]))
    report.append("")

    report.append("## RQ1.2 Pathway Expansion\n")
    report.extend(md_table(pathway_rows, ["distinct_subtask_types", "canonical_path", "n", "resolved", "resolved_rate"]))
    report.append("")

    report.append("## RQ1.3 Validation-Refinement Loops among Complete Repairs\n")
    report.extend(md_table(loop_rows, ["validation_refinement_loops", "n", "resolved", "resolved_rate"]))
    report.append("")

    report.append("## RQ1.3 Validation-Refinement Loops by Agent\n")
    report.extend(md_table(agent_loop_rows, ["agent", "validation_refinement_loops", "n", "resolved", "resolved_rate"]))
    report.append("")

    report.append("## Candidate RQ1.4 Understand-related Signals among Complete Repairs\n")
    report.extend(md_table(understand_tables, ["feature", "value", "n", "resolved", "resolved_rate"]))
    report.append("")

    (out / "rq1_report.md").write_text("\n".join(report), encoding="utf-8")

    print(out / "rq1_report.md")
    print(out / "rq1_subtasks.csv")
    print(out / "rq1_trajectories.csv")


if __name__ == "__main__":
    main()
