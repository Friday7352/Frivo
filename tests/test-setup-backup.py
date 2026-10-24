#!/usr/bin/env python3
"""NEW (2.0.0): the backup setup and the uninstaller make (New-FrivoBackup in
installer/Frivo.Setup.psm1), restored by Frivo itself.

  * it's the zip Frivo's own Back up makes: manifest, settings, profiles,
    saved replies with their audio, tag taste
  * API keys are left out unless asked, everything else in config.json kept
  * saved replies are found where Settings > Storage moved them
  * voices you added only when asked
  * Frivo's Restore (Settings > Updates) brings it all back
  * nothing to back up is an error, and no half-written zip is left

Usage:  python3 tests/test-setup-backup.py     (run from the repo root)
Needs:  pwsh (PowerShell 7) and Frivo's Python packages.
"""

import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PWSH = shutil.which("pwsh") or "/opt/pwsh/pwsh"
failures = []


def check(name, condition, got=None):
    print(("  PASS  " if condition else "  FAIL  ") + name + ("" if condition else "   got=%r" % (got,)))
    if not condition:
        failures.append(name)


os.environ["APPDATA"] = tempfile.mkdtemp(prefix="frivo-sb-home-")


def load(tag):
    data = tempfile.mkdtemp(prefix=f"frivo-sb-{tag}-data-")
    os.environ["VOICE_CONSOLE_DATA"] = data
    ws = tempfile.mkdtemp(prefix=f"frivo-sb-{tag}-")
    shutil.copy(os.path.join(ROOT, "app", "app.py"), os.path.join(ws, "app.py"))
    for d in ("static", "templates"):
        shutil.copytree(os.path.join(ROOT, "app", d), os.path.join(ws, d))
    spec = importlib.util.spec_from_file_location(f"frivo_sb_{tag}", os.path.join(ws, "app.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[f"frivo_sb_{tag}"] = mod
    spec.loader.exec_module(mod)
    return mod, data


def backup(data_dir, dest, *flags):
    module = os.path.join(ROOT, "installer", "Frivo.Setup.psm1")
    cmd = (f"Import-Module '{module}' -Force; "
           f"New-FrivoBackup -DataDir '{data_dir}' -Destination '{dest}' -Version '2.0.0' {' '.join(flags)}")
    r = subprocess.run([PWSH, "-NoProfile", "-Command", cmd], capture_output=True, text=True)
    return r.returncode, r.stdout.strip().splitlines()[-1] if r.stdout.strip() else "", r.stderr


# --- an installed Frivo with some of everything ----------------------------
old, old_data = load("old")
old.CFG["elevenlabs_api_key"] = "sk_old_key"
old.CFG["openai_api_key"] = "sk-openai-old"
old.CFG["tag_amount"] = "dramatic"
# Saved replies moved elsewhere in Settings > Storage.
elsewhere = tempfile.mkdtemp(prefix="frivo-sb-bigdrive-")
old.CFG["storage_saved"] = elsewhere
old.save_config(old.CFG)
old.apply_storage()
profiles = old.load_profiles()
profiles.append({"id": "p-miki", "name": "Miki", "persona": "a friend"})
old.save_profiles(profiles)
os.makedirs(old.SAVED_DIR, exist_ok=True)
items = []
for i in range(3):
    sid = f"{i:032x}"
    with open(os.path.join(old.SAVED_DIR, sid + ".mp3"), "wb") as f:
        f.write(b"ID3" + bytes([i]) * 50)
    items.append({"id": sid, "file": sid + ".mp3", "text": f"line {i}", "voiced": f"line {i}",
                  "voice_name": "Rachel", "profile_name": "Miki", "saved_at": 1000 + i})
old.write_saved(items)
old.record_tag_taste(kept=["laughs", "laughs"], removed=["sighs"])
check("(saved replies are outside the data folder)", old.SAVED_DIR.startswith(elsewhere), old.SAVED_DIR)
voice_dir = os.path.join(old_data, "voices", "my-voice")
os.makedirs(voice_dir)
with open(os.path.join(voice_dir, "model.onnx"), "wb") as f:
    f.write(b"\0" * 100)
with open(os.path.join(old_data, "voices", "voices.json"), "w") as f:
    json.dump([{"key": "my-voice", "name": "My voice"}], f)

# NEW (2.0.0): the copy of each browser's preferences Frivo keeps.
with open(os.path.join(old_data, "browser_prefs.json"), "w") as f:
    json.dump({"Windows PC|Chrome": {"prefs": {"voice_console_voice_favorites": "[\"old\"]"}, "updated": "2026-10-01 10:00:00"},
               "Windows PC|Frivo app": {"prefs": {"voice_console_voice_favorites": "[\"alba\",\"rachel\"]",
                                                  "frivo_output_device": "abc"}, "updated": "2026-10-20 09:00:00"}}, f)

dest = tempfile.mkdtemp(prefix="frivo-sb-backups-")
code, path, err = backup(old_data, dest)
check("setup makes a backup", code == 0 and os.path.isfile(path), (code, path, err))
z = zipfile.ZipFile(path)
names = set(z.namelist())
check("named like Frivo's own", os.path.basename(path).startswith("Frivo backup ") and path.endswith(".zip"), path)
check("with the manifest, settings, profiles and saved list",
      {"frivo-backup.json", "data/config.json", "data/profiles.json", "data/saved/saved.json", "browser.json"} <= names,
      sorted(names))
check("and the saved audio, from where Storage put it", all(f"data/saved/{i['file']}" in names for i in items))
check("and tag taste", "data/tag_taste.json" in names)
check("but not the voices", not any(n.startswith("data/voices/") for n in names))
check("every browser's preferences are in it", "data/browser_prefs.json" in names)
check("and the newest one's are what Restore puts in the browser",
      json.loads(z.read("browser.json")) == {"voice_console_voice_favorites": "[\"alba\",\"rachel\"]", "frivo_output_device": "abc"},
      z.read("browser.json"))
cfg = json.loads(z.read("data/config.json"))
check("API keys are blanked", cfg.get("elevenlabs_api_key") == "" and cfg.get("openai_api_key") == "", cfg)
check("everything else in config.json is kept", cfg.get("tag_amount") == "dramatic")
manifest = json.loads(z.read("frivo-backup.json"))
check("the manifest is Frivo's format", manifest.get("format") == 1 and manifest.get("app") == "Frivo"
      and manifest["counts"]["saved"] == 3 and manifest["counts"]["profiles"] >= 1 and manifest["keys"] is False, manifest)
check("no half-written file is left", not any(n.endswith(".partial") for n in os.listdir(dest)), os.listdir(dest))

code, path2, err = backup(old_data, dest, "-IncludeKeys", "-IncludeVoices")
z2 = zipfile.ZipFile(path2)
check("a second one gets its own name", code == 0 and path2 != path, (path, path2))
check("keys included when asked", json.loads(z2.read("data/config.json")).get("elevenlabs_api_key") == "sk_old_key")
check("voices included when asked", "data/voices/my-voice/model.onnx" in z2.namelist()
      and "data/voices/voices.json" in z2.namelist(), sorted(z2.namelist()))

# --- restored by Frivo's own Restore ---------------------------------------
new, new_data = load("new")
c = new.app.test_client()
with open(path, "rb") as f:
    res = c.post("/api/backup/restore", data={"file": (io.BytesIO(f.read()), "b.zip")},
                 content_type="multipart/form-data")
r = res.get_json()
check("Frivo restores it", res.status_code == 200 and r["kind"] == "backup", (res.status_code, r))
check("saved replies and their audio come back", r["saved"] == 3 and all(
    os.path.isfile(os.path.join(new.SAVED_DIR, i["file"])) for i in items), r)
check("profiles and settings come back", any(p.get("id") == "p-miki" for p in new.load_profiles())
      and new.CFG.get("tag_amount") == "dramatic")
check("a blanked key doesn't overwrite anything", not new.CFG.get("elevenlabs_api_key"))
check("favourite voices and audio devices come back to the browser",
      r.get("browser", {}).get("frivo_output_device") == "abc", r.get("browser"))
check("and Frivo keeps every browser's copy again", set(new.load_browser_prefs()) == {"Windows PC|Chrome", "Windows PC|Frivo app"},
      new.load_browser_prefs())
# NEW (2.0.0): a backup made with its keys puts them back, even over a key already here.
new.CFG["elevenlabs_api_key"] = "sk_some_other_key"
new.save_config(new.CFG)
with open(path2, "rb") as f:
    r2 = c.post("/api/backup/restore", data={"file": (io.BytesIO(f.read()), "b.zip")},
                content_type="multipart/form-data").get_json()
check("a backup with keys restores them", new.CFG.get("elevenlabs_api_key") == "sk_old_key"
      and new.CFG.get("openai_api_key") == "sk-openai-old" and r2.get("keys") == 2, (new.CFG.get("elevenlabs_api_key"), r2.get("keys")))
check("this PC's storage folders aren't taken from the backup", not new.CFG.get("storage_saved"), new.CFG.get("storage_saved"))

# --- nothing to back up ----------------------------------------------------
empty = tempfile.mkdtemp(prefix="frivo-sb-empty-")
code, _, err = backup(empty, dest)
check("an empty data folder is an error, not an empty zip", code != 0 and "no Frivo settings" in err, (code, err))

print()
if failures:
    print(f"{len(failures)} failed")
    sys.exit(1)
print("All setup backup checks passed.")
