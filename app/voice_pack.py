"""
NEW (1.5.0): the free voices included with Frivo.

Six Piper voices, all free to share: Kristin, Cori and Alba (female), and
John, Joe and Norman (male). They're small (32-63 MB each), they run on
the CPU with hardly any load (well under a tenth of one core while a reply
plays), and they need no graphics card, account or key.

Setup runs this once with Frivo's own Python, right after it installs
Frivo's libraries, so the voices are there before Frivo first starts:

    python voice_pack.py install [--dir DIR]   get anything missing or damaged
    python voice_pack.py check   [--dir DIR]   say what's there (exit 0 = all ready)

Each download is checked against the size and SHA-256 written below before
anything is unpacked, and each model again after it's unpacked. The voices
go in voices\\piper next to app.py, inside the install folder. Updates and
Repair leave that folder alone, and only fetch a voice again if it's missing
or damaged. Uninstalling removes it with the rest of Frivo. Frivo itself
never downloads anything: it only reads this folder.

The files come from the sherpa-onnx project's GitHub releases, which
publishes the Piper voices in the form Frivo's speech library (sherpa-onnx)
reads. Only the standard library is used here, so this runs before, and
without, anything else Frivo installs.
"""

import argparse
import hashlib
import json
import os
import shutil
import sys
import tarfile
import tempfile
import time
import urllib.request

RELEASE = "https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/"
DEFAULT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "voices", "piper")
ESPEAK = "espeak-ng-data"            # pronunciation data, the same for every voice
ESPEAK_STAMP = ".frivo-complete"     # written last, so a half-unpacked copy is never used
USER_AGENT = "Frivo-Setup"

# Only voices whose recordings may be shared are here. Others (Ryan, Lessac,
# HFC, Amy, Jenny) are licensed for non-commercial use only, or unclearly.
VOICES = [
    {"key": "kristin", "name": "Kristin", "gender": "female", "culture": "en-US", "region": "United States",
     "archive": "vits-piper-en_US-kristin-medium-fp16.tar.bz2", "archive_size": 35953946,
     "archive_sha256": "2b38aaeb0d81a5cfaf24254f518ca265f95803519d8139487f5d7b1a95f1b9c3",
     "model": "en_US-kristin-medium.onnx", "model_size": 32619229,
     "model_sha256": "62094b69e111b2bd47d290669e19d5f4425d1b4895995b056049cdb9a2b3c74a",
     "license": "Public domain (recordings from LibriVox)"},
    {"key": "cori", "name": "Cori", "gender": "female", "culture": "en-GB", "region": "United Kingdom",
     "archive": "vits-piper-en_GB-cori-medium-fp16.tar.bz2", "archive_size": 35960750,
     "archive_sha256": "96b954d1d0450f281cd780ddb199bcda65200e40dd25ee57c455f8f7ca2cc48d",
     "model": "en_GB-cori-medium.onnx", "model_size": 32619229,
     "model_sha256": "7e861b5d62d2f5379e344ff71c4ca09b529e934fba73f16e64b7003592d66f6c",
     "license": "Public domain (recordings from LibriVox)"},
    {"key": "alba", "name": "Alba", "gender": "female", "culture": "en-GB", "region": "United Kingdom",
     "archive": "vits-piper-en_GB-alba-medium-fp16.tar.bz2", "archive_size": 35917308,
     "archive_sha256": "9e15cd62613c5c9da8305034c6e430282f20c1f93be009857edee368d4b978c0",
     "model": "en_GB-alba-medium.onnx", "model_size": 31951609,
     "model_sha256": "ee5d6345a5abda2de2aeb9d08705e7762b168470023723d995fdb6a475df996c",
     "license": "CC BY 4.0. Recordings: University of Edinburgh, https://datashare.ed.ac.uk/handle/10283/3270"},
    {"key": "john", "name": "John", "gender": "male", "culture": "en-US", "region": "United States",
     # The full-size file: the half-size one for John doesn't load. Same speed.
     "archive": "vits-piper-en_US-john-medium.tar.bz2", "archive_size": 67249181,
     "archive_sha256": "d90362cfa48e429d3096f644785184446145b6e38216f2eaf4c0601b8aad5a36",
     "model": "en_US-john-medium.onnx", "model_size": 63152970,
     "model_sha256": "4fb0dd1c34ec1add55e71a1ea84166f798922867bd4609e0a094ce4a285f940e",
     "license": "Public domain (recordings from LibriVox)"},
    {"key": "joe", "name": "Joe", "gender": "male", "culture": "en-US", "region": "United States",
     # The full-size file, as for John: the half-size one doesn't load.
     "archive": "vits-piper-en_US-joe-medium.tar.bz2", "archive_size": 67169394,
     "archive_sha256": "261b903a1fb2ce621e2b5b14233cd41223c3b9f9590f896c11daee4df22d9bd3",
     "model": "en_US-joe-medium.onnx", "model_size": 63149198,
     "model_sha256": "5c262f54364ad8c75e5c536c2fba9a54a7375b605fcb14a3876013247a1caa6c",
     "license": "CC0 (Nabu Casa voice datasets)"},
    {"key": "norman", "name": "Norman", "gender": "male", "culture": "en-US", "region": "United States",
     "archive": "vits-piper-en_US-norman-medium-fp16.tar.bz2", "archive_size": 35897612,
     "archive_sha256": "996fdc26bf48233e33c8fd5c65d5701daa6ae4ee152957d61d6621530020fcdd",
     "model": "en_US-norman-medium.onnx", "model_size": 32619229,
     "model_sha256": "28956352784992b7686ae067bc8bd5167fb2c8afff46498dddcb37d33e5ee333",
     "license": "Public domain (recordings from LibriVox)"},
]
VOICES_BY_KEY = {v["key"]: v for v in VOICES}
DOWNLOAD_MB = round(sum(v["archive_size"] for v in VOICES) / 1_000_000)


def voice_paths(voice, root=DEFAULT_DIR):
    folder = os.path.join(root, voice["key"])
    return {"folder": folder, "model": os.path.join(folder, "model.onnx"),
            "tokens": os.path.join(folder, "tokens.txt"), "espeak": os.path.join(root, ESPEAK)}


def espeak_ready(root=DEFAULT_DIR):
    return os.path.isfile(os.path.join(root, ESPEAK, ESPEAK_STAMP))


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def voice_ready(voice, root=DEFAULT_DIR, deep=False):
    """True when this voice can be used. deep also checks the model's SHA-256."""
    paths = voice_paths(voice, root)
    if not (espeak_ready(root) and os.path.isfile(paths["tokens"]) and os.path.isfile(paths["model"])):
        return False
    if os.path.getsize(paths["model"]) != voice["model_size"]:
        return False
    return not deep or _sha256(paths["model"]) == voice["model_sha256"]


def status(root=DEFAULT_DIR):
    """[{key, name, ready}] — the quick check Frivo makes when it lists voices."""
    return [{"key": v["key"], "name": v["name"], "ready": voice_ready(v, root)} for v in VOICES]


def _download(voice, dest, log):
    url = RELEASE + voice["archive"]
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    digest, got = hashlib.sha256(), 0
    with urllib.request.urlopen(request, timeout=60) as resp, open(dest, "wb") as out:
        for chunk in iter(lambda: resp.read(1 << 20), b""):
            out.write(chunk)
            digest.update(chunk)
            got += len(chunk)
    if got != voice["archive_size"] or digest.hexdigest() != voice["archive_sha256"]:
        raise RuntimeError(f"{voice['archive']} didn't download correctly (it doesn't match the expected file).")


def _safe_members(archive, top):
    """The members under top/, as (member, path below top). Nothing that could escape."""
    for member in archive.getmembers():
        name = member.name.replace("\\", "/")
        if not name.startswith(top + "/"):
            continue
        rel = name[len(top) + 1:]
        parts = [p for p in rel.split("/") if p not in ("", ".")]
        if not parts or ".." in parts or os.path.isabs(rel) or ":" in parts[0]:
            continue
        if member.isfile() or member.isdir():
            yield member, "/".join(parts)



def _new_staging(parent, prefix):
    """
    NEW (1.6.1): an empty folder to unpack into, inside `parent`.

    Not tempfile.mkdtemp: on Windows, Python 3.12.4 and later create that
    folder readable by only the account that made it, and files moved out
    of it keep that. Setup runs as an administrator, so Frivo's voices ended
    up unreadable by Frivo itself ("Load model ... failed: system error
    number 13"). A plain folder takes its permissions from `parent`.
    """
    import uuid
    os.makedirs(parent, exist_ok=True)
    while True:
        path = os.path.join(parent, prefix + uuid.uuid4().hex[:10])
        try:
            os.mkdir(path)
            return path
        except FileExistsError:
            continue


def _move_into(source_dir, dest_dir):
    """
    Moves every file from source_dir into dest_dir, replacing what's there.
    File by file rather than swapping the folder: a folder can't be swapped
    for another on Windows while it exists, and a file left from before is
    simply overwritten.
    """
    for here, _dirs, files in os.walk(source_dir):
        target_dir = os.path.join(dest_dir, os.path.relpath(here, source_dir))
        os.makedirs(target_dir, exist_ok=True)
        for name in files:
            os.replace(os.path.join(here, name), os.path.join(target_dir, name))


def _unpack(voice, archive_path, root, log):
    top = voice["archive"][: -len(".tar.bz2")]
    paths = voice_paths(voice, root)
    staging = _new_staging(root, ".unpack-")   # CHANGED (1.6.1): not mkdtemp
    try:
        need_espeak = not espeak_ready(root)
        with tarfile.open(archive_path, "r:bz2") as archive:
            for member, rel in _safe_members(archive, top):
                if rel == voice["model"]:
                    target = os.path.join(staging, "voice", "model.onnx")
                elif rel in ("tokens.txt", "MODEL_CARD"):
                    target = os.path.join(staging, "voice", rel)
                elif need_espeak and rel.split("/")[0] == ESPEAK:
                    target = os.path.join(staging, *rel.split("/"))
                else:
                    continue
                if member.isdir():
                    os.makedirs(target, exist_ok=True)
                    continue
                os.makedirs(os.path.dirname(target), exist_ok=True)
                source = archive.extractfile(member)
                with source, open(target, "wb") as out:
                    shutil.copyfileobj(source, out)
        model = os.path.join(staging, "voice", "model.onnx")
        if not os.path.isfile(model) or _sha256(model) != voice["model_sha256"]:
            raise RuntimeError(f"{voice['name']}'s model wasn't in the download as expected.")
        if need_espeak:
            unpacked = os.path.join(staging, ESPEAK)
            if not os.path.isdir(unpacked):
                raise RuntimeError("The pronunciation data wasn't in the download.")
            _move_into(unpacked, paths["espeak"])
            with open(os.path.join(paths["espeak"], ESPEAK_STAMP), "w", encoding="utf-8") as f:
                f.write(voice["archive"])
        # The model goes last, so a voice is never "ready" with old tokens.
        staged = os.path.join(staging, "voice")
        model = os.path.join(staged, "model.onnx")
        os.makedirs(paths["folder"], exist_ok=True)
        for name in ("tokens.txt", "MODEL_CARD"):
            if os.path.isfile(os.path.join(staged, name)):
                os.replace(os.path.join(staged, name), os.path.join(paths["folder"], name))
        os.replace(model, paths["model"])
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def write_credits(root=DEFAULT_DIR):
    lines = ["Frivo's free voices are Piper voices (https://github.com/OHF-Voice/piper1-gpl),",
             "as published by the sherpa-onnx project (https://github.com/k2-fsa/sherpa-onnx).", ""]
    for v in VOICES:
        lines.append(f"{v['name']} ({v['culture']}, {v['gender']}): {v['license']}")
    lines += ["", f"{ESPEAK}: eSpeak NG pronunciation data, GPL-3.0-or-later (https://github.com/espeak-ng/espeak-ng)."]
    with open(os.path.join(root, "CREDITS.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def install(root=DEFAULT_DIR, log=print, retries=2):
    """
    Gets every voice that's missing or damaged. Returns the keys that still
    aren't ready (empty means all six are). Never raises for one bad voice.
    """
    os.makedirs(root, exist_ok=True)
    failed = []
    for voice in VOICES:
        if voice_ready(voice, root, deep=True):
            log(f"{voice['name']}: already installed.")
            continue
        for attempt in range(1, retries + 2):
            fd, archive_path = tempfile.mkstemp(prefix=".download-", suffix=".tar.bz2", dir=root)
            os.close(fd)
            try:
                log(f"{voice['name']}: downloading ({round(voice['archive_size'] / 1_000_000)} MB)...")
                _download(voice, archive_path, log)
                _unpack(voice, archive_path, root, log)
                log(f"{voice['name']}: ready.")
                break
            except Exception as e:
                log(f"{voice['name']}: attempt {attempt} failed: {e}")
                if attempt > retries:
                    failed.append(voice["key"])
                else:
                    time.sleep(2 * attempt)
            finally:
                try:
                    os.remove(archive_path)
                except OSError:
                    pass
    write_credits(root)
    return failed


def main(argv=None):
    parser = argparse.ArgumentParser(description="Frivo's free voices.")
    parser.add_argument("action", choices=["install", "check"])
    parser.add_argument("--dir", default=DEFAULT_DIR)
    args = parser.parse_args(argv)
    if args.action == "check":
        rows = status(args.dir)
        for row in rows:
            print(f"{row['name']}: {'ready' if row['ready'] else 'missing'}")
        return 0 if all(r["ready"] for r in rows) else 1
    failed = install(args.dir, log=lambda m: print(m, flush=True))
    if failed:
        print("Not installed: " + ", ".join(VOICES_BY_KEY[k]["name"] for k in failed)
              + ". Frivo still works; run setup again (Repair) to try again.", flush=True)
        return 1
    print("All free voices are installed.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
