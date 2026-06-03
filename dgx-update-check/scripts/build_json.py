#!/usr/bin/env python3
"""build_json.py — assemble the dgx-update-check data-layer JSON (ADR-4).

Reads raw command outputs from environment variables (set by collect.sh) and emits a
single JSON document on stdout. Pure stdlib (no pip). Does NOT run any commands itself
and has no side-effects — it only parses strings it was handed.
"""
import json
import os
import re
import sys


def env(name, default=""):
    return os.environ.get(name, default)


def try_json(raw):
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


def human_bytes(n):
    if n is None:
        return None
    units = ["B", "KB", "MB", "GB", "TB"]
    f = float(n)
    i = 0
    while f >= 1024 and i < len(units) - 1:
        f /= 1024.0
        i += 1
    if i == 0:
        return f"約 {int(n)} {units[i]}"
    return f"約 {f:.1f} {units[i]}"


# ----- preflight (AC1) -----
pre_reason_raw = env("PRE_REASON", "null")
preflight = {
    "arch": env("ARCH", "unknown"),
    "codename": env("CODENAME", "unknown"),
    "version_id": env("VERSION_ID_VAL", "unknown"),
    "ota_tool": env("OTA_TOOL_PATH") or None,
    "ok": env("PRE_OK", "false") == "true",
    "reason": None if pre_reason_raw == "null" else pre_reason_raw,
}

doc = {
    "schema_version": 1,
    "preflight": preflight,
    "ota": None,
    "apt": None,
    "estimate": None,
    "freshness": None,
    "safety": None,
    "errors": [],
}

# errors list (newline-separated)
errors = [e for e in (env("ERRORS_RAW", "").splitlines()) if e.strip()]
doc["errors"] = errors

# On preflight failure: fail-fast. Leave ota/apt/estimate as null so downstream can see
# nothing was collected (ADR-5). Still emit safety/freshness as null too.
if not preflight["ok"]:
    print(json.dumps(doc, ensure_ascii=False, indent=2))
    sys.exit(0)

# ----- layer 1: OTA (AC2/AC3) -----
ota_avail = try_json(env("OTA_AVAIL_RAW"))
ota_installed = try_json(env("OTA_INSTALLED_RAW"))
ota_torn = try_json(env("OTA_TORN_RAW"))
ota_versions = try_json(env("OTA_VERSIONS_RAW"))  # only present when available==true
doc["ota"] = {
    "is_available": ota_avail,       # {available,name,description,releaseNotesUrl,releaseDate,...}
    "installed_name": ota_installed,  # {name,releaseDate}
    "torn": ota_torn,                 # {name,releaseDate,torn}
    "ota_versions": ota_versions,     # null unless a new generation is available
}

# ----- layer 2: apt parsing (AC4/AC5) -----
upgradable_raw = env("UPGRADABLE_RAW", "")
fullupg_raw = env("FULLUPG_RAW", "")
aptcache_raw = env("APTCACHE_RAW", "")

# (a) parse `apt list --upgradable` -> name -> {ver_to, repos, ver_from}
#     line: name/repo1,repo2 newver arch [upgradable from: oldver]
upg = {}
up_re = re.compile(
    r"^(?P<name>[^/\s]+)/(?P<repos>[^\s]+)\s+(?P<vto>\S+)\s+\S+\s+\[upgradable from:\s*(?P<vfrom>[^\]]+)\]"
)
for line in upgradable_raw.splitlines():
    m = up_re.match(line.strip())
    if not m:
        continue
    repos = [r for r in m.group("repos").split(",") if r]
    upg[m.group("name")] = {
        "ver_to": m.group("vto"),
        "ver_from": m.group("vfrom").strip(),
        "repos": repos,
        "is_security": any("security" in r for r in repos),
    }

# (b) parse `apt-get -s full-upgrade`
#     Inst <name> [oldver] (newver Repo:.../channel, ... [arch])  -> action=install
#     Remv <name> [...]                                            -> action=remove
inst_names = []
remv_names = []
inst_re = re.compile(r"^Inst\s+(\S+)\s+\[(?P<vfrom>[^\]]*)\]\s+\((?P<vto>\S+)\s")
remv_re = re.compile(r"^Remv\s+(\S+)")
inst_meta = {}  # name -> {ver_from, ver_to}
for line in fullupg_raw.splitlines():
    m = inst_re.match(line)
    if m:
        nm = m.group(1)
        inst_names.append(nm)
        inst_meta[nm] = {"ver_from": m.group("vfrom"), "ver_to": m.group("vto")}
        continue
    m = remv_re.match(line)
    if m:
        remv_names.append(m.group(1))

#     phasing-deferred block: the indented line(s) after the phasing header
phasing = []
lines = fullupg_raw.splitlines()
for i, line in enumerate(lines):
    if "deferred due to phasing" in line:
        # following indented lines are package names
        for j in range(i + 1, len(lines)):
            nxt = lines[j]
            if nxt.startswith(" ") or nxt.startswith("\t"):
                phasing.extend(nxt.split())
            else:
                break
        break

#     autoremove candidates appear in the simulation between
#     "no longer required:" and "Use 'apt autoremove'" — extract WITHOUT running autoremove.
autoremove = []
for i, line in enumerate(lines):
    if "no longer required" in line:
        for j in range(i + 1, len(lines)):
            nxt = lines[j]
            if "autoremove" in nxt:  # the "Use 'apt autoremove' ..." terminator
                break
            if nxt.startswith(" ") or nxt.startswith("\t"):
                autoremove.extend(nxt.split())
            else:
                break
        break

# (c) parse apt-cache show blocks -> name -> candidate (first) Size + Description
cache_size = {}
cache_desc = {}
cur = None
seen_size = set()
seen_desc = set()
for line in aptcache_raw.splitlines():
    mk = re.match(r"^===PKG:(.+)===$", line)
    if mk:
        cur = mk.group(1)
        continue
    if cur is None:
        continue
    ms = re.match(r"^Size:\s*(\d+)\s*$", line)
    if ms and cur not in seen_size:   # first Size stanza = candidate version (ADR-6)
        cache_size[cur] = int(ms.group(1))
        seen_size.add(cur)
        continue
    md = re.match(r"^Description(?:-en)?:\s*(.+)$", line)
    if md and cur not in seen_desc:
        cache_desc[cur] = md.group(1).strip()
        seen_desc.add(cur)

# (d) build the unified package list. Source of truth for "what is upgradable" is
#     `apt list --upgradable`; action is decided by the full-upgrade simulation.
packages = []
inst_set = set(inst_names)
phasing_set = set(phasing)
for name in sorted(upg.keys()):
    info = upg[name]
    if name in inst_set:
        action = "install"
    elif name in phasing_set:
        action = "phasing"
    else:
        action = "phasing"  # upgradable but not in Inst and not explicitly listed => held back
    pkg = {
        "name": name,
        "ver_from": inst_meta.get(name, {}).get("ver_from", info["ver_from"]),
        "ver_to": inst_meta.get(name, {}).get("ver_to", info["ver_to"]),
        "repos": info["repos"],
        "is_security": info["is_security"],
        "action": action,
        "size_bytes": cache_size.get(name),  # None if not resolvable (ADR-6)
        "description": cache_desc.get(name),
    }
    packages.append(pkg)

# include any Remv-only packages not in the upgradable list (rare for full-upgrade)
for name in remv_names:
    if name not in upg:
        packages.append({
            "name": name, "ver_from": None, "ver_to": None, "repos": [],
            "is_security": False, "action": "remove",
            "size_bytes": None, "description": cache_desc.get(name),
        })

counts = {
    "install": sum(1 for p in packages if p["action"] == "install"),
    "phasing": sum(1 for p in packages if p["action"] == "phasing"),
    "remove": sum(1 for p in packages if p["action"] == "remove"),
    "new": 0,  # full-upgrade of an up-to-date base introduces no brand-new packages here
}

doc["apt"] = {
    "upgradable_raw": upgradable_raw,
    "packages": packages,
    "phasing_deferred": phasing,
    "autoremove_candidates": autoremove,
    "counts": counts,
}

# ----- estimate (AC8): Σ Size over install packages (ADR-6) -----
dl_total = sum(p["size_bytes"] for p in packages
               if p["action"] == "install" and p["size_bytes"] is not None)
size_unknown = any(p["action"] == "install" and p["size_bytes"] is None for p in packages)

mem_avail_bytes = None
for line in env("MEM_RAW", "").splitlines():
    if line.startswith("Mem:"):
        parts = line.split()
        # free -b columns: total used free shared buff/cache available
        if len(parts) >= 7:
            try:
                mem_avail_bytes = int(parts[6])
            except ValueError:
                mem_avail_bytes = None
        break

def gi(n):
    if n is None:
        return None
    return f"{n / (1024**3):.1f}Gi"

doc["estimate"] = {
    "download_bytes_total": dl_total,
    "download_human": human_bytes(dl_total),
    "size_partial_unknown": size_unknown,  # true if some install pkg had no resolvable Size
    "mem_available_bytes": mem_avail_bytes,
    "mem_available_human": gi(mem_avail_bytes),
}

# ----- freshness (AC10) -----
doc["freshness"] = {
    "apt_index_mtime": env("IDX_MTIME") or None,
    "apt_index_file": env("IDX_FILE") or None,
}

# ----- safety (AC9 / ADR-8) -----
svc = {}
for line in env("SVC_RAW", "").splitlines():
    parts = line.split()
    if len(parts) >= 2:
        svc[parts[0]] = parts[1]
doc["safety"] = {
    "apt_lists_snapshot": env("LISTS_SNAPSHOT") or None,
    "dashboard_services": svc,
}

print(json.dumps(doc, ensure_ascii=False, indent=2))
