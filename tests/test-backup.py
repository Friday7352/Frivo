#!/usr/bin/env python3
"""NEW (1.5.0): back up and restore.

  * a backup holds settings (keys only when asked), profiles, saved replies
    with their audio, tag taste and what the browser sent
  * restoring it on a fresh Frivo brings all of that back; this server's
    Ollama / Evora addresses and a key it already has are kept
  * restoring twice adds nothing twice
  * a zip of an older Frivo's data folder restores too (one folder deep)
  * the "Export all" zip of saved replies restores as saved replies
  * paths that climb out of the zip are ignored; a non-zip is refused

Usage:  python3 tests/test-backup.py     (run from the repo root)
"""

import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
failures = []


def check(name, condition, got=None):
    print(("  PASS  " if condition else "  FAIL  ") + name + ("" if condition else "   got=%r" % (got,)))
    if not condition:
        failures.append(name)


os.environ["APPDATA"] = tempfile.mkdtemp(prefix="frivo-bk-home-")


def load(tag):
    data = tempfile.mkdtemp(prefix=f"frivo-bk-{tag}-data-")
    os.environ["VOICE_CONSOLE_DATA"] = data
    ws = tempfile.mkdtemp(prefix=f"frivo-bk-{tag}-")
    shutil.copy(os.path.join(ROOT, "app", "app.py"), os.path.join(ws, "app.py"))
    for d in ("static", "templates"):
        if os.path.isdir(os.path.join(ROOT, "app", d)):
            shutil.copytree(os.path.join(ROOT, "app", d), os.path.join(ws, d))
    spec = importlib.util.spec_from_file_location(f"frivo_bk_{tag}", os.path.join(ws, "app.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[f"frivo_bk_{tag}"] = mod
    spec.loader.exec_module(mod)
    return mod, data


old, old_data = load("old")
# --- the old server: some of everything ------------------------------------
old.CFG["elevenlabs_api_key"] = "sk_old_key"
old.CFG["ollama_url"] = "http://old-pc:11434"
old.CFG["tag_amount"] = "dramatic"
old.save_config(old.CFG)
profiles = old.load_profiles()
profiles.append({"id": "p-miki", "name": "Miki", "persona": "a friend"})
old.save_profiles(profiles)
os.makedirs(old.SAVED_DIR, exist_ok=True)
items = []
for i in range(3):
    sid = f"{i:032x}"
    with open(os.path.join(old.SAVED_DIR, sid + ".mp3"), "wb") as f:
        f.write(b"ID3" + bytes([i]) * 50)
    items.append({"id": sid, "file": sid + ".mp3", "text": f"line {i}", "voiced": f"[laughs] line {i}",
                  "voice_name": "Rachel", "profile_name": "Miki", "saved_at": 1000 + i})
old.write_saved(items)
old.record_tag_taste(kept=["laughs", "laughs"], removed=["sighs"])

c = old.app.test_client()
browser = {"voice_console_voice_favorites": json.dumps(["v1", "v2"]), "frivo_your_tags": json.dumps(["giggles"]),
           "voice_console_session": "skip-me", "not_ours": "x"}
res = c.post("/api/backup", json={"browser": browser})
check("backup downloads", res.status_code == 200 and res.mimetype == "application/zip", res.status_code)
z = zipfile.ZipFile(io.BytesIO(res.data))
names = set(z.namelist())
check("backup has manifest, settings, profiles, saved list", {"frivo-backup.json", "data/config.json",
      "data/profiles.json", "data/saved/saved.json"} <= names, sorted(names))
check("backup has the saved audio", all(f"data/saved/{i['file']}" in names for i in items))
check("backup has tag taste", "data/tag_taste.json" in names)
cfg_in = json.loads(z.read("data/config.json"))
check("keys left out by default", "elevenlabs_api_key" not in cfg_in)
b = json.loads(z.read("browser.json"))
check("browser data kept, session and others skipped", set(b) == {"voice_console_voice_favorites", "frivo_your_tags"}, b)
manifest = json.loads(z.read("frivo-backup.json"))
check("manifest counts", manifest["counts"]["saved"] == 3 and manifest["counts"]["profiles"] >= 1, manifest)
backup_plain = res.data
res = c.post("/api/backup", json={"include_keys": True, "browser": browser})
with_keys = res.data
check("keys included when asked", json.loads(zipfile.ZipFile(io.BytesIO(with_keys)).read("data/config.json"))
      .get("elevenlabs_api_key") == "sk_old_key")

# --- the new server: fresh --------------------------------------------------
new, new_data = load("new")
new.CFG["ollama_url"] = "http://new-pc:11434"
new.CFG["elevenlabs_api_key"] = "sk_new_key"
new.save_config(new.CFG)
c2 = new.app.test_client()
res = c2.post("/api/backup/restore", data={"file": (io.BytesIO(with_keys), "Frivo backup.zip")},
              content_type="multipart/form-data")
r = res.get_json()
check("restore ok", res.status_code == 200 and r["kind"] == "backup", (res.status_code, r))
check("saved replies restored", r["saved"] == 3 and len(new.load_saved()) == 3, r)
check("saved audio copied", all(os.path.isfile(os.path.join(new.SAVED_DIR, i["file"])) for i in items))
check("profile restored", any(p.get("id") == "p-miki" for p in new.load_profiles()))
check("setting restored", new.CFG.get("tag_amount") == "dramatic", new.CFG.get("tag_amount"))
check("this server's Ollama address kept", new.CFG["ollama_url"] == "http://new-pc:11434", new.CFG["ollama_url"])
check("key already here kept", new.CFG["elevenlabs_api_key"] == "sk_new_key")
on_disk = json.load(open(new.CONFIG_PATH))
check("settings written to disk", on_disk.get("tag_amount") == "dramatic")
check("tag taste restored", new.load_tag_taste().get("laughs", {}).get("kept") == 2, new.load_tag_taste())
check("browser data returned to the page", "voice_console_voice_favorites" in r["browser"], r["browser"])

res = c2.post("/api/backup/restore", data={"file": (io.BytesIO(backup_plain), "again.zip")},
              content_type="multipart/form-data")
r = res.get_json()
check("restoring again adds no saved replies", r["saved"] == 0 and len(new.load_saved()) == 3, r)
check("restoring again doesn't duplicate profiles",
      sum(1 for p in new.load_profiles() if p.get("id") == "p-miki") == 1)

# --- a zip of an older Frivo's data folder ----------------------------------
third, _ = load("third")
buf = io.BytesIO()
with zipfile.ZipFile(buf, "w") as zf:
    for root, _, files in os.walk(old_data):
        for name in files:
            full = os.path.join(root, name)
            zf.write(full, "app/" + os.path.relpath(full, old_data).replace(os.sep, "/"))
    zf.writestr("app/../../evil.txt", "nope")
c3 = third.app.test_client()
res = c3.post("/api/backup/restore", data={"file": (io.BytesIO(buf.getvalue()), "app.zip")},
              content_type="multipart/form-data")
r = res.get_json()
check("data-folder zip restores", res.status_code == 200 and r["kind"] == "folder" and r["saved"] == 3, r)
check("data-folder zip brings the key when none here", third.CFG.get("elevenlabs_api_key") == "sk_old_key")
check("climbing paths ignored", not os.path.exists(os.path.join(os.path.dirname(third.DATA_DIR), "evil.txt")))

# --- the Export all zip -----------------------------------------------------
res = c.get("/api/saved/export.zip")
check("export.zip made", res.status_code == 200, res.status_code)
fourth, _ = load("fourth")
c4 = fourth.app.test_client()
res = c4.post("/api/backup/restore", data={"file": (io.BytesIO(res.data), "Frivo saved.zip")},
              content_type="multipart/form-data")
r = res.get_json()
got = fourth.load_saved()
check("Export all zip restores as saved replies", r and r["kind"] == "saved-export" and r["saved"] == 3, r)
check("their text comes back", sorted(i["voiced"] for i in got) == sorted(i["voiced"] for i in items),
      [i.get("voiced") for i in got])

# --- refused ----------------------------------------------------------------
res = c4.post("/api/backup/restore", data={"file": (io.BytesIO(b"not a zip"), "x.zip")},
              content_type="multipart/form-data")
check("non-zip refused", res.status_code == 400 and "zip" in res.get_json()["error"])
buf = io.BytesIO()
with zipfile.ZipFile(buf, "w") as zf:
    zf.writestr("hello.txt", "hi")
res = c4.post("/api/backup/restore", data={"file": (io.BytesIO(buf.getvalue()), "x.zip")},
              content_type="multipart/form-data")
check("unrelated zip refused", res.status_code == 400)
res = c4.post("/api/backup/restore")
check("no file refused", res.status_code == 400)

print()
print("FAILED: %d" % len(failures) if failures else "All passed.")
sys.exit(1 if failures else 0)
