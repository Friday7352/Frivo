"""
NEW (2.0.0): built-in dictation.

Live dictation that runs inside Frivo, on the PC Frivo runs on: no OpenAI
and no Evora. Words appear as you speak. Settings › Dictation offers three
models; one is downloaded and used at a time:

  * Small:  NVIDIA Nemotron 3.5 ASR Streaming 0.6B (int8, 560 ms chunks),
            about 680 MB. Made for live dictation: it takes the audio as it
            comes and keeps its place, so words appear about half a second
            behind you. About 40 languages, picked automatically. Runs on
            the processor. OpenMDW-1.1 licence.
  * Medium: NVIDIA Parakeet TDT 0.6B v3 (int8), about 670 MB. The most
            accurate for English and 24 other European languages, picked
            automatically. Runs on the processor. CC-BY-4.0.
  * Large:  OpenAI Whisper large-v3-turbo, the model Evora uses, through
            faster-whisper (CTranslate2) on an NVIDIA graphics card, about
            1.6 GB, plus NVIDIA's CUDA libraries (about 1 GB, once). About
            100 languages: the one for Japanese, Korean, Chinese and the
            rest. Needs the card. MIT.

Small and Medium run on sherpa-onnx, which Frivo already has for its free
voices. Large uses faster-whisper, installed by setup with this file's
requirements (requirements-dictation.txt); its CUDA libraries are fetched
here only when Large is downloaded.

The download happens on the PC Frivo runs on, whichever device clicked the
button: the browser only ever sends audio and gets words back. Every file
is pinned here by size, and the big ones by the SHA-256 their publisher
gives for them (Hugging Face's for the models, PyPI's for NVIDIA's
libraries); only a complete, checked set is kept.

The model is loaded when someone starts dictating and freed after it has
been idle (15 minutes by default). Everything lives in
<Frivo data>\\builtin_dictation\\; Remove deletes that folder.

How a browser streams to it (app.py has the routes):

  POST /api/dictation/stream             {"language"} -> {"id"}
  POST /api/dictation/stream/<id>        16 kHz mono 16-bit audio in,
                                         {"lines": [{id, text, complete}]} out
  POST /api/dictation/stream/<id>/stop   -> the final lines

A line is a sentence: Nemotron ends one where it hears the end of one;
for Medium and Large, a pause does (they read each sentence whole, again
every half second or so while it's being said).
"""

import hashlib
import os
import re
import shutil
import sys
import threading
import time
import uuid
import zipfile

import requests

HF = "https://huggingface.co/{repo}/resolve/main/{name}"

MODELS = [
    {
        "id": "small",
        "name": "Small",
        "model": "Nemotron 3.5 Streaming",
        "engine": "nemotron",
        "folder": "nemotron-3.5-asr-streaming-560ms-int8",
        "repo": "csukuangfj2/sherpa-onnx-nemotron-3.5-asr-streaming-0.6b-560ms-int8-2026-06-11",
        "files": [
            {"name": "encoder.int8.onnx", "size": 657_601_403,
             "sha256": "012e9321373af99021415e0b0eb3ec827b4be3153be6f30d9b448fe65e896e68"},
            {"name": "decoder.int8.onnx", "size": 14_978_075,
             "sha256": "19f9c98fc6d0a2c33a65a43b36fdb2e914c26c0aa9764be3aebc502a1e982fb0"},
            {"name": "joiner.int8.onnx", "size": 9_504_438,
             "sha256": "4101c7c679a0bc30483794b27a059e34e79232aa2068d78d51231a22c8b0d7ce"},
            {"name": "tokens.txt", "size": 131_440, "sha256": None},
        ],
        "gpu": False,
        "languages": "About 40, picked automatically",
        "note": "Words appear as you speak, half a second behind. Lightest on the processor.",
    },
    {
        "id": "medium",
        "name": "Medium",
        "model": "Parakeet TDT 0.6B v3",
        "engine": "parakeet",
        "folder": "parakeet-tdt-0.6b-v3-int8",
        "repo": "csukuangfj/sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8",
        "files": [
            {"name": "encoder.int8.onnx", "size": 652_184_281,
             "sha256": "acfc2b4456377e15d04f0243af540b7fe7c992f8d898d751cf134c3a55fd2247"},
            {"name": "decoder.int8.onnx", "size": 11_845_275,
             "sha256": "179e50c43d1a9de79c8a24149a2f9bac6eb5981823f2a2ed88d655b24248db4e"},
            {"name": "joiner.int8.onnx", "size": 6_355_277,
             "sha256": "3164c13fc2821009440d20fcb5fdc78bff28b4db2f8d0f0b329101719c0948b3"},
            {"name": "tokens.txt", "size": 93_939, "sha256": None},
        ],
        "gpu": False,
        "languages": "English and 24 European languages, picked automatically",
        "note": "The most accurate for English and European languages. On the processor.",
    },
    {
        "id": "large",
        "name": "Large",
        "model": "Whisper large-v3-turbo",
        "engine": "whisper",
        "folder": "whisper-large-v3-turbo-ct2",
        "repo": "mobiuslabsgmbh/faster-whisper-large-v3-turbo",
        "files": [
            {"name": "model.bin", "size": 1_617_884_929,
             "sha256": "e76620f83d5f5b69efd3d87e3dc180c1bd21df9fbebacfd4335e5e1efcc018da"},
            {"name": "config.json", "size": 2_263, "sha256": None},
            {"name": "preprocessor_config.json", "size": 340, "sha256": None},
            {"name": "tokenizer.json", "size": 2_710_337, "sha256": None},
            {"name": "vocabulary.json", "size": 1_068_114, "sha256": None},
        ],
        "gpu": True,
        "languages": "About 100, picked automatically",
        "note": "Evora's model, on the graphics card. Best for Japanese, Korean, Chinese and other languages.",
    },
]
for _m in MODELS:
    _m["size"] = sum(f["size"] for f in _m["files"])
MODELS_BY_ID = {m["id"]: m for m in MODELS}
DEFAULT_MODEL = "small"

# NVIDIA's CUDA libraries for Large (faster-whisper loads them as DLLs).
# The same versions Evora uses, from PyPI, which publishes their SHA-256.
CUDA_WHEELS = [
    {"name": "nvidia_cublas_cu12-12.6.4.1-py3-none-win_amd64.whl", "size": 434_535_301,
     "sha256": "9e4fa264f4d8a4eb0cdbd34beadc029f453b3bafae02401e999cf3d5a5af75f8",
     "url": "https://files.pythonhosted.org/packages/84/f7/985e9bdbe3e0ac9298fcc8cfa51a392862a46a0ffaccbbd56939b62a9c83/"
            "nvidia_cublas_cu12-12.6.4.1-py3-none-win_amd64.whl"},
    {"name": "nvidia_cudnn_cu12-9.5.1.17-py3-none-win_amd64.whl", "size": 565_440_743,
     "sha256": "d7af0f8a4f3b4b9dbb3122f2ef553b45694ed9c384d5a75bab197b8eefb79ab8",
     "url": "https://files.pythonhosted.org/packages/b6/b2/3f60d15f037fa5419d9d7f788b100ef33ea913ae5315c87ca6d6fa606c35/"
            "nvidia_cudnn_cu12-9.5.1.17-py3-none-win_amd64.whl"},
]
CUDA_SIZE = sum(w["size"] for w in CUDA_WHEELS)

IDLE_CHOICES = {"5m": 300, "15m": 900, "1h": 3600, "never": 0}
DEFAULT_IDLE = "15m"

SAMPLE_RATE = 16000
STREAM_FORGET_SECONDS = 30      # a stream nobody has sent audio to for this long is closed
MAX_STREAMS = 8                 # at once, across every device
MAX_CHUNK_BYTES = SAMPLE_RATE * 2 * 5   # five seconds of audio in one request is plenty
MAX_TEST_BYTES = SAMPLE_RATE * 2 * 15   # Test: up to 15 seconds

# Medium and Large read a sentence whole. Where one ends: a pause.
FRAME = 320                     # 20 ms
SPEECH_RMS = 0.010              # the level that counts as talking
END_PAUSE_SECONDS = 0.6
MAX_SENTENCE_SECONDS = 25.0     # read and start a new one, however long it goes on
PRE_ROLL_FRAMES = 15            # 0.3 s kept from before speech starts
INTERIM_SECONDS = {"parakeet": 0.5, "whisper": 0.6}

_LANG_TAG = re.compile(r"\s*<\|?[a-z]{2,3}(?:[-_][A-Za-z]{2,4})?\|?>\s*")


IS_WINDOWS = os.name == "nt"   # Large (and NVIDIA's DLLs) are Windows-only; the tests change this


class DictationError(RuntimeError):
    pass


def clean_text(text):
    """Without the language tags Nemotron adds in auto mode (<en-US>)."""
    return re.sub(r"\s{2,}", " ", _LANG_TAG.sub(" ", str(text or ""))).strip()


def tag_language(text):
    """NEW (2.0.0): the language a tag says ("ja" from <ja-JP> or <|ja|>),
    the last one in the text, or None. Listening uses it to skip
    translating what's already in your language."""
    found = re.findall(r"<\|?([a-z]{2,3})(?:[-_][A-Za-z]{2,4})?\|?>", str(text or ""))
    return found[-1] if found else None


def _short_language(value):
    """"en" from "en", "en-US" or "english"-free codes; None when unknown."""
    code = re.split(r"[-_]", str(value or "").strip().lower())[0]
    return code if re.fullmatch(r"[a-z]{2,3}", code) else None


def _np():
    try:
        import numpy
        return numpy
    except Exception:
        return None


def _sherpa():
    try:
        import sherpa_onnx
        return sherpa_onnx
    except Exception:
        return None


def _faster_whisper():
    try:
        import faster_whisper
        return faster_whisper
    except Exception:
        return None


def default_threads():
    cores = os.cpu_count() or 4
    return max(2, min(8, cores // 2))


# ---------------------------------------------------------------- engines
#
# Each one turns a model folder into something with:
#   stream(language)  -> an object with add(samples), stop(), lines()
#   transcribe(samples, language) -> text           (the whole clip at once)
#   close()
# samples are float32, 16 kHz, mono. ENGINES maps an engine name to its
# loader; the tests replace them.

class _Lines:
    """The sentences of one stream, as the browser gets them."""

    def __init__(self):
        self.items = []
        self.next_id = 1

    def current(self):
        if not self.items or self.items[-1]["complete"]:
            self.items.append({"id": str(self.next_id), "text": "", "complete": False})
            self.next_id += 1
        return self.items[-1]

    # CHANGED (2.0.0): each line also says the language it was heard in,
    # when the model says (Small and Large do), for Listening.
    def set_current(self, text, language=None):
        line = self.current()
        line["text"] = text
        if language:
            line["language"] = language

    def complete_current(self, text=None, language=None):
        if not self.items or self.items[-1]["complete"]:
            if not text:
                return
            self.current()
        line = self.items[-1]
        if text is not None:
            line["text"] = text
        if language:
            line["language"] = language
        line["complete"] = True
        if not line["text"]:
            self.items.pop()
        del self.items[:-40]   # only the recent ones are worth sending

    def view(self):
        return [dict(l) for l in self.items]


class _NemotronStream:
    # CHANGED (2.0.0): max_seconds (Listening's "Commit every") finishes a
    # line that goes on that long without a pause; the language tag it
    # writes in automatic mode is kept on the line.
    def __init__(self, recognizer, language, max_seconds=None):
        self.rec = recognizer
        self.s = recognizer.create_stream()
        try:
            self.s.set_option("language", language or "auto")
        except Exception:
            pass
        self.out = _Lines()
        self.forced = language or None
        self.max_seconds = max_seconds
        self.heard = 0.0

    def _decode(self):
        while self.rec.is_ready(self.s):
            self.rec.decode_stream(self.s)
        raw = self.rec.get_result(self.s)
        text = clean_text(raw)
        language = tag_language(raw) or self.forced
        if text:
            self.out.set_current(text, language)
        else:
            self.heard = 0.0   # counted from the first word
        too_long = bool(self.max_seconds and text and self.heard >= self.max_seconds)
        if too_long or self.rec.is_endpoint(self.s):
            self.out.complete_current(text or None, language)
            self.rec.reset(self.s)
            self.heard = 0.0

    def add(self, samples):
        if len(samples):
            self.s.accept_waveform(SAMPLE_RATE, samples)
            self.heard += len(samples) / SAMPLE_RATE
        self._decode()

    def stop(self):
        np = _np()
        # A little silence lets it finish the last word, as sherpa-onnx's
        # own examples do.
        tail = np.zeros(int(SAMPLE_RATE * 0.66), dtype=np.float32) if np is not None else [0.0] * int(SAMPLE_RATE * 0.66)
        self.s.accept_waveform(SAMPLE_RATE, tail)
        self.s.input_finished()
        while self.rec.is_ready(self.s):
            self.rec.decode_stream(self.s)
        raw = self.rec.get_result(self.s)
        self.out.complete_current(clean_text(raw) or None, tag_language(raw) or self.forced)

    def lines(self):
        return self.out.view()


class _SentenceStream:
    """For models that read a sentence whole (Medium, Large): finds where
    sentences start and end by loudness, reads the one being said again
    every INTERIM seconds, and once more when it's over."""

    def __init__(self, engine, language, interim, max_seconds=None):
        self.engine = engine
        self.language = language
        self.interim = interim
        self.max_seconds = max_seconds or MAX_SENTENCE_SECONDS   # NEW (2.0.0): Listening's "Commit every"
        self.pre = []
        self.buf = []
        self.speaking = False
        self.quiet = 0.0
        self.since_read = 0.0
        self.out = _Lines()
        self.leftover = None

    def _frames(self, samples):
        np = _np()
        if self.leftover is not None and len(self.leftover):
            samples = np.concatenate([self.leftover, samples])
        n = len(samples) // FRAME
        self.leftover = samples[n * FRAME:]
        return [samples[i * FRAME:(i + 1) * FRAME] for i in range(n)]

    def _audio(self):
        np = _np()
        frames = self.buf
        # The pause at the end is not part of the sentence.
        keep = max(1, len(frames) - int(self.quiet / 0.02) + 5)
        return np.concatenate(frames[:keep]) if frames else np.zeros(0, dtype=np.float32)

    def _heard_language(self):
        """NEW (2.0.0): the language the engine says it just heard (Large
        does), or the one asked for."""
        return _short_language(getattr(self.engine, "last_language", None)) or self.language

    def _finish(self):
        if self.buf and len(self.buf) * 0.02 - self.quiet >= 0.25:
            text = clean_text(self.engine.transcribe(self._audio(), self.language, final=True))
            self.out.complete_current(text or None, self._heard_language())
        else:
            self.out.complete_current(None)
        self.buf, self.pre = [], []
        self.speaking = False
        self.quiet = 0.0
        self.since_read = 0.0

    def add(self, samples):
        np = _np()
        for frame in self._frames(samples):
            loud = float(np.sqrt(np.mean(frame * frame))) > SPEECH_RMS
            if not self.speaking:
                if loud:
                    self.speaking = True
                    self.buf = self.pre + [frame]
                    self.pre = []
                    self.quiet = 0.0
                    self.since_read = 0.0
                    self.out.current()
                else:
                    self.pre = (self.pre + [frame])[-PRE_ROLL_FRAMES:]
                continue
            self.buf.append(frame)
            self.since_read += 0.02
            self.quiet = 0.0 if loud else self.quiet + 0.02
            if self.quiet >= END_PAUSE_SECONDS or len(self.buf) * 0.02 >= self.max_seconds:
                self._finish()
        if self.speaking and self.since_read >= self.interim and len(self.buf) * 0.02 >= 0.4:
            self.since_read = 0.0
            text = clean_text(self.engine.transcribe(self._audio(), self.language, final=False))
            if text:
                self.out.set_current(text, self._heard_language())

    def stop(self):
        if self.speaking:
            self._finish()

    def lines(self):
        return self.out.view()


class NemotronEngine:
    name = "nemotron"
    on_gpu = False

    def __init__(self, folder, threads):
        so = _sherpa()
        if so is None:
            raise DictationError("Built-in dictation needs a part Frivo's setup installs (sherpa-onnx). Run setup again (Repair).")
        self.rec = so.OnlineRecognizer.from_transducer(
            tokens=os.path.join(folder, "tokens.txt"),
            encoder=os.path.join(folder, "encoder.int8.onnx"),
            decoder=os.path.join(folder, "decoder.int8.onnx"),
            joiner=os.path.join(folder, "joiner.int8.onnx"),
            num_threads=threads,
            sample_rate=SAMPLE_RATE,
            enable_endpoint_detection=True,
            rule1_min_trailing_silence=2.4,
            rule2_min_trailing_silence=0.8,
            rule3_min_utterance_length=30.0,
            decoding_method="greedy_search",
            provider="cpu",
        )

    def stream(self, language, max_seconds=None):
        return _NemotronStream(self.rec, language, max_seconds)

    def transcribe(self, samples, language=None, final=True):
        s = _NemotronStream(self.rec, language)
        s.add(samples)
        s.stop()
        return " ".join(l["text"] for l in s.lines() if l["text"])

    def close(self):
        self.rec = None


class ParakeetEngine:
    name = "parakeet"
    on_gpu = False

    def __init__(self, folder, threads):
        so = _sherpa()
        if so is None:
            raise DictationError("Built-in dictation needs a part Frivo's setup installs (sherpa-onnx). Run setup again (Repair).")
        self.rec = so.OfflineRecognizer.from_transducer(
            encoder=os.path.join(folder, "encoder.int8.onnx"),
            decoder=os.path.join(folder, "decoder.int8.onnx"),
            joiner=os.path.join(folder, "joiner.int8.onnx"),
            tokens=os.path.join(folder, "tokens.txt"),
            num_threads=threads,
            sample_rate=SAMPLE_RATE,
            decoding_method="greedy_search",
            model_type="nemo_transducer",
            provider="cpu",
        )

    def stream(self, language, max_seconds=None):
        return _SentenceStream(self, language, INTERIM_SECONDS["parakeet"], max_seconds)

    def transcribe(self, samples, language=None, final=True):
        if not len(samples):
            return ""
        s = self.rec.create_stream()
        s.accept_waveform(SAMPLE_RATE, samples)
        self.rec.decode_stream(s)
        self.last_language = tag_language(s.result.text) or _short_language(getattr(s.result, "lang", None))
        return s.result.text.strip()

    def close(self):
        self.rec = None


_CUDA_HANDLES = []


def register_cuda(folder):
    """Makes the CUDA libraries in `folder` findable (Windows): CTranslate2
    loads them as plain DLLs, so they have to be on the search path. The
    same thing Evora does for its pip-installed ones."""
    if not os.path.isdir(folder):
        return False
    if os.name == "nt":
        try:
            _CUDA_HANDLES.append(os.add_dll_directory(folder))
        except Exception:
            pass
    if folder not in os.environ.get("PATH", ""):
        os.environ["PATH"] = folder + os.pathsep + os.environ.get("PATH", "")
    return True


def cuda_devices():
    """How many NVIDIA cards CTranslate2 can use (0 without one, or without
    faster-whisper)."""
    try:
        import ctranslate2
        return int(ctranslate2.get_cuda_device_count())
    except Exception:
        return 0


class WhisperEngine:
    name = "whisper"
    on_gpu = True

    def __init__(self, folder, threads):
        fw = _faster_whisper()
        if fw is None:
            raise DictationError("Large needs a part Frivo's setup installs (faster-whisper). Run setup again (Repair).")
        try:
            self.model = fw.WhisperModel(folder, device="cuda", compute_type="int8_float16", cpu_threads=threads)
        except Exception as e:
            message = str(e)
            if "cublas" in message.lower() or "cudnn" in message.lower():
                raise DictationError("NVIDIA's CUDA libraries didn't load. Use Download again on Large.") from e
            raise DictationError(f"Large couldn't start on the graphics card ({message[:160]}).") from e

    def stream(self, language, max_seconds=None):
        return _SentenceStream(self, language, INTERIM_SECONDS["whisper"], max_seconds)

    def transcribe(self, samples, language=None, final=True):
        if not len(samples):
            return ""
        segments, info = self.model.transcribe(
            samples, language=language or None, beam_size=3 if final else 1, temperature=0.0,
            condition_on_previous_text=False, without_timestamps=True, vad_filter=False)
        text = " ".join(seg.text.strip() for seg in segments).strip()
        self.last_language = getattr(info, "language", None)   # NEW (2.0.0): for Listening
        return text

    def close(self):
        self.model = None


ENGINES = {"nemotron": NemotronEngine, "parakeet": ParakeetEngine, "whisper": WhisperEngine}


# ---------------------------------------------------------------- the service

class BuiltinDictation:
    def __init__(self, data_dir, log=print, settings=None, gpu_reader=None):
        self.root = os.path.join(data_dir, "builtin_dictation")
        self.log = log
        # A function returning the current settings: {"model", "idle"}.
        self.settings = settings or (lambda: {})
        # A function returning the card's used memory in MB (or None): how
        # much a model on it takes is measured before and after loading.
        self.gpu_reader = gpu_reader or (lambda: None)
        self._engine_lock = threading.RLock()   # every call into a model
        self._job_lock = threading.Lock()
        self._job = {"state": "idle"}
        self._cancel = threading.Event()
        self._engine = None
        self._loaded_id = None
        self._vram_mb = None
        self._last_used = 0.0
        self._streams = {}
        self.on_ready = None                    # called after a download finishes
        self._remove_legacy()
        if os.path.isdir(self.cuda_dir):
            register_cuda(self.cuda_dir)
        threading.Thread(target=self._idle_loop, daemon=True).start()

    # ------------------------------------------------------------------ files

    @property
    def cuda_dir(self):
        return os.path.join(self.root, "cuda")

    def model_dir(self, model_id):
        model = MODELS_BY_ID.get(model_id)
        return os.path.join(self.root, "models", model["folder"]) if model else None

    def _remove_legacy(self):
        """CHANGED (2.0.0): the Moonshine models from the first try, if any."""
        for old in ("small", "medium"):
            path = os.path.join(self.root, "models", old)
            if os.path.isdir(path):
                shutil.rmtree(path, ignore_errors=True)

    def downloaded(self, model_id):
        """Every file there, at its size (checksums are checked when it's
        downloaded, not each time this is asked), and the CUDA libraries
        for Large."""
        model = MODELS_BY_ID.get(model_id)
        if not model:
            return False
        folder = self.model_dir(model_id)
        if not os.path.isfile(os.path.join(folder, ".complete")):
            return False
        for f in model["files"]:
            path = os.path.join(folder, f["name"])
            if not os.path.isfile(path) or os.path.getsize(path) != f["size"]:
                return False
        if model["gpu"] and IS_WINDOWS and not self.cuda_ready():
            return False
        return True

    def cuda_ready(self):
        return os.path.isfile(os.path.join(self.cuda_dir, ".complete"))

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

    def supported(self, model_id=None):
        """"" when this model can run here, or why not."""
        model = MODELS_BY_ID.get(model_id or self.chosen_model())
        if not model:
            return "Pick Small, Medium or Large."
        if model["engine"] in ("nemotron", "parakeet") and _sherpa() is None:
            return "Built-in dictation needs a part Frivo's setup installs. Run setup again (Repair)."
        if model["gpu"]:
            if not IS_WINDOWS:
                return "Large needs Windows and an NVIDIA graphics card."
            if _faster_whisper() is None:
                return "Large needs a part Frivo's setup installs (faster-whisper). Run setup again (Repair)."
            if not self.gpu_present():
                return "Large needs an NVIDIA graphics card in the PC Frivo runs on."
        return ""

    def gpu_present(self):
        if self.cuda_ready():
            register_cuda(self.cuda_dir)
        if cuda_devices() > 0:
            return True
        # CTranslate2 can't see the card until the CUDA libraries are here;
        # the driver can.
        return self.gpu_reader() is not None

    def problem(self):
        """Why it can't take dictation right now, or ""."""
        model_id = self.chosen_model()
        reason = self.supported(model_id)
        if reason:
            return reason
        if not self.downloaded(model_id):
            return "Built-in dictation isn't downloaded."
        return ""

    def status(self):
        with self._job_lock:
            job = dict(self._job)
        models = []
        for m in MODELS:
            item = {k: v for k, v in m.items() if k not in ("files", "repo", "folder")}
            item["downloaded"] = self.downloaded(m["id"])
            item["problem"] = self.supported(m["id"])
            item["extra_size"] = CUDA_SIZE if (m["gpu"] and IS_WINDOWS and not self.cuda_ready()) else 0
            models.append(item)
        free = None
        try:
            os.makedirs(self.root, exist_ok=True)
            free = shutil.disk_usage(self.root).free
        except OSError:
            pass
        settings = self.settings() or {}
        with self._engine_lock:
            loaded = self._loaded_id if self._engine is not None else ""
        return {
            "supported": any(not m["problem"] for m in models),
            "models": models,
            "model": settings.get("model") or DEFAULT_MODEL,
            "active_model": self.chosen_model(),
            "loaded_model": loaded,
            "vram_mb": self._vram_mb if loaded else None,
            "idle": settings.get("idle") or DEFAULT_IDLE,
            "problem": self.problem(),
            "job": job,
            "free_bytes": free,
            "folder": self.root,
            "streams": len(self._streams),
        }

    def gpu_usage(self):
        """For the GPU graph: what the loaded model holds on the card."""
        with self._engine_lock:
            if self._engine is None or not getattr(self._engine, "on_gpu", False):
                return None
            return {"model": MODELS_BY_ID[self._loaded_id]["model"], "vram_mb": self._vram_mb}

    # --------------------------------------------------------------- download

    def start_download(self, model_id, again=False):
        model = MODELS_BY_ID.get(model_id)
        if not model:
            raise DictationError("Pick Small, Medium or Large.")
        reason = self.supported(model_id)
        if reason:
            raise DictationError(reason)
        with self._job_lock:
            if self._job.get("state") in ("checking", "model", "cuda"):
                raise DictationError("A download is already running.")
            need = model["size"] + (CUDA_SIZE if model["gpu"] and IS_WINDOWS and (again or not self.cuda_ready()) else 0)
            try:
                os.makedirs(self.root, exist_ok=True)
                free = shutil.disk_usage(self.root).free
            except OSError:
                free = None
            if free is not None and free < need * 1.6 + 200_000_000:   # the wheels unpack beside themselves
                raise DictationError(f"There isn't room on the drive: it needs about {need * 1.6 / 1e9:.1f} GB "
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
        staging = None
        try:
            done = 0
            os.makedirs(os.path.join(self.root, "models"), exist_ok=True)
            if model["gpu"] and IS_WINDOWS and (again or not self.cuda_ready()):
                self._set_job(state="cuda")
                done = self._download_cuda(done)
            self._set_job(state="model")
            staging = os.path.join(self.root, "models", f".{model['id']}-{uuid.uuid4().hex[:8]}")
            os.makedirs(staging)
            for f in model["files"]:
                url = HF.format(repo=model["repo"], name=f["name"])
                done = self._fetch(url, os.path.join(staging, f["name"]), f["size"], f["sha256"], done)
            with open(os.path.join(staging, ".complete"), "w", encoding="utf-8") as fh:
                fh.write(time.strftime("%Y-%m-%d %H:%M:%S"))
            # Swapped in whole, so a half-download is never mistaken for a model.
            target = self.model_dir(model["id"])
            with self._engine_lock:
                if self._loaded_id == model["id"]:
                    self._close_streams_locked()
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
            self._set_job(state="done", done=self._job.get("total", done))
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

    def _download_cuda(self, done):
        """NVIDIA's libraries: the two wheels, checked, then only their DLLs kept."""
        staging = os.path.join(self.root, f".cuda-{uuid.uuid4().hex[:8]}")
        os.makedirs(staging)
        try:
            out = os.path.join(staging, "cuda")
            os.makedirs(out)
            for w in CUDA_WHEELS:
                wheel = os.path.join(staging, w["name"])
                done = self._fetch(w["url"], wheel, w["size"], w["sha256"], done)
                with zipfile.ZipFile(wheel) as z:
                    for info in z.infolist():
                        name = info.filename.replace("\\", "/")
                        if re.fullmatch(r"nvidia/[^/]+/bin/[^/]+\.dll", name, re.I):
                            with z.open(info) as src, open(os.path.join(out, os.path.basename(name)), "wb") as dst:
                                shutil.copyfileobj(src, dst, 1024 * 1024)
                os.remove(wheel)
            with open(os.path.join(out, ".complete"), "w", encoding="utf-8") as fh:
                fh.write(time.strftime("%Y-%m-%d %H:%M:%S"))
            if os.path.isdir(self.cuda_dir):
                shutil.rmtree(self.cuda_dir, ignore_errors=True)
            os.replace(out, self.cuda_dir)
            register_cuda(self.cuda_dir)
            return done
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    def _fetch(self, url, target, size, sha256, done):
        """One file, counted into the progress, then checked."""
        digest = hashlib.sha256() if sha256 else None
        try:
            with requests.get(url, stream=True, timeout=(15, 60), headers={"User-Agent": "Frivo"}) as r:
                if r.status_code != 200:
                    raise DictationError(f"The download site answered {r.status_code} for {os.path.basename(target)}.")
                with open(target, "wb") as out:
                    for chunk in r.iter_content(chunk_size=256 * 1024):
                        if self._cancel.is_set():
                            raise DictationError("Cancelled.")
                        if chunk:
                            out.write(chunk)
                            if digest:
                                digest.update(chunk)
                            done += len(chunk)
                            self._set_job(done=done)
        except requests.RequestException as e:
            raise DictationError(f"The download site couldn't be reached from the PC Frivo runs on ({e.__class__.__name__}).")
        if size is not None and os.path.getsize(target) != size:
            raise DictationError(f"{os.path.basename(target)} didn't download completely. Try again.")
        if digest and digest.hexdigest() != sha256:
            raise DictationError(f"{os.path.basename(target)} doesn't match its checksum, so it wasn't kept. Try again.")
        return done

    def remove(self, model_id=None):
        """One model, or everything (model_id None)."""
        with self._engine_lock:
            if model_id is None or self._loaded_id == model_id:
                self._close_streams_locked()
                self._unload_locked()
            path = self.model_dir(model_id) if model_id else self.root
            if path and os.path.isdir(path):
                shutil.rmtree(path, ignore_errors=True)
            if path and os.path.isdir(path):
                raise DictationError("Some of its files are still in use. Restart Frivo, then remove it.")
            # NVIDIA's libraries go with Large, the only one that uses them.
            if model_id == "large" and os.path.isdir(self.cuda_dir):
                shutil.rmtree(self.cuda_dir, ignore_errors=True)

    # ----------------------------------------------------------------- engine

    def _load_locked(self):
        model_id = self.chosen_model()
        if self._engine is not None and self._loaded_id == model_id:
            return self._engine
        reason = self.supported(model_id)
        if reason:
            raise DictationError(reason)
        if not self.downloaded(model_id):
            raise DictationError("Built-in dictation isn't downloaded.")
        self._close_streams_locked()
        self._unload_locked()
        model = MODELS_BY_ID[model_id]
        before = self.gpu_reader() if model["gpu"] else None
        started = time.perf_counter()
        try:
            self._engine = ENGINES[model["engine"]](self.model_dir(model_id), default_threads())
        except DictationError:
            raise
        except Exception as e:
            raise DictationError(f"{model['model']} couldn't start ({str(e)[:160]}).") from e
        self._loaded_id = model_id
        self._vram_mb = None
        if model["gpu"]:
            after = self.gpu_reader()
            if before is not None and after is not None:
                self._vram_mb = max(0, int(after - before))
        self.log(f"Built-in dictation: loaded {model['model']} in {time.perf_counter() - started:.1f}s"
                 + (f" ({self._vram_mb} MB on the graphics card)" if self._vram_mb is not None else ""))
        return self._engine

    def _unload_locked(self):
        if self._engine is not None:
            try:
                self._engine.close()
            except Exception:
                pass
        self._engine = None
        self._loaded_id = None
        self._vram_mb = None

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
            if (self._engine is not None and idle and not self._streams
                    and now - self._last_used > idle):
                self._unload_locked()
                self.log("Built-in dictation: freed its memory after being idle")

    # ---------------------------------------------------------------- streams

    @staticmethod
    def _samples(pcm):
        """16-bit little-endian mono PCM -> float32 samples."""
        np = _np()
        if np is None:
            raise DictationError("Built-in dictation needs numpy. Run Frivo's setup again (Repair).")
        pcm = pcm[: len(pcm) - (len(pcm) % 2)]
        return np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0

    @staticmethod
    def _language(language):
        """"en" from "en-US", or None for automatic."""
        text = str(language or "").strip().lower()
        if not text or text == "auto":
            return None
        code = re.split(r"[-_]", text)[0]
        return code if re.fullmatch(r"[a-z]{2,3}", code) else None

    def open_stream(self, language=None, max_seconds=None):
        """CHANGED (2.0.0): max_seconds finishes a line that goes on that long
        without a pause (Listening's "Commit every"; dictation leaves it)."""
        if max_seconds is not None:
            max_seconds = max(2.0, min(float(max_seconds), MAX_SENTENCE_SECONDS))
        with self._engine_lock:
            if len(self._streams) >= MAX_STREAMS:
                oldest = min(self._streams, key=lambda s: self._streams[s]["last"])
                self._close_stream_locked(oldest)
            engine = self._load_locked()
            sid = uuid.uuid4().hex
            stream = engine.stream(self._language(language), max_seconds) if max_seconds else engine.stream(self._language(language))
            self._streams[sid] = {"stream": stream, "last": time.time(),
                                  "model": self._loaded_id}
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
        samples = self._samples(pcm)
        with self._engine_lock:
            entry = self._get_stream_locked(sid)
            entry["stream"].add(samples)
            entry["last"] = self._last_used = time.time()
            return entry["stream"].lines()

    def stop_stream(self, sid, pcm=b""):
        """The last of the audio, then the final lines."""
        samples = self._samples(pcm) if pcm else None
        with self._engine_lock:
            entry = self._streams.get(sid)
            if entry is None:
                return []
            try:
                if entry["model"] != self._loaded_id:
                    return []
                if samples is not None and len(samples):
                    entry["stream"].add(samples)
                entry["stream"].stop()
                lines = entry["stream"].lines()
            finally:
                self._close_stream_locked(sid)
            self._last_used = time.time()
            return [dict(l, complete=True) for l in lines if l["text"]]

    def _close_stream_locked(self, sid):
        self._streams.pop(sid, None)

    def _close_streams_locked(self):
        self._streams.clear()

    def transcribe(self, pcm, language=None):
        """A whole clip at once (16-bit PCM): Test. Returns (text, seconds,
        seconds it took to load)."""
        if len(pcm) > MAX_TEST_BYTES:
            raise DictationError("That's longer than a test needs.")
        samples = self._samples(pcm)
        with self._engine_lock:
            t = time.perf_counter()
            engine = self._load_locked()
            loaded = time.perf_counter() - t
            t = time.perf_counter()
            text = clean_text(engine.transcribe(samples, self._language(language), final=True))
            took = time.perf_counter() - t
            self._last_used = time.time()
            return text, took, loaded
