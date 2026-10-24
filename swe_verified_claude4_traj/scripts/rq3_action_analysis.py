#!/usr/bin/env python3
import csv
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
IN = ROOT / "data" / "processed" / "rq1" / "rq1_subtasks.csv"
OUT = ROOT / "data" / "processed" / "rq3"

OUTCOME = {
    "scope-formed": "+",
    "no-scope": "-",
    "failure-reproduced": "+",
    "not-reproduced": "-",
    "inconclusive": "?",
    "blocked": "?",
    "target-located": "+",
    "no-target": "-",
    "patch-applied": "+",
    "edit-blocked": "-",
    "pass": "+",
    "fail": "-",
}

ORDER = {"-": 0, "?": 1, "+": 2}


def pct(n, d):
    return 0.0 if d == 0 else 100.0 * n / d


def rate(n, d):
    return 0.0 if d == 0 else n / d


def actions(row):
    raw = row.get("actions_raw") or ""
    return raw.split(" -> ") if raw else []


def motif(row):
    st = row["subtask_type"]
    a = actions(row)
    s = set(a)

    if st == "Failure Reproduction":
        has_run = "Execute" in s
        has_create = "Create" in s
        has_modify = "Modify" in s
        if has_create and not has_run and not has_modify:
            return "Create-only"
        if has_run and not has_create and not has_modify:
            return "Run-only"
        if has_create and has_run and not has_modify:
            return "Create+Run"
        if has_modify and has_run and not has_create:
            return "Modify+Run"
        if has_create and has_modify and has_run:
            return "Create+Modify+Run"
        if has_modify and not has_run:
            return "Modify-only"
        return "Other"

    if st == "Fault Localization":
        has_read = "Read" in s
        has_search = "Search" in s
        has_reason = "Understand" in s
        if has_reason and not has_read and not has_search:
            return "Reason-only"
        if has_read and not has_search and not has_reason:
            return "Read-only"
        if has_search and not has_read and not has_reason:
            return "Search-only"
        if has_read and has_search and not has_reason:
            return "Read+Search"
        if has_read and has_search and has_reason:
            return "Reason+Read+Search"
        if has_read and has_reason and not has_search:
            return "Reason+Read"
        if has_search and has_reason and not has_read:
            return "Reason+Search"
        return "Other"

    if st in {"Patch Construction", "Patch Refinement"}:
        has_modify = "Modify" in s
        has_delete = "Delete" in s
        has_create = "Create" in s
        has_context = bool({"Read", "Search", "Understand"} & s)
        has_run = "Execute" in s
        if has_create and not has_modify and not has_delete:
            return "Create-only"
        if has_delete and not has_modify and not has_create:
            return "Delete-only"
        if has_modify and not has_context and not has_run:
            return "Modify-only"
        if has_modify and "Understand" in s and not {"Read", "Search"} & s and not has_run:
            return "Reason+Modify"
        if has_modify and has_context and not has_run:
            return "Context+Modify"
        if has_modify and has_run:
            return "Modify+Run"
        if not has_modify and not has_delete and not has_create and has_context:
            return "Context-only"
        return "Other"

    if st == "Patch Validation":
        has_run = "Execute" in s
        has_create = "Create" in s
        has_edit = "Modify" in s or "Delete" in s
        has_context = bool({"Read", "Search", "Understand"} & s)
        run_count = a.count("Execute")
        if has_run and not has_create and not has_edit and not has_context:
            return "Run-only" if run_count == 1 else "Run+"
        if has_run and has_create and not has_edit:
            return "Create+Run"
        if has_run and has_context and not has_create and not has_edit:
            return "Context+Run"
        if has_run and has_edit:
            return "Edit+Run"
        if not has_run and has_context:
            return "Context-only"
        if not has_run and has_edit:
            return "Edit-only"
        return "Other"

    if st == "Problem Understanding":
        has_read = "Read" in s
        has_reason = "Understand" in s
        if has_reason and has_read:
            return "Reason+Read"
        if has_reason:
            return "Reason-only"
        if has_read:
            return "Read-only"
        return "Other"

    return "Other"


def read_rows():
    with IN.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for row in rows:
        row["outcome3"] = OUTCOME.get(row["local_outcome"], "?")
        row["motif"] = motif(row)
        row["resolved_int"] = int(row["resolved"])
        row["subtask_index_int"] = int(row["subtask_index"])
    return rows


def write_csv(name, rows):
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / name
    keys = sorted({k for row in rows for k in row})
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)
    return path


def summarize(rows, group_keys, within_key=None, min_n=1):
    groups = defaultdict(list)
    totals = Counter()
    for row in rows:
        key = tuple(row[k] for k in group_keys)
        groups[key].append(row)
        if within_key:
            totals[row[within_key]] += 1
    out = []
    for key, rs in sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        n = len(rs)
        if n < min_n:
            continue
        item = {k: v for k, v in zip(group_keys, key)}
        item["n"] = n
        if within_key:
            item["share"] = f"{pct(n, totals[item[within_key]]):.1f}%"
        item["local_pos_rate"] = f"{rate(sum(r['outcome3'] == '+' for r in rs), n):.3f}"
        item["local_neg_rate"] = f"{rate(sum(r['outcome3'] == '-' for r in rs), n):.3f}"
        item["local_uncertain_rate"] = f"{rate(sum(r['outcome3'] == '?' for r in rs), n):.3f}"
        item["resolved_rate"] = f"{rate(sum(r['resolved_int'] for r in rs), n):.3f}"
        out.append(item)
    return out


def display_sequence(seq, max_tokens=10):
    tokens = [x.strip() for x in (seq or "").split(" -> ") if x.strip()]
    if len(tokens) <= max_tokens:
        return seq
    return " -> ".join(tokens[:6] + ["..."] + tokens[-3:])


def exact_sequence_summary(rows, min_n=1):
    groups = defaultdict(list)
    totals = Counter()
    for row in rows:
        key = (row["subtask_type"], row["action_sequence"])
        groups[key].append(row)
        totals[row["subtask_type"]] += 1
    out = []
    for key, rs in sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        n = len(rs)
        if n < min_n:
            continue
        subtask, seq = key
        out.append(
            {
                "subtask_type": subtask,
                "action_sequence": seq,
                "action_sequence_short": display_sequence(seq),
                "n": n,
                "share": f"{pct(n, totals[subtask]):.1f}%",
                "local_pos_rate": f"{rate(sum(r['outcome3'] == '+' for r in rs), n):.3f}",
                "local_neg_rate": f"{rate(sum(r['outcome3'] == '-' for r in rs), n):.3f}",
                "local_uncertain_rate": f"{rate(sum(r['outcome3'] == '?' for r in rs), n):.3f}",
                "resolved_rate": f"{rate(sum(r['resolved_int'] for r in rs), n):.3f}",
            }
        )
    return out


def exact_sequence_extremes(rows):
    thresholds = {
        "Problem Understanding": 30,
        "Failure Reproduction": 30,
        "Fault Localization": 30,
        "Patch Construction": 30,
        "Patch Refinement": 30,
        "Patch Validation": 30,
    }
    summary = exact_sequence_summary(rows, min_n=1)
    by_subtask = defaultdict(list)
    for row in summary:
        by_subtask[row["subtask_type"]].append(row)

    out = []
    for subtask, rs in sorted(by_subtask.items()):
        eligible = [r for r in rs if int(r["n"]) >= thresholds[subtask]]
        best = sorted(eligible, key=lambda r: (-float(r["resolved_rate"]), -int(r["n"])))[:5]
        worst = sorted(eligible, key=lambda r: (float(r["resolved_rate"]), -int(r["n"])))[:5]
        for kind, selected in [("best", best), ("worst", worst)]:
            for r in selected:
                item = dict(r)
                item["rank_type"] = kind
                out.append(item)
    return out


def first_occurrences(rows):
    by_traj = defaultdict(list)
    for row in rows:
        by_traj[(row["agent"], row["instance_id"])].append(row)
    out = []
    for seq in by_traj.values():
        seq = sorted(seq, key=lambda r: r["subtask_index_int"])
        seen = set()
        for row in seq:
            st = row["subtask_type"]
            if st in seen:
                continue
            seen.add(st)
            out.append(dict(row))
    return out, by_traj


def trajectory_fl_presence(by_traj):
    features = ["Read+Search", "Reason+Read+Search", "Read-only", "Reason-only"]
    rows = []
    scopes = ["ALL", "lingxi", "moatless", "openhands"]
    for scope in scopes:
        seqs = [
            seq
            for (agent, _), seq in by_traj.items()
            if scope == "ALL" or agent == scope
        ]
        for feature in features:
            for present in [True, False]:
                selected = []
                for seq in seqs:
                    has_feature = any(
                        r["subtask_type"] == "Fault Localization" and r["motif"] == feature
                        for r in seq
                    )
                    if has_feature == present:
                        selected.append(seq)
                n = len(selected)
                rows.append(
                    {
                        "agent": scope,
                        "fl_motif": feature,
                        "present": int(present),
                        "n": n,
                        "resolved_rate": f"{rate(sum(seq[0]['resolved_int'] for seq in selected), n):.3f}",
                    }
                )
    return rows


def first_patch_by_agent(first_rows):
    rows = [
        row
        for row in first_rows
        if row["subtask_type"] == "Patch Construction"
    ]
    return summarize(rows, ["agent", "motif"], min_n=20)


def pv_pr_pv(by_traj, by_agent=False):
    rows = []
    for (agent, _), seq in by_traj.items():
        seq = sorted(seq, key=lambda r: r["subtask_index_int"])
        for i in range(len(seq) - 2):
            a, b, c = seq[i], seq[i + 1], seq[i + 2]
            if (
                a["subtask_type"] == "Patch Validation"
                and b["subtask_type"] == "Patch Refinement"
                and c["subtask_type"] == "Patch Validation"
            ):
                first = a["outcome3"]
                nxt = c["outcome3"]
                if ORDER[nxt] > ORDER[first]:
                    change = "improved"
                elif ORDER[nxt] < ORDER[first]:
                    change = "worsened"
                else:
                    change = "unchanged"
                rows.append(
                    {
                        "agent": agent if by_agent else "ALL",
                        "first_pv": first,
                        "pr_motif": b["motif"],
                        "next_pv": nxt,
                        "change": change,
                    }
                )
    groups = defaultdict(list)
    for row in rows:
        groups[(row["agent"], row["first_pv"], row["pr_motif"])].append(row)
    out = []
    for key, rs in sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        n = len(rs)
        if n < 20:
            continue
        agent, first, pr = key
        out.append(
            {
                "agent": agent,
                "first_pv": first,
                "pr_motif": pr,
                "n": n,
                "next_pv_pos_rate": f"{rate(sum(r['next_pv'] == '+' for r in rs), n):.3f}",
                "next_pv_neg_rate": f"{rate(sum(r['next_pv'] == '-' for r in rs), n):.3f}",
                "next_pv_uncertain_rate": f"{rate(sum(r['next_pv'] == '?' for r in rs), n):.3f}",
                "improved_rate": f"{rate(sum(r['change'] == 'improved' for r in rs), n):.3f}",
                "worsened_rate": f"{rate(sum(r['change'] == 'worsened' for r in rs), n):.3f}",
            }
        )
    return out


def md_table(rows, cols):
    lines = ["| " + " | ".join(cols) + " |"]
    lines.append("| " + " | ".join(["---"] * len(cols)) + " |")
    for row in rows:
        lines.append("| " + " | ".join(str(row.get(c, "")) for c in cols) + " |")
    return lines


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    rows = read_rows()
    first_rows, by_traj = first_occurrences(rows)

    segment_summary = summarize(rows, ["subtask_type", "motif"], within_key="subtask_type", min_n=20)
    first_summary = summarize(first_rows, ["subtask_type", "motif"], within_key="subtask_type", min_n=20)
    exact_summary = exact_sequence_summary(rows, min_n=1)
    exact_summary_min10 = exact_sequence_summary(rows, min_n=10)
    exact_extremes = exact_sequence_extremes(rows)
    fl_presence = trajectory_fl_presence(by_traj)
    first_pc_agent = first_patch_by_agent(first_rows)
    pv_pr = pv_pr_pv(by_traj, by_agent=False)
    pv_pr_agent = pv_pr_pv(by_traj, by_agent=True)

    write_csv("rq3_segment_motif_summary.csv", segment_summary)
    write_csv("rq3_first_occurrence_motif_summary.csv", first_summary)
    write_csv("rq3_exact_sequence_summary.csv", exact_summary)
    write_csv("rq3_exact_sequence_summary_min10.csv", exact_summary_min10)
    write_csv("rq3_exact_sequence_extremes.csv", exact_extremes)
    write_csv("rq3_trajectory_fl_presence.csv", fl_presence)
    write_csv("rq3_first_patch_motif_by_agent.csv", first_pc_agent)
    write_csv("rq3_pv_pr_pv_by_pr_motif.csv", pv_pr)
    write_csv("rq3_pv_pr_pv_by_pr_motif_agent.csv", pv_pr_agent)

    def top(table, filt, limit=8):
        selected = [r for r in table if filt(r)]
        return selected[:limit]

    report = []
    report.append("# RQ3 Action Analysis")
    report.append("")
    report.append("## Exact Action Sequences")
    for subtask in [
        "Problem Understanding",
        "Failure Reproduction",
        "Fault Localization",
        "Patch Construction",
        "Patch Refinement",
        "Patch Validation",
    ]:
        report.append("")
        report.append(f"### {subtask}")
        report.extend(
            md_table(
                [r for r in exact_summary_min10 if r["subtask_type"] == subtask][:10],
                ["action_sequence_short", "n", "share", "local_pos_rate", "local_uncertain_rate", "resolved_rate"],
            )
        )
    report.append("")
    report.append("## Exact Sequence Extremes")
    report.extend(
        md_table(
            exact_extremes,
            ["subtask_type", "rank_type", "action_sequence_short", "n", "share", "local_pos_rate", "local_uncertain_rate", "resolved_rate"],
        )
    )
    report.append("")
    report.append("## Segment-level Motifs")
    report.extend(
        md_table(
            top(segment_summary, lambda r: r["subtask_type"] in {"Failure Reproduction", "Patch Validation"}, 14),
            ["subtask_type", "motif", "n", "share", "local_pos_rate", "local_uncertain_rate", "resolved_rate"],
        )
    )
    report.append("")
    report.append("## First Occurrence Motifs")
    report.extend(
        md_table(
            top(first_summary, lambda r: r["subtask_type"] in {"Fault Localization", "Patch Construction", "Patch Validation"}, 16),
            ["subtask_type", "motif", "n", "share", "local_pos_rate", "local_uncertain_rate", "resolved_rate"],
        )
    )
    report.append("")
    report.append("## Trajectory-level FL Motif Presence")
    report.extend(
        md_table(
            [r for r in fl_presence if r["agent"] == "ALL"],
            ["fl_motif", "present", "n", "resolved_rate"],
        )
    )
    report.append("")
    report.append("## First Patch Motif by Agent")
    report.extend(
        md_table(
            first_pc_agent,
            ["agent", "motif", "n", "local_pos_rate", "resolved_rate"],
        )
    )
    report.append("")
    report.append("## PV -> PR -> PV by PR Motif")
    report.extend(
        md_table(
            pv_pr,
            ["first_pv", "pr_motif", "n", "next_pv_pos_rate", "next_pv_neg_rate", "next_pv_uncertain_rate", "improved_rate", "worsened_rate"],
        )
    )
    (OUT / "rq3_report.md").write_text("\n".join(report) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
