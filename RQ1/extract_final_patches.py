#!/usr/bin/env python3
"""Recover the final observable product-source patch from each trajectory."""

import csv
import difflib
import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TRAJ_ROOT = ROOT / "swe_verified_claude4_traj"
OUT_DIR = ROOT / "RQ1" / "discordance" / "final_patches"
META = ROOT / "pre" / "pre-12" / "metadata" / "pre12_reference_patch_meta.csv"
sys.path.insert(0, str(TRAJ_ROOT))

from scripts import pre12_recompute as pre  # noqa: E402


def diff_from_events(events, ref):
    states = {}
    order = []
    for event in events:
        if not pre.is_patch_edit(event, ref):
            continue
        path = pre.norm_path(event.get("path", ""))
        old = str(event.get("old_str") or "")
        new = str(event.get("new_str") or "")
        if not path or not (old or new):
            continue
        if path not in states:
            states[path] = {"old": old, "new": new}
            order.append(path)
        else:
            states[path]["new"] = new
    chunks = []
    for path in order:
        old = states[path]["old"].splitlines(keepends=True)
        new = states[path]["new"].splitlines(keepends=True)
        if old == new:
            continue
        chunks.extend(
            difflib.unified_diff(
                old,
                new,
                fromfile=f"a/{path}",
                tofile=f"b/{path}",
            )
        )
    return "".join(chunks)


def patches_from_file_context(nodes, ref):
    for node in reversed(nodes):
        patches = []
        for file_info in (node.get("file_context") or {}).get("files", []):
            patch = file_info.get("patch")
            file_path = pre.norm_path(file_info.get("file_path", ""))
            if patch and file_path and pre.is_source_like(file_path, ref):
                patches.append(patch.rstrip())
        if patches:
            return "\n".join(patches)
    return ""


def lingxi_final_diff(text):
    """Return the complete diff from Lingxi's last explicit final-patch block."""
    markers = list(
        re.finditer(r"(?im)^\s*(?:the\s+)?final\s+patch(?:\s+is)?\s*:\s*$", text)
    )
    for marker in reversed(markers):
        candidate = text[marker.end() :]
        start = re.search(r"(?m)^diff --git ", candidate)
        if not start:
            continue
        candidate = candidate[start.start() :]
        end = re.search(r"(?m)^</problem_solver(?:\s+\d+)?>", candidate)
        return candidate[: end.start()].rstrip() if end else candidate.rstrip()
    return ""


def lingxi_patch(path, events, ref):
    text = path.read_text(encoding="utf-8", errors="replace")
    patch = lingxi_final_diff(text)
    return patch or diff_from_events(events, ref)


def moatless_patch(path, events, ref):
    obj = json.loads(path.read_text(encoding="utf-8"))
    final_path = pre.moatless_final_path(obj.get("nodes", []))
    patch = patches_from_file_context(final_path, ref)
    if patch:
        return patch
    return diff_from_events(events, ref)


def openhands_patch(path, events, ref):
    obj = json.loads(path.read_text(encoding="utf-8"))
    candidates = []
    for message in obj:
        if message.get("role") != "tool":
            continue
        text = pre.text_from_content(message.get("content"))
        start = text.find("diff --git ")
        if start >= 0:
            candidate = text[start:]
            end = candidate.find("\n[The command completed")
            candidates.append(candidate[:end] if end >= 0 else candidate)
    if candidates:
        return candidates[-1].rstrip()
    return diff_from_events(events, ref)


def observed_patch(agent, path, events, ref):
    if agent == "lingxi":
        return lingxi_patch(path, events, ref), "trajectory_diff"
    if agent == "moatless":
        obj = json.loads(path.read_text(encoding="utf-8"))
        final_path = pre.moatless_final_path(obj.get("nodes", []))
        patch = patches_from_file_context(final_path, ref)
        if patch:
            return patch, "trajectory_file_context"
        patch = diff_from_events(events, ref)
        return patch, "event_reconstruction" if patch else "none"
    obj = json.loads(path.read_text(encoding="utf-8"))
    candidates = []
    for message in obj:
        if message.get("role") != "tool":
            continue
        text = pre.text_from_content(message.get("content"))
        start = text.find("diff --git ")
        if start >= 0:
            candidate = text[start:]
            end = candidate.find("\n[The command completed")
            candidates.append(candidate[:end] if end >= 0 else candidate)
    if candidates:
        return candidates[-1].rstrip(), "trajectory_diff"
    patch = diff_from_events(events, ref)
    return patch, "event_reconstruction" if patch else "none"


def patch_files(patch):
    files = set()
    for line in patch.splitlines():
        if line.startswith("diff --git "):
            match = re.search(r" b/(\S+)", line)
            if match:
                files.add(pre.norm_path(match.group(1)))
        elif line.startswith("+++ b/"):
            files.add(pre.norm_path(line[6:].strip()))
    return sorted(files)


def write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main():
    refs = pre.load_reference(TRAJ_ROOT, Path("/tmp/pre12_final_patch"))
    extractors = {
        "lingxi": lingxi_patch,
        "moatless": moatless_patch,
        "openhands": openhands_patch,
    }
    rows = []
    for agent, instance_id, resolved, events, _ in pre.load_all(TRAJ_ROOT, refs):
        suffix = ".traj" if agent == "lingxi" else ".json"
        raw = TRAJ_ROOT / "data" / "raw" / agent / f"{instance_id}{suffix}"
        patch, method = observed_patch(agent, raw, events, refs[instance_id])
        files = patch_files(patch)
        if patch:
            target = OUT_DIR / agent / f"{instance_id}.patch"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(patch.rstrip() + "\n", encoding="utf-8")
        rows.append(
            {
                "agent": agent,
                "instance_id": instance_id,
                "resolved": int(resolved),
                "available": int(bool(patch)),
                "method": method,
                "patch_files": ";".join(files),
                "reference_files": ";".join(sorted(refs[instance_id]["patch_files"])),
                "file_overlap": len(set(files) & refs[instance_id]["patch_files"]),
                "patch_lines": len(patch.splitlines()),
            }
        )
    write_csv(OUT_DIR / "manifest.csv", rows)
    for agent in extractors:
        subset = [row for row in rows if row["agent"] == agent]
        print(f"{agent}: {sum(row['available'] for row in subset)}/{len(subset)}")


if __name__ == "__main__":
    main()
