#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OFFICIAL="$ROOT/data/official"
RAW="$ROOT/data/raw"
TMP="$ROOT/data/official/tmp"

mkdir -p "$OFFICIAL/results" "$OFFICIAL/metadata" "$OFFICIAL/manifests" "$TMP"
mkdir -p "$RAW/lingxi" "$RAW/moatless" "$RAW/openhands"

BASE_GH="https://raw.githubusercontent.com/SWE-bench/experiments/main/evaluation/verified"
S3_BASE="https://swe-bench-submissions.s3.amazonaws.com"

curl_fetch() {
  local url="$1"
  local out="$2"
  mkdir -p "$(dirname "$out")"
  curl -L -f -sS --retry 8 --retry-all-errors --connect-timeout 20 --max-time 180 -o "$out" "$url"
}

download_official_files() {
  local agent="$1"
  local submission="$2"
  echo "[official] $agent metadata/results"
  curl_fetch "$BASE_GH/$submission/metadata.yaml" "$OFFICIAL/metadata/$agent.yaml"
  curl_fetch "$BASE_GH/$submission/results/results.json" "$OFFICIAL/results/$agent.json"
}

list_s3_prefix() {
  local agent="$1"
  local prefix="$2"
  local page=1
  local token=""
  local xml="$TMP/${agent}_page_${page}.xml"

  : > "$OFFICIAL/manifests/$agent.keys"

  while true; do
    if [[ -z "$token" ]]; then
      curl_fetch "$S3_BASE/?list-type=2&prefix=$prefix" "$xml"
    else
      curl_fetch "$S3_BASE/?list-type=2&prefix=$prefix&continuation-token=$token" "$xml"
    fi

    python3 - "$xml" "$OFFICIAL/manifests/$agent.keys" <<'PY'
import html
import re
import sys
from pathlib import Path

xml_path = Path(sys.argv[1])
out_path = Path(sys.argv[2])
text = xml_path.read_text(encoding="utf-8", errors="replace")
keys = [html.unescape(k) for k in re.findall(r"<Key>(.*?)</Key>", text)]
with out_path.open("a", encoding="utf-8") as f:
    for key in keys:
        f.write(key + "\n")
PY

    local truncated
    truncated="$(python3 - "$xml" <<'PY'
import re
import sys
text = open(sys.argv[1], encoding="utf-8", errors="replace").read()
m = re.search(r"<IsTruncated>(.*?)</IsTruncated>", text)
print(m.group(1).strip().lower() if m else "false")
PY
)"
    if [[ "$truncated" != "true" ]]; then
      break
    fi

    token="$(python3 - "$xml" <<'PY'
import re
import sys
import urllib.parse
text = open(sys.argv[1], encoding="utf-8", errors="replace").read()
m = re.search(r"<NextContinuationToken>(.*?)</NextContinuationToken>", text)
if not m:
    raise SystemExit("Missing NextContinuationToken")
print(urllib.parse.quote(m.group(1), safe=""))
PY
)"
    page=$((page + 1))
    xml="$TMP/${agent}_page_${page}.xml"
  done
}

build_manifest_urls() {
  local agent="$1"
  local mode="$2"

  python3 - "$agent" "$mode" "$OFFICIAL/manifests/$agent.keys" "$OFFICIAL/manifests/$agent.tsv" "$OFFICIAL/manifests/$agent.urls" "$RAW" "$S3_BASE" <<'PY'
import sys
from pathlib import Path

agent, mode, keys_path, tsv_path, urls_path, raw_root, s3_base = sys.argv[1:]
keys = [line.strip() for line in Path(keys_path).read_text(encoding="utf-8").splitlines() if line.strip()]

rows = []
for key in keys:
    if agent == "lingxi":
        if not key.endswith(".traj"):
            continue
        instance_id = Path(key).name[:-5]
        local_rel = f"data/raw/{agent}/{instance_id}.traj"
    elif agent == "openhands":
        if not key.endswith(".json"):
            continue
        instance_id = Path(key).name[:-5]
        local_rel = f"data/raw/{agent}/{instance_id}.json"
    elif agent == "moatless":
        if not key.endswith("/trajectory.json"):
            continue
        parts = key.split("/")
        instance_id = parts[-2]
        local_rel = f"data/raw/{agent}/{instance_id}.json"
    else:
        raise SystemExit(f"Unknown agent: {agent}")

    url = f"{s3_base}/{key}"
    rows.append((instance_id, key, url, local_rel))

rows.sort(key=lambda x: x[0])

Path(tsv_path).write_text(
    "instance_id\ts3_key\turl\tlocal_path\n"
    + "\n".join("\t".join(row) for row in rows)
    + "\n",
    encoding="utf-8",
)
Path(urls_path).write_text(
    "\n".join(f"{url}\t{local_rel}" for instance_id, _key, url, local_rel in rows)
    + "\n",
    encoding="utf-8",
)
print(f"{agent}: {len(rows)} trajectory files")
PY
}

download_from_urls() {
  local agent="$1"
  local urls_file="$OFFICIAL/manifests/$agent.urls"
  local total
  total="$(wc -l < "$urls_file" | tr -d ' ')"
  local jobs="${JOBS:-16}"
  local pending="$TMP/${agent}_pending.tsv"

  echo "[download] $agent trajectories ($total files)"
  python3 - "$urls_file" "$pending" "$ROOT" "$agent" <<'PY'
import sys
from pathlib import Path

urls_file = Path(sys.argv[1])
pending = Path(sys.argv[2])
root = Path(sys.argv[3])
agent = sys.argv[4]
rows = []
for line in urls_file.read_text(encoding="utf-8").splitlines():
    if not line.strip():
        continue
    url, out = line.split("\t", 1)
    out = str(root / "data" / "raw" / agent / Path(out).name)
    if not Path(out).is_file() or Path(out).stat().st_size == 0:
        rows.append((url, out))
pending.write_text("\n".join(f"{url}\t{out}" for url, out in rows) + ("\n" if rows else ""), encoding="utf-8")
print(len(rows))
PY
  local pending_count
  pending_count="$(wc -l < "$pending" | tr -d ' ')"
  echo "  pending: $pending_count, jobs: $jobs"
  if [[ "$pending_count" == "0" ]]; then
    return
  fi

  xargs -d $'\n' -a "$pending" -P "$jobs" -L 1 bash -c '
    set -euo pipefail
    line="$1"
    url="${line%%	*}"
    out="${line#*	}"
    tmp="${out}.part"
    mkdir -p "$(dirname "$out")"
    curl -L -f -sS --retry 8 --retry-all-errors --connect-timeout 20 --max-time 180 -o "$tmp" "$url"
    mv "$tmp" "$out"
  ' _
}

verify_counts() {
  echo "[verify]"
  python3 - "$ROOT" <<'PY'
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
expected = {
    "lingxi": ("*.traj", 500),
    "moatless": ("*.json", 500),
    "openhands": ("*.json", 500),
}
ok = True
for agent, (pattern, n_expected) in expected.items():
    raw_dir = root / "data" / "raw" / agent
    files = sorted(raw_dir.glob(pattern))
    manifest = root / "data" / "official" / "manifests" / f"{agent}.tsv"
    results = root / "data" / "official" / "results" / f"{agent}.json"
    print(f"{agent}: raw={len(files)} manifest_lines={sum(1 for _ in manifest.open(encoding='utf-8')) - 1} results_exists={results.exists()}")
    if len(files) != n_expected:
        ok = False
if not ok:
    raise SystemExit(1)
PY
}

main() {
  download_official_files "lingxi" "20250720_Lingxi-v1.5_claude-4-sonnet-20250514"
  download_official_files "moatless" "20250611_moatless_claude-4-sonnet-20250514"
  download_official_files "openhands" "20250524_openhands_claude_4_sonnet"

  list_s3_prefix "lingxi" "verified/20250720_Lingxi-v1.5_claude-4-sonnet-20250514/trajs/"
  list_s3_prefix "moatless" "verified/20250611_moatless_claude-4-sonnet-20250514/trajs/"
  list_s3_prefix "openhands" "verified/20250524_openhands_claude_4_sonnet/trajs/"

  build_manifest_urls "lingxi" "flat_traj"
  build_manifest_urls "moatless" "nested_json"
  build_manifest_urls "openhands" "flat_json"

  download_from_urls "lingxi"
  download_from_urls "moatless"
  download_from_urls "openhands"

  verify_counts
}

main "$@"
