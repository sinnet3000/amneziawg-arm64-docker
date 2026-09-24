#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Show (and optionally apply) newer versions of everything versions.env pins.

  ./update.py           report only; exit 10 if something is newer, 0 if up to date
  ./update.py --apply   rewrite versions.env with the newest versions and digests

Checks: amneziawg-go and amneziawg-tools (newest tag of the same major, resolved to its commit),
the golang and alpine base images (newest stable line, resolved to the multi-arch index digest),
and a digest refresh when the pinned tag itself has moved. Needs git, network and Python 3 stdlib only.
After --apply: ./upgrade.sh (rebuild + recreate the container, with rollback), then check a client reconnects.
"""
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

ENV = Path(__file__).resolve().parent / "versions.env"
GH = "https://github.com/amnezia-vpn/{}.git"


def get(url, attempts=3):
    """GET with retry/backoff on transient failures (rate limit, 5xx, network blips)."""
    for i in range(attempts):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "awg-update"}), timeout=30) as r:
                return r.read().decode()
        except urllib.error.HTTPError as err:
            if err.code not in (429, 500, 502, 503, 504) or i == attempts - 1:
                raise
        except urllib.error.URLError:
            if i == attempts - 1:
                raise
        time.sleep(1.5 ** i)


def read_env():
    env = {}
    for line in ENV.read_text().splitlines():
        m = re.match(r"^([A-Z_]+)=(.*)$", line)
        if m:
            env[m.group(1)] = m.group(2)
    return env


def newest_tag(repo, current_tag):
    """Newest vMAJOR.x.y[-n] tag with the same major as current_tag, plus its commit."""
    major = current_tag.lstrip("v").split(".")[0]
    out = subprocess.run(["git", "ls-remote", "--tags", GH.format(repo)], capture_output=True, text=True, check=True).stdout
    shas = {}
    for line in out.splitlines():
        sha, ref = line.split("\t")
        name = ref.removeprefix("refs/tags/")
        peeled = name.endswith("^{}")
        name = name.removesuffix("^{}")
        if peeled or name not in shas:  # peeled (annotated tag) commit wins
            shas[name] = sha

    def key(t):
        nums = re.match(r"^v(\d+)\.(\d+)\.(\d+)(?:-(\d+))?$", t)
        return tuple(int(x or 0) for x in nums.groups()) if nums and nums.group(1) == major else None

    cands = [(key(t), t) for t in shas if key(t)]
    if not cands:
        sys.exit(f"update.py: no v{major}.x.y tag found in {GH.format(repo)}")
    _, tag = max(cands)
    return tag, shas[tag]


def hub_digest(image, tag):
    return json.loads(get(f"https://hub.docker.com/v2/repositories/library/{image}/tags/{tag}"))["digest"]


def newest_go(current):
    """Newest N.M-alpine tag at or above the pinned line, found by asking Docker Hub for each next minor."""
    major, minor = (int(x) for x in current.split("-")[0].split("."))
    best, misses, m = current, 0, minor
    while misses < 2:
        m += 1
        tag = f"{major}.{m}-alpine"
        try:
            hub_digest("golang", tag)
            best, misses = tag, 0
        except urllib.error.HTTPError as err:
            if err.code != 404:
                raise
            misses += 1
    return best


def alpine_candidates():
    """Supported Alpine releases, newest first."""
    rels = json.loads(get("https://alpinelinux.org/releases.json"))["release_branches"]
    today = date.today().isoformat()
    ok = [r for r in rels if re.fullmatch(r"v\d+\.\d+", r["rel_branch"]) and (r.get("branch_date") or "9") <= today
          and (r.get("eol_date") or "0") > today]
    ok.sort(key=lambda r: tuple(int(x) for x in r["rel_branch"][1:].split(".")), reverse=True)
    return [r["rel_branch"][1:] for r in ok]


def go_mod_requires(commit):
    try:
        raw = get(f"https://raw.githubusercontent.com/amnezia-vpn/amneziawg-go/{commit}/go.mod")
        return re.search(r"^go (\d+\.\d+)", raw, re.M).group(1)
    except Exception:
        return None


def main():
    apply = "--apply" in sys.argv[1:]
    cur = read_env()
    new = dict(cur)
    rows = []

    for name, repo, tk, ck in (("amneziawg-go", "amneziawg-go", "AWG_GO_TAG", "AWG_GO_COMMIT"),
                               ("amneziawg-tools", "amneziawg-tools", "AWG_TOOLS_TAG", "AWG_TOOLS_COMMIT")):
        tag, sha = newest_tag(repo, cur[tk])
        new[tk], new[ck] = tag, sha
        rows.append((name, cur[tk], tag, sha != cur[ck] or tag != cur[tk]))

    go_tag = newest_go(cur['GO_IMAGE'].split('@')[0].split(':')[1])
    go_img = "golang:%s@%s" % (go_tag, hub_digest("golang", go_tag))
    cur_go = cur["GO_IMAGE"].split("@")[0].split(":")[1]
    new["GO_IMAGE"] = go_img
    rows.append(("golang image", cur_go, go_tag, go_img != cur["GO_IMAGE"]))

    cur_al = cur["ALPINE_IMAGE"].split("@")[0].split(":")[1]
    ver = lambda v: tuple(int(x) for x in v.split("."))
    for al in alpine_candidates():  # a release can exist before its Docker Hub image does
        al = max(al, cur_al, key=ver)  # never propose going back below the pinned release
        try:
            al_img = "alpine:%s@%s" % (al, hub_digest("alpine", al))
            break
        except urllib.error.HTTPError as err:
            if err.code != 404:
                raise
    else:
        sys.exit("update.py: no supported Alpine release has a Docker Hub image")
    new["ALPINE_IMAGE"] = al_img
    rows.append(("alpine image", cur_al, al, al_img != cur["ALPINE_IMAGE"]))

    need = go_mod_requires(new["AWG_GO_COMMIT"])
    go_ok = not need or tuple(map(int, need.split("."))) <= tuple(int(x) for x in go_tag.split("-")[0].split("."))
    if not go_ok:
        print(f"WARNING: amneziawg-go needs Go {need}, newest golang image is {go_tag}", file=sys.stderr)

    print(f"{'component':<18}{'pinned':<20}{'newest':<20}status")
    changed = False
    for name, have, want, diff in rows:
        status = "up to date" if not diff else ("NEWER" if have != want else "same tag, digest/commit moved")
        changed |= diff
        print(f"{name:<18}{have:<20}{want:<20}{status}")
    if need:
        print(f"(amneziawg-go go.mod requires Go >= {need})")

    if apply and not go_ok:
        # Writing this pin would make the next ./upgrade.sh build fail; refuse instead of warning only.
        print("update.py: refusing --apply until the golang image meets the go.mod requirement", file=sys.stderr)
        return 1
    if not changed:
        print("everything is up to date")
        return 0
    if not apply:
        print("\nrun ./update.py --apply to rewrite versions.env, then ./upgrade.sh")
        return 10
    lines = []
    for line in ENV.read_text().splitlines():
        m = re.match(r"^([A-Z_]+)=", line)
        lines.append(f"{m.group(1)}={new[m.group(1)]}" if m and m.group(1) in new else line)
    ENV.write_text("\n".join(lines) + "\n")
    print("\nversions.env updated. Next: ./upgrade.sh (rebuild + recreate container, rolls back on failure),")
    print("then confirm a client reconnects and commit the change.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (urllib.error.URLError, subprocess.CalledProcessError) as err:
        sys.exit(f"update.py: lookup failed: {err}")
