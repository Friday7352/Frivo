#!/usr/bin/env python3
"""NEW (updates): Frivo's half of in-app updates, against the real app.py.

What the page is offered and what it may ask for, driven through Flask's
test client with GitHub replaced by tests/fixtures/github-releases.json:

  * which releases count, newest first — and that this is exactly the list
    the updater task (Frivo.Update.psm1) reads from the same fixture, so
    the browser cannot offer what the task will refuse
  * the chip: a newer release, unless skipped; "Skip this version" only
    silences that version
  * Earlier versions: older than this Frivo, never below oldest_rollback
  * Install: refuses the installed version, anything below the floor,
    anything without a fingerprint, a second install while one runs, and
    a copy that cannot update itself; otherwise writes request.json for
    the task and starts it
  * following an install: queued, then the task's own status, and a
    request nobody picks up is reported instead of waited on for ever
  * the automatic-check switch saves itself and survives a reload

Usage:  python3 tests/test-updates.py     (run from the repo root)
Needs:  pwsh or powershell for the cross-check; skipped without it.
"""

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURE = os.path.join(ROOT, "tests", "fixtures", "github-releases.json")
POLICY = os.path.join(ROOT, "installer", "update-policy.json")

failures = []


def check(name, condition, got=None):
    print(("  PASS  " if condition else "  FAIL  ") + name
          + ("" if condition else "   got=%s" % (got,)))
    if not condition:
        failures.append(name)


def load_app():
    """Import app.py from a copy, so the test never writes into the repo."""
    workspace = tempfile.mkdtemp(prefix="frivo-updates-")
    target = os.path.join(workspace, "app.py")
    shutil.copy(os.path.join(ROOT, "app", "app.py"), target)
    spec = importlib.util.spec_from_file_location("frivo_app_updates", target)
    module = importlib.util.module_from_spec(spec)
    sys.modules["frivo_app_updates"] = module
    spec.loader.exec_module(module)
    return module, workspace


mod, WORKSPACE = load_app()
client = mod.app.test_client()
PROGRAM_DATA = tempfile.mkdtemp(prefix="frivo-programdata-")
with open(FIXTURE, encoding="utf-8") as handle:
    SAMPLE = json.load(handle)

# GitHub, Windows and the task, replaced. Each records what it was asked.
calls = {"fetch": 0, "watcher": [], "task": []}
network = {"up": True}


def fake_fetch(policy):
    calls["fetch"] += 1
    if not network["up"]:
        raise OSError("no network")
    return mod.parse_release_list(SAMPLE, policy)


support = {"value": {"ok": True, "mode": "task", "reason": ""}}

mod.update_policy_path = lambda: POLICY
mod.fetch_releases = fake_fetch
mod.update_support = lambda refresh=False: dict(support["value"])
mod.update_folder = lambda: os.path.join(PROGRAM_DATA, "Frivo", "Updates")
mod._spawn_update_watcher = lambda request_id: calls["watcher"].append(request_id)
mod._start_update_task = lambda mode: calls["task"].append(mode)
os.makedirs(mod.update_folder(), exist_ok=True)


def reset(version="1.4.0"):
    """Known state before every case."""
    mod.APP_VERSION = version
    mod.CFG["update_auto_check"] = True
    mod.CFG["update_skipped"] = ""
    with mod.UPDATE_LOCK:
        mod.UPDATE_STATE.update({"releases": None, "latest": None, "checked_at": None,
                                 "error": None, "pending": None, "support": None})
    for name in os.listdir(mod.update_folder()):
        os.remove(os.path.join(mod.update_folder(), name))
    calls["watcher"].clear()
    calls["task"].clear()
    network["up"] = True
    support["value"] = {"ok": True, "mode": "task", "reason": ""}


def write_status(**fields):
    with open(os.path.join(mod.update_folder(), "status.json"), "w", encoding="utf-8") as handle:
        json.dump(fields, handle)


policy = mod.load_update_policy(POLICY)

print("--- versions ---")
check('"v1.4.0" is 1.4.0', mod.parse_version("v1.4.0") == (1, 4, 0))
check('"1.4" is 1.4.0', mod.parse_version("1.4") == (1, 4, 0))
check('"nightly" is not a version', mod.parse_version("nightly") is None)
check('"1.4.0.1" is not a version (three parts, like the task)', mod.parse_version("1.4.0.1") is None)
check('"../1.4.0" is not a version', mod.parse_version("../1.4.0") is None)
check("a number is not a version string", mod.parse_version(140) is None)

print()
print("--- policy ---")
check("read from installer/update-policy.json", policy and policy["repository"] == "Friday7352/Frivo", policy)
check("oldest version to go back to", policy["oldest_rollback"] == (1, 4, 0), policy["oldest_rollback"])
bad = os.path.join(WORKSPACE, "bad-policy.json")
with open(bad, "w") as handle:
    json.dump({"repository": "../evil", "asset": "FrivoSetup.exe", "oldest_rollback": "1.4.0"}, handle)
check("a repository that is not owner/name is refused", mod.load_update_policy(bad) is None)

print()
print("--- the release list ---")
releases = mod.parse_release_list(SAMPLE, policy)
versions = [r["version"] for r in releases]
check("installable releases, newest first, each once", versions == ["1.5.0", "1.4.5", "1.4.0", "1.3.0", "1.1.0"], versions)
first = releases[0]
check("a version listed twice keeps the first GitHub lists", first["sha256"] == "b" * 64, first["sha256"])
check("no digest, no fingerprint", releases[1]["sha256"] is None)
check("a release page off github.com is replaced", releases[1]["page_url"] == policy["releases_page"], releases[1]["page_url"])

# The browser must not offer what the task will refuse. Same fixture, read
# by Frivo.Update.psm1 — the version, the fingerprint and the size must all
# agree, release for release.
shell = shutil.which("pwsh") or shutil.which("powershell")
if shell:
    script = (
        "Import-Module '%s' -Force; "
        "$p = Get-FrivoUpdatePolicy -Path '%s'; "
        "$r = ConvertFrom-FrivoReleaseList -Json (Get-Content -LiteralPath '%s' -Raw) -Policy $p; "
        "@($r | ForEach-Object { [ordered]@{ version = $_.VersionText; sha256 = $_.Sha256; size = $_.Size; "
        "page_url = $_.PageUrl; download_url = $_.DownloadUrl } }) | ConvertTo-Json -Compress"
    ) % (os.path.join(ROOT, "installer", "Frivo.Update.psm1"), POLICY, FIXTURE)
    out = subprocess.run([shell, "-NoProfile", "-Command", script], capture_output=True, text=True)
    try:
        theirs = json.loads(out.stdout)
    except ValueError:
        theirs = out.stdout + out.stderr
    ours = [{k: r[k] for k in ("version", "sha256", "size", "page_url", "download_url")} for r in releases]
    check("app.py and the updater task read the same releases the same way", theirs == ours,
          json.dumps(theirs)[:400])
else:
    print("  SKIP  no PowerShell; the cross-check with the updater task was not run")

print()
print("--- the chip ---")
reset("1.4.0")
mod.check_for_updates()
data = client.get("/api/updates").get_json()
check("a newer release is announced", data["notify"] and data["notify"]["version"] == "1.5.0", data["notify"])
check("with its notes and page", "Updates" in data["notify"]["notes"] and data["notify"]["page_url"].endswith("/tag/v1.5.0"))
check("and whether it can be verified", data["notify"]["verifiable"] is True)
check("the download URL and fingerprint stay on the server", "download_url" not in data["notify"] and "sha256" not in data["notify"])
client.post("/api/updates/settings", json={"skip": "1.5.0"})
data = client.get("/api/updates").get_json()
check("Skip this version silences it", data["notify"] is None and data["latest"]["version"] == "1.5.0", data)
check("and is saved as that version", mod.CFG["update_skipped"] == "1.5.0", mod.CFG["update_skipped"])
mod.CFG["update_skipped"] = "1.4.9"
data = client.get("/api/updates").get_json()
check("skipping an older version does not silence a newer one", data["notify"] and data["notify"]["version"] == "1.5.0")

reset("1.5.0")
mod.check_for_updates()
data = client.get("/api/updates").get_json()
check("the newest version has nothing to announce", data["latest"] is None and data["notify"] is None, data["latest"])
check("but records that it checked", bool(data["checked_at"]) and data["error"] is None)

reset("1.4.0")
network["up"] = False
mod.check_for_updates()
data = client.get("/api/updates").get_json()
check("being offline is recorded, not raised", data["error"] and data["latest"] is None, data["error"])

print()
print("--- the switch ---")
reset()
res = client.post("/api/updates/settings", json={"auto_check": False})
check("turning the automatic check off saves", res.status_code == 200 and mod.CFG["update_auto_check"] is False)
with open(mod.CONFIG_PATH, encoding="utf-8") as handle:
    saved = json.load(handle)
check("to config.json, so it survives a restart", saved.get("update_auto_check") is False, saved.get("update_auto_check"))
check("and the answer says so", res.get_json()["auto_check"] is False)
saved_path = mod.CONFIG_PATH
mod.CONFIG_PATH = os.path.join(WORKSPACE, "no-such-config.json")
fresh = mod.load_config()
mod.CONFIG_PATH = saved_path
check("a fresh config checks automatically and skips nothing",
      fresh.get("update_auto_check") is True and fresh.get("update_skipped") == "", fresh.get("update_auto_check"))

print()
print("--- earlier versions ---")
reset("1.5.0")
data = client.get("/api/updates/earlier").get_json()
earlier = [r["version"] for r in data["releases"]]
check("older than this, newest first, never below the floor", earlier == ["1.4.5", "1.4.0"], earlier)
check("says where the floor is", data["oldest_rollback"] == "1.4.0")
reset("1.4.0")
data = client.get("/api/updates/earlier").get_json()
check("at the floor there is nothing to go back to", data["releases"] == [], data["releases"])
reset("1.5.0")
network["up"] = False
res = client.get("/api/updates/earlier")
check("offline, it says so instead of an empty list", res.status_code == 502, res.status_code)

print()
print("--- install ---")


def install(version):
    res = client.post("/api/updates/install", json={"version": version})
    return res.status_code, res.get_json()


reset("1.4.0")
code, body = install("1.4.0")
check("the installed version is refused", code == 409 and "already installed" in body["error"], body)
code, body = install("1.3.0")
check("below the floor is refused, and says why", code == 409 and "oldest version that can update itself" in body["error"], body)
code, body = install("1.4.5")
check("a release with no fingerprint is refused", code == 409 and "fingerprint" in body["error"], body)
code, body = install("1.4.1")
check("a pre-release is not a release", code == 409 and "not a release" in body["error"], body)
code, body = install("latest")
check("nonsense is refused", code == 400, body)
check("none of that reached the task", calls["task"] == [] and calls["watcher"] == [], calls)

support["value"] = {"ok": False, "mode": None, "reason": "This copy of Frivo runs from its source folder."}
code, body = install("1.5.0")
check("a copy that cannot update itself says why", code == 409 and "source folder" in body["error"], body)

reset("1.4.0")
network["up"] = False
code, body = install("1.5.0")
check("offline, nothing is requested", code == 502 and calls["task"] == [], body)

reset("1.4.0")
code, body = install("v1.5")
check("an update is accepted", code == 200 and body["ok"] and body["version"] == "1.5.0" and body["kind"] == "update", body)
request_path = os.path.join(mod.update_folder(), "request.json")
with open(request_path, encoding="utf-8") as handle:
    request = json.load(handle)
check("request.json carries the id and the version, and nothing else to trust",
      request["id"] == body["id"] and request["version"] == "1.5.0", request)
check("no temporary request files are left", sorted(os.listdir(mod.update_folder())) == ["request.json"],
      os.listdir(mod.update_folder()))
check("the watcher is started for this request", calls["watcher"] == [body["id"]], calls["watcher"])
time.sleep(0.2)
check("and the task", calls["task"] == ["task"], calls["task"])
code2, body2 = install("1.5.0")
check("a second install while one is queued is refused", code2 == 409 and "already running" in body2["error"], body2)

job = client.get("/api/updates/job").get_json()
check("before the task answers, the job is queued", job["job"]["state"] == "queued" and job["job"]["target"] == "1.5.0", job)
write_status(id="someone-else", state="downloading", received=1, total=2)
job = client.get("/api/updates/job").get_json()
check("a status about another request is not this one", job["job"]["state"] == "queued", job)
write_status(id=body["id"], state="downloading", received=1048576, total=2275000, restart=False,
             message="Downloading", version="1.5.0", kind="update")
job = client.get("/api/updates/job").get_json()
check("then the task's own progress", job["job"]["state"] == "downloading" and job["job"]["received"] == 1048576, job)
check("with the running version, so the page can tell when it changed", job["current"] == "1.4.0")
write_status(id=body["id"], state="failed", message="The download failed: timed out", restart=False)
job = client.get("/api/updates/job").get_json()
check("a failure is passed on with the task's reason", job["job"]["state"] == "failed" and "timed out" in job["job"]["message"], job)
code3, body3 = install("1.5.0")
check("after a failure, trying again is allowed", code3 == 200, body3)

reset("1.5.0")
code, body = install("1.4.0")
check("going back is accepted, and called that", code == 200 and body["kind"] == "rollback", body)

reset("1.4.0")
code, body = install("1.5.0")
with mod.UPDATE_LOCK:
    mod.UPDATE_STATE["pending"]["requested_at"] -= mod.UPDATE_PICKUP_SECONDS + 1
job = client.get("/api/updates/job").get_json()
check("a request nobody picks up is reported, not waited on", job["job"]["state"] == "failed"
      and "did not start" in job["job"]["message"], job)

reset("1.4.0")
code, body = install("1.5.0")
with mod.UPDATE_LOCK:
    mod.UPDATE_STATE["pending"]["error"] = "Windows did not give the updater permission to run."
job = client.get("/api/updates/job").get_json()
check("a declined permission prompt is reported", job["job"]["state"] == "failed" and "permission" in job["job"]["message"], job)

print()
print("--- the page ---")
with open(os.path.join(ROOT, "app", "templates", "index.html"), encoding="utf-8") as handle:
    page = handle.read()
for marker in ("updateChip", "updateOverlay", "checkUpdatesRow", "updateAutoToggle", 'data-page="earlier-versions"'):
    check("index.html has %s" % marker, marker in page)
with open(os.path.join(ROOT, "app", "static", "app.js"), encoding="utf-8") as handle:
    js = handle.read()
check("the automatic-check switch saves itself", '"/api/updates/settings"' in js)
diag = client.get("/diagnose").get_data(as_text=True)
check("/diagnose says how this copy would update", "Updates:" in diag)

print()
if failures:
    print("%d update check(s) failed." % len(failures))
    sys.exit(1)
print("All update checks passed.")
