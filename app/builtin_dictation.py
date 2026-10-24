"""
NEW (2.0.0): built-in dictation.

Live dictation that runs inside Frivo, on the processor of the PC Frivo runs
on: no OpenAI, no Evora, no graphics card. Words appear as you speak.

It uses Moonshine's streaming speech models (moonshine-voice, MIT licensed,
English), run by its own native library with ONNX Runtime. Settings ›
Dictation offers two:

  * Best: Moonshine Streaming Medium, about 270 MB. The most accurate.
  * Fast: Moonshine Streaming Small, about 140 MB. For slower PCs.

The download happens on the PC Frivo runs on, whichever device clicked the
button: the browser only ever sends audio and gets words back. Each file is
checked against the size and CRC32C Moonshine's own catalog gives for it,
and only a complete, checked set is kept.

The model is loaded when someone starts dictating and freed after it has
been idle (15 minutes by default). Everything lives in
<Frivo data>\\builtin_dictation\\; removing it deletes that folder.

How a browser streams to it (app.py has the routes):

  POST /api/dictation/stream             -> {"id"}
  POST /api/dictation/stream/<id>        16 kHz mono 16-bit audio in,
                                         {"lines": [{id, text, complete}]} out
  POST /api/dictation/stream/<id>/stop   -> the final lines

Lines are Moonshine's: it decides where a sentence ends (a pause), marks it
complete, and starts the next.
"""

import array
import os
import shutil
import threading
import time
import uuid

import requests

MODELS = [
    {
        "id": "medium",
        "name": "Best",
        "model": "Moonshine Streaming Medium",
        "arch": "MEDIUM_STREAMING",
        "size": 269_141_623,
        "note": "The most accurate. Words appear as you speak.",
    },
    {
        "id": "small",
        "name": "Fast",
        "model": "Moonshine Streaming Small",
        "arch": "SMALL_STREAMING",
        "size": 142_300_974,
        "note": "Half the size and quicker on a slow PC. A little less accurate.",
    },
]
MODELS_BY_ID = {m["id"]: m for m in MODELS}
DEFAULT_MODEL = "medium"

IDLE_CHOICES = {"5m": 300, "15m": 900, "1h": 3600, "never": 0}
DEFAULT_IDLE = "15m"

SAMPLE_RATE = 16000
STREAM_FORGET_SECONDS = 30      # a stream nobody has sent audio to for this long is closed
MAX_STREAMS = 8                 # at once, across every device
MAX_CHUNK_BYTES = SAMPLE_RATE * 2 * 5   # five seconds of audio in one request is plenty


class DictationError(RuntimeError):
    pass


def _moonshine():
    """The moonshine-voice package, or None. Imported only when needed: it
    loads a native library, and Frivo starts fine without it."""
    try:
        import moonshine_voice
        return moonshine_voice
    except Exception:
        return None


class BuiltinDictation:
    def __init__(self, data_dir, log=print, settings=None):
        self.root = os.path.join(data_dir, "builtin_dictation")
        self.log = log
        # A function returning the current settings: {"model", "idle"}.
        self.settings = settings or (lambda: {})
        self._engine_lock = threading.RLock()   # every call into Moonshine
        self._job_lock = threading.Lock()
        self._job = {"state": "idle"}
        self._cancel = threading.Event()
        self._transcriber = None
        self._loaded_id = None
        self._last_used = 0.0
        self._streams = {}
        self._manifests = {}
        self.on_ready = None                    # called after a download finishes
        threading.Thread(target=self._idle_loop, daemon=True).start()

    # ------------------------------------------------------------------ files

    def manifest(self, model_id):
        """The files a model is made of, with their sizes and checksums, from
        Moonshine's own catalog (built into its library, so no network)."""
        if model_id in self._manifests:
            return self._manifests[model_id]
        ms = _moonshine()
        model = MODELS_BY_ID.get(model_id)
        if ms is None or model is None:
            return None
        from moonshine_voice import download as msdl
        arch = getattr(ms.ModelArch, model["arch"])
        group = msdl._primary_stt_group(msdl.find_model_info("en", arch))
        files = [{"name": f["name"], "url": f.get("url") or f"{group['base_url']}/{f['name']}",
                  "size": f.get("size"), "crc32c": f.get("checksum") if f.get("checksum_type") == "crc32c" else None}
                 for f in group.get("files", [])]
        self._manifests[model_id] = files
        return files

    def model_dir(self, model_id):
        return os.path.join(self.root, "models", model_id)

    def downloaded(self, model_id):
        """Every file there, at its size. (Checksums are checked when it's
        downloaded, not each time this is asked.)"""
        folder = self.model_dir(model_id)
        if not os.path.isfile(os.path.join(folder, ".complete")):
            return False
        try:
            files = self.manifest(model_id)
        except Exception:
            files = None
        if not files:
            return os.path.isdir(folder)
        for f in files:
            path = os.path.join(folder, f["name"])
            if not os.path.isfile(path):
                return False
            if isinstance(f["size"], int) and f["size"] >= 0 and os.path.getsize(path) != f["size"]:
                return False
        return True

    def chosen_model(self):
        wanted = (self.settings() or {}).get("model") or DEFAULT_MODEL
        if wanted not in MODELS_BY_ID:
            wanted = DEFAULT_MODEL
        if self.downloaded(wanted):
            return wanted
        for model in MODELS:   # the one that's there, if the chosen one isn't
            if self.downloaded(model["id"]):
                return model["id"]
        return wanted

    # ----------------------------------------------------------------- status

    def supported(self):
        return _moonshine() is not None

    def problem(self):
        """Why it can't take dictation right now, or ""."""
        if not self.supported():
            return "Built-in dictation needs a part Frivo's setup installs. Run setup again (Repair)."
        if not self.downloaded(self.chosen_model()):
            return "Built-in dictation isn't downloaded."
        return ""

    def status(self):
        with self._job_lock:
            job = dict(self._job)
        models = [dict(m, downloaded=self.downloaded(m["id"])) for m in MODELS]
        free = None
        try:
            os.makedirs(self.root, exist_ok=True)
            free = shutil.disk_usage(self.root).free
        except OSError:
            pass
        settings = self.settings() or {}
        with self._engine_lock:
            loaded = self._loaded_id if self._transcriber is not None else ""
        return {
            "supported": self.supported(),
            "models": models,
            "model": settings.get("model") or DEFAULT_MODEL,
            "active_model": self.chosen_model(),
            "loaded_model": loaded,
            "idle": settings.get("idle") or DEFAULT_IDLE,
            "problem": self.problem(),
            "job": job,
            "free_bytes": free,
            "folder": self.root,
            "streams": len(self._streams),
        }

    # --------------------------------------------------------------- download

    def start_download(self, model_id, again=False):
        model = MODELS_BY_ID.get(model_id)
        if not model:
            raise DictationError("Pick Best or Fast.")
        if not self.supported():
            raise DictationError(self.problem())
        with self._job_lock:
            if self._job.get("state") in ("checking", "model"):
                raise DictationError("A download is already running.")
            need = model["size"]
            try:
                os.makedirs(self.root, exist_ok=True)
                free = shutil.disk_usage(self.root).free
            except OSError:
                free = None
            if free is not None and free < need + 200_000_000:
                raise DictationError(f"There isn't room on the drive: it needs about {need / 1e6:.0f} MB "
                                     f"and {free / 1e6:.0f} MB is free.")
            self._cancel.clear()
            self._job = {"state": "checking", "model": model_id, "done": 0, "total": need, "error": ""}
        threading.Thread(target=self._download, args=(model, again), daemon=True).start()

    def cancel_download(self):
        self._cancel.set()

    def _set_job(self, **changes):
        with self._job_lock:
            self._job.update(changes)

    def _download(self, model, again=False):
        staging = None
        try:
            files = self.manifest(model["id"])
            if not files:
                raise DictationError("Moonshine's list of model files couldn't be read.")
            total = sum(f["size"] for f in files if isinstance(f["size"], int)) or model["size"]
            self._set_job(state="model", total=total, done=0)
            os.makedirs(os.path.join(self.root, "models"), exist_ok=True)
            staging = os.path.join(self.root, "models", f".{model['id']}-{uuid.uuid4().hex[:8]}")
            os.makedirs(staging)
            done = 0
            for f in files:
                done = self._fetch(f, os.path.join(staging, f["name"]), done)
            with open(os.path.join(staging, ".complete"), "w", encoding="utf-8") as fh:
                fh.write(time.strftime("%Y-%m-%d %H:%M:%S"))
            # Swapped in whole, so a half-download is never mistaken for a model.
            target = self.model_dir(model["id"])
            with self._engine_lock:
                if self._loaded_id == model["id"]:
                    self._unload_locked()
                if os.path.isdir(target):
                    shutil.rmtree(target, ignore_errors=True)
                os.replace(staging, target)
            staging = None
            if self.on_ready:
                try:
                    self.on_ready()
                except Exception as e:
                    self.log(f"Built-in dictation: after the download: {e!r}")
            self._set_job(state="done", done=total)
            self.log(f"Built-in dictation: {model['model']} ready")
        except DictationError as e:
            # Nothing half-downloaded is left behind, before anyone is told.
            if staging and os.path.isdir(staging):
                shutil.rmtree(staging, ignore_errors=True)
            if self._cancel.is_set():
                self._set_job(state="cancelled", error="")
            else:
                self._set_job(state="error", error=str(e))
                self.log(f"Built-in dictation: download failed: {e}")
        except Exception as e:
            if staging and os.path.isdir(staging):
                shutil.rmtree(staging, ignore_errors=True)
            self._set_job(state="error", error=f"The download failed ({e}).")
            self.log(f"Built-in dictation: download failed: {e!r}")
        finally:
            if staging and os.path.isdir(staging):
                shutil.rmtree(staging, ignore_errors=True)

    def _fetch(self, f, target, done):
        """One file, counted into the progress, then checked."""
        try:
            with requests.get(f["url"], stream=True, timeout=(15, 60), headers={"User-Agent": "Frivo"}) as r:
                if r.status_code != 200:
                    raise DictationError(f"Moonshine's download site answered {r.status_code} for {f['name']}.")
                with open(target, "wb") as out:
                    for chunk in r.iter_content(chunk_size=64 * 1024):
                        if self._cancel.is_set():
                            raise DictationError("Cancelled.")
                        if chunk:
                            out.write(chunk)
                            done += len(chunk)
                            self._set_job(done=done)
        except requests.RequestException as e:
            raise DictationError(f"Moonshine's download site couldn't be reached from the PC Frivo runs on ({e.__class__.__name__}).")
        if isinstance(f["size"], int) and f["size"] >= 0 and os.path.getsize(target) != f["size"]:
            raise DictationError(f"{f['name']} didn't download completely. Try again.")
        if f["crc32c"]:
            try:
                from moonshine_voice.download_file import crc32c_file
                actual = crc32c_file(target)
            except Exception:
                actual = None
            if actual is not None and actual != f["crc32c"]:
                raise DictationError(f"{f['name']} doesn't match its checksum, so it wasn't kept. Try again.")
        return done

    def remove(self, model_id=None):
        """One model, or everything (model_id None)."""
        with self._engine_lock:
            if model_id is None or self._loaded_id == model_id:
                self._close_streams_locked()
                self._unload_locked()
            path = self.model_dir(model_id) if model_id else self.root
            if os.path.isdir(path):
                shutil.rmtree(path, ignore_errors=True)
            if os.path.isdir(path):
                raise DictationError("Some of its files are still in use. Restart Frivo, then remove it.")

    # ----------------------------------------------------------------- engine

    def _load_locked(self):
        """The transcriber for the chosen model, loading it if needed."""
        model_id = self.chosen_model()
        if self._transcriber is not None and self._loaded_id == model_id:
            return self._transcriber
        if not self.downloaded(model_id):
            raise DictationError(self.problem() or "Built-in dictation isn't downloaded.")
        ms = _moonshine()
        if ms is None:
            raise DictationError(self.problem())
        self._close_streams_locked()
        self._unload_locked()
        started = time.perf_counter()
        arch = getattr(ms.ModelArch, MODELS_BY_ID[model_id]["arch"])
        self._transcriber = ms.Transcriber(self.model_dir(model_id), arch, update_interval=0.2)
        self._loaded_id = model_id
        self.log(f"Built-in dictation: loaded {MODELS_BY_ID[model_id]['model']} "
                 f"in {time.perf_counter() - started:.1f}s")
        return self._transcriber

    def _unload_locked(self):
        if self._transcriber is not None:
            try:
                self._transcriber.close()
            except Exception:
                pass
        self._transcriber = None
        self._loaded_id = None

    def unload(self):
        with self._engine_lock:
            self._close_streams_locked()
            self._unload_locked()

    def _idle_loop(self):
        while True:
            time.sleep(20)
            try:
                self.idle_check()
            except Exception as e:
                self.log(f"Built-in dictation: idle check: {e!r}")

    def idle_check(self, now=None):
        """Closes streams nobody is sending to, and frees the model once
        nothing has used it for the idle time."""
        now = now or time.time()
        with self._engine_lock:
            for sid in [s for s, v in self._streams.items() if now - v["last"] > STREAM_FORGET_SECONDS]:
                self._close_stream_locked(sid)
            idle = IDLE_CHOICES.get((self.settings() or {}).get("idle") or DEFAULT_IDLE, 900)
            if (self._transcriber is not None and idle and not self._streams
                    and now - self._last_used > idle):
                self._unload_locked()
                self.log("Built-in dictation: freed its memory after being idle")

    # ---------------------------------------------------------------- streams

    @staticmethod
    def _floats(pcm):
        """16-bit little-endian mono PCM -> floats, as Moonshine takes them."""
        samples = array.array("h")
        samples.frombytes(pcm[: len(pcm) - (len(pcm) % 2)])
        if samples.itemsize != 2:
            raise DictationError("Unexpected audio format.")
        import sys
        if sys.byteorder != "little":
            samples.byteswap()
        return [s / 32768.0 for s in samples]

    @staticmethod
    def _lines(transcript):
        out = []
        for line in (getattr(transcript, "lines", None) or []):
            text = (line.text or "").strip()
            out.append({"id": str(line.line_id), "text": text, "complete": bool(line.is_complete)})
        return out

    def open_stream(self):
        with self._engine_lock:
            if len(self._streams) >= MAX_STREAMS:
                oldest = min(self._streams, key=lambda s: self._streams[s]["last"])
                self._close_stream_locked(oldest)
            transcriber = self._load_locked()
            # Updates are asked for once per request (add_audio below), not
            # by Moonshine's own timer as audio arrives: that would run a
            # second pass for the same audio. The browser waits for each
            # answer before sending more, so a slow PC gets bigger, fewer
            # passes instead of falling behind.
            stream = transcriber.create_stream(update_interval=1e6)
            stream.start()
            sid = uuid.uuid4().hex
            self._streams[sid] = {"stream": stream, "last": time.time(), "model": self._loaded_id}
            self._last_used = time.time()
            return sid

    def _get_stream_locked(self, sid):
        entry = self._streams.get(sid)
        if entry is None or entry["model"] != self._loaded_id:
            raise DictationError("That dictation ended. Start it again.")
        return entry

    def add_audio(self, sid, pcm):
        """Adds audio and returns the lines so far."""
        if len(pcm) > MAX_CHUNK_BYTES:
            raise DictationError("Too much audio at once.")
        samples = self._floats(pcm)
        from moonshine_voice.transcriber import MOONSHINE_FLAG_FORCE_UPDATE
        with self._engine_lock:
            entry = self._get_stream_locked(sid)
            stream = entry["stream"]
            if samples:
                stream.add_audio(samples, SAMPLE_RATE)
            transcript = stream.update_transcription(MOONSHINE_FLAG_FORCE_UPDATE if samples else 0)
            entry["last"] = self._last_used = time.time()
            return self._lines(transcript)

    def stop_stream(self, sid, pcm=b""):
        """The last of the audio, then the final lines."""
        samples = self._floats(pcm) if pcm else []
        with self._engine_lock:
            entry = self._streams.get(sid)
            if entry is None:
                return []
            stream = entry["stream"]
            try:
                if samples and entry["model"] == self._loaded_id:
                    stream.add_audio(samples, SAMPLE_RATE)
                transcript = stream.stop() if entry["model"] == self._loaded_id else None
                lines = self._lines(transcript) if transcript is not None else []
            finally:
                self._close_stream_locked(sid)
            self._last_used = time.time()
            return [dict(l, complete=True) for l in lines]

    def _close_stream_locked(self, sid):
        entry = self._streams.pop(sid, None)
        if entry is None:
            return
        try:
            entry["stream"].close()
        except Exception:
            pass

    def _close_streams_locked(self):
        for sid in list(self._streams):
            self._close_stream_locked(sid)

    def transcribe(self, samples):
        """A whole clip at once (floats, 16 kHz): the Test button."""
        with self._engine_lock:
            transcriber = self._load_locked()
            transcript = transcriber.transcribe_without_streaming(samples, SAMPLE_RATE)
            self._last_used = time.time()
            return " ".join(l["text"] for l in self._lines(transcript) if l["text"])


def sample_clip(seconds=6.0):
    """A few seconds of speech that comes with Moonshine, at 16 kHz, for Test."""
    ms = _moonshine()
    if ms is None:
        return None
    folder = os.path.join(os.path.dirname(ms.__file__), "assets")
    for name in ("beckett.wav", "two_cities.wav"):
        path = os.path.join(folder, name)
        if not os.path.isfile(path):
            continue
        samples, rate = ms.load_wav_file(path)
        if samples and isinstance(samples[0], (list, tuple)):
            samples = [s[0] for s in samples]
        if rate != SAMPLE_RATE:
            ratio = rate / SAMPLE_RATE
            samples = [samples[int(i * ratio)] for i in range(int(len(samples) / ratio))]
        return samples[: int(SAMPLE_RATE * seconds)]
    return None
