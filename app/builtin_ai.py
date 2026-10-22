"""
NEW (1.6.0): the built-in AI.

For anyone without OpenAI or Ollama: one button in Settings > Providers
downloads a small AI and Frivo runs it itself, on the processor. No
Ollama, no account, no key, nothing else to install.

What one click does:

  1. Downloads the engine: llama.cpp's own build of llama-server for this
     PC (about 25 MB), from llama.cpp's releases on GitHub. The release is
     fixed (ENGINE_TAG) so every Frivo gets the build it was tested with,
     and the file is checked against the SHA-256 GitHub publishes for it
     before anything is unpacked.
  2. Downloads the model you picked (MODELS): a Qwen 3.5 model, Apache 2.0
     licensed, from Hugging Face, checked against the SHA-256 Hugging Face
     publishes for it.
  3. Starts the engine on this PC only (127.0.0.1), at below-normal
     priority so VRChat and everything else stay smooth, with a share of
     the processor's cores.

It's started when a reply needs it and stopped after it has been idle
(an hour by default), which gives the memory back. Frivo talks to it the
same way it talks to OpenAI.

Everything lives in <Frivo data>\\builtin_ai\\. Removing it deletes that
folder.
"""

import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import zipfile

import requests

ENGINE_TAG = "b11790"
ENGINE_REPO = "ggml-org/llama.cpp"
ENGINE_ASSETS = {
    # sys.platform: the build to download (CPU only: no graphics card)
    "win32": f"llama-{ENGINE_TAG}-bin-win-cpu-x64.zip",
    "linux": f"llama-{ENGINE_TAG}-bin-ubuntu-x64.tar.gz",
}
ENGINE_EXE = "llama-server.exe" if sys.platform == "win32" else "llama-server"
MODEL_ALIAS = "frivo-builtin"

MODELS = [
    {
        "id": "small",
        "name": "Small",
        "model": "Qwen 3.5 2B",
        "repo": "unsloth/Qwen3.5-2B-GGUF",
        "file": "Qwen3.5-2B-Q4_K_M.gguf",
        "size": 1_280_835_840,
        "memory_gb": 2.5,
        "note": "Quick on most PCs. Fine for Clean up; replies are simple.",
    },
    {
        "id": "better",
        "name": "Better",
        "model": "Qwen 3.5 4B",
        "repo": "unsloth/Qwen3.5-4B-GGUF",
        "file": "Qwen3.5-4B-Q4_K_M.gguf",
        "size": 2_740_937_888,
        "memory_gb": 4.5,
        "note": "Noticeably better replies and personas. About twice as slow.",
    },
]
MODELS_BY_ID = {m["id"]: m for m in MODELS}

IDLE_CHOICES = {"15m": 900, "1h": 3600, "4h": 14400, "never": 0}
CONTEXT_TOKENS = 4096
START_TIMEOUT = 180          # loading a model from a slow disk
HF_API = "https://huggingface.co/api/models/{repo}?blobs=true"
HF_FILE = "https://huggingface.co/{repo}/resolve/main/{file}"
GH_RELEASE_API = "https://api.github.com/repos/{repo}/releases/tags/{tag}"
GH_DOWNLOAD = "https://github.com/{repo}/releases/download/{tag}/{asset}"


class BuiltinAIError(RuntimeError):
    """Something the person should be told, in words."""


def default_threads():
    """Half the processor's cores, between 2 and 8: quick replies, with
    plenty left for VRChat."""
    cores = os.cpu_count() or 4
    return max(2, min(8, cores // 2))


class BuiltinAI:
    def __init__(self, data_dir, log=print, settings=None):
        self.root = os.path.join(data_dir, "builtin_ai")
        self.log = log
        # A function returning the current settings: model id, idle choice, threads.
        self.settings = settings or (lambda: {})
        self._lock = threading.RLock()        # the process
        self._job_lock = threading.Lock()
        self._job = {"state": "idle"}
        self._cancel = threading.Event()
        self._proc = None
        self._port = None
        self._model_id = None
        self._last_used = 0.0
        self._log_file = None
        self.on_ready = None                  # called after a download finishes
        self._job_object = None               # NEW (1.6.1): Windows: the engine dies with Frivo
        threading.Thread(target=self._idle_loop, daemon=True).start()
        # NEW (1.6.1): an engine left running by a Frivo that was closed
        # (or killed by an update) still holds its files: stop it.
        threading.Thread(target=self.kill_strays, daemon=True).start()

    # ------------------------------------------------------------------ paths

    @property
    def engine_dir(self):
        return os.path.join(self.root, f"engine-{ENGINE_TAG}")

    def engine_path(self):
        if not os.path.isdir(self.engine_dir):
            return None
        for folder, _, files in os.walk(self.engine_dir):
            if ENGINE_EXE in files:
                return os.path.join(folder, ENGINE_EXE)
        return None

    def model_path(self, model_id):
        model = MODELS_BY_ID.get(model_id)
        if not model:
            return None
        path = os.path.join(self.root, "models", model["file"])
        return path if os.path.isfile(path) else None

    def chosen_model(self):
        wanted = (self.settings() or {}).get("model") or "small"
        if self.model_path(wanted):
            return wanted
        # The one that's downloaded, if the chosen one isn't.
        for model in MODELS:
            if self.model_path(model["id"]):
                return model["id"]
        return wanted

    # ----------------------------------------------------------------- status

    def supported(self):
        return sys.platform in ENGINE_ASSETS and (sys.platform != "win32" or _is_64bit_windows())

    def problem(self):
        """Why it can't answer right now, or "" when it can (it may still
        need a few seconds to start)."""
        if not self.supported():
            return "The built-in AI needs 64-bit Windows."
        if not self.engine_path():
            return "the built-in AI isn't downloaded"
        if not self.model_path(self.chosen_model()):
            return "the built-in AI's model isn't downloaded"
        return ""

    def status(self):
        with self._job_lock:
            job = dict(self._job)
        with self._lock:
            running = self._proc is not None and self._proc.poll() is None
        models = []
        for model in MODELS:
            path = self.model_path(model["id"])
            models.append(dict(model, downloaded=bool(path)))
        free = None
        try:
            os.makedirs(self.root, exist_ok=True)
            free = shutil.disk_usage(self.root).free
        except OSError:
            pass
        return {
            "supported": self.supported(),
            "engine": bool(self.engine_path()),
            "engine_version": ENGINE_TAG,
            "models": models,
            # The model you picked (it may not be downloaded yet), and the
            # one that answers now.
            "model": (self.settings() or {}).get("model") or "small",
            "active_model": self.chosen_model(),
            "running": running and self._model_id == self.chosen_model(),
            "loaded_model": self._model_id if running else "",
            "problem": self.problem(),
            "job": job,
            "free_bytes": free,
            "memory_gb": _total_memory_gb(),
            "threads": self.threads(),
            "folder": self.root,
        }

    def threads(self):
        try:
            value = int((self.settings() or {}).get("threads") or 0)
        except (TypeError, ValueError):
            value = 0
        return value if 1 <= value <= 64 else default_threads()

    # --------------------------------------------------------------- download

    def start_download(self, model_id, again=False):
        """Downloads the engine (if needed) and this model, in the
        background. Raises BuiltinAIError when it can't begin.
        CHANGED (1.6.1): again=True replaces what's there (Download again)."""
        model = MODELS_BY_ID.get(model_id)
        if not model:
            raise BuiltinAIError("Pick Small or Better.")
        if not self.supported():
            raise BuiltinAIError(self.problem())
        with self._job_lock:
            if self._job.get("state") in ("engine", "model", "checking"):
                raise BuiltinAIError("A download is already running.")
            if again:
                need = 30_000_000 + model["size"]
            else:
                need = (0 if self.engine_path() else 30_000_000) + (0 if self.model_path(model_id) else model["size"])
            try:
                os.makedirs(self.root, exist_ok=True)
                free = shutil.disk_usage(self.root).free
            except OSError:
                free = None
            if free is not None and free < need + 300_000_000:
                raise BuiltinAIError(f"There isn't room on the drive: it needs about {need / 1e9:.1f} GB "
                                     f"and {free / 1e9:.1f} GB is free.")
            self._cancel.clear()
            self._job = {"state": "checking", "model": model_id, "done": 0, "total": need, "error": ""}
        threading.Thread(target=self._download, args=(model, again), daemon=True).start()

    def cancel_download(self):
        self._cancel.set()

    def _set_job(self, **changes):
        with self._job_lock:
            self._job.update(changes)

    def _download(self, model, again=False):
        try:
            if again:   # NEW (1.6.1): Download again: the old copies go first
                self.stop()
                self.kill_strays()
                if not _rmtree(self.engine_dir):
                    raise BuiltinAIError("The old engine is still in use by another program. Restart the PC Frivo "
                                         "runs on, then try again.")
                _remove(os.path.join(self.root, "models", model["file"]))
            if not self.engine_path():
                self._set_job(state="engine")
                self._download_engine()
            if not self.model_path(model["id"]):
                self._set_job(state="model")
                self._download_model(model)
            if self.on_ready:
                try:
                    self.on_ready()
                except Exception as e:
                    self.log(f"Built-in AI: after the download: {e!r}")
            self._set_job(state="done")
            self.log(f"Built-in AI: {model['model']} ready")
        except BuiltinAIError as e:
            if self._cancel.is_set():
                self._set_job(state="cancelled", error="")
            else:
                self._set_job(state="error", error=str(e))
                self.log(f"Built-in AI: download failed: {e}")
        except Exception as e:
            self._set_job(state="error", error=f"The download failed ({e}).")
            self.log(f"Built-in AI: download failed: {e!r}")

    def _fetch(self, url, target, expected_sha256, expected_size=None):
        """Streams url to target, counting progress, and checks the hash."""
        digest = hashlib.sha256()
        partial = target + ".part"
        try:
            with requests.get(url, stream=True, timeout=(15, 60), headers={"User-Agent": "Frivo"}) as resp:
                if resp.status_code != 200:
                    raise BuiltinAIError(f"The download was refused ({resp.status_code}). Try again later.")
                with open(partial, "wb") as out:
                    for chunk in resp.iter_content(1 << 20):
                        if self._cancel.is_set():
                            raise BuiltinAIError("Cancelled.")
                        out.write(chunk)
                        digest.update(chunk)
                        with self._job_lock:
                            self._job["done"] = self._job.get("done", 0) + len(chunk)
        except requests.RequestException as e:
            _remove(partial)
            raise BuiltinAIError(f"The download stopped ({e.__class__.__name__}). Check the connection and try again.")
        except BaseException:
            _remove(partial)
            raise
        if expected_size and os.path.getsize(partial) != expected_size:
            _remove(partial)
            raise BuiltinAIError("The download came out the wrong size. Try again.")
        if digest.hexdigest().lower() != expected_sha256.lower():
            _remove(partial)
            raise BuiltinAIError("The download didn't match its checksum, so it wasn't used. Try again.")
        os.replace(partial, target)

    def _download_engine(self):
        asset = ENGINE_ASSETS[sys.platform]
        try:
            resp = requests.get(GH_RELEASE_API.format(repo=ENGINE_REPO, tag=ENGINE_TAG), timeout=20,
                                headers={"User-Agent": "Frivo", "Accept": "application/vnd.github+json"})
            resp.raise_for_status()
            release = resp.json()
        except Exception as e:
            raise BuiltinAIError(f"Couldn't reach GitHub to get the engine ({e.__class__.__name__}). Try again later.")
        info = next((a for a in release.get("assets") or [] if a.get("name") == asset), None)
        sha = str((info or {}).get("digest") or "")
        if not info or not sha.startswith("sha256:"):
            raise BuiltinAIError("GitHub didn't give a checksum for the engine, so it wasn't downloaded.")
        os.makedirs(self.root, exist_ok=True)
        archive = os.path.join(self.root, asset)
        self._fetch(GH_DOWNLOAD.format(repo=ENGINE_REPO, tag=ENGINE_TAG, asset=asset), archive,
                    sha[len("sha256:"):], int(info.get("size") or 0) or None)
        staging = _new_staging(self.root, ".engine-")   # CHANGED (1.6.1): not mkdtemp
        try:
            _safe_extract(archive, staging)
            found = None
            for folder, _, files in os.walk(staging):
                if ENGINE_EXE in files:
                    found = folder
                    break
            if not found:
                raise BuiltinAIError("The engine download didn't have llama-server in it.")
            if sys.platform != "win32":
                os.chmod(os.path.join(found, ENGINE_EXE), 0o755)
            self.stop()
            self.kill_strays()   # NEW (1.6.1): a running engine would hold the old files
            if not _rmtree(self.engine_dir):
                raise BuiltinAIError("The old engine is still in use by another program. Restart the PC Frivo "
                                     "runs on, then try again.")
            os.replace(found, self.engine_dir)
        finally:
            shutil.rmtree(staging, ignore_errors=True)
            _remove(archive)
        # Older engines, from an earlier Frivo.
        for name in os.listdir(self.root):
            if name.startswith("engine-") and name != os.path.basename(self.engine_dir):
                shutil.rmtree(os.path.join(self.root, name), ignore_errors=True)

    def _download_model(self, model):
        try:
            resp = requests.get(HF_API.format(repo=model["repo"]), timeout=20, headers={"User-Agent": "Frivo"})
            resp.raise_for_status()
            siblings = resp.json().get("siblings") or []
        except Exception as e:
            raise BuiltinAIError(f"Couldn't reach Hugging Face to get the model ({e.__class__.__name__}). Try again later.")
        info = next((s for s in siblings if s.get("rfilename") == model["file"]), None)
        lfs = (info or {}).get("lfs") or {}
        if not lfs.get("sha256"):
            raise BuiltinAIError("Hugging Face didn't give a checksum for the model, so it wasn't downloaded.")
        folder = os.path.join(self.root, "models")
        os.makedirs(folder, exist_ok=True)
        size = int(lfs.get("size") or info.get("size") or 0) or None
        with self._job_lock:
            # The real size, now it's known.
            if size:
                self._job["total"] = self._job.get("done", 0) + size
        self._fetch(HF_FILE.format(repo=model["repo"], file=model["file"]),
                    os.path.join(folder, model["file"]), lfs["sha256"], size)

    def remove(self, model_id=None):
        """Removes one model, or everything (engine and models).
        CHANGED (1.6.1): stops a stray engine first, and raises
        BuiltinAIError if something couldn't be deleted, instead of
        saying "Removed" with the files still there."""
        self.stop()
        self.kill_strays()
        if model_id:
            model = MODELS_BY_ID.get(model_id)
            if model:
                path = os.path.join(self.root, "models", model["file"])
                _remove(path)
                if os.path.exists(path):
                    raise BuiltinAIError(f"{model['model']} is still in use by another program, so it wasn't deleted. "
                                         "Restart the PC Frivo runs on, then remove it again.")
            return
        with self._job_lock:
            self._job = {"state": "idle"}
        if not _rmtree(self.root):
            raise BuiltinAIError(f"Some of the built-in AI's files are still in use, so {self.root} wasn't fully "
                                 "deleted. Restart the PC Frivo runs on, then remove it again.")

    # ---------------------------------------------------------------- running

    def ensure_running(self):
        """Starts the engine with the chosen model, if it isn't running.
        Returns the port. Raises BuiltinAIError."""
        problem = self.problem()
        if problem:
            raise BuiltinAIError(f"The built-in AI can't answer: {problem}. Download it in Settings > Providers.")
        model_id = self.chosen_model()
        with self._lock:
            if self._proc is not None and self._proc.poll() is None and self._model_id == model_id:
                self._last_used = time.time()
                return self._port
            self._stop_locked()
            self.kill_strays()   # NEW (1.6.1)
            port = _free_port()
            exe = self.engine_path()
            args = [exe, "-m", self.model_path(model_id), "--host", "127.0.0.1", "--port", str(port),
                    "-c", str(CONTEXT_TOKENS), "-t", str(self.threads()), "-np", "1",
                    "--alias", MODEL_ALIAS, "--jinja", "--reasoning", "off", "--no-webui"]
            os.makedirs(self.root, exist_ok=True)
            log_path = os.path.join(self.root, "engine.log")
            self._log_file = open(log_path, "wb")
            kwargs = {"stdout": self._log_file, "stderr": subprocess.STDOUT, "stdin": subprocess.DEVNULL,
                      "cwd": os.path.dirname(exe)}
            if sys.platform == "win32":
                # No console window, and below-normal priority so games stay smooth.
                kwargs["creationflags"] = 0x08000000 | 0x00004000   # CREATE_NO_WINDOW | BELOW_NORMAL
            else:
                kwargs["start_new_session"] = True
            try:
                self._proc = subprocess.Popen(args, **kwargs)
            except OSError as e:
                self._log_file.close()
                self._log_file = None
                raise BuiltinAIError(f"The built-in AI couldn't start ({e}). If your antivirus blocked it, "
                                     f"allow {exe}.")
            self._attach_to_job(self._proc)   # NEW (1.6.1): it dies with Frivo
            self._port = port
            self._model_id = model_id
            self._last_used = time.time()
            self.log(f"Built-in AI: starting {MODELS_BY_ID[model_id]['model']} on port {port}, "
                     f"{self.threads()} threads")
            deadline = time.time() + START_TIMEOUT
            while time.time() < deadline:
                if self._proc.poll() is not None:
                    tail = _tail(log_path)
                    self._stop_locked()
                    raise BuiltinAIError("The built-in AI stopped while starting." + (f" It said: {tail}" if tail else ""))
                try:
                    r = requests.get(f"http://127.0.0.1:{port}/health", timeout=2)
                    if r.status_code == 200:
                        return port
                except requests.RequestException:
                    pass
                time.sleep(0.4)
            self._stop_locked()
            raise BuiltinAIError("The built-in AI took too long to start. Try the Small model, or try again.")

    def chat(self, messages, max_tokens, temperature=None):
        """An OpenAI-style chat completion. Returns (text, finish_reason)."""
        port = self.ensure_running()
        payload = {"model": MODEL_ALIAS, "messages": messages, "max_tokens": int(max_tokens), "stream": False,
                   "chat_template_kwargs": {"enable_thinking": False}}
        if temperature is not None:
            payload["temperature"] = float(temperature)
        try:
            resp = requests.post(f"http://127.0.0.1:{port}/v1/chat/completions", json=payload, timeout=(5, 300))
        except requests.RequestException as e:
            raise BuiltinAIError(f"The built-in AI didn't answer ({e.__class__.__name__}).")
        finally:
            self._last_used = time.time()
        if resp.status_code != 200:
            raise BuiltinAIError(f"The built-in AI refused ({resp.status_code}): {resp.text[:200]}")
        choice = (resp.json().get("choices") or [{}])[0]
        text = ((choice.get("message") or {}).get("content") or "").strip()
        text = re.sub(r"(?s)<think>.*?</think>", "", text).strip()
        if not text:
            raise BuiltinAIError("The built-in AI gave an empty answer.")
        return text, ("length" if choice.get("finish_reason") == "length" else "stop")

    def stop(self):
        with self._lock:
            self._stop_locked()

    # NEW (1.6.1) ------------------------------------------------- strays

    def kill_strays(self):
        """Stops any llama-server running from this folder that isn't the
        one Frivo is using now: left behind when Frivo was closed, crashed
        or was stopped by an update. Those keep the files open, so they
        couldn't be deleted or replaced. Returns how many were stopped."""
        mine = self._proc.pid if self._proc is not None and self._proc.poll() is None else None
        stopped = 0
        for pid, path in _engine_processes():
            if pid == mine or not _inside(path, self.root):
                continue
            if _kill(pid):
                stopped += 1
        if stopped:
            self.log(f"Built-in AI: stopped {stopped} engine(s) left running from before")
            time.sleep(0.5)   # Windows lets go of the files a moment later
        return stopped

    def _attach_to_job(self, proc):
        """Windows: puts the engine in a job that's closed when Frivo's
        process ends, however it ends, so the engine never outlives it."""
        if sys.platform != "win32":
            return
        try:
            import ctypes
            from ctypes import wintypes
            k32 = ctypes.WinDLL("kernel32", use_last_error=True)
            if self._job_object is None:
                k32.CreateJobObjectW.restype = wintypes.HANDLE
                job = k32.CreateJobObjectW(None, None)
                if not job:
                    return

                class BASIC(ctypes.Structure):
                    _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                                ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                                ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                                ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                                ("SchedulingClass", wintypes.DWORD)]

                class IO(ctypes.Structure):
                    _fields_ = [(n, ctypes.c_uint64) for n in ("ReadOperationCount", "WriteOperationCount",
                                                               "OtherOperationCount", "ReadTransferCount",
                                                               "WriteTransferCount", "OtherTransferCount")]

                class EXTENDED(ctypes.Structure):
                    _fields_ = [("BasicLimitInformation", BASIC), ("IoInfo", IO),
                                ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                                ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

                info = EXTENDED()
                info.BasicLimitInformation.LimitFlags = 0x2000   # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
                if not k32.SetInformationJobObject(wintypes.HANDLE(job), 9, ctypes.byref(info), ctypes.sizeof(info)):
                    k32.CloseHandle(wintypes.HANDLE(job))
                    return
                self._job_object = job   # kept open for as long as Frivo runs
            k32.AssignProcessToJobObject(wintypes.HANDLE(self._job_object), wintypes.HANDLE(int(proc._handle)))
        except Exception as e:
            self.log(f"Built-in AI: couldn't tie the engine to Frivo ({e!r})")

    def _stop_locked(self):
        proc, self._proc = self._proc, None
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
            self.log("Built-in AI: stopped")
        if self._log_file:
            try:
                self._log_file.close()
            except Exception:
                pass
            self._log_file = None
        self._model_id = None

    def _idle_loop(self):
        while True:
            time.sleep(30)
            try:
                idle = IDLE_CHOICES.get((self.settings() or {}).get("idle") or "1h", 3600)
                with self._lock:
                    running = self._proc is not None and self._proc.poll() is None
                    if running and idle and time.time() - self._last_used > idle:
                        self.log("Built-in AI: idle, freeing its memory")
                        self._stop_locked()
                    elif self._proc is not None and not running:
                        self._stop_locked()   # it exited on its own
            except Exception:
                pass


# ---------------------------------------------------------------------- helpers


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


def _remove(path):
    try:
        os.remove(path)
    except OSError:
        pass


def _rmtree(path, tries=6):
    """NEW (1.6.1): deletes a folder, trying again for a few seconds while
    Windows lets go of files. True when it's gone."""
    for attempt in range(tries):
        shutil.rmtree(path, ignore_errors=True)
        if not os.path.exists(path):
            return True
        time.sleep(0.5)
    return not os.path.exists(path)


def _inside(path, folder):
    try:
        path = os.path.normcase(os.path.realpath(path))
        folder = os.path.normcase(os.path.realpath(folder))
    except (OSError, ValueError):
        return False
    return path.startswith(folder + os.sep)


def _engine_processes():
    """NEW (1.6.1): (pid, executable path) of every running llama-server."""
    found = []
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes
            k32 = ctypes.WinDLL("kernel32", use_last_error=True)

            class ENTRY(ctypes.Structure):
                _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                            ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
                            ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                            ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long),
                            ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_wchar * 260)]

            k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
            k32.OpenProcess.restype = wintypes.HANDLE
            snap = k32.CreateToolhelp32Snapshot(0x2, 0)   # TH32CS_SNAPPROCESS
            if not snap or snap == wintypes.HANDLE(-1).value:
                return found
            try:
                entry = ENTRY()
                entry.dwSize = ctypes.sizeof(ENTRY)
                ok = k32.Process32FirstW(wintypes.HANDLE(snap), ctypes.byref(entry))
                while ok:
                    if entry.szExeFile.lower() == ENGINE_EXE.lower():
                        pid = int(entry.th32ProcessID)
                        handle = k32.OpenProcess(0x1000, False, pid)   # PROCESS_QUERY_LIMITED_INFORMATION
                        if handle:
                            try:
                                buf = ctypes.create_unicode_buffer(1024)
                                size = wintypes.DWORD(len(buf))
                                if k32.QueryFullProcessImageNameW(wintypes.HANDLE(handle), 0, buf, ctypes.byref(size)):
                                    found.append((pid, buf.value))
                            finally:
                                k32.CloseHandle(wintypes.HANDLE(handle))
                    ok = k32.Process32NextW(wintypes.HANDLE(snap), ctypes.byref(entry))
            finally:
                k32.CloseHandle(wintypes.HANDLE(snap))
        except Exception:
            pass
        return found
    try:
        for name in os.listdir("/proc"):
            if not name.isdigit():
                continue
            try:
                exe = os.readlink(f"/proc/{name}/exe")
            except OSError:
                continue
            if os.path.basename(exe).replace(" (deleted)", "") == ENGINE_EXE:
                found.append((int(name), exe.replace(" (deleted)", "")))
    except OSError:
        pass
    return found


def _kill(pid):
    """Stops one process. True if it's gone."""
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes
            k32 = ctypes.WinDLL("kernel32", use_last_error=True)
            k32.OpenProcess.restype = wintypes.HANDLE
            handle = k32.OpenProcess(0x0001 | 0x00100000, False, pid)   # TERMINATE | SYNCHRONIZE
            if not handle:
                return False
            try:
                k32.TerminateProcess(wintypes.HANDLE(handle), 1)
                k32.WaitForSingleObject(wintypes.HANDLE(handle), 5000)
                return True
            finally:
                k32.CloseHandle(wintypes.HANDLE(handle))
        except Exception:
            return False
    try:
        import signal
        os.kill(pid, signal.SIGKILL)
        return True
    except OSError:
        return False


def _free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _tail(path, chars=300):
    try:
        with open(path, "rb") as f:
            data = f.read()[-4000:].decode("utf-8", "replace")
        lines = [l for l in data.splitlines() if l.strip()]
        errors = [l for l in lines if re.search(r"error|fail|unknown|invalid", l, re.I)]
        return ((errors or lines)[-1] if (errors or lines) else "")[:chars]
    except OSError:
        return ""


def _safe_extract(archive, target):
    """Unpacks a .zip or .tar.gz without letting any file land outside
    `target`."""
    root = os.path.realpath(target)

    def inside(name):
        dest = os.path.realpath(os.path.join(root, name))
        return dest == root or dest.startswith(root + os.sep)

    if archive.endswith(".zip"):
        with zipfile.ZipFile(archive) as z:
            for info in z.infolist():
                if not inside(info.filename):
                    raise BuiltinAIError("The engine download had an unsafe file in it, so it wasn't used.")
            z.extractall(root)
    else:
        with tarfile.open(archive, "r:*") as t:
            for member in t.getmembers():
                if not inside(member.name):
                    raise BuiltinAIError("The engine download had an unsafe file in it, so it wasn't used.")
                if (member.issym() or member.islnk()) and not inside(
                        os.path.join(os.path.dirname(member.name), member.linkname)):
                    raise BuiltinAIError("The engine download had an unsafe file in it, so it wasn't used.")
            if hasattr(tarfile, "data_filter"):
                t.extractall(root, filter="data")
            else:
                t.extractall(root)


def _is_64bit_windows():
    return sys.maxsize > 2 ** 32 or os.environ.get("PROCESSOR_ARCHITEW6432") is not None


def _total_memory_gb():
    try:
        if sys.platform == "win32":
            import ctypes

            class MemoryStatus(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("sullAvailExtendedVirtual", ctypes.c_ulonglong)]
            status = MemoryStatus()
            status.dwLength = ctypes.sizeof(MemoryStatus)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
            return round(status.ullTotalPhys / 1024 ** 3, 1)
        return round(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1024 ** 3, 1)
    except Exception:
        return None
