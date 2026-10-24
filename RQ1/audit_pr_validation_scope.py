#!/usr/bin/env python3
"""Check whether PR outcome transitions compare equivalent validation scopes."""

import csv
import hashlib
import re
import shlex
import sys
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TRAJ_ROOT = ROOT / "swe_verified_claude4_traj"
OUT_DIR = ROOT / "RQ1" / "audit"
sys.path.insert(0, str(TRAJ_ROOT))

from scripts import pre12_recompute as pre  # noqa: E402


def clean_target(token):
    target = token.strip("'\"(),")
    target = re.sub(r"^/workspace/[^/]+/", "", target)
    target = re.sub(r"^/testbed/", "", target)
    return target.removeprefix("./")


def norm_scope(event):
    command = str(event.get("command", "")).strip()
    if not command:
        return "", set(), "<unknown>"
    try:
        tokens = shlex.split(command)
    except ValueError:
        tokens = command.split()
    lowered = [token.lower() for token in tokens]
    runner = ""
    start = -1
    for index, token in enumerate(lowered):
        base = Path(token).name
        if base in {"pytest", "py.test", "runtests.py", "tox", "make"}:
            runner = "pytest" if base in {"pytest", "py.test"} else base
            start = index + 1
            break
        if base.startswith("python") and index + 2 < len(tokens) and lowered[index + 1] == "-m":
            module = lowered[index + 2]
            if module in {"pytest", "unittest"}:
                runner = module
                start = index + 3
                break
        if base.startswith("python") and index + 1 < len(tokens):
            script = tokens[index + 1]
            if script == "-c" and index + 2 < len(tokens):
                digest = hashlib.sha1(tokens[index + 2].encode()).hexdigest()[:12]
                return "python", {f"inline:{digest}"}, f"python|inline:{digest}"
            if script.endswith(".py"):
                target = clean_target(script)
                return "python", {target}, f"python|{target}"
    if not runner:
        return "", set(), "<unknown>"

    targets = set()
    index = start
    while index < len(tokens):
        token = tokens[index]
        if token in {"&&", "||", ";", "|"}:
            break
        if token in {"-k", "-m"} and index + 1 < len(tokens):
            targets.add(f"{token}:{tokens[index + 1]}")
            index += 2
            continue
        if not token.startswith("-") and "=" not in token:
            targets.add(clean_target(token))
        index += 1
    if not targets:
        targets.add("<suite>")
    encoded = f"{runner}|{'|'.join(sorted(targets))}"
    return runner, targets, encoded


def scope_relation(before, after):
    before_runner, before_targets, before_encoded = before
    after_runner, after_targets, after_encoded = after
    if before_encoded == "<unknown>" or after_encoded == "<unknown>":
        return "scope_unknown"
    if before_runner != after_runner:
        return "changed_scope"
    if before_targets == after_targets:
        return "same_scope"
    if before_targets < after_targets:
        return "expanded_scope"
    if after_targets < before_targets:
        return "narrowed_scope"
    return "changed_scope"


def decisive_runs(events):
    return [
        event
        for event in events
        if (event["action"] == "Run" or event.get("executes"))
        and event.get("outcome") in {"pass", "fail"}
    ]


def write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main():
    refs = pre.load_reference(TRAJ_ROOT, Path("/tmp/pre12_pr_scope_audit"))
    rows = []
    counts = Counter()
    for agent, instance_id, resolved, events, segments in pre.load_all(TRAJ_ROOT, refs):
        for index, segment in enumerate(segments):
            if segment["subtask_code"] != "PR":
                continue
            previous = next(
                (item for item in reversed(segments[:index]) if item["subtask_code"] == "PV"),
                None,
            )
            following = next(
                (item for item in segments[index + 1 :] if item["subtask_code"] == "PV"),
                None,
            )
            before_events = (
                events[previous["start_event"] : previous["end_event"] + 1]
                if previous
                else []
            )
            after_events = (
                events[following["start_event"] : following["end_event"] + 1]
                if following
                else []
            )
            before = decisive_runs(before_events)
            after = decisive_runs(after_events)
            before_event = before[-1] if before else None
            after_event = after[-1] if after else None
            before = norm_scope(before_event) if before_event else ("", set(), "<none>")
            after = norm_scope(after_event) if after_event else ("", set(), "<none>")
            before_scope = before[2]
            after_scope = after[2]
            if before_scope == "<none>" or after_scope == "<none>":
                relation = "missing_side"
            else:
                relation = scope_relation(before, after)
            transition = f"{before_event.get('outcome') if before_event else 'none'}-to-{after_event.get('outcome') if after_event else 'none'}"
            counts[(segment["local_outcome_basis"], transition, relation)] += 1
            rows.append(
                {
                    "agent": agent,
                    "instance_id": instance_id,
                    "resolved": int(resolved),
                    "subtask_index": segment["subtask_index"],
                    "local_outcome": segment["local_outcome"],
                    "local_outcome_basis": segment["local_outcome_basis"],
                    "transition": transition,
                    "scope_relation": relation,
                    "before_scope": before_scope,
                    "after_scope": after_scope,
                }
            )

    summary = [
        {
            "local_outcome_basis": basis,
            "transition": transition,
            "scope_relation": relation,
            "n": n,
        }
        for (basis, transition, relation), n in sorted(counts.items())
    ]
    write_csv(OUT_DIR / "pr_validation_scope_cases.csv", rows)
    write_csv(OUT_DIR / "pr_validation_scope_summary.csv", summary)
    print(f"pr_records={len(rows)}")
    for row in summary:
        if row["local_outcome_basis"].startswith("validation"):
            print(
                f"{row['local_outcome_basis']}: {row['scope_relation']} = {row['n']}"
            )


if __name__ == "__main__":
    main()
