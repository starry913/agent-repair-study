#!/usr/bin/env python3
import csv
import math
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
IN = ROOT / "data" / "processed" / "rq1" / "rq1_subtasks.csv"
OUT = ROOT / "data" / "processed" / "rq2_deep"

CODE = {
    "Problem Understanding": "PU",
    "Failure Reproduction": "FR",
    "Fault Localization": "FL",
    "Patch Construction": "PC",
    "Patch Refinement": "PR",
    "Patch Validation": "PV",
}

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


def read_rows():
    with IN.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_csv(name, rows):
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / name
    keys = sorted({k for r in rows for k in r})
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)
    return path


def pct(x, n):
    return 0.0 if n == 0 else 100 * x / n


def dist(counter):
    total = sum(counter.values())
    return {k: counter[k] / total for k in counter} if total else {}


def tvd(a, b):
    keys = set(a) | set(b)
    return 0.5 * sum(abs(a.get(k, 0.0) - b.get(k, 0.0)) for k in keys)


def entropy(counter):
    total = sum(counter.values())
    if not total:
        return 0.0
    h = 0.0
    for n in counter.values():
        p = n / total
        if p:
            h -= p * math.log2(p)
    return h


def md_table(rows, cols):
    lines = ["| " + " | ".join(cols) + " |"]
    lines.append("| " + " | ".join(["---"] * len(cols)) + " |")
    for r in rows:
        lines.append("| " + " | ".join(str(r.get(c, "")) for c in cols) + " |")
    return lines


def summarize(rows, keys):
    c = defaultdict(int)
    for r in rows:
        c[tuple(r[k] for k in keys)] += 1
    out = []
    totals = Counter()
    for key, n in c.items():
        totals[key[:-1]] += n
    for key, n in sorted(c.items()):
        row = {k: v for k, v in zip(keys, key)}
        denom = totals[key[:-1]] if len(keys) > 1 else sum(c.values())
        row["n"] = n
        row["share"] = f"{pct(n, denom):.1f}%"
        out.append(row)
    return out


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    rows = read_rows()
    by = defaultdict(list)
    for r in rows:
        by[(r["agent"], r["instance_id"])].append(r)

    sequences = {}
    transitions = []
    for key, rs in by.items():
        ordered = sorted(rs, key=lambda x: int(x["subtask_index"]))
        seq = [
            {
                "type": CODE[r["subtask_type"]],
                "outcome": OUTCOME.get(r["local_outcome"], "?"),
                "agent": r["agent"],
                "instance_id": r["instance_id"],
            }
            for r in ordered
        ]
        sequences[key] = seq
        for i in range(len(seq) - 1):
            a, b = seq[i], seq[i + 1]
            transitions.append(
                {
                    "from_type": a["type"],
                    "from_outcome": a["outcome"],
                    "to_type": b["type"],
                    "to_outcome": b["outcome"],
                    "transition": f"{a['type']}{a['outcome']}->{b['type']}{b['outcome']}",
                }
            )

    # RQ2.1: routing sensitivity of next subtask to current local outcome.
    sensitivity_rows = []
    routing_rows = []
    for subtask in ["FR", "FL", "PV"]:
        by_outcome = defaultdict(Counter)
        for t in transitions:
            if t["from_type"] == subtask:
                by_outcome[t["from_outcome"]][t["to_type"]] += 1
        outcomes = sorted(by_outcome)
        dists = {o: dist(c) for o, c in by_outcome.items()}
        max_pair = 0.0
        for i, a in enumerate(outcomes):
            for b in outcomes[i + 1 :]:
                max_pair = max(max_pair, tvd(dists[a], dists[b]))
        total_counter = Counter()
        for c in by_outcome.values():
            total_counter.update(c)
        weighted_h = 0.0
        total = sum(total_counter.values())
        for o, c in by_outcome.items():
            weighted_h += (sum(c.values()) / total) * entropy(c)
            for nxt, n in c.items():
                routing_rows.append(
                    {
                        "subtask": subtask,
                        "outcome": o,
                        "next_subtask": nxt,
                        "n": n,
                        "share": f"{pct(n, sum(c.values())):.1f}%",
                    }
                )
        sensitivity_rows.append(
            {
                "subtask": subtask,
                "n": total,
                "next_entropy": f"{entropy(total_counter):.3f}",
                "conditional_entropy": f"{weighted_h:.3f}",
                "entropy_reduction": f"{entropy(total_counter) - weighted_h:.3f}",
                "max_pairwise_tvd": f"{max_pair:.3f}",
            }
        )

    # RQ2.2: pre-patch recovery before first PC.
    pre_recovery = []
    for key, seq in sequences.items():
        first_pc = next((i for i, x in enumerate(seq) if x["type"] == "PC"), len(seq))
        for i, x in enumerate(seq[:first_pc]):
            if x["type"] == "FR" and x["outcome"] in {"-", "?"}:
                later = seq[i + 1 : first_pc]
                next_fl_pos = next((j for j, y in enumerate(later, 1) if y["type"] == "FL" and y["outcome"] == "+"), None)
                next_fr_pos = next((j for j, y in enumerate(later, 1) if y["type"] == "FR" and y["outcome"] == "+"), None)
                pre_recovery.append(
                    {
                        "source": f"FR{x['outcome']}",
                        "recovery": "FL+ before PC" if next_fl_pos is not None else "no FL+ before PC",
                        "steps_to_recovery": next_fl_pos if next_fl_pos is not None else "",
                    }
                )
                if next_fr_pos is not None:
                    pre_recovery.append(
                        {
                            "source": f"FR{x['outcome']}",
                            "recovery": "FR+ before PC",
                            "steps_to_recovery": next_fr_pos,
                        }
                    )
            if x["type"] == "FL" and x["outcome"] == "-":
                later = seq[i + 1 : first_pc]
                next_fl_pos = next((j for j, y in enumerate(later, 1) if y["type"] == "FL" and y["outcome"] == "+"), None)
                next_fr_pos = next((j for j, y in enumerate(later, 1) if y["type"] == "FR" and y["outcome"] == "+"), None)
                label = []
                if next_fl_pos is not None:
                    label.append("FL+ before PC")
                if next_fr_pos is not None:
                    label.append("FR+ before PC")
                pre_recovery.append(
                    {
                        "source": "FL-",
                        "recovery": " + ".join(label) if label else "no positive FR/FL before PC",
                        "steps_to_recovery": min([x for x in [next_fl_pos, next_fr_pos] if x is not None], default=""),
                    }
                )

    pre_recovery_summary = summarize(pre_recovery, ["source", "recovery"])

    # RQ2.3: post-patch feedback dynamics after PV -> PR -> PV.
    triads = []
    pv_events = []
    for key, seq in sequences.items():
        for i, x in enumerate(seq):
            if x["type"] != "PV":
                continue
            nxt = seq[i + 1]["type"] if i + 1 < len(seq) else "END"
            pv_events.append(
                {
                    "pv_outcome": x["outcome"],
                    "next": nxt,
                }
            )
        for i in range(len(seq) - 2):
            a, b, c = seq[i], seq[i + 1], seq[i + 2]
            if a["type"] == "PV" and b["type"] == "PR" and c["type"] == "PV":
                if ORDER[c["outcome"]] > ORDER[a["outcome"]]:
                    change = "improved"
                elif ORDER[c["outcome"]] < ORDER[a["outcome"]]:
                    change = "worsened"
                else:
                    change = "unchanged"
                triads.append(
                    {
                        "first_pv": a["outcome"],
                        "next_pv": c["outcome"],
                        "change": change,
                    }
                )

    pv_next_summary = summarize(pv_events, ["pv_outcome", "next"])
    triad_matrix = summarize(triads, ["first_pv", "next_pv"])
    triad_change = summarize(triads, ["first_pv", "change"])

    # Save.
    write_csv("routing_sensitivity.csv", sensitivity_rows)
    write_csv("routing_distribution.csv", routing_rows)
    write_csv("pre_patch_recovery.csv", pre_recovery_summary)
    write_csv("pv_next_distribution.csv", pv_next_summary)
    write_csv("pv_pr_pv_matrix.csv", triad_matrix)
    write_csv("pv_pr_pv_change.csv", triad_change)

    report = ["# RQ2 Deep Dive\n"]
    report.append("## Routing Sensitivity\n")
    report.extend(md_table(sensitivity_rows, ["subtask", "n", "next_entropy", "conditional_entropy", "entropy_reduction", "max_pairwise_tvd"]))
    report.append("")
    report.append("## Routing Distribution\n")
    report.extend(md_table(routing_rows, ["subtask", "outcome", "next_subtask", "n", "share"]))
    report.append("")
    report.append("## Pre-patch Recovery\n")
    report.extend(md_table(pre_recovery_summary, ["source", "recovery", "n", "share"]))
    report.append("")
    report.append("## PV Next Distribution\n")
    report.extend(md_table(pv_next_summary, ["pv_outcome", "next", "n", "share"]))
    report.append("")
    report.append("## PV -> PR -> PV Matrix\n")
    report.extend(md_table(triad_matrix, ["first_pv", "next_pv", "n", "share"]))
    report.append("")
    report.append("## PV -> PR -> PV Change\n")
    report.extend(md_table(triad_change, ["first_pv", "change", "n", "share"]))
    report.append("")
    (OUT / "rq2_deep_report.md").write_text("\n".join(report), encoding="utf-8")
    print(OUT / "rq2_deep_report.md")


if __name__ == "__main__":
    main()
