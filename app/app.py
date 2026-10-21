# === app.py ===
# RYZEN SERVER  ->  voice_chat_web\app.py
"""
Voice Chat App — Web version
-----------------------------
Type a prompt, GPT replies, ElevenLabs speaks it.

Features:
  - Voice picker populated from your ElevenLabs account
  - Profiles: saved voice + personality presets, each with its own history
  - Reply length target in words. The model writes to that target and
    finishes its thought; the full reply is what gets spoken.
  - Response style + personality presets, so you don't have to type
    "translate this exactly" or a personality description into every
    profile — pick them from a list instead. The personality box can be
    left blank; the selected preset fills in for it.
  - Dictation: click the mic button to speak your message instead of typing
    it. Requires a secure context (HTTPS, or localhost) — see below.

Length handling:
  The word target is a writing instruction, not a cut-off. The model is
  asked to land near the target and complete its final sentence. max_tokens
  is set well above the target purely as a runaway guard, so normal replies
  never bump into it. In the rare case a reply does hit that ceiling and
  comes back clipped, it's rolled back to the last complete sentence — so
  nothing mid-sentence ever reaches ElevenLabs.

Setup:
1. pip install -r requirements.txt
   (make sure `cryptography` and `cheroot` are among them — the first
   enables HTTPS, the second is what actually serves it reliably)
2. python app.py
3. The server starts over HTTPS with a self-signed certificate (needed for
   the dictation mic button to work from devices other than localhost —
   browsers block microphone access entirely on plain HTTP otherwise).
   Open the https://<server-ip>:5000 URL printed in the terminal; each
   device's browser will show a one-time "not private" warning to click
   through — that's expected for a self-signed cert on a private network.
   If a browser won't let you click through (managed Chrome/Edge profiles
   can disable that link by policy), install cert.pem on that device into
   "Trusted Root Certification Authorities" and the warning disappears.
   Add your API keys under Settings once it loads.
   Set VOICE_CONSOLE_HTTP=1 to run plain HTTP instead (dictation then only
   works when opened as http://localhost:5000 on this machine).

IMPORTANT: There is no login/auth built in. Anyone who can reach the port
can use your API keys and rack up charges. Keep it on a trusted private
network. See README.md for options to lock it down.
"""

import json
import os
import queue
import re
import shutil  # NEW (1.5.0): finding PowerShell for Windows voices
import signal
import socket
import struct
import subprocess  # NEW (updates): schtasks and the relaunch watcher
import sys
import time
import uuid
import tempfile  # NEW (1.5.0): adding your own voices
import threading

from flask import Flask, request, jsonify, render_template, send_from_directory, redirect, g, Response  # CHANGED (1.5.0): g, Response
from urllib.parse import urlsplit
import requests
from openai import OpenAI

# The product name, used for the window title, the data directory and the
# console banner. Defined once so renaming is a one-line change.
APP_NAME = "Frivo"

BASE_DIR = os.path.dirname(__file__)


def _dir_is_writable(path):
    """Can this process actually create a file here? Asked, not assumed."""
    if not path:
        path = "."
    try:
        probe = os.path.join(path, f".write-test-{uuid.uuid4().hex}")
        with open(probe, "w") as f:
            f.write("")
        os.remove(probe)
        return True
    except OSError:
        return False


def _under_program_files(path):
    """True when path sits inside either Program Files directory."""
    probe = os.path.abspath(path).lower().rstrip("\\/") + os.sep
    for env in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432"):
        root = os.environ.get(env)
        if root and probe.startswith(os.path.abspath(root).lower().rstrip("\\/") + os.sep):
            return True
    return False


def _resolve_data_dir():
    """
    Where everything this app *writes* goes: settings, profiles, the daily
    usage ledger, generated audio, the TLS certificate and the log.

    Program files and user data are separated only when they have to be.
    Run from a folder you own — a git checkout, an unzipped copy — and
    everything stays together next to app.py, which is easier to find and
    is how every previous version behaved. Installed somewhere managed,
    like C:\\Program Files, that folder isn't writable, so the data moves
    to the per-user application-data directory instead. Writing there is
    also the correct thing on Windows for anything user-specific.

    VOICE_CONSOLE_DATA overrides both, for anyone who wants the data on a
    different drive.
    """
    override = os.environ.get("VOICE_CONSOLE_DATA", "").strip()
    if override:
        return os.path.abspath(override)

    # No os.name gate: the ProgramFiles variables only exist on Windows, so
    # this is a no-op everywhere else — and staying platform-neutral lets
    # the test suite exercise it.
    if _under_program_files(BASE_DIR):
        # Never keep data inside Program Files, even when it happens to be
        # writable. It IS writable exactly once: while the installer runs
        # elevated — and trusting the writability probe there made the
        # installer's certificate land next to app.py while the app, run
        # normally later, looked in %APPDATA% and generated a second,
        # different one. Installed copies always use the per-user folder.
        root = os.environ.get("APPDATA") or os.path.expanduser("~")
        return os.path.join(root, APP_NAME)

    if _dir_is_writable(BASE_DIR):
        return BASE_DIR

    if os.name == "nt":
        root = os.environ.get("APPDATA") or os.path.expanduser("~")
        return os.path.join(root, APP_NAME)
    return os.path.join(
        os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config"),
        APP_NAME.lower(),
    )


def _legacy_data_dirs():
    """
    Where earlier versions kept their data. Read once, on the first run
    that finds nothing in the current location, so a rename or a move to
    Program Files never looks like a factory reset.
    """
    dirs = [BASE_DIR]
    if os.name == "nt":
        root = os.environ.get("APPDATA") or os.path.expanduser("~")
        dirs.append(os.path.join(root, "Voice Console"))
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
        dirs.append(os.path.join(base, "voice-console"))
    return dirs


DATA_DIR = _resolve_data_dir()
try:
    os.makedirs(DATA_DIR, exist_ok=True)
except OSError:
    # Last resort. Not the working directory: launched from Program Files,
    # or by a scheduled task from C:\Windows\System32, that is exactly as
    # unwritable as the place that just failed, and the app would die on
    # import instead of starting somewhere usable.
    import tempfile

    DATA_DIR = os.path.join(tempfile.gettempdir(), APP_NAME)
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
    except OSError:
        DATA_DIR = tempfile.gettempdir()

def _migrate_legacy_data():
    """
    Carries settings forward from wherever a previous version kept them:
    beside app.py (which is where everything lived before this app could be
    installed into Program Files), and under the application's former name.

    Only ever copies, never moves. The old copy staying put means a botched
    upgrade can be undone by going back to the previous version.
    """
    for legacy in _legacy_data_dirs():
        if not legacy or os.path.abspath(legacy) == os.path.abspath(DATA_DIR):
            continue
        for name in ("config.json", "profiles.json", "usage.json"):
            old_path = os.path.join(legacy, name)
            new_path = os.path.join(DATA_DIR, name)
            if os.path.exists(new_path) or not os.path.exists(old_path):
                continue
            try:
                with open(old_path, "rb") as src, open(new_path, "wb") as dst:
                    dst.write(src.read())
            except OSError:
                # Not fatal: a fresh file gets written in its place. Losing
                # the old settings is bad; refusing to start is worse.
                pass


_migrate_legacy_data()

CONFIG_PATH = os.path.join(DATA_DIR, "config.json")
PROFILES_PATH = os.path.join(DATA_DIR, "profiles.json")
USAGE_PATH = os.path.join(DATA_DIR, "usage.json")
AUDIO_DIR = os.path.join(DATA_DIR, "audio_cache")
# The server's own certificate and key — what gets presented to browsers.
CERT_PATH = os.path.join(DATA_DIR, "cert.pem")
KEY_PATH = os.path.join(DATA_DIR, "key.pem")

# Local certificate authority used to sign the server certificate. ca.crt is
# provided for Windows certificate import.
CA_CERT_PATH = os.path.join(DATA_DIR, "ca.pem")
CA_CERT_CRT_PATH = os.path.join(DATA_DIR, "ca.crt")
CA_KEY_PATH = os.path.join(DATA_DIR, "ca-key.pem")

# Local provider defaults used while configuration loads.
DEFAULT_OLLAMA_URL = "http://localhost:11434"
DEFAULT_OLLAMA_MODEL = "llama3.1:8b"
# NEW (1.5.0): three Ollama models to switch between: quickest, a middle
# one, and the best one. "ollama_model" stays the Fast one, so a config
# from before this keeps the model it had.
OLLAMA_TIERS = [("fast", "Fast"), ("balanced", "Balanced"), ("best", "Best")]
OLLAMA_TIER_KEYS = {"fast": "ollama_model", "balanced": "ollama_model_balanced", "best": "ollama_model_best"}
# NEW (1.5.0): how long Ollama keeps a model on the graphics card after the
# last reply, before handing the memory back. Ollama's own idle timer does
# it, so it counts from the last request and every reply restarts it.
OLLAMA_IDLE_UNLOAD = {"15m": "15 minutes", "1h": "1 hour", "4h": "4 hours", "never": "Never"}
DEFAULT_OLLAMA_IDLE_UNLOAD = "1h"
# NEW (1.5.0): Evora's two idle timers (see Evora's evora_idle.py): its
# listening models after listening stops, and speech-to-text after no
# dictation or listening. In minutes for Evora; 0 is never.
EVORA_IDLE_LISTEN = {"5m": 5, "15m": 15, "1h": 60, "never": 0}
EVORA_IDLE_SPEECH = {"15m": 15, "1h": 60, "4h": 240, "never": 0}
# CHANGED (1.5.0): Never, unless you turn them on. On a card Evora shares
# with Ollama, memory Evora gave up was memory Ollama took, and listening
# couldn't get it back: slow, or no speaker labels at all.
DEFAULT_EVORA_IDLE_LISTEN = "never"
DEFAULT_EVORA_IDLE_SPEECH = "never"
OLLAMA_TIER_DEFAULTS = {"fast": DEFAULT_OLLAMA_MODEL, "balanced": "qwen3.5:4b", "best": "qwen3.5:9b"}
DEFAULT_WHISPER_URL = "http://localhost:9000"

# How long to wait on a local service before deciding it isn't there. Short,
# because the whole point of the fallback is that a powered-off GPU box
# shouldn't leave you staring at a spinner.
LOCAL_CONNECT_TIMEOUT = 4
LOCAL_READ_TIMEOUT = 180

# A single Evora model cannot usefully process overlapping clips. Live
# listening can otherwise send an in-progress clip and its final replacement
# together, filling Evora's worker pool while the GPU works through a backlog.
EVORA_TRANSCRIPTION_LOCK = threading.Lock()

SERVER_LOG_PATH = os.path.join(DATA_DIR, "server.log")
SERVER_LOG_LOCK = threading.Lock()

# Filled in at startup — which HTTP server is actually handling requests.
SERVER_BACKEND = "not started"


def log_server_event(message):
    """Appends a timestamped line to server.log, never raising."""
    try:
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with SERVER_LOG_LOCK:
            with open(SERVER_LOG_PATH, "a", encoding="utf-8") as f:
                f.write(f"[{stamp}] {message}\n")
    except Exception:
        pass
try:
    os.makedirs(AUDIO_DIR, exist_ok=True)
except OSError as e:
    # Generated speech is a cache; not being able to make it is a reason to
    # complain, not a reason to refuse to start.
    print(f"Warning: could not create the audio cache at {AUDIO_DIR}: {e}")

# Bounds for the reply-length control, in words
MIN_WORDS = 15
MAX_WORDS = 400

# Languages supported by eleven_multilingual_v2. "chars" is the rough number
# of characters per word in that language, used only to estimate credit cost
# in the UI — ElevenLabs bills per character, so this varies a lot by language.
# `speech` is the BCP-47 tag handed to the browser's speech recogniser for
# live dictation, so speaking Japanese into the box transcribes as Japanese
# rather than as mangled English.
LANGUAGES = [
    # "region" only groups the dropdown. A flat list of 29 is a wall of text
    # to scan; grouped, you look in one place and find it.
    {"name": "English", "native": "English", "chars": 6.0, "speech": "en-US", "region": "Western Europe"},
    {"name": "German", "native": "Deutsch", "chars": 7.5, "speech": "de-DE", "region": "Western Europe"},
    {"name": "Spanish", "native": "Español", "chars": 6.5, "speech": "es-ES", "region": "Western Europe"},
    {"name": "French", "native": "Français", "chars": 6.5, "speech": "fr-FR", "region": "Western Europe"},
    {"name": "Italian", "native": "Italiano", "chars": 6.8, "speech": "it-IT", "region": "Western Europe"},
    {"name": "Portuguese", "native": "Português", "chars": 6.5, "speech": "pt-PT", "region": "Western Europe"},
    {"name": "Dutch", "native": "Nederlands", "chars": 7.0, "speech": "nl-NL", "region": "Western Europe"},
    {"name": "Polish", "native": "Polski", "chars": 7.5, "speech": "pl-PL", "region": "Central & Eastern Europe"},
    {"name": "Russian", "native": "Русский", "chars": 7.0, "speech": "ru-RU", "region": "Central & Eastern Europe"},
    {"name": "Ukrainian", "native": "Українська", "chars": 7.0, "speech": "uk-UA", "region": "Central & Eastern Europe"},
    {"name": "Czech", "native": "Čeština", "chars": 7.0, "speech": "cs-CZ", "region": "Central & Eastern Europe"},
    {"name": "Slovak", "native": "Slovenčina", "chars": 7.0, "speech": "sk-SK", "region": "Central & Eastern Europe"},
    {"name": "Croatian", "native": "Hrvatski", "chars": 7.0, "speech": "hr-HR", "region": "Central & Eastern Europe"},
    {"name": "Bulgarian", "native": "Български", "chars": 7.0, "speech": "bg-BG", "region": "Central & Eastern Europe"},
    {"name": "Romanian", "native": "Română", "chars": 7.0, "speech": "ro-RO", "region": "Central & Eastern Europe"},
    {"name": "Greek", "native": "Ελληνικά", "chars": 7.5, "speech": "el-GR", "region": "Central & Eastern Europe"},
    {"name": "Swedish", "native": "Svenska", "chars": 7.0, "speech": "sv-SE", "region": "Nordic"},
    {"name": "Danish", "native": "Dansk", "chars": 6.8, "speech": "da-DK", "region": "Nordic"},
    {"name": "Finnish", "native": "Suomi", "chars": 8.5, "speech": "fi-FI", "region": "Nordic"},
    {"name": "Turkish", "native": "Türkçe", "chars": 7.5, "speech": "tr-TR", "region": "Middle East & South Asia"},
    {"name": "Arabic", "native": "العربية", "chars": 6.0, "speech": "ar-SA", "region": "Middle East & South Asia"},
    {"name": "Hindi", "native": "हिन्दी", "chars": 6.0, "speech": "hi-IN", "region": "Middle East & South Asia"},
    {"name": "Tamil", "native": "தமிழ்", "chars": 7.0, "speech": "ta-IN", "region": "Middle East & South Asia"},
    {"name": "Indonesian", "native": "Bahasa Indonesia", "chars": 7.0, "speech": "id-ID", "region": "Southeast Asia"},
    {"name": "Malay", "native": "Bahasa Melayu", "chars": 7.0, "speech": "ms-MY", "region": "Southeast Asia"},
    {"name": "Filipino", "native": "Filipino", "chars": 7.0, "speech": "fil-PH", "region": "Southeast Asia"},
    {"name": "Japanese", "native": "日本語", "chars": 2.5, "speech": "ja-JP", "region": "East Asia"},
    {"name": "Chinese", "native": "中文", "chars": 1.8, "speech": "zh-CN", "region": "East Asia"},
    {"name": "Korean", "native": "한국어", "chars": 3.0, "speech": "ko-KR", "region": "East Asia"},
]

LANGUAGE_NAMES = {lang["name"] for lang in LANGUAGES}

# Languages written without spaces between words — word counting works
# differently for these.
SPACELESS_LANGUAGES = {"Japanese", "Chinese"}

# ---------------------------------------------------------------------------
# Response styles + personality presets
#
# Two separate knobs:
#   - response_style: what happens to what you type. CHANGED (1.5.0): three
#     styles, from loosest to strictest —
#       "reply"  -> Reply: the persona answers it, in character.
#       "echo"   -> Clean up: what you meant to say, with typos, misheard
#                   words and grammar fixed and garbled bits made clear; the
#                   personality showing only in punctuation and emphasis.
#                   Checked after the model runs (cleanup_stays_on_message) and put
#                   back to your words if it reworded anything.
#       "mimic"  -> Word for word: exactly what you typed. No model at all in English;
#                   in any other language, only a literal translation.
#     The old "flair" (loose rewrite in character) and "Exact echo" styles
#     are gone; saved settings and profiles holding them read as Echo.
#   - personality_preset: which canned personality to use when the
#     personality text box is left blank. A saved custom personality always
#     wins over the preset.
# ---------------------------------------------------------------------------

RESPONSE_STYLES = [
    {
        "id": "reply",
        "name": "Reply",
        "description": "Type what someone said to you, and the persona answers it in character.",
    },
    {
        # The id stays "echo" so saved settings and profiles keep working.
        "id": "echo",
        "name": "Clean up",
        "description": "Says what you meant to say: typos, misheard words and grammar fixed, nothing added.",
    },
    {
        "id": "mimic",
        "name": "Word for word",
        "description": "Says exactly what you typed, untouched. Only translated when another language is selected.",
    },
]
RESPONSE_STYLE_IDS = {s["id"] for s in RESPONSE_STYLES}
DEFAULT_RESPONSE_STYLE = "echo"
# NEW (1.5.0): styles that no longer exist, and what they read as now.
# (Names on screen are Reply / Clean up / Word for word; the ids are older.)
RESPONSE_STYLE_ALIASES = {"flair": "echo"}

PERSONALITY_PRESETS = [
    {
        "id": "neutral",
        "name": "Neutral (no personality)",
        "prompt": (
            "Speak in a plain, neutral, natural voice. Do not add exaggeration, "
            "jokes, or commentary — just convey it clearly and naturally, the way "
            "a normal person would say it aloud."
        ),
    },
    {
        "id": "sarcastic_friend",
        "name": "Sarcastic Friend",
        "prompt": (
            "Deliver this with dry wit and light sarcasm, like a close friend "
            "teasing you — a little attitude, a little eye-roll, but still warm "
            "underneath it."
        ),
    },
    {
        "id": "late_night_dj",
        "name": "Late-Night DJ",
        "prompt": (
            "Speak like a smooth late-night radio DJ — relaxed, low and cool, "
            "unhurried, like you're talking to one listener at 2am."
        ),
    },
    {
        "id": "hype_man",
        "name": "Hype Man",
        "prompt": (
            "Deliver this with huge, over-the-top hype and energy, like a hype "
            "man firing up a crowd before the headliner comes out."
        ),
    },
    {
        "id": "robot",
        "name": "Robot Assistant",
        "prompt": (
            "Speak in a precise, clipped, matter-of-fact tone, like a helpful "
            "but slightly robotic AI assistant reporting information."
        ),
    },
    {
        "id": "noir_narrator",
        "name": "Noir Narrator",
        "prompt": (
            "Speak like a world-weary film noir detective narrating over a "
            "rainy city street — moody, deliberate, with dramatic pauses."
        ),
    },
    {
        "id": "wise_mentor",
        "name": "Wise Mentor",
        "prompt": (
            "Speak like a calm, patient mentor offering thoughtful guidance — "
            "measured, warm, a little sage."
        ),
    },
    {
        "id": "grumpy_old_man",
        "name": "Grumpy Old Man",
        "prompt": (
            "Speak like a grumpy old man who's mildly annoyed by everything but "
            "says it anyway — gruff, blunt, a bit of a groan in it."
        ),
    },
    {
        "id": "chipper_assistant",
        "name": "Chipper Assistant",
        "prompt": (
            "Speak brightly and cheerfully, upbeat and encouraging, like an "
            "enthusiastic personal assistant who's genuinely excited to help."
        ),
    },
    {
        "id": "posh_butler",
        "name": "Posh Butler",
        "prompt": (
            "Speak like an impeccably polite, formal butler — refined "
            "vocabulary, unfailingly courteous, with faintly dry humor."
        ),
    },
]
PERSONALITY_PRESET_MAP = {p["id"]: p for p in PERSONALITY_PRESETS}
DEFAULT_PERSONALITY_PRESET = "neutral"


def normalize_response_style(value, fallback=DEFAULT_RESPONSE_STYLE):
    # CHANGED (1.5.0): a style that was renamed or folded into another reads
    # as its replacement, so old settings and profiles keep working.
    value = RESPONSE_STYLE_ALIASES.get(value, value)
    if value in RESPONSE_STYLE_IDS:
        return value
    return RESPONSE_STYLE_ALIASES.get(fallback, fallback)


def normalize_personality_preset(value, fallback=DEFAULT_PERSONALITY_PRESET):
    if value in PERSONALITY_PRESET_MAP:
        return value
    return fallback


def resolve_personality_text(system_prompt, personality_preset):
    """
    A saved custom personality (the text box) always wins. If it's blank,
    fall back to whichever preset was selected — this is what lets the
    personality box stay empty.
    """
    if system_prompt and system_prompt.strip():
        return system_prompt.strip()
    preset = PERSONALITY_PRESET_MAP.get(personality_preset) or PERSONALITY_PRESET_MAP[DEFAULT_PERSONALITY_PRESET]
    return preset["prompt"]


# ---------------------------------------------------------------------------
# Chat model catalog
#
# The "text" model writes the actual reply (echo/flair/reply). The
# "translation" model only handles the small English-translation side task
# (the ---EN--- line, and the hover-to-translate fallback) — a much simpler
# job, so a cheaper/smaller model is normally the right call there even when
# a bigger model is picked for text.
#
# Prices are USD per 1M tokens and are used only for approximate UI estimates.
# Users are billed directly by their provider. Speed tiers are estimates.
# ---------------------------------------------------------------------------

TEXT_MODELS = [
    {
        "id": "gpt-4.1-nano",
        "name": "GPT-4.1 Nano",
        "tier": "nano",
        "input_price": 0.10,
        "output_price": 0.40,
        "note": "Best for echo mode and translation — no personality to hold onto, so the cheapest reliable model does the job.",
    },
    {
        "id": "gpt-5-nano",
        "name": "GPT-5 Nano",
        "tier": "nano",
        "input_price": 0.05,
        "output_price": 0.40,
        "note": "Same use case as 4.1 Nano (echo/translation) — marginally cheaper input tokens, otherwise an equivalent pick.",
    },
    {
        "id": "gpt-4o-mini",
        "name": "GPT-4o Mini",
        "tier": "mini",
        "input_price": 0.15,
        "output_price": 0.60,
        "note": "Default for flair/reply — fast and reliable at following a personality without costing much.",
    },
    {
        "id": "gpt-4.1-mini",
        "name": "GPT-4.1 Mini",
        "tier": "mini",
        "input_price": 0.40,
        "output_price": 1.60,
        "note": "Try this if 4o Mini's replies feel generic — follows personality/tone instructions more precisely, for a bit more per token.",
    },
    {
        "id": "gpt-5-mini",
        "name": "GPT-5 Mini",
        "tier": "mini",
        "input_price": 0.25,
        "output_price": 2.00,
        "note": "Newer than 4.1 Mini with the same strengths — another option if a persona isn't landing on 4o Mini.",
    },
    {
        "id": "gpt-4.1",
        "name": "GPT-4.1",
        "tier": "standard",
        "input_price": 2.00,
        "output_price": 8.00,
        "note": "For reply mode when you want sharper, less generic conversation and don't mind the extra latency and cost.",
    },
    {
        "id": "gpt-4o",
        "name": "GPT-4o",
        "tier": "standard",
        "input_price": 2.50,
        "output_price": 10.00,
        "note": "Older flagship, generally outclassed by 4.1/5 now — mainly here for compatibility with existing setups.",
    },
    {
        "id": "gpt-5",
        "name": "GPT-5",
        "tier": "standard",
        "input_price": 1.25,
        "output_price": 10.00,
        "note": "Best overall reply quality on offer — reach for this in reply mode when the conversation itself matters most.",
    },
]
TEXT_MODEL_MAP = {m["id"]: m for m in TEXT_MODELS}

# Defaults compatible with the application's chat-completion request format.
RECOMMENDED_TEXT_MODEL = "gpt-4o-mini"
RECOMMENDED_TRANSLATION_MODEL = "gpt-4.1-nano"

MODEL_TIER_THROUGHPUT = {"nano": 110, "mini": 70, "standard": 40}  # rough tokens/sec, for the UI estimate only
MODEL_TIER_SPEED_LABEL = {"nano": "Fastest", "mini": "Fast", "standard": "Moderate"}

# Speech-to-text for the dictation button. gpt-4o-mini-transcribe is cheap
# and current; whisper-1 is the long-established fallback in case a given
# account/region doesn't have the newer model available.
TRANSCRIBE_MODEL = "gpt-4o-mini-transcribe"
TRANSCRIBE_FALLBACK_MODEL = "whisper-1"


def resolve_model_id(value, fallback):
    if isinstance(value, str) and value.strip():
        return value.strip()
    return fallback


app = Flask(__name__)

# Browsers cache /static/ files aggressively, and they cache per origin — so
# http://127.0.0.1:5000 and http://192.168.x.x:5000 keep *separate* copies.
# That means refreshing on one address doesn't clear the other, and an old
# app.js can keep being served to other machines long after the file changed.
# Disabling the cache here plus stamping the URLs below removes the problem.
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0

# Jinja compiles a template once per process and then never looks at the file
# again unless told to. With debug off — which is how Frivo always runs — that
# means editing index.html changes nothing until the server is restarted, and
# the symptom is a setting you added that simply is not on the page. The stat
# per render this costs is nothing next to the time lost to that.
app.config["TEMPLATES_AUTO_RELOAD"] = True

# Stamped onto the static URLs so a browser cannot reuse an old app.js. Taken
# from the newest file rather than from startup time, so it also moves when a
# file changes under a server that is already running.
_STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")


def asset_version():
    newest = 0.0
    try:
        for name in os.listdir(_STATIC_DIR):
            if name.endswith((".js", ".css")):
                newest = max(newest, os.path.getmtime(os.path.join(_STATIC_DIR, name)))
    except OSError:
        pass
    # Falls back to process start time if static/ cannot be read, which is
    # the old behaviour and still correct, just coarser.
    return str(int(newest or time.time()))


def app_version():
    """The number in the VERSION file at the repo root.

    The same file the installer, the Inno container and the compiled host
    read, so "which version is this?" has one answer everywhere. Read once
    at startup: it does not change while the server is running, and an
    install that is missing the file should still start.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    for candidate in (os.path.join(here, "VERSION"),
                      os.path.join(os.path.dirname(here), "VERSION")):
        try:
            with open(candidate, "r", encoding="utf-8") as handle:
                text = handle.read().strip()
            if text:
                return text
        except OSError:
            continue
    return "unknown"


APP_VERSION = app_version()

ASSET_VERSION = asset_version()

# Shown on the diagnostics page. A server started before the file you just
# edited is the single most common reason a new setting is not on the page.
SERVER_STARTED = time.strftime("%Y-%m-%d %H:%M:%S")


@app.after_request
def add_no_cache_headers(response):
    if request.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

SESSIONS = {}
SESSIONS_LOCK = threading.Lock()
PROFILES_LOCK = threading.Lock()


def load_config():
    cfg = {
        "openai_api_key": os.environ.get("OPENAI_API_KEY", ""),
        "elevenlabs_api_key": os.environ.get("ELEVENLABS_API_KEY", ""),
        "voice_id": "21m00Tcm4TlvDq8ikWAM",
        "voice_name": "Rachel",
        "model": RECOMMENDED_TEXT_MODEL,
        "translation_model": RECOMMENDED_TRANSLATION_MODEL,
        # Left blank by default so a fresh install uses the personality
        # preset below instead. Fill this in to override the preset.
        "system_prompt": "",
        "response_style": DEFAULT_RESPONSE_STYLE,
        "personality_preset": DEFAULT_PERSONALITY_PRESET,
        "max_words": 80,
        "language": "English",
        # How fast the voice talks. 1.0 is ElevenLabs' natural pace.
        "speaking_speed": 1.0,
        # NEW (1.5.0): Expressive voice (audio tags) and Delivery, for the
        # default profile. Each profile has its own.
        "expressive_voice": False,
        "voice_delivery": "natural",
        "tag_amount": "normal",   # NEW (1.5.0)
        # NEW (1.5.0): continuity between v3 lines (see _elevenlabs_payload).
        # CHANGED (1.5.0): Off by default. Anchor and Follow hold the accent
        # by pulling every line toward another recording, which dulls the
        # tags; v4 and its Similarity setting hold it without that.
        "hold_accent": "off",
        "expressive_model": "eleven_v4",   # NEW (1.5.0)
        # NEW (1.5.0): the Tags model speaks every line, not only the ones
        # with tags, so the voice sounds the same either way.
        "expressive_every_line": True,
        # NEW (1.5.0): ElevenLabs replies start playing as they're made.
        "elevenlabs_streaming": True,
        "voice_accent": "auto",   # NEW (1.5.0): the accent the anchor is made in
        # NEW (1.5.0): Tag words (see DEFAULT_TAG_WORDS); None means the defaults.
        "tag_words": None,
        # Sampling temperature for the reply. 0.7 is the long-standing
        # OpenAI default and what this app used implicitly before the
        # setting was exposed, so an existing config behaves identically.
        "temperature": 0.7,
        # 0 = derive the ceiling from the reply-length target, which is the
        # behaviour every version before this one had. A non-zero value is
        # an explicit override.
        "max_tokens": 0,
        # Providers. Every default here is the pre-provider behaviour, so a
        # config.json written before this existed loads unchanged and keeps
        # using OpenAI for everything.
        "chat_provider": "openai",
        "translation_provider": "openai",
        "transcription_provider": "openai",
        "ollama_url": DEFAULT_OLLAMA_URL,
        "ollama_model": DEFAULT_OLLAMA_MODEL,
        # NEW (1.5.0): the Balanced and Best models, and which of the three is in use.
        "ollama_model_balanced": OLLAMA_TIER_DEFAULTS["balanced"],
        "ollama_model_best": OLLAMA_TIER_DEFAULTS["best"],
        "ollama_tier": "fast",
        "ollama_idle_unload": DEFAULT_OLLAMA_IDLE_UNLOAD,   # NEW (1.5.0)
        "evora_idle_listen": DEFAULT_EVORA_IDLE_LISTEN,     # NEW (1.5.0)
        "evora_idle_speech": DEFAULT_EVORA_IDLE_SPEECH,     # NEW (1.5.0)
        # Blank uses the chat model for translation.
        "ollama_translation_model": "",
        "whisper_url": DEFAULT_WHISPER_URL,
        # Optional local command configured by the administrator.
        # Optional OpenAI fallback when a selected local provider is unavailable.
        "allow_openai_fallback": False,
        # VRChat, through FrivOSC. Frivo no longer speaks OSC itself —
        # FrivOSC runs on the VRChat PC and owns the protocol, the ports
        # and the paging. All that is left here is whether the feature is
        # on, so there is no address or port for anyone to get wrong.
        "osc_enabled": False,
        # Independent of the chatbox on purpose: sending replies to VRChat
        # and letting VRChat's mute button drive dictation are two separate
        # things to want, and one of them takes over your microphone.
        "osc_mute_sync": False,
        # Unmutes the VRChat microphone when you send a message, so a
        # spoken reply is not delivered into a muted mic. Its own switch
        # because it presses a virtual key in VRChat, which the other two
        # never do.
        "osc_unmute_on_send": False,
        # NEW (typing): VRChat's typing dots above your head while you are
        # responding — talking with dictation on, or with unsent text in the
        # message box. Only ever shown with the chatbox switched on.
        "osc_typing": True,
        # NEW (updates): look for a newer Frivo a few seconds after starting
        # and every six hours after that. Only ever shows a chip; installing
        # is always a click.
        "update_auto_check": True,
        # NEW (updates): "Skip this version". The chip stays away until a
        # release newer than this one comes out.
        "update_skipped": "",
        # NEW (1.5.0): spoken replies older than this are deleted from
        # audio_cache. 0 keeps them all.
        "audio_keep_days": 7,
    }
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                saved = json.load(f)
            # Older versions stored a character cap; convert it once so the
            # slider doesn't reset to default on upgrade.
            if "max_words" not in saved and "max_chars" in saved:
                saved["max_words"] = max(MIN_WORDS, min(MAX_WORDS, int(saved["max_chars"]) // 6))
            saved.pop("max_chars", None)
            cfg.update(saved)
        except Exception:
            pass
    return cfg


def save_config(cfg):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)


def load_profiles():
    if os.path.exists(PROFILES_PATH):
        try:
            with open(PROFILES_PATH, "r", encoding="utf-8") as f:
                profiles = json.load(f)
        except Exception:
            return []
        # NEW (1.5.0): a profile saved with a style that no longer exists
        # ("flair") shows and works as its replacement.
        for profile in profiles if isinstance(profiles, list) else []:
            if isinstance(profile, dict) and "response_style" in profile:
                profile["response_style"] = normalize_response_style(profile.get("response_style"))
        return profiles
    return []


def save_profiles(profiles):
    with open(PROFILES_PATH, "w", encoding="utf-8") as f:
        json.dump(profiles, f, indent=2)


CFG = load_config()
# NEW (1.5.0): once, when v4 arrived: Hold the accent goes back to Off (it
# dulled the tags), and expressive lines move to v4.
if not CFG.get("_moved_to_v4"):
    CFG["hold_accent"] = "off"
    CFG["expressive_model"] = "eleven_v4"
    CFG["_moved_to_v4"] = True
    try:
        save_config(CFG)
    except Exception:
        pass
# NEW (1.5.0): once: Evora's idle timers go back to Never (the old defaults
# starved Evora on a shared card). Set them again in Settings > Evora if
# you want them.
if not CFG.get("_evora_idle_off"):
    CFG["evora_idle_listen"] = "never"
    CFG["evora_idle_speech"] = "never"
    CFG["_evora_idle_off"] = True
    try:
        save_config(CFG)
    except Exception:
        pass


def clamp_words(value, fallback=80):
    try:
        n = int(value)
    except (TypeError, ValueError):
        return fallback
    return max(MIN_WORDS, min(MAX_WORDS, n))


# ElevenLabs accepts a speed multiplier inside voice_settings. Outside this
# range it rejects the request outright, and even near the edges the voice
# starts to sound artefacted, so this is the API's own documented window
# rather than a taste judgement.
MIN_SPEAKING_SPEED = 0.7
MAX_SPEAKING_SPEED = 1.2


def clamp_speaking_speed(value, fallback=1.0):
    try:
        speed = float(value)
    except (TypeError, ValueError):
        return fallback
    return max(MIN_SPEAKING_SPEED, min(MAX_SPEAKING_SPEED, speed))


def clamp_temperature(value, fallback=0.7):
    try:
        temp = float(value)
    except (TypeError, ValueError):
        return fallback
    return max(0.0, min(2.0, temp))


def clamp_max_tokens(value, fallback=0):
    """
    0 means "work it out from the reply-length target", which is what this
    app did before the setting existed and remains the default. Anything
    else is an explicit ceiling.
    """
    try:
        n = int(value)
    except (TypeError, ValueError):
        return fallback
    if n <= 0:
        return 0
    return max(64, min(32000, n))


# Scripts written without spaces between words. Splitting these on whitespace
# reports a whole paragraph as one "word", which would silently disable the
# length control — so they're counted by character and divided by the average
# characters-per-word for that script.
#
# Detection is by script, not by the selected language: if the model replies in
# a different script than requested, or mixes scripts, the count still holds up.
HAN_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\U00020000-\U0002ffff]")
KANA_RE = re.compile(r"[\u3040-\u30ff\u31f0-\u31ff\uff66-\uff9d]")

OTHER_SPACELESS = [
    ("thai", re.compile(r"[\u0e00-\u0e7f]"), 3.5),
    ("lao", re.compile(r"[\u0e80-\u0eff]"), 3.5),
    ("khmer", re.compile(r"[\u1780-\u17ff]"), 4.0),
    ("myanmar", re.compile(r"[\u1000-\u109f]"), 4.0),
    ("tibetan", re.compile(r"[\u0f00-\u0fff]"), 4.0),
]

# Average characters per word. Japanese runs longer than Chinese because kana
# inflections trail each word.
CHARS_PER_WORD_JA = 2.0
CHARS_PER_WORD_ZH = 1.6


def count_words(text, language=None):
    """
    Approximate word count that holds up across scripts.

    Space-delimited languages (English, German, Russian, Arabic, Hindi, Korean,
    and most others) just split on whitespace. Scripts that don't use spaces
    are counted by character and converted to word-equivalents, so the length
    control behaves consistently no matter what language is selected.
    """
    if not text or not text.strip():
        return 0
    text = strip_audio_tags(text)   # NEW (1.5.0): tags are performed, not said
    if not text:
        return 0

    total = 0
    remaining = text

    han = len(HAN_RE.findall(text))
    kana = len(KANA_RE.findall(text))
    if han or kana:
        # Kana present means Japanese. Kanji-only text is treated as Japanese
        # if that's what was asked for, otherwise Chinese.
        if kana or language == "Japanese":
            divisor = CHARS_PER_WORD_JA
        else:
            divisor = CHARS_PER_WORD_ZH
        total += round((han + kana) / divisor)
        remaining = KANA_RE.sub(" ", HAN_RE.sub(" ", remaining))

    for _name, pattern, divisor in OTHER_SPACELESS:
        found = len(pattern.findall(remaining))
        if found:
            total += round(found / divisor)
            remaining = pattern.sub(" ", remaining)

    # Whatever is left is space-delimited. Ignore stray punctuation tokens so
    # they don't inflate the count.
    total += sum(1 for token in remaining.split() if any(c.isalnum() for c in token))

    return total


def normalize_language(value):
    if isinstance(value, str) and value in LANGUAGE_NAMES:
        return value
    return None


def repair_if_clipped(text):
    """
    Safety net only. If a reply came back clipped by the token ceiling
    (i.e. it doesn't end on sentence punctuation), roll back to the last
    complete sentence so ElevenLabs never speaks a half-finished thought.
    Normal replies pass through untouched.
    """
    stripped = text.rstrip()
    if not stripped:
        return text, False

    # Already ends cleanly — leave it alone.
    if re.search(r'[.!?]["\')\]]?$', stripped):
        return stripped, False

    # Find the last complete sentence.
    ends = [m.end() for m in re.finditer(r'[.!?]["\')\]]?(?=\s|$)', stripped)]
    if ends:
        return stripped[: ends[-1]].rstrip(), True

    # No sentence boundary at all (very short or unpunctuated reply) —
    # speaking it as-is is better than returning nothing.
    return stripped, False


def estimate_sentences(max_words):
    """Rough spoken-sentence count for a word budget (~18 words/sentence)."""
    return max(1, round(max_words / 18))


EN_DELIMITER = "---EN---"


# NEW (1.5.0): what the prompt preview shows as "your personality" for Mimic,
# which never sends the personality anywhere.
MIMIC_PROFILE_TEXT = "(Word for word: no personality — your exact words, translated literally when needed.)"


def build_system_prompt(base_prompt, max_words, language="English", response_style=DEFAULT_RESPONSE_STYLE,
                        voice_style=None):
    """
    CHANGED (1.5.0): three response styles.

      "reply" -> the user is typing in something someone else said TO them,
      and the model actually replies to it in character, like a real
      conversational turn. It must *not* just repeat the source text.

      "echo" -> the user's own words come back with spelling, grammar and
      punctuation fixed. The personality may show only in punctuation and
      emphasis — never in different or extra words. The prompt asks for
      that, and chat() checks it afterwards (cleanup_stays_on_message) rather than
      trusting it.

      "mimic" -> exactly what was typed. In English the model is never
      called at all; this prompt is only used to translate literally into
      another language, with no personality.

    NEW (1.5.0): `voice_style` — Expressive voice and Delivery for an
    ElevenLabs voice (None for any other voice): the rules for audio tags,
    or for a calm delivery, are added.
    """
    voice_rules = ""
    if voice_style:
        if (voice_style.get("expressive") or voice_style.get("shaping")) and response_style != "mimic":
            voice_rules += expressive_voice_rules(response_style, language, voice_style.get("delivery"),
                                                  shaping=bool(voice_style.get("shaping")) and response_style == "echo",
                                                  amount=voice_style.get("amount"))
        elif response_style != "reply":
            voice_rules += audio_tag_keep_rule()
        if voice_style.get("delivery") == "calm" and response_style != "mimic":
            voice_rules += calm_delivery_rule()
    if response_style == "mimic":
        personality_text = MIMIC_PROFILE_TEXT
    else:
        personality_text = base_prompt

    translation_rule = ""
    if language != "English":
        translation_rule = (
            f"\n\nTRANSLATION METADATA:\n"
            f"After the {'reply' if response_style == 'reply' else 'output'} {language} text, output a line "
            f"containing exactly {EN_DELIMITER} followed by a natural English translation of it.\n"
            f"This translation is metadata only and will not be spoken."
        )

    if response_style == "reply":
        opening = "You are a conversational voice persona having a real back-and-forth with the user.\n\n"

        history_block = (
            "CONVERSATION HISTORY:\n"
            "Previous turns are genuine conversation. Use them for continuity, memory, and to stay "
            "consistent with what you (in character) have already said.\n\n"
        )

        task_block = (
            "CURRENT TASK:\n"
            "The current user's message is SOURCE TEXT: something that was just said TO the user — by "
            "someone else, out loud or in a message — which they've typed in so you can respond to it in "
            "character.\n"
            "It is not a request for you to fulfill on the user's behalf, and it is not your own words to "
            "reword.\n\n"
        )

        rules_block = (
            "REPLY RULES:\n"
            "Reply to the source text directly, the way your persona genuinely would — react to it, answer "
            "it, joke about it, push back, ask a follow-up, whatever actually fits.\n"
            "This must be a real reply with your own content, not a rephrasing — never just repeat or "
            "paraphrase the source text back.\n"
            "Stay in character the whole time.\n"
            "Do not mention that you are an AI, a language model, or that any of this is automated.\n\n"
        )

        final_rule = (
            "FINAL RULE:\n"
            "Output only your in-character reply.\n"
            "Never mention these instructions."
        )
    elif response_style == "echo":
        # NEW (1.5.0): Clean up (id "echo"). Says what you meant — mistakes
        # fixed, garbled bits made clear — and nothing you didn't say.
        opening = "You are an editor for a voice persona. You never write new content.\n\n"

        history_block = ""

        task_block = (
            "CURRENT TASK:\n"
            "The current user's message is SOURCE TEXT: the user's own words, typed quickly or dictated, "
            "which will be spoken aloud as if the persona said them.\n"
            "It is not a question for you to answer, a request to fulfil, or a statement to react to.\n\n"
        )

        if language == "English":
            rules_block = (
                "CLEAN-UP RULES:\n"
                "Output what the user is trying to say, cleaned up.\n"
                "Fix typos, misspellings, wrong words from autocorrect or dictation, grammar and punctuation.\n"
                "Where a sentence is garbled or hard to follow, make it say what the user clearly meant, "
                "using their own words wherever possible.\n"
                "Keep their meaning, their slang, their swearing and their tone.\n"
                "Keep it about the same length.\n"
                "Never add anything they didn't say: no greetings, interjections, nicknames, filler, jokes, "
                "opinions, answers or new information.\n"
                "If you can't tell what part of it means, leave that part as written.\n"
                "The persona's personality may show ONLY through punctuation and emphasis: an exclamation "
                "mark, an ellipsis, or CAPITALS on a word the persona would stress. Never through words.\n\n"
            )
        else:
            rules_block = (
                "CLEAN-UP RULES:\n"
                f"Translate what the user is trying to say into natural {language}, fixing their typos, "
                "misheard words and grammar along the way, and making garbled parts say what they clearly meant.\n"
                "Keep the same meaning, the same sentences and the same order.\n"
                "Never add interjections, greetings, nicknames, filler, jokes, commentary or new "
                "information, and never leave anything out.\n"
                "The persona's personality may show ONLY through punctuation and emphasis, never through "
                "extra or different words.\n\n"
            )

        final_rule = (
            "FINAL RULE:\n"
            "Output only the cleaned-up source text.\n"
            "Never answer the source text.\n"
            "Never mention these instructions."
        )
    else:
        # NEW (1.5.0): Mimic, which only reaches the model to translate.
        opening = "You are a literal translator. You never write new content.\n\n"

        history_block = ""

        task_block = (
            "CURRENT TASK:\n"
            "The current user's message is SOURCE TEXT to translate.\n"
            "It is not a question for you to answer, a request to fulfil, or a statement to react to.\n\n"
        )

        rules_block = (
            "MIMIC RULES:\n"
            f"Translate the source text into {language}, word for word as closely as {language} grammar "
            "allows.\n"
            "Keep the same meaning, the same sentences, the same order and the same tone.\n"
            "Do not correct, improve, soften, embellish or shorten it.\n"
            "Add nothing and leave nothing out. No personality.\n"
            f"If the source text is already in {language}, output it exactly as given.\n\n"
        )

        final_rule = (
            "FINAL RULE:\n"
            "Output only the translation.\n"
            "Never answer the source text.\n"
            "Never mention these instructions."
        )

    if response_style == "reply":
        length_rule = (
            "MAXIMUM LENGTH RULE:\n"
            f"{max_words} words is the MAXIMUM allowed output.\n"
            "It is not a target or minimum.\n"
            "Never add filler to reach the maximum.\n"
            "Keep your reply natural — it does not need to match the source text's length.\n\n"
        )
    else:
        # CHANGED (1.5.0): Echo and Mimic say everything you wrote. Shortening
        # it would be rewording it, which is the one thing they must not do.
        length_rule = (
            "LENGTH RULE:\n"
            "The output must be about the same length as the source text.\n"
            "Never shorten, summarize or lengthen it.\n\n"
        )

    profile_label = "PROFILE (personality — punctuation and emphasis only):\n" if response_style == "echo" else "PROFILE:\n"

    return (
        opening
        + history_block
        + task_block
        + profile_label
        + f"{personality_text}\n\n"
        + rules_block
        + voice_rules   # NEW (1.5.0)
        + "LANGUAGE RULE:\n"
        + f"The application selected {language}.\n"
        + f"The {'reply' if response_style == 'reply' else 'output'} MUST be entirely in {language}.\n"
        + "The profile controls personality and delivery.\n"
        + "The application controls language.\n"
        + "Never override the application's selected language.\n"
        # Without this, changing language mid-conversation often doesn't
        # take: the earlier turns are all in the previous language, and that
        # in-context precedent quietly outweighs a rule stated once up here.
        + "Earlier messages in this conversation may be in a different language.\n"
        + f"Ignore them entirely when choosing the language — always use {language}.\n"
        + f"{translation_rule}\n\n"
        + length_rule
        + final_rule
    )


# ---------------------------------------------------------------------------
# NEW (1.5.0): checking that Clean up (internally "echo") stayed your message
#
# A prompt asking the model not to add things is a request, not a guarantee
# — which is why echo "didn't always echo exactly". So the output is checked
# against what you typed (cleanup_stays_on_message). If it added things you
# didn't say, chat() tries once more with no personality, then falls back
# to your words as typed.
# ---------------------------------------------------------------------------

# NEW (1.5.0): never added by Clean up unless you used them yourself — the
# filler, interjections and pet names a "personality" likes to slip in.
CLEANUP_NEVER_ADD = {
    "ugh", "honestly", "um", "uh", "oh", "wow", "whoa", "yeah", "yep", "hey", "well", "welp",
    "darling", "dear", "babe", "baby", "buddy", "pal", "friend", "mate", "champ", "dude",
    "bro", "sweetie", "honey", "sweetheart", "folks", "guys", "lol", "haha", "hehe",
    "totally", "literally", "absolutely", "seriously", "basically", "actually", "truly",
    "definitely", "certainly", "indeed", "alright", "anyway", "anyways", "listen", "look",
}

ECHO_SHORTHAND = {
    "u": "you", "ur": "your", "r": "are", "y": "why", "n": "and", "k": "okay", "ok": "okay",
    "kk": "okay", "rn": "right now", "brb": "be right back", "idk": "i do not know",
    "imo": "in my opinion", "tbh": "to be honest", "btw": "by the way", "pls": "please",
    "plz": "please", "thx": "thanks", "ty": "thank you", "bc": "because", "cuz": "because",
    "cause": "because", "tho": "though", "thru": "through", "w": "with", "wo": "without",
    "ppl": "people", "msg": "message", "gonna": "going to", "wanna": "want to",
    "gotta": "got to", "ima": "i am going to", "im": "i am", "ive": "i have", "ill": "i will",
    "id": "i would", "youre": "you are", "dont": "do not", "doesnt": "does not",
    "didnt": "did not", "cant": "cannot", "can't": "cannot", "wont": "will not",
    "isnt": "is not", "arent": "are not", "wasnt": "was not", "shouldnt": "should not",
    "couldnt": "could not", "wouldnt": "would not", "thats": "that is", "whats": "what is",
    "theres": "there is", "lets": "let us", "its": "it is", "hes": "he is", "shes": "she is",
}

# Words grammar fixes add or remove. Changing one of these is never a change
# of meaning or of personality.
ECHO_GRAMMAR_WORDS = {
    "a", "an", "the", "is", "are", "am", "was", "were", "be", "been", "to", "of", "it",
    "do", "does", "did", "have", "has", "had", "will", "would", "i", "that", "for", "in",
    "on", "at", "and", "not",
}

_CONTRACTIONS = [
    (r"n't\b", " not"), (r"'re\b", " are"), (r"'m\b", " am"), (r"'ve\b", " have"),
    (r"'ll\b", " will"), (r"'d\b", " would"), (r"\bit's\b", "it is"), (r"\bthat's\b", "that is"),
    (r"\bwhat's\b", "what is"), (r"\bthere's\b", "there is"), (r"\blet's\b", "let us"),
    (r"\bhe's\b", "he is"), (r"\bshe's\b", "she is"),
]


def _echo_words(text):
    """Lower-cased words with contractions and shorthand written out."""
    text = text.lower().replace("’", "'").replace("can't", "cannot").replace("won't", "will not")
    for pattern, repl in _CONTRACTIONS:
        text = re.sub(pattern, repl, text)
    words = []
    for word in re.findall(r"[\w']+", text):
        word = word.strip("'")
        if not word:
            continue
        words.extend(ECHO_SHORTHAND.get(word, word).split())
    return words


def _close_spelling(a, b):
    """Is b the same word as a, spelled right (or a near miss of one)?"""
    if a == b:
        return True
    if not a or not b:
        return False
    from difflib import SequenceMatcher
    return SequenceMatcher(None, a, b).ratio() >= 0.6


# NEW (1.5.0): what Shape words for tags may add without it counting as new
# content: the short lead-ins and fillers that go with a performed tag.
TAG_SHAPING_WORDS = {
    "oh", "ah", "aw", "ooh", "uh", "um", "hmm", "well", "wow", "whoa", "okay", "ok", "so", "yeah",
    "huh", "hey", "ha", "haha", "phew", "ugh", "man", "god", "gosh", "geez", "jeez", "alright", "right",
}


# NEW (1.5.0): Tag words: words and phrases that Shape words for tags turns
# into tags instead of reading out. One central list (Settings > Voices),
# used by every profile with Shape words for tags on. Each entry has a tag,
# or "" for "AI picks": the AI chooses from how it's meant (a light "lol" is
# [chuckles], an awkward one [nervous laugh], a sarcastic one [scoffs]).
DEFAULT_TAG_WORDS = [{"word": w, "tag": ""} for w in
                     ("lol", "haha", "lmao", "lmfao", "rofl", "hehe", "heh", "teehee", "omg", "ugh", "smh", "pfft")]
TAG_WORDS_MAX = 100
# What the backstop uses for an "AI picks" word the AI left in, by how big
# it is. A word you added yourself on "AI picks" has no guess and is left
# to the AI.
_TAG_WORD_GUESS = {
    "lol": "laughs", "haha": "laughs", "lmao": "laughs hard", "lmfao": "laughs hard", "rofl": "laughs hard",
    "hehe": "giggles", "teehee": "giggles", "heh": "chuckles", "lel": "chuckles", "omg": "gasps",
    "ugh": "sighs", "smh": "sighs", "pfft": "scoffs",
}
_LAUGHISH = ("laugh", "chuckl", "giggl", "gasp", "sigh", "groan", "scoff")


def normalize_tag_words(value):
    """A clean list: [{"word", "tag"}], words lowercased and unique, tags valid or ""."""
    if not isinstance(value, list):
        return [dict(e) for e in DEFAULT_TAG_WORDS]
    out, seen = [], set()
    for entry in value:
        if not isinstance(entry, dict):
            continue
        word = re.sub(r"\s+", " ", str(entry.get("word") or "")).strip().lower()[:40]
        tag = re.sub(r"[\[\]]", "", str(entry.get("tag") or "")).strip().lower()[:38]
        if not word or word in seen or not re.search(r"\w", word):
            continue
        if tag and not AUDIO_TAG_RE.fullmatch(f"[{tag}]"):
            tag = ""
        seen.add(word)
        out.append({"word": word, "tag": tag})
        if len(out) >= TAG_WORDS_MAX:
            break
    return out


def tag_words():
    return normalize_tag_words(CFG.get("tag_words", DEFAULT_TAG_WORDS))


def _tag_word_pattern(word):
    """How a typed word is matched: "haha" also matches "hahaha", "lol"
    also "lool" and "LOL", and a phrase allows any spacing."""
    unit = re.fullmatch(r"([a-z]{2})\1+", word)
    if unit:
        return f"a?(?:{re.escape(unit.group(1))}){{2,}}h?"
    if " " in word:
        return r"\s+".join(re.escape(part) for part in word.split())
    if re.fullmatch(r"[a-z]+", word):
        return "".join(re.escape(c) + "+" for c in word)
    return re.escape(word)


_TAG_WORD_CACHE = {"key": None, "re": None, "entries": []}


def _tag_word_matcher():
    entries = tag_words()
    key = json.dumps(entries)
    if _TAG_WORD_CACHE["key"] != key:
        compiled = [(e, re.compile(_tag_word_pattern(e["word"]), re.I)) for e in entries]
        alts = "|".join(f"(?:{_tag_word_pattern(e['word'])})" for e in sorted(entries, key=lambda e: -len(e["word"])))
        _TAG_WORD_CACHE.update(key=key, entries=compiled,
                               re=re.compile(rf"(?<![\w\[])(?P<w>{alts})(?![\w\]])", re.I) if alts else None)
    return _TAG_WORD_CACHE["re"], _TAG_WORD_CACHE["entries"]


def tag_word_entry(text):
    """The Tag words entry `text` is, or None."""
    _, entries = _tag_word_matcher()
    for entry, pattern in entries:
        if pattern.fullmatch(text or ""):
            return entry
    return None


def is_text_speak(word):
    return tag_word_entry(word) is not None


def text_speak_tag(word):
    """The tag a Tag word becomes when the AI left it in: its own tag, or
    for "AI picks" a guess by how big it is (None when there's no guess)."""
    entry = tag_word_entry(word)
    if not entry:
        return None
    if entry["tag"]:
        return entry["tag"]
    w = entry["word"]
    guess = _TAG_WORD_GUESS.get(w)
    if guess in ("laughs", "chuckles") and ((word.isupper() and len(word) > 2)
                                             or re.fullmatch(r"a?(?:ha){3,}h?", word.lower())):
        return "laughs hard"
    return guess


def replace_text_speak(text):
    """
    NEW (1.5.0): any Tag word left in `text` becomes its tag where it was,
    so the voice never reads out "lol". One already next to a tag of the
    same kind is just dropped; an "AI picks" word with no guess is left.
    """
    matcher, _ = _tag_word_matcher()
    if not text or not matcher or not matcher.search(text):
        return text

    def swap(m):
        tag = text_speak_tag(m.group("w"))
        if not tag:
            return m.group(0)
        before = text[:m.start()].rstrip()
        after = text[m.end():].lstrip()
        near = re.search(r"\[([^\]]+)\]\s*$", before) or re.match(r"^\[([^\]]+)\]", after)
        if near and (near.group(1).lower() == tag or (any(k in tag for k in _LAUGHISH)
                                                     and any(k in near.group(1).lower() for k in _LAUGHISH))):
            return ""
        return f"[{tag}]"

    out = matcher.sub(swap, text)
    out = re.sub(r"[ \t]{2,}", " ", out)
    out = re.sub(r" +([.,!?;:…])", r"\1", out)
    out = tidy_audio_tags(out.strip())
    return re.sub(r"^[\s,.;:]+(?=\S)", "", out)   # a message that was only "lol."


def tag_words_prompt():
    """What the AI is told about the Tag words list."""
    entries = tag_words()
    if not entries:
        return ""
    fixed = [e for e in entries if e["tag"]]
    picks = [e for e in entries if not e["tag"]]
    lines = ["TEXT-SPEAK BECOMES A TAG:",
             "These words and phrases are never said aloud. Wherever one appears (in any capitalisation or "
             "stretched out, like \"lool\" or \"hahaha\"), remove it and put a tag where it was."]
    if fixed:
        lines.append("Always these tags:")
        lines += [f"- \"{e['word']}\": [{e['tag']}]" for e in fixed]
    if picks:
        lines.append("For these, choose the tag that fits how it's meant here: "
                     + ", ".join(f"\"{e['word']}\"" for e in picks) + ".")
        lines += [
            "- light, after something mildly funny: [chuckles]; at something actually funny: [laughs]",
            "- stretched or in capitals (\"hahaha\", \"LMAO\", \"LOL\"): [laughs hard]",
            "- playful or mischievous (\"hehe\"): [giggles]",
            "- awkward or nervous (after an apology, bad news, something embarrassing): [nervous laugh]",
            "- sarcastic or dismissive: [scoffs]",
            "- surprise: [gasps]; frustration or disbelief: [sighs] or [groans]",
            "Read the whole message to decide which fits.",
        ]
    return "\n".join(lines) + "\n"


def tag_shaping_stays_on_message(source, output):
    """
    NEW (1.5.0): cleanup_stays_on_message for Shape words for tags, where
    the AI may drop words a tag performs and add a short lead-in. Still
    caught: new content (more than a few new words that aren't lead-ins),
    losing most of the message, and growing much longer.
    """
    import math
    a, b = _echo_words(source), _echo_words(output)
    if not b:
        return not a
    if len(b) > len(a) * 1.3 + 5:
        return False

    def traced(word, pool):
        return (word in ECHO_GRAMMAR_WORDS or word in TAG_SHAPING_WORDS or is_text_speak(word)
                or any(_close_spelling(word, other) for other in pool))

    a_content = [w for w in a if w not in ECHO_GRAMMAR_WORDS and w not in TAG_SHAPING_WORDS and not is_text_speak(w)]
    b_content = [w for w in b if w not in ECHO_GRAMMAR_WORDS]
    new_words = [w for w in b_content if not traced(w, a)]
    if len(new_words) > max(2, math.ceil(0.2 * len(a_content))):
        return False
    if a_content:
        kept = sum(1 for w in a_content if traced(w, b))
        if kept / len(a_content) < 0.7:
            return False
    return True


def cleanup_stays_on_message(source, output):
    """
    CHANGED (1.5.0): True when `output` is still your message — mistakes
    fixed and garbled bits made clear are fine; things you never said are
    not. (This replaced a stricter word-for-word check once Clean up was
    allowed to fix what you meant, not only how you spelled it.)

    Caught:
      - filler, interjections and pet names you didn't use ("ugh",
        "honestly", "darling", "absolutely", ...)
      - more than a couple of new words that aren't a fix of one of yours
        (rewritten fancier, or new content)
      - losing most of what you said (an answer instead of your message)
      - growing much longer than what you typed
    """
    import math

    a, b = _echo_words(source), _echo_words(output)
    if not b:
        return not a
    if len(b) > len(a) * 1.5 + 3:
        return False

    def traced(word, pool):
        return word in ECHO_GRAMMAR_WORDS or any(_close_spelling(word, other) for other in pool)

    # A misspelled "frend" may become "friend"; a "friend" from nowhere may not.
    if any(w in CLEANUP_NEVER_ADD and not any(_close_spelling(w, x) for x in a) for w in b):
        return False

    a_content = [w for w in a if w not in ECHO_GRAMMAR_WORDS]
    b_content = [w for w in b if w not in ECHO_GRAMMAR_WORDS]

    new_words = [w for w in b_content if not traced(w, a)]
    if len(new_words) > max(2, math.ceil(0.3 * len(a_content))):
        return False

    if a_content:
        kept = sum(1 for w in a_content if traced(w, b))
        if kept / len(a_content) < 0.5:
            return False
    return True


# ---------------------------------------------------------------------------
# NEW (1.5.0): "Follow reply length", per profile
#
# On, every style keeps to the reply-length slider: Reply as it always has,
# and Clean up and Word for word by summarizing a message that's too long
# (summarize_to_length), falling back to the last whole sentence that fits
# (fit_to_length). Off, nothing is shortened — Reply gets no limit either.
#
# A profile saved before this existed has no setting; it keeps doing what
# it did (Reply follows the slider, Clean up and Word for word say
# everything).
# ---------------------------------------------------------------------------

def normalize_follow_length(value, response_style):
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in {"true", "false", "1", "0", "on", "off"}:
        return value.strip().lower() in {"true", "1", "on"}
    return response_style == "reply"


# Words a sentence cut short must not end on — "...and I went to the." is
# worse than "...and I went."
_DANGLING_WORDS = {
    "a", "an", "the", "and", "or", "but", "so", "to", "of", "with", "for", "because",
    "that", "which", "who", "if", "when", "while", "than", "then", "as", "at", "in", "on",
    "by", "from", "into", "about", "my", "your", "his", "her", "their", "our", "its", "i",
    "is", "are", "was", "were", "be", "very", "just", "really", "like",
}

_SENTENCE_RE = re.compile(r".+?(?:[.!?…。！？]+[\"'”’)\]]*(?=\s|$)|[。！？]+|$)", re.S)


def fit_to_length(text, max_words, language="English"):
    """
    NEW (1.5.0): shorten `text` to `max_words` without rewording it. Whole
    sentences are kept for as long as they fit. If even the first sentence
    is too long, it is cut at a word boundary, any word that would leave it
    hanging ("the", "and", ...) is dropped, and it is given a full stop, so
    it still sounds finished rather than cut off.

    Returns (text, was_shortened).
    """
    text = (text or "").strip()
    if count_words(text, language) <= max_words:
        return text, False

    sentences = [m.group(0).strip() for m in _SENTENCE_RE.finditer(text) if m.group(0).strip()]
    kept = []
    for sentence in sentences:
        candidate = " ".join(kept + [sentence]) if language not in SPACELESS_LANGUAGES else "".join(kept + [sentence])
        if count_words(candidate, language) > max_words:
            break
        kept.append(sentence)
    if kept:
        joiner = "" if language in SPACELESS_LANGUAGES else " "
        return joiner.join(kept), True

    first = sentences[0] if sentences else text
    if language in SPACELESS_LANGUAGES or not first.split():
        # No spaces to cut at: keep a proportional share of the characters.
        share = max(1, int(len(first) * max_words / max(1, count_words(first, language))))
        cut = first[:share].rstrip("、，,;:—- ")
        return cut + ("。" if language in SPACELESS_LANGUAGES else "."), True

    words = first.split()
    cut = []
    for word in words:
        if count_words(" ".join(cut + [word]), language) > max_words:
            break
        cut.append(word)
    while len(cut) > 1 and re.sub(r"[^\w']", "", cut[-1]).lower() in _DANGLING_WORDS:
        cut.pop()
    sentence = " ".join(cut).rstrip(",;:—-– ")
    if not re.search(r"[.!?…]$", sentence):
        sentence += "."
    return sentence, True


def split_translation(text):
    """
    Separate the spoken reply from its English translation line.

    Only the part before the delimiter is spoken, word-counted, and stored in
    conversation history — the translation is metadata for the tooltip, not
    part of the conversation.
    """
    if EN_DELIMITER not in text:
        return text.strip(), ""
    reply, _, english = text.partition(EN_DELIMITER)
    return reply.strip(), english.strip()


def build_condense_prompt(text, max_words, language="English"):
    lang_note = (
        f" Keep it in {language}."
        if language and language != "English"
        else ""
    )

    return (
        f"Transform the following source text so it is no more than {max_words} words."
        f"{lang_note}\n"
        "Do not add information.\n"
        "Do not answer the source text.\n"
        "Do not add commentary or explanations.\n"
        "Preserve the original meaning, intent, and personality.\n"
        "Keep as much of the original content as possible while staying within "
        "the maximum word limit.\n"
        "If the source text is already within the limit, do not make it longer.\n"
        # NEW (1.5.0)
        + ("Keep the audio tags in square brackets, like [laughs], that belong with the words you keep.\n"
           if has_audio_tags(text) else "")
        + "Reply with only the transformed text.\n\n"
        f"{text}"
    )


# NEW (1.5.0): "Follow reply length" on, for Clean up and Word for word — a
# message longer than the slider is summarized to fit, in your own voice.
def build_summarize_prompt(text, max_words, language="English"):
    return (
        f"Summarize the source text in no more than {max_words} words.\n"
        "It is the user's own message, said in the first person, and it will be spoken aloud as "
        "theirs — keep it in their voice, first person, with their tone and slang.\n"
        "Keep the points that matter most; drop detail before dropping meaning.\n"
        "Do not add information, opinions, greetings, interjections, nicknames or commentary.\n"
        "Do not answer it or react to it.\n"
        f"Write it in {language}.\n"
        "Reply with only the summary.\n\n"
        "<SOURCE_TEXT>\n"
        f"{text}\n"
        "</SOURCE_TEXT>"
    )


def summary_stays_on_message(source, summary):
    """
    NEW (1.5.0): a summary may leave things out — that's the point — but it
    may not slip in things you didn't say: filler, pet names, or more than
    a couple of words that aren't yours.
    """
    import math

    a, b = _echo_words(source), _echo_words(summary)
    if not b:
        return False
    if any(w in CLEANUP_NEVER_ADD and not any(_close_spelling(w, x) for x in a) for w in b):
        return False
    new_words = [
        w for w in b
        if w not in ECHO_GRAMMAR_WORDS and not any(_close_spelling(w, x) for x in a)
    ]
    b_content = [w for w in b if w not in ECHO_GRAMMAR_WORDS]
    return len(new_words) <= max(3, math.ceil(0.35 * len(b_content)))


def summarize_to_length(text, max_words, language="English"):
    """
    NEW (1.5.0): returns (summary, seconds), or (None, seconds) when there's
    no model to ask, it failed, or the summary added things — the caller
    then keeps whole sentences instead (fit_to_length).
    """
    if not CFG.get("openai_api_key") and resolve_provider("chat_provider", CHAT_PROVIDERS) == "openai":
        return None, 0.0
    started = time.perf_counter()
    try:
        response = create_chat_completion(
            make_openai_client(),
            provider=resolve_provider("chat_provider", CHAT_PROVIDERS),
            model=CFG.get("model", RECOMMENDED_TEXT_MODEL),
            ollama_model=active_ollama_model(),   # CHANGED (1.5.0)
            messages=[{"role": "user", "content": build_summarize_prompt(text, max_words, language)}],
            max_tokens=int(max_words * 4) + 60,
            temperature=0.2,
        )
        summary, _ = split_translation((response.choices[0].message.content or "").strip())
    except Exception:
        return None, time.perf_counter() - started
    seconds = time.perf_counter() - started
    if not summary:
        return None, seconds
    if language == "English" and not summary_stays_on_message(text, summary):
        return None, seconds
    return summary, seconds


# ---------------------------------------------------------------------------
# Providers
#
# Each function the app performs can be pointed at a different backend. This
# is strictly additive: every default below is the behaviour the app had
# before providers existed, so an existing config.json keeps working
# untouched and nothing contacts a local service unless it's been chosen.
#
# What can move off OpenAI, and what can't:
#   chat          -> OpenAI or Ollama
#   translation   -> OpenAI or Ollama
#   transcription -> OpenAI or a local faster-whisper service
#   speech (TTS)  -> ElevenLabs only; there's no local equivalent at that
#                    quality, so it isn't offered as a choice.
# ---------------------------------------------------------------------------

CHAT_PROVIDERS = [
    {
        "id": "openai",
        "name": "OpenAI",
        "note": "Best at holding a personality consistently across turns. Costs pennies.",
    },
    {
        "id": "ollama",
        "name": "Ollama (local)",
        "note": "Free and private, runs on your own GPU. Smaller models hold a persona less consistently.",
    },
]

TRANSLATION_PROVIDERS = [
    {
        "id": "openai",
        "name": "OpenAI",
        "note": "Reliable across every language in the list. Fractions of a penny per translation.",
    },
    {
        "id": "ollama",
        "name": "Ollama (local)",
        "note": "Free. Good on major languages, weaker on the less common ones.",
    },
]

TRANSCRIPTION_PROVIDERS = [
    {
        "id": "openai",
        "name": "OpenAI",
        "note": "Works with no extra setup. Around 5-10 cents per hour of speech.",
    },
    {
        "id": "local_whisper",
        "name": "Evora",
        "note": "Free, private transcription on this computer or your network. Install Evora on the machine that will process audio.",
    },
]

def provider_ids(provider_list):
    return {p["id"] for p in provider_list}


def resolve_provider(key, provider_list, default="openai"):
    """Reads a provider choice from config, falling back to the default."""
    value = (CFG.get(key) or "").strip()
    return value if value in provider_ids(provider_list) else default


def ollama_base_url():
    url = (CFG.get("ollama_url") or DEFAULT_OLLAMA_URL).strip().rstrip("/")
    return url or DEFAULT_OLLAMA_URL


def ollama_tier():
    """NEW (1.5.0): which of the three Ollama models is in use."""
    tier = CFG.get("ollama_tier") or "fast"
    return tier if tier in OLLAMA_TIER_KEYS else "fast"


def tier_model(tier):
    """NEW (1.5.0): the model name in one of the three slots."""
    return (CFG.get(OLLAMA_TIER_KEYS[tier]) or "").strip() or OLLAMA_TIER_DEFAULTS[tier]


def ollama_keep_alive():
    """
    NEW (1.5.0): Ollama's keep_alive for Frivo's requests: "1h" and the
    like, or -1 to stay loaded until Ollama stops.
    """
    choice = CFG.get("ollama_idle_unload") or DEFAULT_OLLAMA_IDLE_UNLOAD
    if choice not in OLLAMA_IDLE_UNLOAD:
        choice = DEFAULT_OLLAMA_IDLE_UNLOAD
    return -1 if choice == "never" else choice


def active_ollama_model():
    """NEW (1.5.0): the Ollama model replies use right now."""
    return tier_model(ollama_tier())


def note_text_engine(name):
    """
    NEW (1.5.0): remembers which AI wrote (part of) this reply, so the reply
    can say so. The hover used to say "ChatGPT" whatever actually answered.
    """
    try:
        from flask import g, has_request_context
        if has_request_context():
            engines = g.setdefault("text_engines", [])
            if name not in engines:
                engines.append(name)
    except Exception:
        pass


def whisper_base_url():
    url = (CFG.get("whisper_url") or DEFAULT_WHISPER_URL).strip().rstrip("/")
    return url or DEFAULT_WHISPER_URL


def fallback_allowed():
    """
    Whether an unreachable local provider may quietly be replaced by OpenAI.

    Off unless explicitly enabled. Choosing local Whisper or Ollama is a
    decision about cost and privacy, and honouring it only while convenient
    isn't honouring it — the failure mode is that everything keeps working
    perfectly while quietly costing money, which is precisely the case you
    would want to be told about.
    """
    return bool(CFG.get("allow_openai_fallback", False))


def make_openai_client():
    """
    Returns an OpenAI client, or None when no key is configured.

    Local providers do not require an OpenAI client.
    """
    key = CFG.get("openai_api_key")
    return OpenAI(api_key=key) if key else None


class _ShimMessage:
    def __init__(self, content):
        self.content = content


class _ShimChoice:
    def __init__(self, content, finish_reason):
        self.message = _ShimMessage(content)
        self.finish_reason = finish_reason


class _ShimResponse:
    """
    Mimics the shape of an OpenAI chat completion response.

    Gives local-provider responses the interface used by OpenAI responses.
    """

    def __init__(self, content, finish_reason="stop"):
        self.choices = [_ShimChoice(content, finish_reason)]


# CHANGED (dictation speed): one kept-alive connection to Evora instead of a
# new TCP connection per clip. Live dictation sends a clip about every
# 0.7s while you talk; the handshake is small, but it is paid every time.
EVORA_HTTP = requests.Session()

# CHANGED (dictation speed): Evora answers 429 at once when its model is
# busy (another client, or the listening panel) instead of queueing. A
# dictation clip is worth a short wait rather than a failed sentence.
EVORA_BUSY_RETRIES = 6
EVORA_BUSY_WAIT = 0.15


def local_whisper_transcribe(file_tuple, language=None):
    """
    Sends audio to a local faster-whisper service and returns the text.

    The endpoint follows OpenAI's transcription request and response shape.

    CHANGED (dictation speed): asks for words only — speaker=0. Evora runs
    its full speaker analysis on every clip unless told not to, and that
    analysis is most of what each clip cost. Dictation never uses it: the
    speaker is always you. The listening panel, which does use it, goes
    through local_whisper_transcribe_verbose and is unaffected. An Evora
    from before the speaker field existed ignores it.
    """
    filename, audio_bytes, content_type = file_tuple
    files = {"file": (filename, audio_bytes, content_type)}
    data = {"speaker": "0"}
    if language:
        data["language"] = language

    started = time.perf_counter()
    for attempt in range(EVORA_BUSY_RETRIES + 1):
        with EVORA_TRANSCRIPTION_LOCK:
            response = EVORA_HTTP.post(
                f"{whisper_base_url()}/v1/audio/transcriptions",
                files=files,
                data=data,
                timeout=(LOCAL_CONNECT_TIMEOUT, LOCAL_READ_TIMEOUT),
            )
        if response.status_code != 429 or attempt == EVORA_BUSY_RETRIES:
            break
        time.sleep(EVORA_BUSY_WAIT)
    response.raise_for_status()
    elapsed = time.perf_counter() - started
    # Slow clips are what make dictation feel laggy; leave a trail of them.
    if elapsed > 2.0:
        log_server_event(f"slow dictation clip: {elapsed:.1f}s for {len(audio_bytes):,} bytes")
    return (response.json().get("text") or "").strip()


def local_whisper_transcribe_verbose(file_tuple, want_speaker=True, listening_session=None):
    """
    As local_whisper_transcribe, but also returns the language Whisper
    detected. The listening panel wants that — knowing a segment came back
    as Japanese when you expected German is the difference between "the
    translation is wrong" and "it heard the wrong person".
    """
    filename, audio_bytes, content_type = file_tuple
    with EVORA_TRANSCRIPTION_LOCK:
        response = requests.post(
            f"{whisper_base_url()}/v1/audio/transcriptions",
            files={"file": (filename, audio_bytes, content_type)},
            data={"speaker": "1" if want_speaker else "0", "listening_session": listening_session or ""},
            timeout=(LOCAL_CONNECT_TIMEOUT, LOCAL_READ_TIMEOUT),
        )
    response.raise_for_status()
    payload = response.json()
    return (
        (payload.get("text") or "").strip(),
        payload.get("language") or "",
        payload.get("speaker"),
        payload.get("segments") or [],
        payload.get("speaker_status") or {},
    )


def openai_transcribe(file_tuple, language=None):
    """Transcribes via OpenAI, with the same model fallback used elsewhere."""
    client = make_openai_client()
    if client is None:
        raise RuntimeError("Add your OpenAI key in Settings first.")

    extra = {"language": language} if language else {}
    try:
        result = client.audio.transcriptions.create(
            model=TRANSCRIBE_MODEL, file=file_tuple, **extra
        )
    except Exception:
        if TRANSCRIBE_MODEL == TRANSCRIBE_FALLBACK_MODEL:
            raise
        result = client.audio.transcriptions.create(
            model=TRANSCRIBE_FALLBACK_MODEL, file=file_tuple, **extra
        )
    return (getattr(result, "text", "") or "").strip()


def probe_provider(kind, timeout=None):
    """
    Checks local-provider connectivity for the Settings test buttons.
    """
    try:
        if kind == "ollama":
            response = requests.get(f"{ollama_base_url()}/api/tags", timeout=timeout or LOCAL_CONNECT_TIMEOUT)
            response.raise_for_status()
            models = [m.get("name", "") for m in (response.json().get("models") or [])]
            if not models:
                return True, "Connected, but no models are pulled yet. Run: ollama pull llama3.1:8b"
            wanted = active_ollama_model()   # CHANGED (1.5.0)
            if wanted and wanted not in models:
                return True, (
                    f"Connected. {len(models)} model(s) available, but '{wanted}' isn't one of "
                    f"them — run: ollama pull {wanted}"
                )
            return True, f"Connected. {len(models)} model(s) available, including {wanted}."

        if kind == "whisper":
            response = requests.get(f"{whisper_base_url()}/health", timeout=timeout or LOCAL_CONNECT_TIMEOUT)
            response.raise_for_status()
            info = response.json()
            return True, (
                f"Connected. Model '{info.get('model', '?')}' on {info.get('device', '?')}."
            )
    except requests.exceptions.ConnectTimeout:
        return False, "Timed out connecting — is the machine on and reachable?"
    except requests.exceptions.ConnectionError:
        return False, "Nothing is listening at that address."
    except Exception as e:
        return False, str(e)

    return False, "Unknown provider."


class OllamaModelMissing(RuntimeError):
    """NEW (1.5.0): Ollama is there, but this model hasn't been downloaded."""


def ollama_chat(*, model, messages, max_tokens, temperature=None):
    """
    Calls an Ollama server's /api/chat and returns an OpenAI-shaped response.

    Raises on any failure so the caller can decide whether to fall back.
    """
    url = f"{ollama_base_url()}/api/chat"
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {"num_predict": max_tokens},
        # NEW (1.5.0): answer straight away. Models that "think" first would
        # spend the word allowance thinking and come back slow, or empty.
        "think": False,
        # CHANGED (1.5.0): stay loaded while you're using it, and free the
        # graphics card after the idle time set in Settings (an hour by
        # default). Ollama's own default is five minutes, after which every
        # reply waited for the model to load again. Switching to another of
        # the three unloads this one (set_ollama_tier).
        "keep_alive": ollama_keep_alive(),
    }
    if temperature is not None:
        payload["options"]["temperature"] = temperature
    response = requests.post(
        url, json=payload, timeout=(LOCAL_CONNECT_TIMEOUT, LOCAL_READ_TIMEOUT)
    )
    # NEW (1.5.0): an older Ollama, or a model with no thinking switch, may
    # refuse "think". Asked again without it.
    if response.status_code == 400 and "think" in response.text.lower():
        payload.pop("think", None)
        response = requests.post(
            url, json=payload, timeout=(LOCAL_CONNECT_TIMEOUT, LOCAL_READ_TIMEOUT)
        )
    if response.status_code == 404 and "not found" in response.text.lower():
        raise OllamaModelMissing(f"The model '{model}' isn't on the Ollama PC yet. On that PC, run: ollama pull {model}")
    response.raise_for_status()
    data = response.json()

    content = ((data.get("message") or {}).get("content") or "").strip()
    # NEW (1.5.0): a model that thinks anyway sometimes puts it in the reply.
    content = re.sub(r"(?s)<think>.*?</think>", "", content).strip()
    if not content:
        raise RuntimeError("Ollama returned an empty reply.")
    note_text_engine(f"Ollama · {model}")   # NEW (1.5.0)

    # Ollama reports why generation stopped; "length" is the same signal
    # OpenAI gives when the token ceiling was hit.
    finish_reason = "length" if data.get("done_reason") == "length" else "stop"
    return _ShimResponse(content, finish_reason)


def create_chat_completion(client, *, max_tokens, provider="openai", temperature=None, **kwargs):
    """
    Wraps client.chat.completions.create() to paper over OpenAI's split
    between the `max_tokens` and `max_completion_tokens` parameters.

    Newer models (o-series, and everything in this app's model picker —
    gpt-4o, gpt-4.1, gpt-5 families) require `max_completion_tokens` and
    reject `max_tokens` outright. Older models (gpt-3.5-turbo, legacy gpt-4)
    only accept `max_tokens`. Since the model is user-selectable (including
    a free-typed custom model ID), this tries the modern parameter first —
    correct for every model in the picker — and falls back to the legacy
    one only if the API specifically rejects it, so an older custom model
    still works without the app needing to hardcode which models are "old".

    When `provider` is "ollama" the request goes to the local Ollama server
    instead. If that server can't be reached — box powered off, wrong
    address, model not pulled — it falls back to OpenAI rather than failing
    the request, and records why in server.log. A local GPU being unavailable
    should degrade to "slightly more expensive", not "the app is broken".
    """
    if provider == "ollama":
        try:
            return ollama_chat(
                model=kwargs.get("ollama_model") or kwargs.get("model"),
                messages=kwargs["messages"],
                max_tokens=max_tokens,
                temperature=temperature,
            )
        except Exception as e:
            if not fallback_allowed():
                log_server_event(f"Ollama unavailable ({e!r}) — fallback off, failing.")
                # NEW (1.5.0): Ollama is fine, the model just isn't downloaded:
                # say that, not "isn't reachable".
                if isinstance(e, OllamaModelMissing):
                    raise
                raise RuntimeError(
                    "Ollama isn't reachable. Start it, or switch Chat replies to "
                    "OpenAI in Settings. (Automatic fallback to OpenAI is turned "
                    "off, so nothing was sent to a paid service.)"
                ) from e

            log_server_event(f"Ollama unavailable ({e!r}) — falling back to OpenAI.")
            if client is None:
                raise RuntimeError(
                    "Ollama isn't reachable and there's no OpenAI key to fall back on. "
                    "Check the Ollama address in Settings, or add an OpenAI key."
                ) from e
            # Fall through to OpenAI using the OpenAI model, not the Ollama
            # one — an Ollama model name means nothing to OpenAI.

    kwargs.pop("ollama_model", None)

    if client is None:
        raise RuntimeError("Add your OpenAI key in Settings first.")

    # The reasoning models (o-series, gpt-5) accept only the default
    # temperature and reject any explicit value, so a user-set temperature
    # must not be allowed to make those models unusable. It's sent when set,
    # and dropped on the specific complaint the API raises about it — the
    # same shape of retry the max_tokens split below already uses.
    if temperature is not None:
        kwargs["temperature"] = temperature

    def _create(**extra):
        return client.chat.completions.create(**extra, **kwargs)

    note_text_engine(f"OpenAI · {kwargs.get('model', '')}".rstrip(" ·"))   # NEW (1.5.0)

    def _without_temperature(**extra):
        kwargs.pop("temperature", None)
        return client.chat.completions.create(**extra, **kwargs)

    try:
        return _create(max_completion_tokens=max_tokens)
    except Exception as e:
        message = str(e)
        rejects_temperature = "temperature" in message and (
            "unsupported_value" in message or "unsupported_parameter" in message
        )
        rejects_ceiling = "max_completion_tokens" in message and "unsupported_parameter" in message

        if rejects_temperature and rejects_ceiling:
            return _without_temperature(max_tokens=max_tokens)
        if rejects_temperature:
            return _without_temperature(max_completion_tokens=max_tokens)
        if rejects_ceiling:
            return _create(max_tokens=max_tokens)
        raise


def get_history(session_id, profile_id, system_prompt):
    key = f"{session_id}::{profile_id or 'default'}"
    with SESSIONS_LOCK:
        if key not in SESSIONS:
            SESSIONS[key] = [{"role": "system", "content": system_prompt}]
        else:
            SESSIONS[key][0] = {"role": "system", "content": system_prompt}
        return SESSIONS[key]


def get_chat_reply(history, max_words, language="English", condense=True, temperature=None):
    """
    CHANGED (1.5.0): `condense=False` skips the rewrite-to-length pass (Echo
    and Mimic say everything you wrote), and `temperature` overrides the
    Settings value (Mimic translates at 0 so it doesn't get creative).

    Generate a reply near the word target. If the model badly overshoots, ask
    it once to rewrite at the right length — that keeps every sentence intact,
    unlike cutting the text, and stops a runaway reply from burning credits.

    For non-English languages the model also returns an English translation
    after a delimiter. That's split off first, so the translation never counts
    toward the word target or triggers a false overshoot.

    Returns the OpenAI time spent (wall-clock seconds actually waiting on
    the API) alongside the reply, so the UI can show it — this is the sum of
    both calls when the condense/rewrite pass runs, not just the first one.
    """
    client = make_openai_client()
    model = CFG.get("model", RECOMMENDED_TEXT_MODEL)
    provider = resolve_provider("chat_provider", CHAT_PROVIDERS)
    ollama_model = active_ollama_model()   # CHANGED (1.5.0): the slot in use

    per_word = 1.4
    if language in SPACELESS_LANGUAGES or language in {"Korean", "Russian", "Ukrainian",
                                                       "Bulgarian", "Greek", "Arabic",
                                                       "Hindi", "Tamil"}:
        per_word = 3.0
    max_tokens = int(max_words * per_word * 1.8) + 40
    # Room for the translation line, which is generated in the same response.
    if language != "English":
        max_tokens = int(max_tokens * 1.9)

    # An explicit ceiling from Settings wins over the derived one. Left at
    # Auto (0) the calculation above stands, so the reply-length fader keeps
    # working exactly as it always has.
    override = clamp_max_tokens(CFG.get("max_tokens", 0))
    if override:
        max_tokens = override

    if temperature is None:
        temperature = clamp_temperature(CFG.get("temperature", 0.7))

    openai_seconds = 0.0

    call_start = time.perf_counter()
    response = create_chat_completion(
        client,
        provider=provider,
        model=model,
        ollama_model=ollama_model,
        messages=history,
        max_tokens=max_tokens,
        temperature=temperature,
    )
    openai_seconds += time.perf_counter() - call_start

    choice = response.choices[0]
    raw = choice.message.content.strip()
    hit_ceiling = choice.finish_reason == "length"

    reply, english = split_translation(raw)

    if not condense or (count_words(reply, language) <= max_words and not hit_ceiling):
        return reply, english, False, hit_ceiling, openai_seconds

    call_start = time.perf_counter()
    condensed = create_chat_completion(
        client,
        provider=provider,
        model=model,
        ollama_model=ollama_model,
        messages=[{"role": "user", "content": build_condense_prompt(reply, max_words, language)}],
        max_tokens=max_tokens,
        temperature=temperature,
    )
    openai_seconds += time.perf_counter() - call_start

    condensed_choice = condensed.choices[0]
    condensed_raw = condensed_choice.message.content.strip()
    condensed_text, condensed_english = split_translation(condensed_raw)

    if condensed_text and count_words(condensed_text, language) < count_words(reply, language):
        # The rewrite pass isn't asked for a translation, so keep the original
        # one only if the rewrite didn't supply its own.
        return (
            condensed_text,
            condensed_english or english,
            True,
            condensed_choice.finish_reason == "length",
            openai_seconds,
        )

    return reply, english, False, hit_ceiling, openai_seconds


# ---------------------------------------------------------------------------
# NEW (1.5.0): free voices, the ones built into Windows
#
# ElevenLabs stays exactly as it was. It's the AI voice, for anyone who wants
# one. The free voices are plain text-to-speech built into Windows: no
# account, no key, no download, no graphics card, and very little CPU.
#
#   windows:<name>  the desktop voices (David, Zira, and any other SAPI voice
#                   installed). What Frivo has always used.
#   onecore:<id>    the newer voices Windows installs with each language
#                   (Settings > Time & language > Speech adds more). Desktop
#                   programs can't reach these through the usual speech API,
#                   so Frivo didn't list them before.
#
# CHANGED (1.5.0): Kokoro, an AI voice model added earlier in 1.5.0, has been
# removed. A free voice should be light, and AI voices are what ElevenLabs is
# for. Anything set to a Kokoro voice is moved to a Windows voice, and the
# downloaded model is deleted (replace_retired_voices, remove_retired_voice_files).
#
# Both kinds are spoken by app\windows_speech.ps1, which Frivo starts once and
# keeps running (WindowsSpeechHost). Starting PowerShell and the speech engine
# again for every reply used to add about a second.
# ---------------------------------------------------------------------------

import atexit
import collections
from urllib.parse import quote

WINDOWS_PREFIX = "windows:"
ONECORE_PREFIX = "onecore:"
# CHANGED (1.5.0): voices from an engine Frivo no longer has.
RETIRED_PREFIXES = ("kokoro:",)
RETIRED_VOICE_DIRS = [os.path.join(DATA_DIR, "voices", "kokoro")]
WINDOWS_SPEECH_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "windows_speech.ps1")
WINDOWS_VOICES_CACHE = {"voices": None, "at": 0.0, "error": ""}
WINDOWS_VOICES_LOCK = threading.Lock()
WINDOWS_VOICES_CACHE_SECONDS = 600


def tts_engine(voice_id):
    voice_id = voice_id or ""
    if voice_id.startswith("piper:"):   # NEW (1.5.0): the voices included with Frivo
        return "piper"
    if voice_id.startswith((WINDOWS_PREFIX, ONECORE_PREFIX)):
        return "windows"
    if voice_id.startswith(RETIRED_PREFIXES):
        return "retired"
    return "elevenlabs"


TTS_ENGINE_NAMES = {"elevenlabs": "ElevenLabs", "piper": "Frivo voice (free)",   # CHANGED (1.5.0): piper
                    "windows": "Windows voice (free)", "retired": "Removed voice"}


def windows_voices_available():
    return os.name == "nt" and bool(_powershell_path())


def _powershell_path():
    root = os.environ.get("SystemRoot") or r"C:\Windows"
    candidate = os.path.join(root, "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
    return candidate if os.path.isfile(candidate) else shutil.which("powershell")


def _ps_literal(value):
    return "'" + str(value).replace("'", "''") + "'"


class WindowsSpeechGone(RuntimeError):
    """The helper wasn't running, or stopped. Starting it again may help."""


class WindowsSpeechHost:
    """
    The one running copy of windows_speech.ps1, and how to talk to it.

    One request at a time. A helper that stops is started again on the next
    request, and one that hangs is stopped and replaced, so a voice that
    breaks can't take the next reply down with it.
    """

    START_SECONDS = 30   # extra time allowed when the helper has to start first

    def __init__(self, command=None):
        self._command = command
        self.proc = None
        self.answers = None
        self.lock = threading.Lock()
        self.stderr = collections.deque(maxlen=20)

    def command(self):
        if self._command:
            return list(self._command)
        # The script is read and run as a script block rather than run as a
        # file, so a PC whose execution policy blocks scripts still runs it.
        return [_powershell_path(), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command",
                "& ([scriptblock]::Create([IO.File]::ReadAllText(%s, [Text.Encoding]::UTF8)))"
                % _ps_literal(WINDOWS_SPEECH_SCRIPT)]

    def _start(self):
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        proc = subprocess.Popen(self.command(), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, creationflags=flags)
        answers = queue.Queue()

        def read_answers():
            for raw in iter(proc.stdout.readline, b""):
                line = raw.decode("utf-8", errors="replace").strip()
                if line.startswith("@@FRIVO "):
                    answers.put(line[len("@@FRIVO "):])
            answers.put(None)   # the helper has stopped

        def read_errors():
            for raw in iter(proc.stderr.readline, b""):
                text = raw.decode("utf-8", errors="replace").strip()
                if text:
                    self.stderr.append(text)

        threading.Thread(target=read_answers, name="windows-speech-out", daemon=True).start()
        threading.Thread(target=read_errors, name="windows-speech-err", daemon=True).start()
        self.proc, self.answers = proc, answers

    def _stop(self):
        proc, self.proc = self.proc, None
        if proc is not None:
            try:
                proc.kill()
            except OSError:
                pass

    def close(self):
        with self.lock:
            self._stop()

    def _ask(self, request, timeout):
        if self.proc is None or self.proc.poll() is not None:
            self._start()
            timeout += self.START_SECONDS
        try:
            # ASCII on the way in (non-English text travels as \u escapes), so
            # the console's code page can never garble it.
            self.proc.stdin.write((json.dumps(request, ensure_ascii=True) + "\n").encode("ascii"))
            self.proc.stdin.flush()
        except OSError as e:
            self._stop()
            raise WindowsSpeechGone(f"The Windows speech helper stopped ({e}).")
        try:
            line = self.answers.get(timeout=timeout)
        except queue.Empty:
            self._stop()
            raise RuntimeError("The Windows voice took too long to answer.")
        if line is None:
            detail = " ".join(self.stderr)[-300:]
            self._stop()
            raise WindowsSpeechGone("The Windows speech helper stopped." + (f" {detail}" if detail else ""))
        return json.loads(line)

    def request(self, request, timeout=60):
        """Sends one request and returns the answer. Raises if it failed."""
        with self.lock:
            try:
                answer = self._ask(request, timeout)
            except WindowsSpeechGone:
                # Once more with a fresh helper: one that died since the last
                # reply shouldn't cost this one.
                answer = self._ask(request, timeout)
        if not answer.get("ok"):
            raise RuntimeError(answer.get("error") or "The Windows voice couldn't speak.")
        return answer


WINDOWS_SPEECH = WindowsSpeechHost()
atexit.register(WINDOWS_SPEECH.close)


def _short_voice_name(name):
    return re.sub(r"^Microsoft\s+|\s+(Desktop|Mobile)$", "", name or "").strip()


def list_windows_voices(force=False):
    """
    Every Windows voice, as {kind, id, name, gender, culture, language}.
    Kept for ten minutes. A failed look is kept for only thirty seconds.
    """
    if not windows_voices_available():
        return []
    now = time.time()
    with WINDOWS_VOICES_LOCK:
        cached = WINDOWS_VOICES_CACHE["voices"]
        if not force and cached is not None and now - WINDOWS_VOICES_CACHE["at"] < WINDOWS_VOICES_CACHE_SECONDS:
            return cached
    voices, error, at = [], "", now
    try:
        answer = WINDOWS_SPEECH.request({"op": "list"}, timeout=30)
        voices = [v for v in (answer.get("voices") or [])
                  if isinstance(v, dict) and v.get("id") and v.get("kind") in ("sapi", "onecore")]
        error = answer.get("onecore_error") or ""
        if error:
            log_server_event(f"Windows voices: the newer voices aren't available: {error}")
    except Exception as e:
        log_server_event(f"Windows voices: couldn't list them: {e!r}")
        error = str(e)
        at = now - WINDOWS_VOICES_CACHE_SECONDS + 30
    with WINDOWS_VOICES_LOCK:
        WINDOWS_VOICES_CACHE.update(voices=voices, at=at, error=error)
    return voices


def _newer_copies(voices):
    """{(short name, culture): newer voice} for the voices Windows has in both kinds."""
    return {(_short_voice_name(v["name"]).lower(), (v.get("culture") or "").lower()): v
            for v in voices if v["kind"] == "onecore"}


def _newer_copy_of(voice_id, voices):
    """The onecore: id of the same voice in its newer form, or None."""
    if not voice_id.startswith(WINDOWS_PREFIX):
        return None
    desktop = next((v for v in voices if v["kind"] == "sapi" and WINDOWS_PREFIX + v["id"] == voice_id), None)
    if not desktop:
        return None
    match = _newer_copies(voices).get((_short_voice_name(desktop["name"]).lower(),
                                       (desktop.get("culture") or "").lower()))
    return (ONECORE_PREFIX + match["id"], _short_voice_name(match["name"])) if match else None


def windows_voice_entries():
    voices = list_windows_voices()
    # The newer copy of a voice is listed, not both. CHANGED (1.5.0): with
    # no exception for one in use; upgrade_desktop_voices() moves those over.
    newer = _newer_copies(voices)
    entries = []
    for v in voices:
        prefix = ONECORE_PREFIX if v["kind"] == "onecore" else WINDOWS_PREFIX
        voice_id = prefix + v["id"]
        short = _short_voice_name(v["name"])
        culture = v.get("culture") or ""
        if v["kind"] == "sapi" and (short.lower(), culture.lower()) in newer:
            continue
        code = culture.split("-")[0].lower()
        region = re.search(r"\(([^)]+)\)\s*$", v.get("language") or "")
        lang_name = VOICE_LANGUAGE_NAMES.get(code, (v.get("language") or code.upper()).split(" (")[0])
        entries.append({
            "voice_id": voice_id,
            "name": short or v["name"],
            "category": "built into Windows",
            "tags": ["windows", "free"],
            "gender": (v.get("gender") or "").lower(),
            "created_at": None,
            "languages": [{"code": code, "name": f"{lang_name} · {region.group(1)}" if region else lang_name}] if code else [],
            "language_source": "declared",
            "preview_url": "/api/voices/preview?voice_id=" + quote(voice_id, safe=""),
            "description": "Free voice built into Windows. No download, and light on the PC.",
        })
    return entries


# ---------------------------------------------------------------------------
# NEW (1.5.0): the free voices included with Frivo (Piper)
#
# Six voices that sound clearly better than Windows' own: Kristin, Cori and
# Alba (female), John, Joe and Norman (male), in American and British
# English. Setup downloads them once (voice_pack.py) into voices\piper next
# to this file. Frivo only reads that folder and never downloads anything
# itself.
#
# They're light by design. They run on one CPU thread, never the graphics
# card, and a reply takes well under a tenth of that thread while it plays.
# The speech library is sherpa-onnx (Apache 2.0, in requirements.txt). At
# most two voices are kept loaded, about 170 MB of memory each.
# ---------------------------------------------------------------------------

import collections as _collections
import importlib.util as _importlib_util

PIPER_PREFIX = "piper:"
PIPER_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "voices", "piper")
PIPER_THREADS = 1
PIPER_KEEP_LOADED = 2
PIPER_LOCK = threading.Lock()          # the loaded voices
PIPER_SPEAK_LOCK = threading.Lock()    # one reply at a time: one thread, never more
PIPER_ENGINES = _collections.OrderedDict()
PIPER_STATE = {"package_problem": None}


def _load_voice_pack():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "voice_pack.py")
    if not os.path.isfile(path):
        return None
    try:
        spec = _importlib_util.spec_from_file_location("frivo_voice_pack", path)
        module = _importlib_util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    except Exception as e:
        log_server_event(f"Frivo voices: voice_pack.py couldn't load: {e!r}")
        return None


VOICE_PACK = _load_voice_pack()


def piper_package_problem():
    """None when the speech library can be used, else why not."""
    with PIPER_LOCK:
        if PIPER_STATE["package_problem"] is not None:
            return PIPER_STATE["package_problem"] or None
    problem = ""
    if VOICE_PACK is None:
        problem = "Frivo's voices are missing a file (voice_pack.py). Run Frivo's setup again (Repair)."
    elif "sherpa_onnx" not in sys.modules and _importlib_util.find_spec("sherpa_onnx") is None:
        problem = "Frivo's voices need its speech library. Run Frivo's setup again (Repair) to add it."
    with PIPER_LOCK:
        PIPER_STATE["package_problem"] = problem
    return problem or None


def piper_voice(voice_id):
    if VOICE_PACK is None or not (voice_id or "").startswith(PIPER_PREFIX):
        return None
    key = voice_id[len(PIPER_PREFIX):]
    if key.startswith(CUSTOM_VOICE_PREFIX):   # NEW (1.5.0): a voice you added
        return custom_voice(key)
    return VOICE_PACK.VOICES_BY_KEY.get(key)


def piper_paths(voice):
    """
    NEW (1.5.0): where a voice's files are. Frivo's own are in the install
    folder; ones you added are in %APPDATA%/Frivo/voices, and share the
    pronunciation data that came with Frivo's.
    """
    if voice.get("custom"):
        folder = os.path.join(CUSTOM_VOICES_DIR, voice["key"])
        return {"folder": folder, "model": os.path.join(folder, "model.onnx"),
                "tokens": os.path.join(folder, "tokens.txt"),
                "espeak": os.path.join(PIPER_DIR, VOICE_PACK.ESPEAK)}
    return VOICE_PACK.voice_paths(voice, PIPER_DIR)


def piper_voice_ready(voice):
    if VOICE_PACK is None:
        return False
    if voice.get("custom"):   # NEW (1.5.0)
        paths = piper_paths(voice)
        return (VOICE_PACK.espeak_ready(PIPER_DIR) and os.path.isfile(paths["model"])
                and os.path.isfile(paths["tokens"]))
    return VOICE_PACK.voice_ready(voice, PIPER_DIR)


def piper_problem(voice_id, language):
    problem = piper_package_problem()
    if problem:
        return problem
    voice = piper_voice(voice_id)
    if voice is None:
        if (voice_id or "").startswith(PIPER_PREFIX + CUSTOM_VOICE_PREFIX):   # NEW (1.5.0)
            return "That voice you added has been removed. Pick another voice in the Voice list."
        return "That voice isn't one of Frivo's voices. Pick another voice in the Voice list."
    if voice.get("custom"):   # NEW (1.5.0): a voice you added speaks its own language
        if not piper_voice_ready(voice):
            if not VOICE_PACK.espeak_ready(PIPER_DIR):
                return "Voices you add use the pronunciation data that comes with Frivo's voices. Run Frivo's setup again (Repair)."
            return f"The {voice['name']} voice's files are missing. Remove it and add it again."
        spoken = voice.get("language_name") or ""
        if language and spoken and language != spoken:
            return (f"{voice['name']} speaks {spoken}. Pick a voice for {language}, "
                    f"switch the language to {spoken}, or turn Speak off.")
        return None
    if not piper_voice_ready(voice):
        return f"The {voice['name']} voice isn't installed. Run Frivo's setup again (Repair) to put it back."
    if language and language != "English":   # CHANGED (1.5.0): no language = don't check (previews)
        return (f"Frivo's voices speak English. Pick a Windows voice or an ElevenLabs voice for {language}, "
                "or turn Speak off.")
    return None


def piper_engine(voice):
    """The loaded voice, loading it (and letting the oldest go) if needed."""
    key = voice["key"]
    with PIPER_LOCK:
        if key in PIPER_ENGINES:
            PIPER_ENGINES.move_to_end(key)
            return PIPER_ENGINES[key]
    try:
        import sherpa_onnx
    except Exception as e:
        problem = f"Frivo's voices couldn't start ({e}). Run Frivo's setup again (Repair)."
        with PIPER_LOCK:
            PIPER_STATE["package_problem"] = problem
        raise RuntimeError(problem)
    paths = piper_paths(voice)   # CHANGED (1.5.0): Frivo's own, or one you added
    engine = sherpa_onnx.OfflineTts(sherpa_onnx.OfflineTtsConfig(model=sherpa_onnx.OfflineTtsModelConfig(
        num_threads=PIPER_THREADS, provider="cpu",
        vits=sherpa_onnx.OfflineTtsVitsModelConfig(model=paths["model"], tokens=paths["tokens"],
                                                   data_dir=paths["espeak"]))))
    with PIPER_LOCK:
        PIPER_ENGINES[key] = engine
        PIPER_ENGINES.move_to_end(key)
        while len(PIPER_ENGINES) > PIPER_KEEP_LOADED:
            PIPER_ENGINES.popitem(last=False)
        return engine


def _piper_generate(voice, pages):
    """[(samples, rate)] for each page, spoken one after another."""
    speed = clamp_speaking_speed(CFG.get("speaking_speed", 1.0))
    engine = piper_engine(voice)
    out = []
    with PIPER_SPEAK_LOCK:
        for page in pages:
            audio = engine.generate(page, sid=0, speed=speed)
            if not audio.samples:
                raise RuntimeError(f"The {voice['name']} voice didn't make any audio.")
            out.append((list(audio.samples), audio.sample_rate))
    return out


def piper_speak(text, voice_id, path):
    import sherpa_onnx

    samples, rate = _piper_generate(piper_voice(voice_id), [text])[0]
    sherpa_onnx.write_wave(path, samples, rate)


def piper_speak_pages(pages, voice_id, path):
    """Each chatbox page spoken on its own, joined. Returns the second each page ends."""
    import sherpa_onnx

    parts = _piper_generate(piper_voice(voice_id), pages)
    rate = parts[0][1]
    joined, ends, total = [], [], 0
    for samples, _ in parts:
        joined.extend(samples)
        total += len(samples)
        ends.append(total / float(rate))
    sherpa_onnx.write_wave(path, joined, rate)
    return ends


def piper_voice_entries():
    if VOICE_PACK is None or piper_package_problem():
        return []
    entries = custom_voice_entries()   # NEW (1.5.0): voices you added, listed first
    for voice in VOICE_PACK.VOICES:
        if not piper_voice_ready(voice):
            continue
        voice_id = PIPER_PREFIX + voice["key"]
        entries.append({
            "voice_id": voice_id,
            "name": voice["name"],
            "category": "included with Frivo",
            "tags": ["included", "free"],
            "gender": voice["gender"],
            "created_at": None,
            "languages": [{"code": "en", "name": f"English · {voice['region']}"}],
            "language_source": "declared",
            "preview_url": "/api/voices/preview?voice_id=" + quote(voice_id, safe=""),
            "description": "Free voice included with Frivo. Runs on this PC with very little CPU and no graphics card.",
        })
    return entries


# ---------------------------------------------------------------------------
# NEW (1.5.0): voices you add yourself
#
# Any Piper voice works: there are hundreds, free, in dozens of languages
# (the Piper voice library on Hugging Face, or the sherpa-onnx collection
# on GitHub). Add one from the voice list ("Add a voice") as either
#   * the voice's .onnx file and its .onnx.json, or
#   * an archive with them in it (.zip, .tar.gz, .tar.bz2), including the
#     sherpa-onnx ones, which already come in the form Frivo reads.
# A plain Piper voice is converted on the way in: the list of sounds in its
# .onnx.json becomes tokens.txt, and the few facts the speech library reads
# (language, sample rate, that it's a Piper voice) are added to the model
# file. No extra software is needed for that. Each one is tried out (it
# says a word) before it's kept, so a file that isn't a working voice is
# turned away with a reason.
#
# They're kept in %APPDATA%\Frivo\voices\<key>\, with your settings, so
# updates and Repair leave them alone. Nothing is ever run from them: a
# voice is data for the speech library, not a program.
# ---------------------------------------------------------------------------

CUSTOM_VOICE_PREFIX = "custom-"
CUSTOM_VOICES_DIR = os.path.join(DATA_DIR, "voices")
CUSTOM_VOICES_INDEX = os.path.join(CUSTOM_VOICES_DIR, "voices.json")
CUSTOM_VOICES_LOCK = threading.Lock()
CUSTOM_VOICE_MAX_BYTES = 400 * 1024 * 1024     # the biggest Piper voices are about 120 MB
CUSTOM_VOICE_MAX_COUNT = 100
_CUSTOM_KEY_RE = re.compile(r"^custom-[a-z0-9-]{1,40}-[0-9a-f]{6}$")


def load_custom_voices():
    try:
        with open(CUSTOM_VOICES_INDEX, "r", encoding="utf-8") as f:
            items = json.load(f)
        return [v for v in items if isinstance(v, dict) and _CUSTOM_KEY_RE.match(str(v.get("key", "")))]
    except (OSError, ValueError, TypeError):
        return []


def write_custom_voices(items):
    os.makedirs(CUSTOM_VOICES_DIR, exist_ok=True)
    temp = CUSTOM_VOICES_INDEX + ".tmp"
    with open(temp, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=1)
    os.replace(temp, CUSTOM_VOICES_INDEX)


def custom_voice(key):
    for voice in load_custom_voices():
        if voice["key"] == key:
            return dict(voice, custom=True)
    return None


def custom_voice_entries():
    entries = []
    for voice in load_custom_voices():
        voice = dict(voice, custom=True)
        if not piper_voice_ready(voice):
            continue
        voice_id = PIPER_PREFIX + voice["key"]
        label = voice.get("language_name") or "Unknown language"
        if voice.get("region"):
            label += f" · {voice['region']}"
        entries.append({
            "voice_id": voice_id,
            "name": voice["name"],
            "category": "added by you",
            "tags": ["custom", "free"],
            "gender": voice.get("gender") or "",
            "created_at": None,
            "languages": [{"code": voice.get("language_code") or "en", "name": label}],
            "language_source": "declared",
            "preview_url": "/api/voices/preview?voice_id=" + quote(voice_id, safe=""),
            "description": "A voice you added. Free, and runs on this PC with very little CPU and no graphics card.",
            "custom": True,
        })
    return entries


def _protobuf_varint(number):
    out = bytearray()
    while True:
        byte = number & 0x7F
        number >>= 7
        if number:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def _onnx_metadata_entry(key, value):
    """One ModelProto.metadata_props entry (field 14), as protobuf bytes."""
    k, v = key.encode("utf-8"), str(value).encode("utf-8")
    body = b"\x0a" + _protobuf_varint(len(k)) + k + b"\x12" + _protobuf_varint(len(v)) + v
    return b"\x72" + _protobuf_varint(len(body)) + body


def _voice_name_from_file(stem):
    """'en_US-amy-medium' or 'vits-piper-en_GB-alan-low' -> 'Amy'."""
    stem = re.sub(r"\.onnx$", "", stem)
    stem = re.sub(r"^vits-piper-", "", stem)
    stem = re.sub(r"-(fp16|int8)$", "", stem)
    parts = [p for p in re.split(r"[-_]", stem) if p]
    skip = {"x", "low", "medium", "high", "en", "us", "gb", "uk"}
    words = [p for p in parts if p.lower() not in skip and not re.fullmatch(r"[a-z]{2}", p.lower() if len(p) == 2 else "--")]
    name = " ".join(words) or stem or "My voice"
    return name.replace("_", " ").title()[:40]


def _language_from_code(code):
    """'en_US' -> ('en', 'English', 'United States') as far as is known."""
    names = {"en": "English", "de": "German", "fr": "French", "es": "Spanish", "it": "Italian",
             "pt": "Portuguese", "nl": "Dutch", "ru": "Russian", "pl": "Polish", "uk": "Ukrainian",
             "zh": "Chinese", "ja": "Japanese", "ko": "Korean", "sv": "Swedish", "no": "Norwegian",
             "da": "Danish", "fi": "Finnish", "tr": "Turkish", "cs": "Czech", "el": "Greek",
             "hu": "Hungarian", "ro": "Romanian", "ar": "Arabic", "vi": "Vietnamese", "ca": "Catalan"}
    regions = {"US": "US", "GB": "UK", "AU": "AU", "IN": "IN", "DE": "DE", "AT": "AT", "CH": "CH",
               "FR": "FR", "ES": "ES", "MX": "MX", "BR": "BR", "PT": "PT", "NL": "NL", "BE": "BE"}
    match = re.match(r"^([a-z]{2,3})(?:[_-]([A-Z]{2}))?$", code or "")
    if not match:
        return "", "", ""
    return match.group(1), names.get(match.group(1), ""), regions.get(match.group(2) or "", match.group(2) or "")


def _try_voice(model, tokens):
    """Makes the voice say a word. Raises with a plain reason if it can't."""
    import sherpa_onnx
    try:
        engine = sherpa_onnx.OfflineTts(sherpa_onnx.OfflineTtsConfig(model=sherpa_onnx.OfflineTtsModelConfig(
            num_threads=PIPER_THREADS, provider="cpu",
            vits=sherpa_onnx.OfflineTtsVitsModelConfig(model=model, tokens=tokens,
                                                       data_dir=os.path.join(PIPER_DIR, VOICE_PACK.ESPEAK)))))
        audio = engine.generate("Hello.", sid=0, speed=1.0)
    except Exception as e:
        raise ValueError(f"That file isn't a voice Frivo can use ({str(e)[:160]}).")
    if not audio.samples:
        raise ValueError("That voice didn't make any sound when tried.")


def _unpack_voice_upload(paths, staging):
    """Unpacks any archives among the uploaded files. Returns every file there now."""
    import tarfile
    import zipfile

    found = []
    for path in paths:
        name = os.path.basename(path).lower()
        target = os.path.join(staging, "x" + uuid.uuid4().hex[:8])
        if name.endswith((".tar.bz2", ".tbz2", ".tar.gz", ".tgz", ".tar")):
            os.makedirs(target)
            with tarfile.open(path, "r:*") as archive:
                for member in archive.getmembers():
                    base = os.path.basename(member.name.replace("\\", "/"))
                    if not member.isfile() or not base.lower().endswith((".onnx", ".json", ".txt")):
                        continue   # only the voice's own files; pronunciation data is Frivo's
                    out = os.path.join(target, uuid.uuid4().hex[:6] + "-" + base)
                    with archive.extractfile(member) as src, open(out, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                    found.append((out, base))
        elif name.endswith(".zip"):
            os.makedirs(target)
            with zipfile.ZipFile(path) as archive:
                for info in archive.infolist():
                    base = os.path.basename(info.filename.replace("\\", "/"))
                    if info.is_dir() or not base.lower().endswith((".onnx", ".json", ".txt")):
                        continue
                    out = os.path.join(target, uuid.uuid4().hex[:6] + "-" + base)
                    with archive.open(info) as src, open(out, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                    found.append((out, base))
        else:
            found.append((path, os.path.basename(path)))
    return found


def add_custom_voice(paths, name=""):
    """
    Turns uploaded files into a voice Frivo can use, and keeps it. Returns
    the new voice's entry. Raises ValueError with a reason for the person.
    """
    if VOICE_PACK is None or piper_package_problem():
        raise ValueError(piper_package_problem() or "Frivo's voices aren't set up. Run Frivo's setup again (Repair).")
    if not VOICE_PACK.espeak_ready(PIPER_DIR):
        raise ValueError("Voices you add use the pronunciation data that comes with Frivo's voices. Run Frivo's setup again (Repair).")
    staging = tempfile.mkdtemp(prefix=".adding-", dir=CUSTOM_VOICES_DIR)
    try:
        files = _unpack_voice_upload(paths, staging)
        models = [(p, b) for p, b in files if b.lower().endswith(".onnx")]
        if not models:
            raise ValueError("There's no voice in that. A Piper voice is an .onnx file (with its .onnx.json), "
                             "or an archive with them in it. Programs (.exe, .vb, …) can't be voices.")
        if len(models) > 1:
            models.sort(key=lambda m: os.path.getsize(m[0]), reverse=True)   # the voice, not a helper model
        model_path, model_name = models[0]
        config = next((p for p, b in files if b.lower() in (model_name.lower() + ".json", "config.json")
                       or b.lower().endswith(".onnx.json")), None)
        tokens = next((p for p, b in files if b.lower() == "tokens.txt"), None)
        if not config and not tokens:
            raise ValueError("That voice is missing its .onnx.json file. Add the .onnx and the .onnx.json together.")
        # The same voice added again is recognised by its model file.
        fingerprint = VOICE_PACK._sha256(model_path)
        with CUSTOM_VOICES_LOCK:
            twin = next((v for v in load_custom_voices() if v.get("sha256") == fingerprint), None)
        if twin:
            raise ValueError(f"You've already added this voice: it's {twin['name']}.")
        info = {}
        if config:
            with open(config, "r", encoding="utf-8") as f:
                info = json.load(f)
        stem = re.sub(r"\.onnx$", "", model_name, flags=re.I)
        lang = info.get("language") or {}
        # The language: stated in the .onnx.json by newer voices; older ones
        # only give their eSpeak voice ("en-us") and their file name.
        code = lang.get("code") or ""
        if not code:
            hint = (info.get("espeak") or {}).get("voice") or ""
            found = re.match(r"^([a-z]{2,3})(?:[-_]([a-z]{2}))?$", hint, re.I) \
                or re.search(r"(?:^|[-_])([a-z]{2})[-_]([a-z]{2})(?:[-_]|$)", stem, re.I)
            if found:
                code = found.group(1).lower() + (("_" + found.group(2).upper()) if found.group(2) else "")
        lang_code, lang_name, region = _language_from_code(code)
        if lang.get("name_english"):
            lang_name = lang["name_english"]
        if lang.get("country_english") and not region:
            region = lang["country_english"]
        label = (name or "").strip()[:40] or _voice_name_from_file(info.get("dataset") or stem)
        slug = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")[:40] or "voice"
        key = f"{CUSTOM_VOICE_PREFIX}{slug}-{uuid.uuid4().hex[:6]}"
        made = os.path.join(staging, key)
        os.makedirs(made)
        out_model = os.path.join(made, "model.onnx")
        out_tokens = os.path.join(made, "tokens.txt")
        if config and "phoneme_id_map" in info:
            # A plain Piper voice: write tokens.txt, and add what the speech
            # library reads to the model file.
            espeak_voice = (info.get("espeak") or {}).get("voice") or code.replace("_", "-").lower() or "en-us"
            meta = {"model_type": "vits", "comment": "piper", "language": lang_name or "English",
                    "voice": espeak_voice, "has_espeak": 1,
                    "n_speakers": int(info.get("num_speakers") or 1),
                    "sample_rate": int((info.get("audio") or {}).get("sample_rate") or 22050)}
            with open(model_path, "rb") as src, open(out_model, "wb") as dst:
                shutil.copyfileobj(src, dst)
                for k, v in meta.items():
                    dst.write(_onnx_metadata_entry(k, v))
            with open(out_tokens, "w", encoding="utf-8") as f:
                for symbol, ids in info["phoneme_id_map"].items():
                    if ids:
                        f.write(f"{symbol} {int(ids[0])}\n")
        elif tokens:
            # Already in the speech library's form (a sherpa-onnx archive).
            shutil.copyfile(model_path, out_model)
            shutil.copyfile(tokens, out_tokens)
        else:
            raise ValueError("That voice is missing its .onnx.json file. Add the .onnx and the .onnx.json together.")
        _try_voice(out_model, out_tokens)
        with CUSTOM_VOICES_LOCK:
            items = load_custom_voices()
            if len(items) >= CUSTOM_VOICE_MAX_COUNT:
                raise ValueError(f"You've added {CUSTOM_VOICE_MAX_COUNT} voices. Remove some to add more.")
            os.replace(made, os.path.join(CUSTOM_VOICES_DIR, key))
            entry = {"key": key, "name": label, "gender": "", "language_code": lang_code,
                     "language_name": lang_name, "region": region, "source": model_name[:120],
                     "sha256": fingerprint,
                     "added_at": time.time()}
            items.append(entry)
            write_custom_voices(items)
        return entry
    finally:
        shutil.rmtree(staging, ignore_errors=True)


@app.route("/api/voices/custom", methods=["POST"])
def custom_voice_add():
    uploads = request.files.getlist("files")
    if not uploads:
        return jsonify({"error": "Choose the voice's files to add."}), 400
    os.makedirs(CUSTOM_VOICES_DIR, exist_ok=True)
    holding = tempfile.mkdtemp(prefix=".upload-", dir=CUSTOM_VOICES_DIR)
    try:
        saved, total = [], 0
        for upload in uploads[:10]:
            base = re.sub(r"[^A-Za-z0-9._-]+", "_", os.path.basename(upload.filename or "file"))[:120] or "file"
            path = os.path.join(holding, uuid.uuid4().hex[:6] + "-" + base)
            with open(path, "wb") as out:
                while True:
                    chunk = upload.stream.read(1 << 20)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > CUSTOM_VOICE_MAX_BYTES:
                        return jsonify({"error": "That's too big to be a voice (over 400 MB)."}), 400
                    out.write(chunk)
            saved.append(path)
        # The uploaded names, without the prefix added above, decide what each file is.
        named = []
        for path in saved:
            original = os.path.basename(path)[7:]
            clean = os.path.join(holding, "n" + uuid.uuid4().hex[:6])
            os.makedirs(clean)
            target = os.path.join(clean, original)
            os.replace(path, target)
            named.append(target)
        try:
            entry = add_custom_voice(named, request.form.get("name") or "")
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        except Exception as e:
            log_server_event(f"Add a voice: {e!r}")
            return jsonify({"error": f"That voice couldn't be added ({e})."}), 500
        return jsonify({"ok": True, "voice_id": PIPER_PREFIX + entry["key"], "name": entry["name"]})
    finally:
        shutil.rmtree(holding, ignore_errors=True)


@app.route("/api/voices/custom/<key>", methods=["DELETE", "PATCH"])
def custom_voice_change(key):
    if not _CUSTOM_KEY_RE.match(key or ""):
        return jsonify({"error": "Not found."}), 404
    with CUSTOM_VOICES_LOCK:
        items = load_custom_voices()
        voice = next((v for v in items if v["key"] == key), None)
        if not voice:
            return jsonify({"error": "Not found."}), 404
        if request.method == "PATCH":
            name = str((request.get_json(silent=True) or {}).get("name") or "").strip()[:40]
            if not name:
                return jsonify({"error": "Give it a name."}), 400
            voice["name"] = name
            write_custom_voices(items)
            return jsonify({"ok": True, "name": name})
        items = [v for v in items if v["key"] != key]
        write_custom_voices(items)
    with PIPER_LOCK:
        PIPER_ENGINES.pop(key, None)
    shutil.rmtree(os.path.join(CUSTOM_VOICES_DIR, key), ignore_errors=True)
    return jsonify({"ok": True})


def piper_status():
    problem = piper_package_problem()
    total = len(VOICE_PACK.VOICES) if VOICE_PACK else 0
    ready = 0 if problem else sum(1 for v in VOICE_PACK.VOICES if piper_voice_ready(v))
    return {"available": problem is None, "problem": problem or "", "count": ready, "total": total}


def free_voice_problem(voice_id, language):
    """None when this free voice can speak right now, else a message for the person."""
    engine = tts_engine(voice_id)
    if engine == "piper":   # NEW (1.5.0)
        return piper_problem(voice_id, language)
    if engine == "retired":
        return "That voice was removed in Frivo 1.5.0. Pick another voice in the Voice list."
    if engine == "windows" and not windows_voices_available():
        return "Windows voices only work when Frivo runs on Windows."
    return None


def _windows_speak_request(voice_id, pages, outs):
    kind = "onecore" if voice_id.startswith(ONECORE_PREFIX) else "sapi"
    speed = clamp_speaking_speed(CFG.get("speaking_speed", 1.0))
    answer = WINDOWS_SPEECH.request({   # CHANGED (1.5.0): keeps the answer
        "op": "speak",
        "kind": kind,
        "voice": voice_id.split(":", 1)[1],
        # The desktop voices take a rate from -10 to 10, the newer ones a
        # multiplier like ElevenLabs'.
        "sapi_rate": max(-10, min(10, round((speed - 1.0) * 10))),
        "speed": round(speed, 3),
        "pages": list(pages),
        "outs": list(outs),
    }, timeout=60 + 15 * len(pages))
    for out_path in outs:
        if not os.path.isfile(out_path) or os.path.getsize(out_path) == 0:
            raise RuntimeError("The Windows voice didn't make any audio.")
    # NEW (1.5.0): where each word starts, per page, when Windows said.
    return answer.get("words") if isinstance(answer, dict) else None


def windows_speak(text, voice_id, path):
    # CHANGED (1.5.0): through the running helper, and takes the whole voice id.
    _windows_speak_request(voice_id, [text], [path])


def windows_speak_pages(pages, voice_id, path):
    """
    CHANGED (1.5.0): speaks each chatbox page to its own wave file, then
    joins them. Returns the second each page ends.
    """
    import wave

    stem = os.path.join(AUDIO_DIR, uuid.uuid4().hex)
    outs = [f"{stem}-{i}.part.wav" for i in range(len(pages))]
    try:
        boundaries = _windows_speak_request(voice_id, pages, outs)   # CHANGED (1.5.0)
        frames, ends, total, params = [], [], 0, None
        for out_path in outs:
            with wave.open(out_path, "rb") as part:
                these = (part.getnchannels(), part.getsampwidth(), part.getframerate())
                if params and these != params:
                    raise RuntimeError("The Windows voice changed format between pages.")
                params = these
                count = part.getnframes()
                frames.append(part.readframes(count))
                total += count
                ends.append(total / float(params[2]))
        with wave.open(path, "wb") as joined:
            joined.setnchannels(params[0])
            joined.setsampwidth(params[1])
            joined.setframerate(params[2])
            joined.writeframes(b"".join(frames))
        # CHANGED (1.5.0): and when each word is spoken, if Windows said.
        try:
            words = word_times_from_boundaries(pages, boundaries, ends)
        except Exception as e:
            log_server_event(f"Word timing (Windows): {e!r}")
            words = None
        return ends, words
    finally:
        for leftover in outs:
            try:
                os.remove(leftover)
            except OSError:
                pass


def free_tts_audio(text, voice_id, language):
    filename = f"{uuid.uuid4().hex}.wav"
    path = os.path.join(AUDIO_DIR, filename)
    if tts_engine(voice_id) == "piper":   # NEW (1.5.0)
        piper_speak(text, voice_id, path)
    else:
        windows_speak(text, voice_id, path)
    return filename


def _replacement_for_retired(voice_id):
    """CHANGED (1.5.0): a Windows voice to use instead of a removed one."""
    key = voice_id.split(":", 1)[-1]
    # Kokoro's voice names start with language and gender: "af_heart" is
    # American female, "bm_george" British male.
    gender = {"f": "female", "m": "male"}.get(key[1:2], "")
    # CHANGED (1.5.0): Frivo's own voices first; they're the closest in sound.
    for entry in piper_voice_entries():
        if entry["gender"] == gender:
            return entry["voice_id"], entry["name"]
    entries = windows_voice_entries()
    english = [e for e in entries if e["languages"] and e["languages"][0]["code"] == "en"]
    for pool in ([e for e in english if e["gender"] == gender and e["voice_id"].startswith(ONECORE_PREFIX)],
                 [e for e in english if e["gender"] == gender], english, entries):
        if pool:
            choice = sorted(pool, key=lambda e: e["name"])[0]
            return choice["voice_id"], choice["name"]
    return None


def upgrade_desktop_voices():
    """
    CHANGED (1.5.0): settings and profiles on an older (desktop) Windows
    voice that Windows also has in its newer form move to the newer one.
    It's the same voice, and only the newer one is listed, so this stops the
    Voice list showing it twice.
    """
    voices = list_windows_voices()
    if not voices:
        return
    found = _newer_copy_of(CFG.get("voice_id", ""), voices)
    if found:
        log_server_event(f"Voices: {CFG['voice_id']} moved to its newer copy {found[0]}.")
        CFG["voice_id"], CFG["voice_name"] = found
        save_config(CFG)
    profiles = load_profiles()
    changed = False
    for profile in profiles:
        found = _newer_copy_of(str(profile.get("voice_id", "")), voices)
        if found:
            log_server_event(f"Voices: profile {profile.get('name')!r} moved to {found[0]}.")
            profile["voice_id"] = found[0]
            if "voice_name" in profile:
                profile["voice_name"] = found[1]
            changed = True
    if changed:
        save_profiles(profiles)


def replace_retired_voices():
    """CHANGED (1.5.0): moves settings and profiles off removed voices."""
    if CFG.get("voice_id", "").startswith(RETIRED_PREFIXES):
        found = _replacement_for_retired(CFG["voice_id"])
        if found:
            log_server_event(f"Voices: {CFG['voice_id']} was removed; now using {found[0]}.")
            CFG["voice_id"], CFG["voice_name"] = found
            save_config(CFG)
    profiles = load_profiles()
    changed = False
    for profile in profiles:
        if str(profile.get("voice_id", "")).startswith(RETIRED_PREFIXES):
            found = _replacement_for_retired(profile["voice_id"])
            if found:
                log_server_event(f"Voices: profile {profile.get('name')!r} moved from {profile['voice_id']} to {found[0]}.")
                profile["voice_id"] = found[0]
                if "voice_name" in profile:
                    profile["voice_name"] = found[1]
                changed = True
    if changed:
        save_profiles(profiles)


def remove_retired_voice_files():
    """CHANGED (1.5.0): deletes the Kokoro model that 1.5.0 downloaded earlier."""
    for folder in RETIRED_VOICE_DIRS:
        if os.path.isdir(folder):
            shutil.rmtree(folder, ignore_errors=True)
            log_server_event(f"Voices: deleted the removed voice files in {folder}.")
        parent = os.path.dirname(folder)
        try:
            if os.path.isdir(parent) and not os.listdir(parent):
                os.rmdir(parent)
        except OSError:
            pass


def warm_free_voices():
    """
    CHANGED (1.5.0): starts the Windows speech helper and lists the voices
    when Frivo starts, so the first reply with a Windows voice doesn't wait
    for them. Then tidies up after Kokoro.
    """
    try:
        if windows_voices_available():
            list_windows_voices(force=True)
        # NEW (1.5.0): load the Frivo voices in use (at most two).
        in_use = [CFG.get("voice_id", "")] + [p.get("voice_id", "") for p in load_profiles()]
        for voice_id in dict.fromkeys(v for v in in_use if tts_engine(v) == "piper"):
            voice = piper_voice(voice_id)
            if voice and not piper_problem(voice_id, "English"):
                piper_engine(voice)
        replace_retired_voices()
        upgrade_desktop_voices()   # CHANGED (1.5.0)
        remove_retired_voice_files()
    except Exception as e:
        log_server_event(f"Free voices: start-up check failed: {e!r}")


# ---------------------------------------------------------------------------
# NEW (1.5.0): Expressive voice — ElevenLabs audio tags — and Delivery
#
# ElevenLabs' v3 model follows audio tags: a word or two in square brackets,
# like [whispers], [laughs] or [sighs], performed rather than read out. They
# get into a reply three ways: you add them with the tag button (or ask the
# AI to suggest some for your message), or a profile with Expressive voice
# on lets the AI use them itself, and is told how.
#
# A reply keeps two versions: what the voice is given (with its tags,
# "voiced") and what everything else sees (without them): the chatbox, the
# word count, the free voices, the translation. Anything with a tag, or any
# reply from an Expressive profile, is spoken with v3; everything else with
# the same model as always.
#
# Delivery (Calm / Natural / Lively) sets how much the voice swings. Natural
# is exactly what Frivo always sent. Calm is the cure for a voice that
# sometimes yells: steadier voice settings, and the AI is told to stop
# writing in capitals and exclamation marks.
# ---------------------------------------------------------------------------

AUDIO_TAG_RE = re.compile(r"\[([A-Za-z][A-Za-z' \-]{0,38})\]")
ELEVEN_V2_MODEL = "eleven_multilingual_v2"
ELEVEN_V3_MODEL = "eleven_v3"
# NEW (1.5.0): Eleven v4 (September 2026). ElevenLabs: "Eleven v4 and
# Eleven v3 support audio tags. We recommend Eleven v4", "a net upgrade
# over Eleven v3, delivering better results in almost every case". The
# same tags work with both. v4 Turbo is the low-latency one.
ELEVEN_V4_MODEL = "eleven_v4"
ELEVEN_V4_TURBO_MODEL = "eleven_v4_turbo"
EXPRESSIVE_MODELS = [
    {"id": ELEVEN_V4_MODEL, "name": "v4", "description": "ElevenLabs' newest expressive model, and the one they recommend for tags."},
    {"id": ELEVEN_V4_TURBO_MODEL, "name": "v4 Turbo", "description": "v4, faster to start speaking. A little less polished."},
    {"id": ELEVEN_V3_MODEL, "name": "v3", "description": "The previous expressive model, which Frivo used before v4."},
]
EXPRESSIVE_MODEL_IDS = {m["id"] for m in EXPRESSIVE_MODELS}
DEFAULT_EXPRESSIVE_MODEL = ELEVEN_V4_MODEL
V4_SIMILARITY = 0.85
# A model ElevenLabs refused (not on the account yet, say) is skipped for an
# hour: v4 steps down to v3, and v3 to the standard model without tags.
REFUSED_MODELS = {}   # model id -> when it was refused
# NEW (1.5.0): why, in ElevenLabs' words, for Settings and the status line.
MODEL_REFUSALS = {}   # model id -> {"status", "message", "at"}
# The optional extras a model refused (language_code, similarity_boost,
# previous_request_ids...). Before a model is given up on, it's tried once
# without them; if that works, it just isn't sent them again.
REFUSED_EXTRAS = {}   # model id -> set of field names
_OPTIONAL_FIELDS = ("language_code", "seed", "previous_request_ids", "previous_text")
_OPTIONAL_SETTINGS = ("similarity_boost",)


# NEW (1.5.0): ElevenLabs won't speak a line with no words in it once the
# tags and emojis are taken out ("lol" turned into [laughs], or a message
# that was only an emoji). That's the line, not the model, so it must never
# count as the model refusing (it used to, and every reply dropped to v2
# for an hour). The line is given a word to say instead.
_INPUT_PROBLEM_RE = re.compile(r"empty text|non-empty text|must include", re.I)
_EMOJI_TAGS = (("😂🤣😆😹😅", "laughs"), ("😭😢🥲", "sniffles"), ("😮‍💨😔😩😮", "sighs"),
               ("😱😲😳", "gasps"), ("😏", "chuckles"))
_STAND_INS = (("laugh", "Haha!"), ("giggl", "Hehe!"), ("chuckl", "Heh."), ("snicker", "Heh."),
              ("sigh", "Hmm."), ("exhal", "Hmm."), ("gasp", "Oh!"), ("groan", "Ugh."), ("scoff", "Pfft."),
              ("cry", "Oh..."), ("sob", "Oh..."), ("sniff", "Oh..."), ("hum", "Hmm."), ("yawn", "Mm."))


def has_spoken_words(text):
    """True when `text` has something to say besides tags, emojis and punctuation."""
    return bool(re.search(r"[^\W_]", strip_audio_tags(text or "")))


def ensure_spoken_words(text):
    """
    `text` unchanged when it has words; otherwise its sound said as a word,
    with the tag kept so the voice performs it: "[laughs]" -> "[laughs] Haha!".
    """
    if not text or has_spoken_words(text):
        return text
    tags = [t for _, t in audio_tag_positions(text)]
    if not tags:
        for chars, tag in _EMOJI_TAGS:
            if any(c in text for c in chars):
                tags = [tag]
                break
    word = next((w for t in tags for k, w in _STAND_INS if k in t), "Hmm.")
    lead = " ".join(f"[{t}]" for t in tags[:2])
    return f"{lead} {word}".strip()


def _refusal_message(resp):
    """ElevenLabs' own words for a refusal."""
    try:
        body = resp.json()
        detail = body.get("detail", body)
        if isinstance(detail, dict):
            return str(detail.get("message") or detail.get("status") or detail)[:240]
        if isinstance(detail, list) and detail:
            first = detail[0]
            return str(first.get("msg") if isinstance(first, dict) else first)[:240]
        return str(detail)[:240]
    except Exception:
        return (getattr(resp, "text", "") or "")[:240]


def _without_extras(payload):
    """The same request without the optional extras; None if it had none."""
    slim = {k: v for k, v in payload.items() if k not in _OPTIONAL_FIELDS}
    settings = {k: v for k, v in (payload.get("voice_settings") or {}).items() if k not in _OPTIONAL_SETTINGS}
    slim["voice_settings"] = settings
    if slim == payload:
        return None
    return slim


def _note_voice(message):
    """A note for the status line about how this reply was spoken."""
    from flask import has_request_context
    if has_request_context():
        g.voice_notice = message


def is_expressive_model(model_id):
    return model_id in EXPRESSIVE_MODEL_IDS


def normalize_expressive_model(value, fallback=DEFAULT_EXPRESSIVE_MODEL):
    value = str(value or "").strip().lower()
    return value if value in EXPRESSIVE_MODEL_IDS else fallback


def expressive_model():
    """The expressive model to use now: the chosen one, unless it was just refused."""
    chosen = normalize_expressive_model(CFG.get("expressive_model"))
    for model in (chosen, ELEVEN_V3_MODEL):
        if time.time() - REFUSED_MODELS.get(model, 0) > 3600:
            return model
    return None   # nothing expressive works: the standard model, without tags


def model_label(model_id):
    return {ELEVEN_V4_MODEL: "v4", ELEVEN_V4_TURBO_MODEL: "v4 Turbo", ELEVEN_V3_MODEL: "v3"}.get(model_id, "standard (v2)")
# NEW (1.5.0): accent tags ([british accent]) change who the voice is. Only
# kept when you typed them yourself.
ACCENT_TAG_RE = re.compile(r"\[[^\]\n]*\baccent\b[^\]\n]*\]\s*", re.I)

VOICE_DELIVERIES = [
    {"id": "calm", "name": "Calm", "description": "Steady and even. Doesn't shout."},
    {"id": "natural", "name": "Natural", "description": "The voice as it comes."},
    {"id": "lively", "name": "Lively", "description": "Bigger ups and downs. Can get loud."},
]
VOICE_DELIVERY_IDS = {d["id"] for d in VOICE_DELIVERIES}
DEFAULT_VOICE_DELIVERY = "natural"
# v2 takes any stability (lower swings more) and a style boost; v3 takes
# three settings only: 0 (Creative), 0.5 (Natural) and 1 (Robust).
DELIVERY_SETTINGS = {
    # v3's three settings: Robust holds the voice steadiest but follows tags
    # less; Creative follows them most but wanders. Calm is Robust;
    # Natural and Lively are Natural, and what keeps their accent steady is
    # the stitching below, not the setting.
    "calm": {"v2": {"stability": 0.75, "similarity_boost": 0.75}, "v3": 1.0},
    "natural": {"v2": {"stability": 0.5, "similarity_boost": 0.75}, "v3": 0.5},
    "lively": {"v2": {"stability": 0.3, "similarity_boost": 0.75, "style": 0.35}, "v3": 0.5},
}

# NEW (1.5.0): why a v3 voice changed accent between replies, and what's
# done about each:
#
#   * v3 works out the language from each line by itself and, ElevenLabs
#     says, "very short prompts are more likely to produce variable
#     results" (under about 250 characters, which is most replies). Each
#     request now names the language, and carries ElevenLabs' continuity
#     fields: the ids of the last three things this voice said in this
#     conversation (previous_request_ids) and the words themselves
#     (previous_text), which the API uses to match the new line to them.
#   * v3 and the usual model make the same voice sound different enough to
#     seem like another accent, so a conversation that has used v3 stays on
#     v3 for a while instead of flipping between models.
#   * a fixed seed, so the same settings don't roll a new delivery each time.
V3_STICKY_SECONDS = 30 * 60
V3_LAST_USED = {}   # "session::profile" -> when v3 last spoke
SPEECH_THREADS = {}   # "session::profile::voice::model" -> {"ids": [...], "text": "..."}
SPEECH_THREADS_LOCK = threading.Lock()


def voice_how(voiced):
    """NEW (1.5.0): the ElevenLabs settings a reply was spoken with, in words."""
    payload = _elevenlabs_payload(voiced)
    style = current_voice_style()
    delivery = next((d["name"] for d in VOICE_DELIVERIES if d["id"] == normalize_voice_delivery(style.get("delivery"))), "Natural")
    if is_expressive_model(payload["model_id"]):
        parts = [model_label(payload["model_id"]), delivery]
        mode = normalize_hold_accent(CFG.get("hold_accent"))
        parts.append({"anchor": "anchored", "follow": "following last lines"}.get(mode, "spoken fresh")
                     if payload.get("previous_request_ids") or payload.get("previous_text") else "spoken fresh")
        if has_audio_tags(voiced):
            parts.append(f"{len(AUDIO_TAG_RE.findall(voiced))} tag{'s' if len(AUDIO_TAG_RE.findall(voiced)) != 1 else ''}")
        return " · ".join(parts)
    return f"standard (v2) · {delivery}"


def _step_down(url, headers, text, payload, resp):
    """
    NEW (1.5.0): a refused expressive request. First the same model without
    its optional extras (if that works, those extras aren't sent to it
    again); then the next model (v4 to v3); then the standard model,
    without the tags. Each refusal is remembered with ElevenLabs' reason.
    A refusal isn't billed. Returns the payload and response that won.
    """
    refused = (400, 403, 404, 422)
    first = payload.get("model_id")
    for _ in range(4):
        model = payload.get("model_id")
        if not (resp.status_code in refused and is_expressive_model(model)):
            break
        reason = _refusal_message(resp)
        if _INPUT_PROBLEM_RE.search(reason or ""):
            # NEW (1.5.0): a problem with the line, not the model. Nothing is
            # remembered against the model; the line goes to the standard
            # model as plain words, or fails with ElevenLabs' reason.
            log_server_event(f"Expressive voice: {model} couldn't speak this line ({reason}); not counted against it")
            plain = strip_audio_tags(text)
            if has_spoken_words(plain):
                payload = _elevenlabs_payload(plain, force_v2=True)
                resp = requests.post(url, headers=headers, json=payload, timeout=60)
            break
        slim = _without_extras(payload)
        if slim is not None:
            retry = requests.post(url, headers=headers, json=slim, timeout=60)
            if retry.status_code == 200:
                dropped = {k for k in _OPTIONAL_FIELDS if k in payload} | \
                          {k for k in _OPTIONAL_SETTINGS if k in (payload.get("voice_settings") or {})}
                REFUSED_EXTRAS.setdefault(model, set()).update(dropped)
                log_server_event(f"Expressive voice: {model} refused {sorted(dropped)} ({resp.status_code}: {reason}); "
                                 "not sending them again")
                return slim, retry
            reason = _refusal_message(retry) or reason
        REFUSED_MODELS[model] = time.time()
        MODEL_REFUSALS[model] = {"status": resp.status_code, "message": reason, "at": time.time()}
        log_server_event(f"Expressive voice: {model} refused ({resp.status_code}: {reason}); trying the next model")
        payload = _elevenlabs_payload(text) if expressive_model() else _elevenlabs_payload(text, force_v2=True)
        resp = requests.post(url, headers=headers, json=payload, timeout=60)
    if payload.get("model_id") != first and is_expressive_model(first):
        why = MODEL_REFUSALS.get(first, {}).get("message", "")
        now = model_label(payload.get("model_id"))
        _note_voice(f"ElevenLabs refused {model_label(first)}{': ' + why if why else ''}. "
                    f"Spoken with {now}{'' if is_expressive_model(payload.get('model_id')) else ', without the tags'}.")
    return payload, resp


def _drop_stale_anchor(payload):
    """The anchor in `payload` was refused: forget it (and the thread's ids)."""
    from flask import has_request_context
    if not has_request_context():
        return
    voice_id = getattr(g, "speech_voice", None)
    code = payload.get("language_code") or "en"
    if voice_id:
        with ANCHORS_LOCK:
            anchors = load_anchors()
            entry = anchors.get(anchor_key(voice_id, code))
        if entry and entry.get("id") in (payload.get("previous_request_ids") or []):
            forget_anchor(voice_id, code)
            log_server_event(f"Hold the accent: ElevenLabs no longer knows the anchor for {voice_id}; a new one will be made")
    if getattr(g, "speech_thread", None):
        with SPEECH_THREADS_LOCK:
            SPEECH_THREADS.pop(g.speech_thread, None)


def speech_thread_key(session_id, profile_id, voice_id, model_id):
    return f"{session_id}::{profile_id or 'default'}::{voice_id}::{model_id}"


# NEW (1.5.0): "Hold the accent" has three settings:
#
#   off      every line is spoken fresh
#   anchor   every line is matched to ONE short, plain sentence this voice
#            said once (made the first time, about 40 credits, kept in
#            voice_anchors.json). The accent is pinned to that one sample,
#            and nothing carries over from line to line.
#   follow   every line is matched to the last three the voice said in the
#            conversation. Holds the accent too, but a line inherits the
#            mood and pace of the one before it (a whisper makes the next
#            line whispery), which is what Friday heard as "terrible".
HOLD_ACCENT_MODES = [
    {"id": "off", "name": "Off", "description": "Every line is spoken fresh, so the tags sound natural. Best for tags."},
    {"id": "anchor", "name": "Anchor", "description": "Every line is matched to one plain sentence this voice said once. Steadier accent, but the tags come out duller."},
    {"id": "follow", "name": "Follow", "description": "Every line is matched to the last few the voice said. Steadier accent, but each line takes on the mood of the one before."},
]
HOLD_ACCENT_IDS = {m["id"] for m in HOLD_ACCENT_MODES}
DEFAULT_HOLD_ACCENT = "off"
ANCHORS_FILE = os.path.join(DATA_DIR, "voice_anchors.json")
ANCHORS_LOCK = threading.Lock()
ANCHOR_FAILED_AT = {}   # voice::language -> when making its anchor last failed
ANCHORS_DIR = os.path.join(DATA_DIR, "anchors")   # the anchor recordings, to hear
# NEW (1.5.0): the accent the anchor is made in. v3's accent tags change who
# the voice is when they're on every line, so they go on the anchor only:
# the one plain sentence is said in the chosen accent, and every line is
# matched to that recording. "auto" is whatever the voice does on its own.
VOICE_ACCENTS = [
    {"id": "auto", "name": "Voice's own", "tag": ""},
    {"id": "american", "name": "American", "tag": "american accent"},
    {"id": "southern", "name": "Southern US", "tag": "southern american accent"},
    {"id": "british", "name": "British", "tag": "british accent"},
    {"id": "scottish", "name": "Scottish", "tag": "scottish accent"},
    {"id": "irish", "name": "Irish", "tag": "irish accent"},
    {"id": "australian", "name": "Australian", "tag": "australian accent"},
    {"id": "french", "name": "French", "tag": "french accent"},
    {"id": "german", "name": "German", "tag": "german accent"},
    {"id": "russian", "name": "Russian", "tag": "russian accent"},
    {"id": "japanese", "name": "Japanese", "tag": "japanese accent"},
]
VOICE_ACCENT_IDS = {a["id"] for a in VOICE_ACCENTS}


def normalize_voice_accent(value, fallback="auto"):
    value = str(value or "").strip().lower()
    return value if value in VOICE_ACCENT_IDS else fallback


def anchor_key(voice_id, code):
    return f"{voice_id}::{code}::{normalize_voice_accent(CFG.get('voice_accent'))}"
# What the anchor says: plain, unemotional, long enough to settle the voice.
ANCHOR_LINES = {
    "en": "Right, so here's the plan for today. We'll start with the usual things, and then see where it goes from there.",
    "de": "Also gut, hier ist der Plan für heute. Wir fangen mit den üblichen Dingen an und sehen dann, wie es weitergeht.",
    "es": "Bueno, este es el plan para hoy. Empezamos con lo de siempre y luego vemos cómo sigue.",
    "fr": "Bon, voilà le programme pour aujourd'hui. On commence par les choses habituelles, et on verra ensuite.",
    "it": "Allora, ecco il piano per oggi. Cominciamo con le solite cose e poi vediamo come va.",
    "pt": "Então, este é o plano para hoje. Começamos com as coisas de sempre e depois vemos como corre.",
    "ja": "さて、今日の予定はこんな感じです。まずはいつものことから始めて、その後の様子を見ましょう。",
}


def normalize_hold_accent(value, fallback=DEFAULT_HOLD_ACCENT):
    if value is True:
        return "anchor"
    if value is False:
        return "off"
    value = str(value or "").strip().lower()
    return value if value in HOLD_ACCENT_IDS else fallback


def load_anchors():
    try:
        with open(ANCHORS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def write_anchors(anchors):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(ANCHORS_FILE, "w", encoding="utf-8") as f:
        json.dump(anchors, f, indent=2)


def forget_anchor(voice_id, code):
    key = anchor_key(voice_id, code)
    with ANCHORS_LOCK:
        anchors = load_anchors()
        gone = anchors.pop(key, None)
        if gone is not None:
            write_anchors(anchors)
    if gone and gone.get("file"):
        try:
            os.remove(os.path.join(ANCHORS_DIR, gone["file"]))
        except OSError:
            pass
    ANCHOR_FAILED_AT.pop(key, None)


def voice_anchor(voice_id, code, delivery_v3):
    """
    The anchor for this voice and language: {"id": request id, "text":
    what it said}. Made now if there isn't one (one v3 request), or None
    when it can't be.
    """
    key = anchor_key(voice_id, code)
    with ANCHORS_LOCK:
        anchors = load_anchors()
        if key in anchors and anchors[key].get("id"):
            return anchors[key]
    # Not retried for a while after a failure, so a voice that can't use v3
    # doesn't cost a failed request on every reply.
    if time.time() - ANCHOR_FAILED_AT.get(key, 0) < 600:
        return None
    text = ANCHOR_LINES.get(code, ANCHOR_LINES["en"])
    accent = next((a for a in VOICE_ACCENTS if a["id"] == normalize_voice_accent(CFG.get("voice_accent"))), VOICE_ACCENTS[0])
    said = f"[{accent['tag']}] {text}" if accent["tag"] else text
    try:
        resp = requests.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
            headers={"xi-api-key": CFG["elevenlabs_api_key"], "Content-Type": "application/json",
                     "Accept": "audio/mpeg"},
            json={"text": said, "model_id": expressive_model() or ELEVEN_V3_MODEL, "language_code": code,
                  "voice_settings": {"stability": delivery_v3}},
            timeout=60,
        )
        request_id = (resp.headers.get("request-id") or resp.headers.get("x-request-id") or "").strip() \
            if resp.status_code == 200 and getattr(resp, "headers", None) else ""
    except Exception as e:
        ANCHOR_FAILED_AT[key] = time.time()
        log_server_event(f"Hold the accent: couldn't make the anchor for {voice_id}: {e!r}")
        return None
    if not request_id:
        ANCHOR_FAILED_AT[key] = time.time()
        log_server_event(f"Hold the accent: no request id for the anchor ({getattr(resp, 'status_code', '?')})")
        return None
    log_server_event(f"Hold the accent: made the anchor for {voice_id} ({code}, {accent['name']}), {len(said)} credits once")
    # Kept, so you can hear what the voice is being matched to.
    filename = f"{uuid.uuid4().hex}.mp3"
    try:
        os.makedirs(ANCHORS_DIR, exist_ok=True)
        with open(os.path.join(ANCHORS_DIR, filename), "wb") as f:
            f.write(resp.content)
    except OSError:
        filename = ""
    anchor = {"id": request_id, "text": said, "at": time.time(), "file": filename,
              "accent": accent["id"], "voice_id": voice_id, "language": code}
    with ANCHORS_LOCK:
        anchors = load_anchors()
        anchors[key] = anchor
        write_anchors(anchors)
    return anchor


def remember_speech(resp, voiced):
    """After ElevenLabs spoke: keep its request id and words for next time."""
    from flask import has_request_context
    if not has_request_context() or not getattr(g, "speech_thread", None):
        return
    request_id = (resp.headers.get("request-id") or resp.headers.get("x-request-id") or "").strip() \
        if getattr(resp, "headers", None) else ""
    with SPEECH_THREADS_LOCK:
        thread = SPEECH_THREADS.setdefault(g.speech_thread, {"ids": [], "text": ""})
        if request_id:
            thread["ids"] = (thread["ids"] + [request_id])[-3:]
        thread["text"] = (voiced or "")[-600:]
        thread["at"] = time.time()

# The tag button's choices. Any tag works; these are the dependable ones.
AUDIO_TAG_GROUPS = [
    {"name": "Feeling", "tags": ["happy", "excited", "sad", "nervous", "curious", "sarcastic", "annoyed", "warmly"]},
    {"name": "Voice", "tags": ["softly", "whispers", "calm", "slowly", "quickly", "dramatically", "shouts"]},
    {"name": "Sounds", "tags": ["laughs", "chuckles", "giggles", "sighs", "gasps", "clears throat", "pause"]},
]


def normalize_voice_delivery(value, fallback=DEFAULT_VOICE_DELIVERY):
    value = str(value or "").strip().lower()
    return value if value in VOICE_DELIVERY_IDS else fallback


def has_audio_tags(text):
    return bool(text) and bool(AUDIO_TAG_RE.search(text))


def strip_audio_tags(text):
    """The text without its audio tags, re-spaced as if they were never there."""
    if not text or "[" not in text:
        return text
    out = AUDIO_TAG_RE.sub(" ", text)
    out = re.sub(r"[ \t]{2,}", " ", out)
    out = re.sub(r" +([.,!?;:…])", r"\1", out)
    out = re.sub(r"(^|\n) +", r"\1", out)
    return out.strip()


def tidy_audio_tags(text):
    """Tags as ElevenLabs likes them: lowercase, single-spaced, a space after."""
    def fix(m):
        return "[" + re.sub(r"\s+", " ", m.group(1)).strip().lower() + "]"
    out = AUDIO_TAG_RE.sub(fix, text or "")
    # A tag just before punctuation ("fine [sighs]. Okay") goes after it,
    # so the words read the same with or without the tags.
    out = re.sub(r"[ \t]*(\[[^\]\n]*\])[ \t]*([.,!?;:…]+)", r"\2 \1", out)
    out = re.sub(r"\](?=[^\s\[\].,!?;:…])", "] ", out)
    return out.strip()


def transplant_audio_tags(original, tagged):
    """
    The words of `original`, with the tags from `tagged` put in the same
    places. For a suggestion: the AI may only add tags, never change a
    word, and anything else it changed is quietly put back.
    """
    words = original.split()
    plan = {}   # word index -> tags that go before it
    count = 0
    for token in re.split(r"(\[[^\]]*\])|\s+", tagged or ""):
        if not token:
            continue
        if AUDIO_TAG_RE.fullmatch(token):
            plan.setdefault(min(count, len(words)), []).append(token.lower())
        elif not token.isspace():
            count += 1
    if count != len(words):
        # The AI reworded it. Place each tag at the same share of the way through.
        scaled = {}
        for index, tags in plan.items():
            scaled.setdefault(round(index * len(words) / max(1, count)), []).extend(tags)
        plan = scaled
    out = []
    for i, word in enumerate(words + [None]):
        out.extend(plan.get(i, []))
        if word is not None:
            out.append(word)
    return " ".join(out)


def audio_tag_positions(text):
    """
    NEW (1.5.0): where the tags in `text` are: [(word index, tag), ...],
    counting only the words that are said. A tag before the 3rd word is at
    2; one after the last word is at the word count.
    """
    out, count = [], 0
    for token in re.findall(r"\[[^\]\n]*\]|\S+", text or ""):
        if AUDIO_TAG_RE.fullmatch(token):
            out.append((count, AUDIO_TAG_RE.fullmatch(token).group(1).lower()))
        else:
            count += 1
    return out


def voice_style_of(profile=None):
    """Expressive voice and Delivery, from a profile or the defaults in Settings."""
    source = profile if profile is not None else CFG
    return {
        "expressive": source.get("expressive_voice") is True,
        "delivery": normalize_voice_delivery(source.get("voice_delivery")),
        # NEW (1.5.0): Shape words for tags (Clean up only; see chat()).
        "shaping": source.get("tag_shaping") is True,
        "amount": normalize_tag_amount(source.get("tag_amount")),   # NEW (1.5.0): Tag amount
    }


def current_voice_style():
    """The style chat() set for this request, or the Settings defaults."""
    from flask import has_request_context
    if has_request_context() and getattr(g, "voice_style", None):
        return g.voice_style
    return voice_style_of(None)


def alignment_without_tags(voiced, spoken, alignment):
    """
    ElevenLabs' per-character timings with any audio tags' characters taken
    out, so they line up with the reply as everything else sees it. Returned
    unchanged when the timings already skip the tags; None when they match
    neither.
    """
    if voiced == spoken:
        return alignment   # no tags: nothing to take out
    try:
        chars = [str(c) for c in alignment["characters"]]
        starts = alignment.get("character_start_times_seconds") or [0.0] * len(chars)
        ends = alignment["character_end_times_seconds"]
    except (KeyError, TypeError, AttributeError):
        return None
    joined = "".join(chars)
    if joined == spoken:
        return alignment
    def solid(t):
        return "".join(t.split())
    if joined != voiced:
        return alignment if solid(joined) == solid(spoken) else None
    inside = [False] * len(voiced)
    for m in AUDIO_TAG_RE.finditer(voiced):
        for i in range(m.start(), m.end()):
            inside[i] = True
    keep = [i for i in range(len(chars)) if not inside[i]]
    return {
        "characters": [chars[i] for i in keep],
        "character_start_times_seconds": [starts[i] for i in keep],
        "character_end_times_seconds": [ends[i] for i in keep],
    }


# ---------------------------------------------------------------------------
# NEW (1.5.0): better tags
#
#   * Tag amount (per profile): Subtle, Normal or Dramatic.
#   * The tagger is given context: the last lines of the conversation, the
#     persona, examples of good and bad tagging, and the user's taste.
#   * The rules (refine_tags): what the AI adds is checked, not trusted. A
#     feeling tag at the very end colours nothing and goes; a tag that
#     repeats a word next to it goes; there's a cap per sentence; repeats
#     and piles go; tags the user keeps removing go. Tags the user typed are
#     never touched.
#   * Taste: which tags the user keeps, adds and removes is counted
#     (tag_taste.json) and passed on.
# ---------------------------------------------------------------------------

TAG_AMOUNTS = [
    {"id": "subtle", "name": "Subtle", "description": "A tag only where it really counts. Often none."},
    {"id": "normal", "name": "Normal", "description": "A tag or two where the feeling clearly calls for one."},
    {"id": "dramatic", "name": "Dramatic", "description": "Plenty of tags and bold choices: a performance."},
]
TAG_AMOUNT_IDS = {a["id"] for a in TAG_AMOUNTS}
DEFAULT_TAG_AMOUNT = "normal"
TAG_DENSITY = {
    "subtle": ("At most one tag, and none if nothing clearly calls for it.", "at most one"),
    "normal": ("Usually one or two; never more than one per sentence.", "one to three"),
    "dramatic": ("Two to four, with bold, specific choices; up to two per sentence.", "two to four"),
}
# Reactions the voice performs (and which can end a line). Everything else
# is a feeling or a delivery, which colours the words after it.
_SOUND_TAG_RE = re.compile(r"laugh|chuckl|giggl|sigh|gasp|groan|scoff|cough|sniff|yawn|exhal|inhal|gulp|snort|"
                           r"whistl|\bcr(y|ies|ying)\b|\bsob|\bhum|wheez|clears throat|snicker|tsk|mutter", re.I)
TAG_TASTE_PATH = os.path.join(DATA_DIR, "tag_taste.json")
TAG_TASTE_LOCK = threading.Lock()


def normalize_tag_amount(value, fallback=DEFAULT_TAG_AMOUNT):
    value = str(value or "").strip().lower()
    return value if value in TAG_AMOUNT_IDS else fallback


def is_sound_tag(tag):
    return bool(_SOUND_TAG_RE.search(tag or ""))


def _tag_stem(tag):
    """'excited' -> 'excit', 'happily' -> 'happ': for spotting a tag that repeats a word."""
    word = (tag or "").split()[0] if tag else ""
    word = re.sub(r"(ily|ly|ed|ing|es|s)$", "", word.lower())
    return word[:5] if len(word) >= 3 else ""


def load_tag_taste():
    try:
        with open(TAG_TASTE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def record_tag_taste(kept=(), removed=(), added=()):
    """Counts what the user did with tags. Each a list of tag texts."""
    with TAG_TASTE_LOCK:
        taste = load_tag_taste()
        for key, tags in (("kept", kept), ("removed", removed), ("added", added)):
            for tag in tags:
                tag = re.sub(r"\s+", " ", str(tag or "").strip().lower().strip("[]"))
                if not tag or not AUDIO_TAG_RE.fullmatch(f"[{tag}]"):
                    continue
                entry = taste.setdefault(tag, {"kept": 0, "removed": 0, "added": 0})
                entry[key] = entry.get(key, 0) + 1
                entry["at"] = time.time()
        if len(taste) > 200:   # keep the most recent
            taste = dict(sorted(taste.items(), key=lambda kv: -kv[1].get("at", 0))[:200])
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            with open(TAG_TASTE_PATH, "w", encoding="utf-8") as f:
                json.dump(taste, f, indent=1)
        except OSError:
            pass


def tag_taste_summary():
    """(liked, avoided, never): tags the user favours, tends to remove, and always removes."""
    taste = load_tag_taste()
    liked, avoided, never = [], [], []
    for tag, e in taste.items():
        good = e.get("kept", 0) + 2 * e.get("added", 0)
        bad = e.get("removed", 0)
        if good >= 3 and good > bad * 2:
            liked.append((good, tag))
        elif bad >= 2 and bad > good:
            avoided.append((bad, tag))
            if bad >= 3 and good == 0:
                never.append(tag)
    return ([t for _, t in sorted(liked, reverse=True)[:6]],
            [t for _, t in sorted(avoided, reverse=True)[:6]],
            set(never))


def tag_taste_prompt():
    liked, avoided, _ = tag_taste_summary()
    if not liked and not avoided:
        return ""
    parts = []
    if liked:
        parts.append("they like " + ", ".join(f"[{t}]" for t in liked))
    if avoided:
        parts.append("they usually remove " + ", ".join(f"[{t}]" for t in avoided) + " (avoid these)")
    return "THE USER'S TASTE (from the tags they keep and remove): " + "; ".join(parts) + ".\n"


TAG_EXAMPLES = (
    "EXAMPLES OF GOOD TAGGING:\n"
    "- \"Wait, you actually beat it?\" -> \"[gasps] Wait, you actually beat it?\"\n"
    "- \"I guess I'll just do it myself then.\" -> \"[sighs] I guess I'll just do it myself then.\"\n"
    "- \"That's the funniest thing I've heard all week.\" -> \"That's the funniest thing I've heard all week. [laughs]\"\n"
    "- \"Sorry, I didn't mean to wake you.\" -> \"[softly] Sorry, I didn't mean to wake you.\"\n"
    "- \"Oh sure, that'll definitely work.\" -> \"[sarcastic] Oh sure, that'll definitely work.\"\n"
    "MISTAKES TO AVOID:\n"
    "- \"[happy] I'm so happy for you!\": the tag repeats the words. Leave it out, or use a reaction.\n"
    "- \"[confused] What is going on? [nervous]\": [confused] repeats the question, and [nervous] at the very end "
    "colours nothing. A tag goes before the words it colours; only a sound like [laughs] or [sighs] can end a line.\n"
    "- Prefer reactions the voice performs ([sighs], [chuckles], [gasps]) to feeling labels ([confused]).\n"
)


def tag_context(profile=None, session_id=None, profile_id=None, persona=True):
    """The last lines of the conversation (and the persona), for the tagger."""
    lines = []
    if session_id:
        key = f"{session_id}::{profile_id or 'default'}"
        with SESSIONS_LOCK:
            history = list(SESSIONS.get(key, []))
        for m in history[-8:]:
            content = m.get("content") or ""
            if m.get("role") == "assistant":
                label = "The voice"
                text = content
            elif m.get("role") == "user":
                found = re.search(r"<SOURCE_TEXT>\n(.*?)\n</SOURCE_TEXT>", content, re.S)
                if not found or "said to you" not in content:
                    continue   # Clean up / Word for word: the voice's line says it already
                label, text = "Said to the voice", found.group(1)
            else:
                continue
            text = strip_audio_tags(text).strip()
            if text:
                lines.append(f"{label}: {text[:200]}")
    who = ""
    if persona:
        source = profile if profile is not None else CFG
        who = resolve_personality_text(source.get("system_prompt", ""),
                                       source.get("personality_preset", DEFAULT_PERSONALITY_PRESET))[:400]
    out = ""
    if who:
        out += f"THE VOICE'S PERSONA (for tone):\n{who}\n"
    if lines:
        out += "RECENT LINES IN THIS CONVERSATION (for tone only; don't tag these):\n" + "\n".join(f"- {l}" for l in lines[-4:]) + "\n"
    return out


# NEW (1.5.0): tags that ask for nothing ("[neutral]" was suggested a lot):
# dropped unless you typed them.
EMPTY_TAGS = {"neutral", "normal", "normally", "plain", "plainly", "default", "none", "no emotion",
              "neutral tone", "neutrally", "flat", "regular", "matter-of-fact"}


def refine_tags(text, protected=(), amount=DEFAULT_TAG_AMOUNT):
    """
    The rules for tags the AI added (see the block comment above). Tags in
    `protected` (the user's own) are never removed. Returns the text.
    """
    if not text or not has_audio_tags(text):
        return text
    amount = normalize_tag_amount(amount)
    protected = {t.lower() for t in protected}
    _, _, never = tag_taste_summary()
    tokens = re.findall(r"\[[^\]\n]*\]|\S+", text)
    items = []   # [kind, text, sentence, keep]
    sentence = 0
    for tok in tokens:
        m = AUDIO_TAG_RE.fullmatch(tok)
        if m:
            items.append(["tag", m.group(1).lower(), None, True])
        else:
            items.append(["word", tok, sentence, True])
            if re.search(r"[.!?]+[\"')\]]*$", tok):
                sentence += 1
    # A tag belongs to the sentence of the word after it; one with no word
    # after it, to the last sentence.
    last_sentence = max([it[2] for it in items if it[0] == "word"] or [0])
    for i, it in enumerate(items):
        if it[0] == "tag":
            nxt = next((x for x in items[i + 1:] if x[0] == "word"), None)
            it[2] = nxt[2] if nxt else last_sentence
            it.append(nxt is None)   # trailing
    words_plain = lambda seq: [re.sub(r"[^\w']", "", x[1]).lower() for x in seq if x[0] == "word"]

    for i, it in enumerate(items):
        if it[0] != "tag" or it[1] in protected:
            continue
        tag = it[1]
        # NEW (1.5.0): a tag that asks for nothing.
        if tag in EMPTY_TAGS:
            it[3] = False
            continue
        # The user always removes it.
        if tag in never:
            it[3] = False
            continue
        # A feeling (or a pause) at the very end colours nothing.
        if it[4] and (not is_sound_tag(tag) or "pause" in tag):
            it[3] = False
            continue
        # Repeats a word right next to it.
        stem = _tag_stem(tag)
        if stem and not is_sound_tag(tag):
            near = words_plain(items[max(0, i - 4):i]) + words_plain(items[i + 1:i + 7])
            if any(w.startswith(stem) for w in near):
                it[3] = False
                continue
    # Repeats and piles: the same tag twice in a sentence; more than two
    # tags with no words between them.
    seen = set()
    run = []
    for it in items:
        if it[0] == "word":
            run = []
            continue
        if not it[3]:
            continue
        if (it[1], it[2]) in seen and it[1] not in protected:
            it[3] = False
            continue
        seen.add((it[1], it[2]))
        run.append(it)
        if len(run) > 2 and it[1] not in protected:
            it[3] = False
    # The cap per sentence, by Tag amount. Sounds are kept before feelings,
    # the user's own tags before the AI's, earlier before later.
    cap = {"subtle": 1, "normal": 1, "dramatic": 2}[amount]
    by_sentence = {}
    for idx, it in enumerate(items):
        if it[0] == "tag" and it[3]:
            by_sentence.setdefault(it[2], []).append((idx, it))
    for group in by_sentence.values():
        ranked = sorted(group, key=lambda p: (p[1][1] not in protected, not is_sound_tag(p[1][1]), p[0]))
        for n, (_, it) in enumerate(ranked):
            if n >= cap and it[1] not in protected:
                it[3] = False
    if amount == "subtle":
        # And few in all: one, plus one more for every three sentences.
        allowed = 1 + (last_sentence + 1) // 3
        kept = [it for it in items if it[0] == "tag" and it[3] and it[1] not in protected]
        ranked = sorted(kept, key=lambda it: (not is_sound_tag(it[1]), items.index(it)))
        for it in ranked[allowed:]:
            it[3] = False
    out = " ".join((f"[{it[1]}]" if it[0] == "tag" else it[1]) for it in items if it[3])
    return tidy_audio_tags(out)


def expressive_voice_rules(response_style, language, delivery, shaping=False, amount=DEFAULT_TAG_AMOUNT):
    """What the AI is told when Expressive voice is on (ElevenLabs voices only)."""
    examples = "[softly], [laughs], [sighs], [excited], [whispers], [sarcastic], [curious], [nervous], [chuckles], [pause]"
    if delivery == "calm":
        examples = "[softly], [warmly], [laughs], [sighs], [calm], [curious], [chuckles], [pause]"
    common = (
        "An audio tag is a word or two in square brackets placed right before the words it colours, "
        f"for example {examples}. The voice performs it; it is never read out.\n"
        "Never use accent tags, like [british accent]: the voice keeps its own accent.\n"
        "Write tags in English and lowercase"
        + (f", even though the words are in {language}" if language != "English" else "")
        + ".\nTags don't count toward the length.\n"
    )
    if delivery == "calm":
        common += "Keep the delivery calm: never use [shouts] or [yells].\n"
    if response_style == "reply":
        return (
            "VOICE TAGS:\n"
            "Your reply is spoken by an expressive voice that follows audio tags.\n"
            + common
            + "Use them the way an actor uses stage directions: only where they genuinely fit your persona "
            "and the moment. " + TAG_DENSITY[normalize_tag_amount(amount)][0] + "\n"   # CHANGED (1.5.0): Tag amount
            "Let the tags carry the emotion: no words in ALL CAPITALS and no strings of exclamation marks.\n"
            + TAG_EXAMPLES + tag_taste_prompt() + "\n"
        )
    if response_style == "echo" and shaping:
        # NEW (1.5.0): Shape words for tags (a Clean up profile's switch).
        return (
            "VOICE TAGS:\n"
            "The output is spoken by an expressive voice that follows audio tags.\n"
            + common
            + "Keep every tag already in the source text, in the same place.\n"
            "Add " + TAG_DENSITY[normalize_tag_amount(amount)][1] + " more where the message's feeling clearly calls for it; "
            "fewer for a short message.\n"
            + TAG_EXAMPLES + tag_taste_prompt() +
            "SHAPING THE WORDS AROUND A TAG:\n"
            "Within a few words of each tag, and only there, you may make small changes so the line "
            "flows naturally with the tag performed:\n"
            "- remove words the tag now performs (\"[laughs] haha that's funny\" becomes \"[laughs] That's funny\"; "
            "\"ugh [sighs]\" becomes \"[sighs]\")\n"
            "- add a short natural lead-in of one or two words after a tag (\"[gasps] Oh,\", \"[sighs] Well,\")\n"
            "- adjust punctuation next to a tag (a comma, an ellipsis, a full stop) so the pause lands right\n"
            + tag_words_prompt()
            + "Everything else stays as cleaned up: same meaning, same order, nothing new said. Never add a "
            "sentence, an opinion, a name or a fact.\n\n"
        )
    if response_style == "echo":
        return (
            "VOICE TAGS:\n"
            "The output is spoken by an expressive voice that follows audio tags.\n"
            + common
            + "Keep every tag already in the source text exactly as written, in the same place.\n"
            "You may add at most one or two where the persona's delivery clearly calls for it. "
            "Adding a tag is the only addition allowed; it never replaces punctuation or words.\n\n"
        )
    return ""


def audio_tag_keep_rule():
    """For Clean up and Word for word: tags you typed survive the AI."""
    return (
        "AUDIO TAGS:\n"
        "Words in square brackets, like [whispers] or [laughs], are directions for the voice. "
        "Keep each one exactly as written, in English, in the same place. Never translate, "
        "explain or remove them.\n\n"
    )


def calm_delivery_rule():
    return (
        "DELIVERY:\n"
        "The voice must stay calm and even. Never write words in ALL CAPITALS for emphasis, "
        "and use at most one exclamation mark in the whole output.\n\n"
    )


def _elevenlabs_payload(text, force_v2=False):
    """CHANGED (1.5.0): shared by get_tts_audio() and elevenlabs_tts_timed()."""
    # NEW (1.5.0): Delivery and Expressive voice (see above). Natural, with
    # no tags, sends exactly what Frivo always sent.
    style = current_voice_style()
    delivery = DELIVERY_SETTINGS[normalize_voice_delivery(style.get("delivery"))]
    text = ensure_spoken_words(text)   # NEW (1.5.0): never a line of only tags
    model = expressive_model()
    # CHANGED (1.5.0): "Every line" (on by default): a line without tags is
    # spoken by the Tags model too. Switching models line by line changed
    # how the voice sounded, and with fewer tags (the tag rules) most lines
    # had gone to v2.
    every_line = CFG.get("expressive_every_line", True) is not False
    if model and not force_v2 and (every_line or style.get("expressive") or style.get("stay_on_v3") or has_audio_tags(text)):
        # v3 and v4 have no speed setting; the reply speaks at its natural pace.
        payload = {
            "text": text,
            "model_id": model,
            "voice_settings": {"stability": delivery["v3"]},
        }
        if model.startswith("eleven_v4"):
            # NEW (1.5.0): v4's Similarity holds every line closer to the
            # voice's own recording: the accent, without copying any other
            # line's mood the way Hold the accent does.
            payload["voice_settings"]["similarity_boost"] = V4_SIMILARITY
        # NEW (1.5.0): v3 works out the language from each line by itself,
        # and on a short or tagged line it guesses differently, so the same
        # voice came out American, Scottish, Russian... Told the language,
        # it keeps one accent.
        code = language_iso(style.get("language") or CFG.get("language") or "English")
        if code:
            payload["language_code"] = code
        # Hold the accent (see HOLD_ACCENT_MODES).
        from flask import has_request_context
        mode = normalize_hold_accent(CFG.get("hold_accent"))
        if mode == "anchor" and has_request_context() and getattr(g, "speech_voice", None) and not getattr(g, "making_anchor", False):
            g.making_anchor = True
            try:
                anchor = voice_anchor(g.speech_voice, code or "en", delivery["v3"])
            finally:
                g.making_anchor = False
            if anchor:
                payload["previous_request_ids"] = [anchor["id"]]
                payload["previous_text"] = anchor["text"]
        elif mode == "follow" and has_request_context() and getattr(g, "speech_thread", None):
            with SPEECH_THREADS_LOCK:
                thread = SPEECH_THREADS.get(g.speech_thread)
            if thread and time.time() - thread.get("at", 0) < V3_STICKY_SECONDS:
                if thread.get("ids"):
                    payload["previous_request_ids"] = list(thread["ids"])
                if thread.get("text"):
                    payload["previous_text"] = thread["text"]
        # NEW (1.5.0): extras this model refused before aren't sent.
        for field in REFUSED_EXTRAS.get(model, ()):
            payload.pop(field, None)
            payload["voice_settings"].pop(field, None)
        return payload
    # CHANGED (1.5.0): the standard model reads tags out as words, so it
    # never gets them, however it came to be used.
    text = strip_audio_tags(text) or text
    voice_settings = dict(delivery["v2"])
    # Only sent when it isn't the natural pace. Older ElevenLabs models
    # reject an unknown key outright, and there's no reason to risk that on
    # a value that means "leave it alone".
    speed = clamp_speaking_speed(CFG.get("speaking_speed", 1.0))
    if abs(speed - 1.0) > 0.001:
        voice_settings["speed"] = round(speed, 3)

    return {
        "text": text,
        "model_id": ELEVEN_V2_MODEL,
        "voice_settings": voice_settings,
    }


def get_tts_audio(text, voice_id, language="English"):
    # NEW (1.5.0): a free voice is spoken on this PC; everything below is
    # the ElevenLabs path, unchanged.
    if tts_engine(voice_id) != "elevenlabs":
        return free_tts_audio(text, voice_id, language)

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    headers = {
        "xi-api-key": CFG["elevenlabs_api_key"],
        "Content-Type": "application/json",
        "Accept": "audio/mpeg",
    }
    payload = _elevenlabs_payload(text)   # CHANGED (1.5.0)
    resp = requests.post(url, headers=headers, json=payload, timeout=60)
    # NEW (1.5.0): an anchor ElevenLabs no longer knows (history cleared):
    # forget it and speak without, once.
    if resp.status_code in (400, 404, 422) and payload.get("previous_request_ids"):
        _drop_stale_anchor(payload)
        payload = _elevenlabs_payload(text)
        resp = requests.post(url, headers=headers, json=payload, timeout=60)
    payload, resp = _step_down(url, headers, text, payload, resp)
    if resp.status_code != 200:
        raise RuntimeError(f"ElevenLabs error {resp.status_code}: {resp.text[:300]}")
    if is_expressive_model(payload.get("model_id")):
        remember_speech(resp, payload["text"])   # NEW (1.5.0)

    filename = f"{uuid.uuid4().hex}.mp3"
    with open(os.path.join(AUDIO_DIR, filename), "wb") as f:
        f.write(resp.content)
    return filename


class TimedSpeechUnavailable(Exception):
    """NEW (1.5.0): the timed request was refused, and nothing was spoken."""


def page_ends_from_alignment(pages, alignment):
    """
    NEW (1.5.0): when the voice finishes each page's last character, from
    ElevenLabs' per-character timings. Matched by counting non-space
    characters, because the pages are re-spaced and the timings follow the
    original text. None if the two don't line up.
    """
    try:
        chars = alignment["characters"]
        char_ends = alignment["character_end_times_seconds"]
    except (KeyError, TypeError):
        return None
    times = [end for ch, end in zip(chars, char_ends) if not str(ch).isspace()]
    counts = [sum(1 for c in page if not c.isspace()) for page in pages]
    if not counts or sum(counts) != len(times) or 0 in counts:
        return None
    ends, seen = [], 0
    for count in counts:
        seen += count
        ends.append(float(times[seen - 1]))
    return ends


def elevenlabs_tts_timed(text, voice_id, pages, voiced=None):
    """
    NEW (1.5.0): ElevenLabs' with-timestamps request. Same voice, same
    credits, and it also says when each character is spoken.
    CHANGED (1.5.0): `voiced` is the reply with its audio tags, which is what
    the voice is given; the timings are matched back to `text`.
    """
    voiced = voiced or text
    import base64

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/with-timestamps"
    headers = {
        "xi-api-key": CFG["elevenlabs_api_key"],
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    payload = _elevenlabs_payload(voiced)
    resp = requests.post(url, headers=headers, json=payload, timeout=60)
    if resp.status_code in (400, 404, 422) and payload.get("previous_request_ids"):   # NEW (1.5.0): a stale anchor
        _drop_stale_anchor(payload)
        payload = _elevenlabs_payload(voiced)
        resp = requests.post(url, headers=headers, json=payload, timeout=60)
    if resp.status_code != 200:
        # Refused, so nothing was spoken or billed. The plain request is
        # tried next, and its error is the one you see if it fails too.
        raise TimedSpeechUnavailable(f"ElevenLabs timestamps {resp.status_code}: {resp.text[:200]}")
    if is_expressive_model(payload.get("model_id")):
        remember_speech(resp, payload["text"])   # NEW (1.5.0)
    data = resp.json()
    audio = base64.b64decode(data["audio_base64"])
    filename = f"{uuid.uuid4().hex}.mp3"
    with open(os.path.join(AUDIO_DIR, filename), "wb") as f:
        f.write(audio)
    # CHANGED (1.5.0): without the tags' characters, which aren't spoken.
    alignment = alignment_without_tags(voiced, text, data.get("alignment"))
    normalized = alignment_without_tags(voiced, text, data.get("normalized_alignment"))
    ends = page_ends_from_alignment(pages, alignment) \
        or page_ends_from_alignment(pages, normalized)
    # NEW (1.5.0): and when each word is spoken, for the highlight.
    words = word_times_from_alignment(text, alignment)
    return filename, ends, words


def word_times_from_alignment(text, alignment):
    """
    NEW (1.5.0): when each word of `text` is spoken, from ElevenLabs'
    per-character timings: [[start, end], ...], one per word (split on
    spaces), in seconds. None unless the timings follow the text exactly,
    because the reply only highlights words when the timing is exact.
    """
    try:
        chars = alignment["characters"]
        starts = alignment["character_start_times_seconds"]
        finishes = alignment["character_end_times_seconds"]
    except (KeyError, TypeError):
        return None
    if not (len(chars) == len(starts) == len(finishes)):
        return None
    timed = [(str(c), s, e) for c, s, e in zip(chars, starts, finishes) if not str(c).isspace()]
    words = text.split()
    if "".join(c for c, _, _ in timed) != "".join(words) or any(len(c) != 1 for c, _, _ in timed):
        return None
    out, i = [], 0
    for word in words:
        part = timed[i:i + len(word)]
        i += len(word)
        out.append([round(float(part[0][1]), 3), round(float(part[-1][2]), 3)])
    return out


def word_times_from_boundaries(pages, boundaries, page_ends):
    """
    NEW (1.5.0): the same, from the word boundaries a Windows voice reports
    while speaking: for each page, [[character position, length, seconds
    into the page], ...]. Every word with a letter or digit in it must have
    been reported; a word of punctuation alone shares the word before's
    time. Otherwise None.
    """
    if not boundaries or len(boundaries) != len(pages) or len(page_ends) != len(pages):
        return None
    out, page_start = [], 0.0
    for page, events, page_end in zip(pages, boundaries, page_ends):
        spans = [(m.start(), m.end()) for m in re.finditer(r"\S+", page)]
        starts = [None] * len(spans)
        for event in events or []:
            pos, length, at = int(event[0]), int(event[1]), float(event[2])
            for k, (a, b) in enumerate(spans):
                if a <= pos < b or (pos < a < pos + max(length, 1)):
                    if starts[k] is None or at < starts[k]:
                        starts[k] = at
                    break
        for k, (a, b) in enumerate(spans):
            if starts[k] is None:
                if re.search(r"\w", page[a:b]):
                    return None
                starts[k] = starts[k - 1] if k else 0.0
        length_of_page = page_end - page_start
        for k in range(len(spans)):
            begin = starts[k]
            finish = starts[k + 1] if k + 1 < len(spans) else length_of_page
            out.append([round(page_start + begin, 3), round(page_start + max(begin, finish), 3)])
        page_start = page_end
    return out


def speak_reply(text, voice_id, language, plan, voiced=None):
    """
    NEW (1.5.0): speaks a reply, and says as exactly as it can when things
    happen in it. Returns (filename, page_ends, word_times):

      page_ends   when the voice finishes the last word of each chatbox page
                  in `plan`; None for a one-page reply or when unknown, and
                  then the page estimates instead.
      word_times  when each word is spoken, for the highlight that follows
                  the voice; None unless exact (ElevenLabs, or a Windows
                  voice that reported its words). Frivo's own free voices
                  don't report words, so they get no highlight.

    CHANGED (1.5.0): `voiced` is the reply with its audio tags. Only
    ElevenLabs is given it; every other voice says `text`.
    """
    pages = [_CHATBOX_COUNTER_RE.sub("", p["text"]) for p in plan] or [text]
    engine = tts_engine(voice_id)
    if engine == "elevenlabs":
        # The with-timestamps request costs the same credits as the plain
        # one, so it's used for every reply. Only a refused request falls
        # back: anything after ElevenLabs said yes may already be billed,
        # and asking again would bill it twice.
        try:
            filename, ends, words = elevenlabs_tts_timed(text, voice_id, pages, voiced)
            return filename, (ends if len(pages) > 1 else None), words
        except TimedSpeechUnavailable as e:
            log_server_event(f"Speech timing: falling back to the plain request: {e}")
            return get_tts_audio(voiced or text, voice_id, language), None, None
    if engine == "piper" and len(pages) <= 1:
        return get_tts_audio(text, voice_id, language), None, None
    if len(pages) <= 1:
        # A one-page reply in a Windows voice: the same single request as
        # before, now also asking for the words. Its errors are the reply's
        # errors, as they always were; there's nothing to fall back to.
        filename = f"{uuid.uuid4().hex}.wav"
        _, words = windows_speak_pages([text], voice_id, os.path.join(AUDIO_DIR, filename))
        if words is not None and len(words) != len(text.split()):
            words = None
        return filename, None, words
    try:
        filename = f"{uuid.uuid4().hex}.wav"
        path = os.path.join(AUDIO_DIR, filename)
        if engine == "piper":   # NEW (1.5.0)
            ends, words = piper_speak_pages(pages, voice_id, path), None
        else:
            ends, words = windows_speak_pages(pages, voice_id, path)
        if words is not None and len(words) != len(text.split()):
            words = None   # the pages didn't cover the reply word for word
        return filename, (ends if len(pages) > 1 else None), words
    except Exception as e:
        # Free voices cost nothing, so any problem here just means the reply
        # is spoken the usual way and the pages use the estimate.
        log_server_event(f"Speech timing: falling back to an estimate ({engine}): {e!r}")
        return get_tts_audio(text, voice_id, language), None, None


# NEW (1.5.0): "Suggest tags" — the AI adds audio tags to a message you're
# about to send. Only tags: every word stays yours (transplant_audio_tags
# puts back anything else it changed).
def build_tag_suggestion_prompt(text, delivery, context="", amount=DEFAULT_TAG_AMOUNT, avoid=(), light=False):
    gentle = (" Keep it calm: no [shouts]." if delivery == "calm" else "")
    # CHANGED (1.5.0): with the conversation, the persona, examples, the
    # user's taste and the Tag amount.
    # CHANGED (1.5.0): `light` (the ideas as you type) leaves out the
    # examples and the persona: a third of the prompt, asked many times a
    # message, on a card the model shares with Evora.
    density = TAG_DENSITY[normalize_tag_amount(amount)][1]
    skip = ("Don't use these this time: " + ", ".join(f"[{t}]" for t in avoid) + ".\n") if avoid else ""
    if light:
        context = "\n".join(l for l in context.splitlines() if l.startswith("- ") or l.startswith("RECENT LINES"))
        context = context + "\n" if context else ""
    return (
        context
        + ("" if light else TAG_EXAMPLES) + tag_taste_prompt() + skip + "\n"
        + "Add ElevenLabs audio tags to the message below. It will be spoken aloud, as the writer's own words, "
        "by an expressive voice that performs the tags instead of reading them.\n"
        "An audio tag is a word or two of lowercase English in square brackets, placed right before the words "
        "it colours. Good ones: [happy], [excited], [sad], [nervous], [curious], [sarcastic], [warmly], "
        "[softly], [whispers], [slowly], [laughs], [chuckles], [sighs], [gasps], [pause]." + gentle + "\n"
        "Never use accent tags.\n"
        "Never put the message's own words in brackets: a tag is a stage direction you add, not part of the message.\n"
        "Never use [neutral] or any tag that means no feeling: leave the words plain instead.\n"
        f"Add {density}, where they clearly fit the feeling of the message, read in the light of the conversation. "
        "Keep any tags already there.\n"
        "Do not change, add, remove or reorder any word or punctuation.\n"
        "Output only the message with the tags added.\n\n"
        f"<MESSAGE>\n{text}\n</MESSAGE>"
    )


def _old_build_tag_suggestion_prompt(text, delivery):
    gentle = (" Keep it calm: no [shouts]." if delivery == "calm" else "")
    return (
        "Add ElevenLabs audio tags to the message below. It will be spoken aloud, as the writer's own words, "
        "by an expressive voice that performs the tags instead of reading them.\n"
        "An audio tag is a word or two of lowercase English in square brackets, placed right before the words "
        "it colours. Good ones: [happy], [excited], [sad], [nervous], [curious], [sarcastic], [warmly], "
        "[softly], [whispers], [slowly], [laughs], [chuckles], [sighs], [gasps], [pause]." + gentle + "\n"
        "Never use accent tags.\n"
        "Add one to three, where they clearly fit the feeling of the message; one for a short message. "
        "Keep any tags already there.\n"
        "Do not change, add, remove or reorder any word or punctuation.\n"
        "Output only the message with the tags added.\n\n"
        f"<MESSAGE>\n{text}\n</MESSAGE>"
    )


def _plain_words(text):
    return [w for w in re.sub(r"[^\w'\s]", " ", strip_audio_tags(text or "").lower()).split() if w]


def unwrap_message_words(original, tagged):
    """
    NEW (1.5.0): a small model sometimes puts the message's own words in
    brackets ("[i was thinking] [about] writing"), which then showed up as
    tags. Brackets around words that are in the message are taken off, so
    they count as the words they are. Tags already in the message stay.
    """
    words = _plain_words(original)
    joined = " " + " ".join(words) + " "
    kept = {t for _, t in audio_tag_positions(original)}

    def fix(m):
        inner = m.group(1)
        if inner.lower() in kept:
            return m.group(0)
        seq = _plain_words(inner)
        if seq and (" " + " ".join(seq) + " ") in joined:
            return inner
        return m.group(0)

    return re.sub(r"\[([^\]\n]{1,60})\]", fix, tagged or "")


def tag_message_with_ai(text, delivery, context="", amount=DEFAULT_TAG_AMOUNT, avoid=(), light=False):
    """
    NEW (1.5.0): `text` with the AI's audio tags added and nothing else
    changed. Used by Suggest, and by Auto tags on every message you send.
    Raises ValueError when there's no AI to ask, RuntimeError when it failed.
    """
    if not CFG.get("openai_api_key") and resolve_provider("chat_provider", CHAT_PROVIDERS) == "openai":
        raise ValueError("Suggesting tags needs an AI: add your OpenAI key, or pick Ollama for chat replies.")
    try:
        response = create_chat_completion(
            make_openai_client(),
            provider=resolve_provider("chat_provider", CHAT_PROVIDERS),
            model=CFG.get("model", RECOMMENDED_TEXT_MODEL),
            ollama_model=active_ollama_model(),
            messages=[{"role": "user", "content": build_tag_suggestion_prompt(text, delivery, context, amount, avoid, light)}],
            max_tokens=int(len(text.split()) * 3) + 80,
            temperature=0.8 if avoid else 0.4,   # CHANGED (1.5.0): Retake asks for something different
        )
        raw = (response.choices[0].message.content or "").strip()
    except Exception as e:
        raise RuntimeError(f"Couldn't ask the AI: {e}")
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.S | re.I)
    raw = re.sub(r"</?MESSAGE>", "", raw).strip()
    raw = unwrap_message_words(text, raw)   # NEW (1.5.0)
    suggested = transplant_audio_tags(strip_audio_tags(text), tidy_audio_tags(raw if ACCENT_TAG_RE.search(text) else ACCENT_TAG_RE.sub("", raw)))
    if delivery == "calm":
        suggested = re.sub(r"\[(?:shouts|shouting|yells|yelling|screams)\]\s*", "", suggested, flags=re.I)
    if avoid:
        suggested = re.sub(r"\[(?:" + "|".join(re.escape(t) for t in avoid) + r")\]\s*", "", suggested)
    # NEW (1.5.0): the rules, sparing the tags that were already there.
    return refine_tags(suggested, protected=[t for _, t in audio_tag_positions(text)], amount=amount)


# NEW (1.5.0): your tag taste. The page reports what happened to the tags
# it offered: kept (sent), removed (offered, then deleted, or retaken
# without), added (typed or picked by you).
@app.route("/api/voice-tags/feedback", methods=["POST"])
def voice_tags_feedback():
    data = request.get_json(force=True) or {}
    lists = {}
    for key in ("kept", "removed", "added"):
        value = data.get(key) or []
        if not isinstance(value, list):
            return jsonify({"error": f"{key} should be a list of tags."}), 400
        lists[key] = [str(t)[:40] for t in value[:30]]
    record_tag_taste(**lists)
    return jsonify({"ok": True})


@app.route("/api/voice-tags/taste", methods=["GET", "DELETE"])
def voice_tags_taste():
    if request.method == "DELETE":
        with TAG_TASTE_LOCK:
            try:
                os.remove(TAG_TASTE_PATH)
            except OSError:
                pass
    liked, avoided, never = tag_taste_summary()
    return jsonify({"liked": liked, "avoided": avoided, "never": sorted(never),
                    "counted": len(load_tag_taste())})


# NEW (1.5.0): Retake. Speaks the last reply again: the same ("same"),
# without its tags ("plain"), or with different ones ("fresh"). The words
# don't change. The reply in the conversation's history is replaced, so
# the AI carries on from the version you kept.
@app.route("/api/retake", methods=["POST"])
def retake():
    data = request.get_json(force=True) or {}
    mode = data.get("mode") if data.get("mode") in ("same", "plain", "fresh") else "same"
    voiced = tidy_audio_tags(str(data.get("voiced") or data.get("reply") or "").strip())[:SAVED_MAX_TEXT + 600]
    reply = strip_audio_tags(voiced) or voiced
    if not reply:
        return jsonify({"error": "Nothing to say again."}), 400
    session_id = data.get("session_id") or "default"
    profile_id = data.get("profile_id")
    language = normalize_language(data.get("language")) or CFG.get("language", "English")
    profile = None
    if profile_id:
        profile = next((p for p in load_profiles() if p["id"] == profile_id), None)
        if not profile:
            return jsonify({"error": "That profile no longer exists."}), 400
    voice_id = profile["voice_id"] if profile else CFG["voice_id"]
    if tts_engine(voice_id) != "elevenlabs":
        return jsonify({"error": "Retake is for ElevenLabs voices."}), 400
    if not CFG["elevenlabs_api_key"]:
        return jsonify({"error": "Add your ElevenLabs key in Settings."}), 400
    style = voice_style_of(profile)
    old_tags = [t for _, t in audio_tag_positions(voiced)]
    tag_seconds = 0.0
    if mode == "plain":
        voiced = reply
    elif mode == "fresh":
        start = time.perf_counter()
        try:
            tagged = tag_message_with_ai(reply, style["delivery"], tag_context(profile, session_id, profile_id),
                                         style["amount"], avoid=sorted(set(old_tags)))
        except Exception as e:
            return jsonify({"error": f"Couldn't get different tags: {e}"}), 502
        tag_seconds = time.perf_counter() - start
        voiced = tagged if has_audio_tags(tagged) else reply
    voiced = ensure_spoken_words(voiced)   # NEW (1.5.0)
    g.voice_style = dict(style, language=language, expressive=has_audio_tags(voiced) or style["expressive"])
    g.speech_thread = speech_thread_key(session_id, profile_id, voice_id, ELEVEN_V3_MODEL)
    g.speech_voice = voice_id
    plan = chatbox_page_plan(reply)
    audio_start = time.perf_counter()
    try:
        filename, page_ends, word_times = speak_reply(reply, voice_id, language, plan, voiced=voiced)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    audio_seconds = time.perf_counter() - audio_start
    if page_ends and len(page_ends) == len(plan):
        for i, page in enumerate(plan):
            page["at"] = 0.0 if i == 0 else round(page_ends[i - 1], 3)
    credits = len(voiced)
    record_usage(credits)
    # The history keeps the version you're hearing.
    key = f"{session_id}::{profile_id or 'default'}"
    old = tidy_audio_tags(str(data.get("voiced") or reply))
    with SESSIONS_LOCK:
        for m in reversed(SESSIONS.get(key, [])):
            if m.get("role") == "assistant" and strip_audio_tags(m.get("content") or "") == strip_audio_tags(old):
                m["content"] = voiced
                break
    return jsonify({
        "reply": reply,
        "voiced": voiced,
        "mode": mode,
        # Only "without tags" says you didn't like them; "different" may
        # just be wanting variety.
        "removed_tags": old_tags if mode == "plain" else [],
        "audio_url": f"/audio/{filename}" if filename else None,
        "word_times": word_times,
        "chatbox_pages": plan,
        "credits": credits,
        "voice_notice": getattr(g, "voice_notice", "") or "",
        "voice_model": _elevenlabs_payload(voiced)["model_id"],
        "voice_how": voice_how(voiced),
        "text_seconds": round(tag_seconds, 2),
        "audio_seconds": round(audio_seconds, 2),
        "total_seconds": round(tag_seconds + audio_seconds, 2),
    })


@app.route("/api/voice-tags/suggest", methods=["POST"])
def suggest_voice_tags():
    data = request.get_json(force=True) or {}
    text = tidy_audio_tags(str(data.get("text") or "").strip())[:2000]
    if not strip_audio_tags(text):
        return jsonify({"error": "Type your message first, then Suggest adds tags to it."}), 400
    profile = None
    if data.get("profile_id"):
        profile = next((p for p in load_profiles() if p["id"] == data.get("profile_id")), None)
    style = voice_style_of(profile)
    delivery = style["delivery"]
    started = time.perf_counter()
    light = data.get("light") is True   # NEW (1.5.0): the ideas as you type: a shorter ask
    context = tag_context(profile, data.get("session_id"), data.get("profile_id"), persona=not light)   # NEW (1.5.0)
    try:
        suggested = tag_message_with_ai(text, delivery, context, style["amount"], light=light)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 502
    added = len(AUDIO_TAG_RE.findall(suggested)) - len(AUDIO_TAG_RE.findall(text))
    # NEW (1.5.0): the new tags one by one, for the ideas that pop up as you
    # type: each with the word it goes before ("at", counting said words only).
    had = list(audio_tag_positions(text))
    ideas = []
    for at, tag in audio_tag_positions(suggested):
        if (at, tag) in had:
            had.remove((at, tag))
            continue
        ideas.append({"at": at, "tag": tag})
    return jsonify({
        "text": suggested,
        "ideas": ideas,
        "added": max(0, added),
        "seconds": round(time.perf_counter() - started, 2),
    })


# ---------------------------------------------------------------------------
# NEW (1.5.0): the personality maker
#
# Writing a personality that works well is a skill, so the AI you've set up
# for chat replies (Ollama or OpenAI) helps:
#
#   /api/personality/create    a one-line idea becomes a full personality
#   /api/personality/suggest   ideas to add, from what's written so far and
#                              from how the profile has actually been
#                              talking in your conversation
#   /api/personality/merge     "Add all": the ideas woven into the text
#
# Each is one request, written for small local models as much as big ones,
# and what comes back is checked rather than trusted.
# ---------------------------------------------------------------------------

PERSONALITY_MAX_CHARS = 4000

# What the writer is told about how Frivo uses a personality, so what it
# writes works with the rules Frivo adds and doesn't fight them.
PERSONALITY_STYLE_NOTES = {
    "reply": ("This profile REPLIES: people say things to the user, the user types them in, and the "
              "character answers out loud in its own words. So the personality should say how it reacts, "
              "what it cares about, its opinions and humour, and how it talks."),
    "echo": ("This profile CLEANS UP the user's own words before they're spoken: the character never adds "
             "words of its own, and its personality shows only in tone, punctuation and emphasis. So the "
             "personality should be about delivery: mood, energy, pacing and attitude, not opinions or "
             "catchphrases."),
    "mimic": ("This profile says the user's words exactly, so a personality isn't used. Write one anyway, "
              "about tone and delivery, in case the style changes."),
}


def ask_writing_ai(prompt, max_tokens, temperature=0.7):
    """One request to the AI set up for chat replies. Returns (text, seconds)."""
    if not CFG.get("openai_api_key") and resolve_provider("chat_provider", CHAT_PROVIDERS) == "openai":
        raise ValueError("This needs an AI to write with: add your OpenAI key in Settings, "
                         "or choose Ollama for chat replies.")
    started = time.perf_counter()
    response = create_chat_completion(
        make_openai_client(),
        provider=resolve_provider("chat_provider", CHAT_PROVIDERS),
        model=CFG.get("model", RECOMMENDED_TEXT_MODEL),
        ollama_model=active_ollama_model(),
        messages=[{"role": "user", "content": prompt}],
        max_tokens=max_tokens,
        temperature=temperature,
    )
    text = (response.choices[0].message.content or "").strip()
    # Reasoning models (some on Ollama) think out loud first.
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S | re.I).strip()
    return text, time.perf_counter() - started


def _clean_personality_text(text):
    """What a model wraps its answer in, taken off: fences, a preface, quotes."""
    text = (text or "").strip()
    first, _, rest = text.partition("\n")
    if rest and re.match(r"^(here(?:'s| is)|sure|okay|certainly)\b.*:\s*$", first.strip(), re.I):
        text = rest.strip()
    text = re.sub(r"(?m)^\s*```[a-z]*\s*$\n?", "", text).strip()
    text = re.sub(r"</?PERSONALITY>", "", text, flags=re.I).strip()
    if len(text) > 1 and text[0] == text[-1] == '"':
        text = text[1:-1].strip()
    # Markdown headings and bold read as clutter in the box; the model
    # follows plain text just as well.
    text = re.sub(r"(?m)^#{1,6}\s*", "", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    return text[:PERSONALITY_MAX_CHARS].strip()


def _personality_context(data):
    name = str(data.get("name") or "").strip()[:80]
    style = normalize_response_style(data.get("response_style"), DEFAULT_RESPONSE_STYLE)
    language = normalize_language(data.get("language")) or ""
    return name, style, language


def _conversation_memory(data, limit=6):
    """
    How the profile has been talking: the last few exchanges the page kept
    for it ([{"you": ..., "reply": ...}]), tags and all taken out. Empty
    when there are none.
    """
    lines = []
    for turn in (data.get("recent") or [])[-limit:]:
        if not isinstance(turn, dict):
            continue
        said = strip_audio_tags(str(turn.get("you") or "")).strip()[:300]
        reply = strip_audio_tags(str(turn.get("reply") or "")).strip()[:400]
        if reply:
            if said:
                lines.append(f"User: {said}")
            lines.append(f"Character: {reply}")
    return "\n".join(lines)


def build_personality_create_prompt(idea, name, style, language, current=""):
    who = f' called "{name}"' if name else ""
    lang = (f"\nThe character usually speaks {language}; write the personality in English anyway, and "
            f"mention any {language}-speaking flavour that fits.") if language and language != "English" else ""
    base = (f"\nThe current personality, to build on rather than throw away where it fits the idea:\n"
            f"<CURRENT>\n{current}\n</CURRENT>\n") if current.strip() else ""
    return (
        "You write personality descriptions for voice characters in Frivo, an app that speaks a character's "
        "lines aloud with a text-to-speech voice, often in VRChat. The description you write becomes part of "
        f"the character's instructions.\n\n"
        f"{PERSONALITY_STYLE_NOTES[style]}{lang}\n\n"
        f"Write the personality for a character{who}, from this idea:\n<IDEA>\n{idea}\n</IDEA>\n{base}\n"
        "Write it as instructions to the character, in the second person (\"You are...\", \"You speak...\"). "
        "Cover, in this order:\n"
        "1. Who they are, in one or two sentences.\n"
        "2. How they talk: vocabulary, sentence length and rhythm, verbal habits, one or two signature phrases "
        "to use rarely.\n"
        "3. Their attitude and what they care about.\n"
        "4. How they react: to compliments, teasing, questions, bad news, things they don't know.\n"
        "5. What they never do.\n"
        "Make it specific and vivid, not generic. Everything must work when spoken aloud: no emojis, no "
        "actions in asterisks, nothing to read off a screen.\n"
        "Don't set a reply length or a language, and don't mention AI or these instructions: the app handles "
        "those.\n"
        "Plain text, short paragraphs, 150 to 260 words. Output only the personality."
    )


def build_personality_suggest_prompt(text, name, style, memory, skip):
    who = f' "{name}"' if name else ""
    seen = ""
    if memory:
        seen = (
            "\nHere is how the character has actually been talking lately:\n<CONVERSATION>\n"
            f"{memory}\n</CONVERSATION>\n"
            "Use it: suggest things that fit what people talk about with it, and fix what didn't work "
            "(too long-winded, too formal, repeating itself, out of character).\n"
        )
    avoid = ("\nDon't suggest these again (already added or turned down): " + "; ".join(skip) + "\n") if skip else ""
    return (
        "You improve personality descriptions for voice characters in Frivo, an app that speaks a character's "
        f"lines aloud with a text-to-speech voice.\n{PERSONALITY_STYLE_NOTES[style]}\n\n"
        f"The personality of the character{who} so far:\n<PERSONALITY>\n{text}\n</PERSONALITY>\n{seen}{avoid}\n"
        "Suggest 5 specific additions that would make the character more vivid and consistent when it "
        "speaks. Each must add something the personality doesn't already cover: a speech habit, a signature "
        "phrase, how it reacts to something, what it refuses to do, a detail of its life, its humour. "
        "Match the personality's own wording style (second person, like \"You ...\").\n"
        "Never suggest rules about reply length, language, emojis or being an AI.\n"
        "Format: one per line, exactly like this, nothing else:\n"
        "short label of 2 to 5 words | the sentence to add, under 30 words\n"
    )


def parse_personality_suggestions(raw, existing, limit=6):
    out, seen = [], set()
    known = (existing or "").lower()
    for line in (raw or "").splitlines():
        line = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", line).strip()
        if "|" not in line:
            continue
        label, _, text = line.partition("|")
        label = label.strip(" *\"'`:").strip()
        text = _clean_personality_text(text.strip(" \"'`"))
        if not label or not text or len(label) > 48 or len(text) > 320:
            continue
        key = label.lower()
        if key in seen or text.lower() in known:
            continue
        seen.add(key)
        if text[-1] not in ".!?\"'":
            text += "."
        out.append({"id": uuid.uuid4().hex[:10], "label": label[:1].upper() + label[1:], "text": text})
        if len(out) >= limit:
            break
    return out


def build_personality_merge_prompt(text, additions):
    listed = "\n".join(f"- {a}" for a in additions)
    return (
        "Here is a personality description for a voice character, and some additions to work into it.\n"
        f"<PERSONALITY>\n{text}\n</PERSONALITY>\n<ADDITIONS>\n{listed}\n</ADDITIONS>\n\n"
        "Rewrite the personality with every addition worked in where it belongs, so it reads as one piece. "
        "Keep everything that's already there, its meaning and its voice; only reword where an addition has "
        "to fit in. Plain text, the same style. Output only the personality."
    )


def _merged_keeps_original(original, merged):
    """True when a merge kept the personality rather than replacing it."""
    a = set(re.findall(r"[a-z']{4,}", original.lower()))
    if not a:
        return bool(merged.strip())
    b = set(re.findall(r"[a-z']{4,}", merged.lower()))
    return len(merged) >= len(original) * 0.8 and len(a & b) / len(a) >= 0.6


@app.route("/api/personality/create", methods=["POST"])
def personality_create():
    data = request.get_json(force=True) or {}
    idea = str(data.get("idea") or "").strip()[:600]
    if len(idea) < 3:
        return jsonify({"error": "Describe the personality in a few words first."}), 400
    name, style, language = _personality_context(data)
    current = str(data.get("current") or "").strip()[:PERSONALITY_MAX_CHARS] if data.get("build_on") else ""
    try:
        raw, seconds = ask_writing_ai(build_personality_create_prompt(idea, name, style, language, current),
                                      max_tokens=900, temperature=0.8)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": f"Couldn't reach the AI: {e}"}), 502
    text = _clean_personality_text(raw)
    if len(text) < 40:
        return jsonify({"error": "The AI didn't write a usable personality. Try again, or describe it differently."}), 502
    return jsonify({"text": text, "seconds": round(seconds, 2), "engine": ", ".join(g.get("text_engines", []))})


@app.route("/api/personality/suggest", methods=["POST"])
def personality_suggest():
    data = request.get_json(force=True) or {}
    text = str(data.get("text") or "").strip()[:PERSONALITY_MAX_CHARS]
    if len(text) < 15:
        return jsonify({"suggestions": [], "reason": "short"})
    name, style, _ = _personality_context(data)
    skip = [str(x)[:60] for x in (data.get("skip") or [])][:30]
    memory = _conversation_memory(data)
    try:
        raw, seconds = ask_writing_ai(build_personality_suggest_prompt(text, name, style, memory, skip),
                                      max_tokens=600, temperature=0.9)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": f"Couldn't reach the AI: {e}"}), 502
    skipped = {s.lower() for s in skip}
    suggestions = [s for s in parse_personality_suggestions(raw, text) if s["label"].lower() not in skipped]
    return jsonify({"suggestions": suggestions, "used_conversation": bool(memory), "seconds": round(seconds, 2)})


@app.route("/api/personality/merge", methods=["POST"])
def personality_merge():
    data = request.get_json(force=True) or {}
    text = str(data.get("text") or "").strip()[:PERSONALITY_MAX_CHARS]
    additions = [str(a).strip()[:320] for a in (data.get("additions") or []) if str(a).strip()][:10]
    if not additions:
        return jsonify({"error": "There's nothing to add."}), 400
    appended = (text + ("\n\n" if text else "") + " ".join(additions)).strip()
    if not text:
        return jsonify({"text": appended, "woven": False})
    try:
        raw, seconds = ask_writing_ai(build_personality_merge_prompt(text, additions),
                                      max_tokens=1200, temperature=0.4)
        merged = _clean_personality_text(raw)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception:
        merged = ""
    # A merge that lost what you wrote isn't a merge: add them at the end instead.
    if not merged or not _merged_keeps_original(text, merged):
        return jsonify({"text": appended, "woven": False})
    return jsonify({"text": merged, "woven": True})


def get_tts_audio_timed(text, voice_id, language, plan):
    """
    NEW (1.5.0): speaks `text`, and says exactly when the voice finishes
    the last word of each chatbox page in `plan`. Returns (filename, ends).
    CHANGED (1.5.0): now a wrapper for speak_reply(), which also returns
    the word timings.
    """
    filename, ends, _ = speak_reply(text, voice_id, language, plan)
    return filename, ends


# ---------- Routes ----------


@app.route("/")
def index():
    return render_template(
        "index.html",
        min_words=MIN_WORDS,
        max_words_limit=MAX_WORDS,
        asset_version=asset_version(),
    )


# NEW (1.5.0): "Set up local AI", the step-by-step Ollama guide. Linked
# from Settings > Providers > Ollama.
@app.route("/setup/ollama")
def setup_ollama_guide():
    return render_template("setup_ollama.html", asset_version=asset_version())


@app.route("/diagnose")
def diagnose():
    """
    Server-rendered diagnostics that work without application assets.
    """
    def file_info(path):
        if not os.path.exists(path):
            return {"exists": False, "size": 0, "modified": "—"}
        return {
            "exists": True,
            "size": os.path.getsize(path),
            "modified": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(os.path.getmtime(path))),
        }

    files = {
        "app.py": file_info(os.path.join(BASE_DIR, "app.py")),
        "templates/index.html": file_info(os.path.join(BASE_DIR, "templates", "index.html")),
        "static/app.js": file_info(os.path.join(BASE_DIR, "static", "app.js")),
        "static/style.css": file_info(os.path.join(BASE_DIR, "static", "style.css")),
        "config.json": file_info(CONFIG_PATH),
        "profiles.json": file_info(PROFILES_PATH),
    }

    # Does index.html contain the elements app.js expects?
    index_path = os.path.join(BASE_DIR, "templates", "index.html")
    markers = {}
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            content = f.read()
        # The newest additions go at the end. "Why don't I see that option?"
        # is almost always the running process serving a template it compiled
        # before the file changed, and this table is how you tell the two
        # apart: the file on disk has the marker, the page does not.
        for marker in ["languageSelect", "masterVolumeSlider", "newProfileBtn",
                       "profileModalOverlay", "messageInput", "asset_version",
                       "responseStyleRadios", "personalityPresetSelect",
                       "dictateBtn", "micSelect", "dictationModeRadios",
                       "oscEnabledToggle", "oscMuteSyncToggle",
                       "frivoscMicValue", "serviceStatus",
                       "updateChip", "updateOverlay",   # NEW (updates)
                       "aiChip", "setup/ollama",        # NEW (1.5.0): the AI chip, the guide link
                       "gpuCard"]:                      # NEW (1.5.0): the graphics-card graph
            markers[marker] = marker in content

    js_path = os.path.join(BASE_DIR, "static", "app.js")
    js_markers = {}
    if os.path.exists(js_path):
        with open(js_path, "r", encoding="utf-8") as f:
            js = f.read()
        # CHANGED (1.5.0): buildAudioPlayer became attachBubbleAudio long ago,
        # so it always read MISSING. whereWritten is the newest addition.
        for marker in ["reportMissingElements", "attachBubbleAudio",
                       "masterVolumeSlider", "fillLanguages", "fillOptionList",
                       "loadUpdates", "whereWritten",    # NEW (updates); NEW (1.5.0) whereWritten
                       "renderGpu",                      # NEW (1.5.0): the graphics-card graph
                       "growFrom",                       # NEW (1.5.0): motion, round 1
                       "makeSpeechVisuals"]:             # NEW (1.5.0): motion, round 2
            js_markers[marker] = marker in js

    try:
        profile_count = len(load_profiles())
        profiles_ok = True
    except Exception:
        profile_count = 0
        profiles_ok = False

    rows = "".join(
        f"<tr><td>{name}</td><td>{'yes' if i['exists'] else 'MISSING'}</td>"
        f"<td>{i['size']:,}</td><td>{i['modified']}</td></tr>"
        for name, i in files.items()
    )
    marker_rows = "".join(
        f"<tr><td>{k}</td><td>{'found' if v else 'MISSING'}</td></tr>" for k, v in markers.items()
    )
    js_rows = "".join(
        f"<tr><td>{k}</td><td>{'found' if v else 'MISSING'}</td></tr>" for k, v in js_markers.items()
    )

    # NEW (updates): how this copy would install an update, if at all.
    updater = update_support()
    updater_mode = updater["mode"] or "unavailable"
    updater_reason = updater["reason"]

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Frivo diagnostics</title></head>
<body style="font-family:monospace;background:#16171c;color:#e6e2d8;padding:24px;line-height:1.6">
<h1 style="font-size:18px">Frivo — diagnostics</h1>
<p>This page uses no JavaScript and no external CSS. If you can read it styled
dark, the server is reachable from this device.</p>

<h2 style="font-size:15px">Server</h2>
<p>Frivo version: <b>{APP_VERSION}</b><br>
Asset version: <b>{asset_version()}</b><br>
Server started: <b>{SERVER_STARTED}</b><br>
Updates: <b>{updater_mode}</b> {updater_reason}<br>
You requested this from: <b>{request.host}</b><br>
Files load from: <b>{BASE_DIR or '(current directory)'}</b><br>
Profiles on disk: <b>{profile_count}</b> {'' if profiles_ok else '(profiles.json is unreadable/corrupt)'}</p>

<h2 style="font-size:15px">Files on disk</h2>
<table border="1" cellpadding="6" style="border-collapse:collapse">
<tr><th>File</th><th>Exists</th><th>Bytes</th><th>Last modified</th></tr>{rows}</table>

<h2 style="font-size:15px">index.html contains</h2>
<table border="1" cellpadding="6" style="border-collapse:collapse">{marker_rows}</table>

<h2 style="font-size:15px">app.js contains</h2>
<table border="1" cellpadding="6" style="border-collapse:collapse">{js_rows}</table>

<h2 style="font-size:15px">Direct static file test</h2>
<p>Click each. Both should open readable code, not an error:</p>
<ul>
<li><a style="color:#e9a13b" href="/static/app.js?v={asset_version()}">/static/app.js</a></li>
<li><a style="color:#e9a13b" href="/static/style.css?v={asset_version()}">/static/style.css</a></li>
<li><a style="color:#e9a13b" href="/api/settings">/api/settings</a> (should be JSON including a long "languages" list)</li>
<li><a style="color:#e9a13b" href="/api/profiles">/api/profiles</a> (should be JSON listing your profiles)</li>
</ul>

<h2 style="font-size:15px">Typing test (no JavaScript involved)</h2>
<p>If you can type in this box, the browser itself is fine and any typing
problem on the main page is caused by something overlaying the input:</p>
<input type="text" placeholder="Type here…" style="padding:8px;width:280px;background:#141517;color:#e6e2d8;border:1px solid #32353a">
</body></html>"""


@app.route("/api/settings", methods=["GET", "POST"])
def settings():
    global CFG
    if request.method == "POST":
        data = request.get_json(force=True)
        CFG["openai_api_key"] = data.get("openai_api_key", CFG["openai_api_key"]).strip()
        CFG["elevenlabs_api_key"] = data.get("elevenlabs_api_key", CFG["elevenlabs_api_key"]).strip()
        CFG["voice_id"] = data.get("voice_id", CFG["voice_id"]).strip()
        CFG["voice_name"] = data.get("voice_name", CFG.get("voice_name", "")).strip()
        CFG["model"] = resolve_model_id(data.get("model", CFG["model"]), RECOMMENDED_TEXT_MODEL)
        if "translation_model" in data:
            CFG["translation_model"] = resolve_model_id(
                data.get("translation_model"), CFG.get("translation_model", RECOMMENDED_TRANSLATION_MODEL)
            )
        CFG["system_prompt"] = data.get("system_prompt", CFG["system_prompt"]).strip()
        if "max_words" in data:
            CFG["max_words"] = clamp_words(data["max_words"], CFG.get("max_words", 80))
        if "speaking_speed" in data:
            CFG["speaking_speed"] = clamp_speaking_speed(
                data.get("speaking_speed"), CFG.get("speaking_speed", 1.0)
            )
        if "temperature" in data:
            CFG["temperature"] = clamp_temperature(
                data.get("temperature"), CFG.get("temperature", 0.7)
            )
        if "max_tokens" in data:
            CFG["max_tokens"] = clamp_max_tokens(
                data.get("max_tokens"), CFG.get("max_tokens", 0)
            )
        if "language" in data:
            CFG["language"] = normalize_language(data["language"]) or CFG.get("language", "English")
        # NEW (1.5.0)
        if "expressive_voice" in data:
            CFG["expressive_voice"] = data.get("expressive_voice") is True
        if "tag_shaping" in data:   # NEW (1.5.0)
            CFG["tag_shaping"] = data.get("tag_shaping") is True
        if "tag_amount" in data:    # NEW (1.5.0)
            CFG["tag_amount"] = normalize_tag_amount(data.get("tag_amount"), CFG.get("tag_amount", DEFAULT_TAG_AMOUNT))
        if "tag_words" in data:     # NEW (1.5.0)
            CFG["tag_words"] = normalize_tag_words(data.get("tag_words"))
        if "voice_delivery" in data:
            CFG["voice_delivery"] = normalize_voice_delivery(data.get("voice_delivery"), CFG.get("voice_delivery", DEFAULT_VOICE_DELIVERY))
        if "hold_accent" in data:
            CFG["hold_accent"] = normalize_hold_accent(data.get("hold_accent"), normalize_hold_accent(CFG.get("hold_accent")))
        if "elevenlabs_streaming" in data:   # NEW (1.5.0)
            CFG["elevenlabs_streaming"] = data.get("elevenlabs_streaming") is not False
        if "expressive_every_line" in data:   # NEW (1.5.0)
            CFG["expressive_every_line"] = data.get("expressive_every_line") is not False
        if "expressive_model" in data:
            CFG["expressive_model"] = normalize_expressive_model(data.get("expressive_model"), normalize_expressive_model(CFG.get("expressive_model")))
            REFUSED_MODELS.pop(CFG["expressive_model"], None)   # a fresh pick is tried again
        if data.get("retry_expressive_models"):   # NEW (1.5.0): "Try again"
            REFUSED_MODELS.clear()
            MODEL_REFUSALS.clear()
            REFUSED_EXTRAS.clear()
        if "voice_accent" in data:
            CFG["voice_accent"] = normalize_voice_accent(data.get("voice_accent"), normalize_voice_accent(CFG.get("voice_accent")))
        if "response_style" in data:
            CFG["response_style"] = normalize_response_style(
                data.get("response_style"), CFG.get("response_style", DEFAULT_RESPONSE_STYLE)
            )
        if "personality_preset" in data:
            CFG["personality_preset"] = normalize_personality_preset(
                data.get("personality_preset"), CFG.get("personality_preset", DEFAULT_PERSONALITY_PRESET)
            )
        # Providers. Each is validated against its own list, so an unknown
        # value in a hand-edited config can't put the app into a state where
        # nothing works — it just falls back to OpenAI.
        for key, options in (
            ("chat_provider", CHAT_PROVIDERS),
            ("translation_provider", TRANSLATION_PROVIDERS),
            ("transcription_provider", TRANSCRIPTION_PROVIDERS),
        ):
            if key in data:
                value = (data.get(key) or "").strip()
                CFG[key] = value if value in provider_ids(options) else "openai"

        for key, default in (
            ("ollama_url", DEFAULT_OLLAMA_URL),
            ("whisper_url", DEFAULT_WHISPER_URL),
            ("ollama_model", DEFAULT_OLLAMA_MODEL),
            ("ollama_model_balanced", OLLAMA_TIER_DEFAULTS["balanced"]),   # NEW (1.5.0)
            ("ollama_model_best", OLLAMA_TIER_DEFAULTS["best"]),           # NEW (1.5.0)
            ("ollama_translation_model", ""),
        ):
            if key in data:
                CFG[key] = (data.get(key) or "").strip() or default
        if data.get("ollama_tier") in OLLAMA_TIER_KEYS:   # NEW (1.5.0)
            CFG["ollama_tier"] = data["ollama_tier"]
        # NEW (1.5.0): Evora's idle timers, passed straight on to Evora.
        evora_changed = False
        if data.get("evora_idle_listen") in EVORA_IDLE_LISTEN and data["evora_idle_listen"] != CFG.get("evora_idle_listen"):
            CFG["evora_idle_listen"] = data["evora_idle_listen"]
            evora_changed = True
        if data.get("evora_idle_speech") in EVORA_IDLE_SPEECH and data["evora_idle_speech"] != CFG.get("evora_idle_speech"):
            CFG["evora_idle_speech"] = data["evora_idle_speech"]
            evora_changed = True
        if evora_changed:
            threading.Thread(target=apply_evora_idle_timers, daemon=True, name="evora-idle").start()
        if data.get("ollama_idle_unload") in OLLAMA_IDLE_UNLOAD:   # NEW (1.5.0)
            changed = CFG.get("ollama_idle_unload") != data["ollama_idle_unload"]
            CFG["ollama_idle_unload"] = data["ollama_idle_unload"]
            if changed:
                # Applied to the model on the card now, not at the next reply.
                threading.Thread(target=apply_ollama_idle_timer, name="ollama-idle", daemon=True).start()

        if "allow_openai_fallback" in data:
            CFG["allow_openai_fallback"] = bool(data.get("allow_openai_fallback"))

        if "osc_enabled" in data:
            CFG["osc_enabled"] = bool(data.get("osc_enabled"))

        if "osc_mute_sync" in data:
            CFG["osc_mute_sync"] = bool(data.get("osc_mute_sync"))

        if "osc_unmute_on_send" in data:
            CFG["osc_unmute_on_send"] = bool(data.get("osc_unmute_on_send"))

        if "osc_typing" in data:   # NEW (typing)
            CFG["osc_typing"] = bool(data.get("osc_typing"))

        save_config(CFG)
        return jsonify({"ok": True})

    return jsonify(
        {
            "openai_key_set": bool(CFG["openai_api_key"]),
            "chat_provider": resolve_provider("chat_provider", CHAT_PROVIDERS),
            "translation_provider": resolve_provider("translation_provider", TRANSLATION_PROVIDERS),
            "transcription_provider": resolve_provider(
                "transcription_provider", TRANSCRIPTION_PROVIDERS
            ),
            "chat_providers": CHAT_PROVIDERS,
            "translation_providers": TRANSLATION_PROVIDERS,
            "transcription_providers": TRANSCRIPTION_PROVIDERS,
            "ollama_url": CFG.get("ollama_url", DEFAULT_OLLAMA_URL),
            "ollama_model": CFG.get("ollama_model", DEFAULT_OLLAMA_MODEL),
            "ollama_model_balanced": tier_model("balanced"),   # NEW (1.5.0)
            "ollama_model_best": tier_model("best"),           # NEW (1.5.0)
            "ollama_tier": ollama_tier(),                      # NEW (1.5.0)
            "ollama_idle_unload": CFG.get("ollama_idle_unload") or DEFAULT_OLLAMA_IDLE_UNLOAD,   # NEW (1.5.0)
            "evora_idle_listen": CFG.get("evora_idle_listen") or DEFAULT_EVORA_IDLE_LISTEN,      # NEW (1.5.0)
            "evora_idle_speech": CFG.get("evora_idle_speech") or DEFAULT_EVORA_IDLE_SPEECH,      # NEW (1.5.0)
            "ollama_translation_model": CFG.get("ollama_translation_model", ""),
            "whisper_url": CFG.get("whisper_url", DEFAULT_WHISPER_URL),
            "allow_openai_fallback": bool(CFG.get("allow_openai_fallback", False)),
            "osc_enabled": bool(CFG.get("osc_enabled", False)),
            "osc_mute_sync": bool(CFG.get("osc_mute_sync", False)),
            "osc_unmute_on_send": bool(CFG.get("osc_unmute_on_send", False)),
            "osc_typing": bool(CFG.get("osc_typing", True)),   # NEW (typing)
            "elevenlabs_key_set": bool(CFG["elevenlabs_api_key"]),
            "voice_id": CFG["voice_id"],
            "voice_name": CFG.get("voice_name", ""),
            "model": CFG["model"],
            "translation_model": CFG.get("translation_model", RECOMMENDED_TRANSLATION_MODEL),
            "text_models": TEXT_MODELS,
            "recommended_text_model": RECOMMENDED_TEXT_MODEL,
            "recommended_translation_model": RECOMMENDED_TRANSLATION_MODEL,
            "model_tier_throughput": MODEL_TIER_THROUGHPUT,
            "model_tier_speed_label": MODEL_TIER_SPEED_LABEL,
            "system_prompt": CFG["system_prompt"],
            "response_style": normalize_response_style(CFG.get("response_style")),  # CHANGED (1.5.0)
            "personality_preset": CFG.get("personality_preset", DEFAULT_PERSONALITY_PRESET),
            "response_styles": RESPONSE_STYLES,
            "personality_presets": PERSONALITY_PRESETS,
            "max_words": CFG.get("max_words", 80),
            "speaking_speed": clamp_speaking_speed(CFG.get("speaking_speed", 1.0)),
            # NEW (1.5.0)
            "expressive_voice": CFG.get("expressive_voice") is True,
            "tag_shaping": CFG.get("tag_shaping") is True,   # NEW (1.5.0)
            "tag_amount": normalize_tag_amount(CFG.get("tag_amount")),   # NEW (1.5.0)
            "tag_amounts": TAG_AMOUNTS,
            "tag_words": tag_words(),                        # NEW (1.5.0)
            "voice_delivery": normalize_voice_delivery(CFG.get("voice_delivery")),
            "hold_accent": normalize_hold_accent(CFG.get("hold_accent")),
            "hold_accent_modes": HOLD_ACCENT_MODES,
            "voice_accent": normalize_voice_accent(CFG.get("voice_accent")),
            "expressive_model": normalize_expressive_model(CFG.get("expressive_model")),
            "expressive_every_line": CFG.get("expressive_every_line", True) is not False,   # NEW (1.5.0)
            "elevenlabs_streaming": elevenlabs_streaming_on(),   # NEW (1.5.0)
            # NEW (1.5.0): models ElevenLabs refused this hour, and why.
            "expressive_refusals": {m: dict(r, label=model_label(m)) for m, r in MODEL_REFUSALS.items()
                                    if time.time() - REFUSED_MODELS.get(m, 0) < 3600},
            "expressive_models": EXPRESSIVE_MODELS,
            "voice_accents": [{"id": a["id"], "name": a["name"]} for a in VOICE_ACCENTS],
            "voice_deliveries": VOICE_DELIVERIES,
            "audio_tag_groups": AUDIO_TAG_GROUPS,
            "min_speaking_speed": MIN_SPEAKING_SPEED,
            "max_speaking_speed": MAX_SPEAKING_SPEED,
            "temperature": clamp_temperature(CFG.get("temperature", 0.7)),
            "max_tokens": clamp_max_tokens(CFG.get("max_tokens", 0)),
            "language": CFG.get("language", "English"),
            "languages": LANGUAGES,
        }
    )


@app.route("/api/local-status")
def local_status():
    """
    Health of the local services this install actually depends on.

    Only reports on providers that are currently selected — with everything
    on OpenAI there is nothing local to be down, and an indicator for a
    service you aren't using is just another light to ignore. Kept fast with
    a short timeout, since the browser polls this and a slow check would
    make the whole page feel sluggish.
    """
    chat = resolve_provider("chat_provider", CHAT_PROVIDERS)
    translation = resolve_provider("translation_provider", TRANSLATION_PROVIDERS)
    transcription = resolve_provider("transcription_provider", TRANSCRIPTION_PROVIDERS)

    services = []

    if "ollama" in (chat, translation):
        ok, message = probe_provider("ollama", timeout=2)
        uses = [
            label
            for label, provider in (("chat", chat), ("translation", translation))
            if provider == "ollama"
        ]
        services.append({
            "id": "ollama",
            "name": "Ollama",
            "ok": ok,
            "message": message,
            "url": ollama_base_url(),
            "used_for": uses,
            "fallback": True,
        })

    if transcription == "local_whisper":
        ok, message = probe_provider("whisper", timeout=2)
        services.append({
            "id": "whisper",
            "name": "Evora",
            "ok": ok,
            "message": message,
            "url": whisper_base_url(),
            "used_for": ["transcription"],
            "fallback": True,
        })

    # FrivOSC reports itself, so there is nothing to probe — it either
    # checked in recently or it did not. Listed here rather than in its own
    # indicator because it is the same question as Evora's: a companion
    # this install depends on, up or down. Only shown once the feature is
    # switched on, matching the rule the providers above follow.
    if CFG.get("osc_enabled", False):
        status = frivosc_status()
        services.append({
            "id": "frivosc",
            "name": "FrivOSC",
            "ok": bool(status["connected"]),
            "message": (
                "Connected." if status["connected"]
                else "Not connected. Start FrivOSC on the PC you play VRChat on."
            ),
            "url": status.get("hostname") or "this network",
            "used_for": ["VRChat chatbox", "VRChat microphone"],
            # No OpenAI to fall back to: if FrivOSC is down, VRChat simply
            # gets nothing. The client uses this to pick the right sentence.
            "fallback": False,
        })

    return jsonify({
        "services": services,
        # True when nothing local is selected at all, so the client can hide
        # the indicator entirely rather than showing a meaningless "all ok".
        "none_selected": not services,
        "all_ok": all(s["ok"] for s in services),
    })


@app.route("/api/provider-test", methods=["POST"])
def provider_test():
    """
    Backs the "Test" buttons next to the local provider addresses. Runs
    server-side because the browser can't reach a plain-HTTP LAN service
    from an HTTPS page — mixed content is blocked — and because the server
    is what will actually be making these calls in anger.
    """
    data = request.get_json(force=True) or {}
    kind = (data.get("kind") or "").strip()
    if kind not in {"ollama", "whisper"}:
        return jsonify({"error": "Unknown provider."}), 400

    # Test against the address in the form, not the saved one, so it can be
    # checked before committing it.
    url = (data.get("url") or "").strip()
    original = None
    key = "ollama_url" if kind == "ollama" else "whisper_url"
    if url:
        original = CFG.get(key)
        CFG[key] = url
    try:
        ok, message = probe_provider(kind)
    finally:
        if original is not None:
            CFG[key] = original

    return jsonify({"ok": ok, "message": message})


def language_iso(name):
    """
    ISO-639-1 code for a language name from LANGUAGES ("German" -> "de").

    Derived from the BCP-47 speech tag already stored there, so there's one
    list to keep current rather than two.
    """
    for lang in LANGUAGES:
        if lang["name"] == name:
            return (lang.get("speech") or "").split("-")[0].lower()
    return ""


def translate_text(text, target_language):
    """
    Translates into the target language using whichever provider is
    configured. Returns the text unchanged if it's already in that language
    or translation fails — a missing translation should degrade the
    listening panel to "shows the original", not break it.
    """
    if not text:
        return text

    provider = resolve_provider("translation_provider", TRANSLATION_PROVIDERS)
    client = make_openai_client()
    if provider == "openai" and client is None:
        return text

    prompt = (
        f"Translate the following into {target_language}. Render it the way a "
        f"fluent {target_language} speaker would actually say it, not as a stiff "
        "literal translation, and keep the original tone. If it is already in "
        f"{target_language}, repeat it back unchanged. Reply with only the "
        "translation, nothing else.\n\n" + text
    )

    try:
        response = create_chat_completion(
            client,
            provider=provider,
            model=CFG.get("translation_model", RECOMMENDED_TRANSLATION_MODEL),
            ollama_model=CFG.get("ollama_translation_model")
            or active_ollama_model(),   # CHANGED (1.5.0)
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max(120, len(text) // 2),
        )
        return response.choices[0].message.content.strip() or text
    except Exception as e:
        log_server_event(f"Listen translation failed ({e!r}) — showing original.")
        return text


def group_listen_segments(segments):
    """Build utterances per speaker, keeping recovered simultaneous tracks separate."""
    rows = []
    tracks = {}
    for segment in sorted(segments, key=lambda item: (item.get("start", 0), item.get("end", 0))):
        text = segment.get("text") or ""
        if not text.strip():
            continue
        speaker = segment.get("speaker")
        source = segment.get("source", "unknown")
        voice_track = segment.get("voice_track")
        key = (speaker.get("id") if speaker else (voice_track or {}).get("id", segment.get("track")),
               source, segment.get("language"))
        previous = tracks.get(key)
        start, end = segment.get("start", 0), segment.get("end", 0)
        if previous and start - previous["end"] <= 1.2 and (source == "separated" or previous is rows[-1]):
            previous["original"] += text
            previous["end"] = max(previous["end"], end)
        else:
            previous = {"original": text, "start": start, "end": end, "speaker": speaker,
                        "source": source, "overlapping": bool(segment.get("overlapping")),
                        "accepted": bool(segment.get("accepted")), "voice_track": voice_track,
                        "detected_language": segment.get("language")}
            rows.append(previous)
            tracks[key] = previous
    for row in rows:
        row["original"] = row["original"].strip()
    return rows


@app.get("/api/evora-speaker-settings")
def evora_speaker_settings():
    base = whisper_base_url()
    parsed = urlsplit(base)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        return "Set a valid Evora HTTP or HTTPS address in Frivo settings first.", 400
    return redirect(base + "/speaker-settings")


@app.route("/api/listen-session", methods=["POST", "DELETE"])
def listen_session():
    if resolve_provider("transcription_provider", TRANSCRIPTION_PROVIDERS) != "local_whisper":
        return jsonify(listening_session=None, speaker_status={"state": "unavailable"})
    try:
        with EVORA_TRANSCRIPTION_LOCK:
            if request.method == "POST":
                response = requests.post(f"{whisper_base_url()}/v1/listening-sessions", timeout=LOCAL_CONNECT_TIMEOUT)
            else:
                data = request.get_json(silent=True) or {}
                ident = data.get("listening_session", "")
                if not isinstance(ident, str) or not re.fullmatch(r"[A-Za-z0-9_-]{20,64}", ident):
                    return jsonify(error="Invalid listening session"), 400
                response = requests.delete(f"{whisper_base_url()}/v1/listening-sessions/{ident}", timeout=LOCAL_CONNECT_TIMEOUT)
        if response.status_code == 404:
            return jsonify(error="Update Evora to 1.2.0 to use session speaker recognition."), 409
        return jsonify(response.json()), response.status_code
    except requests.RequestException:
        return jsonify(error="Evora isn't reachable. Check its address and service status."), 502


@app.route("/api/listen", methods=["POST"])
def listen():
    """
    One audio segment of someone else speaking -> transcript + translation.

    Unlike dictation, this endpoint detects the spoken language and returns a
    server-side translation for the listening panel.
    """
    audio_file = request.files.get("audio")
    if not audio_file or not audio_file.filename:
        return jsonify({"error": "No audio received."}), 400

    audio_bytes = audio_file.read()
    if not audio_bytes:
        return jsonify({"error": "Empty audio segment."}), 400

    target_language = normalize_language(request.form.get("target_language")) or "English"
    file_tuple = (audio_file.filename, audio_bytes, audio_file.mimetype or "audio/webm")

    # An "interim" request is a partial utterance sent while someone is
    # still talking, to be replaced by the full one shortly. Speaker
    # identification is skipped for these: a half-sentence gives a weaker
    # fingerprint, and feeding those into the clustering would pollute the
    # voice profiles with low-quality samples of the same person.
    interim = (request.form.get("interim") or "").strip() in {"1", "true", "yes"}

    provider = resolve_provider("transcription_provider", TRANSCRIPTION_PROVIDERS)
    started = time.perf_counter()
    original = ""
    detected = ""
    speaker = None
    segments = []
    speaker_status = {}

    try:
        if provider == "local_whisper":
            try:
                original, detected, speaker, segments, speaker_status = local_whisper_transcribe_verbose(
                    file_tuple, want_speaker=not interim, listening_session=request.form.get("listening_session")
                )
            except Exception as e:
                log_server_event(f"Listen: local Whisper unavailable ({e!r}).")
                if isinstance(e, requests.HTTPError) and e.response is not None and e.response.status_code == 409:
                    return jsonify(error="Speaker session expired. Stop and restart listening."), 409
                if not fallback_allowed():
                    return jsonify({
                        "error": (
                            "Evora server unreachable. Automatic fallback to OpenAI "
                            "is off, so nothing was sent to a paid service."
                        )
                    }), 503
                if not CFG["openai_api_key"]:
                    return jsonify({
                        "error": "Evora server unreachable and no OpenAI key set."
                    }), 502
                original = openai_transcribe(file_tuple)
        else:
            if not CFG["openai_api_key"]:
                return jsonify({"error": "Add your OpenAI key in Settings first."}), 400
            original = openai_transcribe(file_tuple)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    transcribe_seconds = time.perf_counter() - started

    original = (original or "").strip()
    if not original:
        # Silence or noise that got past the gate. Not an error — just
        # nothing worth showing.
        return jsonify({"text": "", "original": "", "empty": True})

    # If they're already speaking the language you want to read, there is
    # nothing to translate. Skipping the call outright is both faster and
    # cheaper — and it fixes English appearing twice, once as the "original"
    # and once as a translation that had merely reworded it. Comparing the
    # two strings couldn't catch that, because a faithful rewording is still
    # a different string.
    target_iso = language_iso(target_language)
    same_language = bool(detected) and bool(target_iso) and detected.lower() == target_iso

    started = time.perf_counter()
    rows = group_listen_segments(segments) if not interim else []
    for row in rows:
        row_language = row["detected_language"] or detected
        row_same_language = bool(row_language) and bool(target_iso) and row_language.lower() == target_iso
        row["text"] = row["original"] if row_same_language else translate_text(row["original"], target_language)
        row["translated"] = row["text"] != row["original"]
        row["detected_language"] = row_language
    translated = (" ".join(row["text"] for row in rows) if rows else
                  original if same_language else translate_text(original, target_language))
    translate_seconds = time.perf_counter() - started

    return jsonify({
        "original": original,
        "text": translated,
        "speaker": speaker,
        "segments": rows,
        "speaker_status": speaker_status,
        "detected_language": detected,
        "target_language": target_language,
        # Drives whether the client shows the original underneath. False
        # when no translation happened, and also when one was attempted but
        # came back unchanged.
        "translated": (
            not same_language
            and translated.strip().lower() != original.strip().lower()
        ),
        "transcribe_seconds": round(transcribe_seconds, 2),
        "translate_seconds": round(translate_seconds, 2),
    })


@app.route("/api/listen-speakers", methods=["GET", "POST", "DELETE"])
def listen_speakers():
    """
    Reads, tunes and clears the voice profiles the Whisper server has
    learned. Proxied for the same mixed-content reason as the model
    endpoint.
    """
    try:
        if request.method == "GET":
            response = requests.get(
                f"{whisper_base_url()}/speakers", timeout=LOCAL_CONNECT_TIMEOUT
            )
        elif request.method == "POST":
            data = request.get_json(force=True) or {}
            response = requests.post(
                f"{whisper_base_url()}/speakers/threshold",
                json={"threshold": data.get("threshold")},
                timeout=LOCAL_CONNECT_TIMEOUT,
            )
        else:
            response = requests.delete(
                f"{whisper_base_url()}/speakers", timeout=LOCAL_CONNECT_TIMEOUT
            )
        return jsonify(response.json()), response.status_code
    except requests.exceptions.ConnectionError:
        return jsonify({"error": "Evora isn't reachable."}), 502
    except Exception as e:
        return jsonify({"error": str(e)}), 502


@app.route("/api/whisper-model", methods=["GET", "POST"])
def whisper_model():
    """
    Reads and changes the model on the local Whisper server.

    Proxied through here rather than called from the browser because the app
    is served over HTTPS and the Whisper service is plain HTTP on the LAN —
    browsers block that combination as mixed content, with no override.
    """
    try:
        if request.method == "GET":
            response = requests.get(
                f"{whisper_base_url()}/health", timeout=LOCAL_CONNECT_TIMEOUT
            )
            response.raise_for_status()
            return jsonify(response.json())

        data = request.get_json(force=True) or {}
        response = requests.post(
            f"{whisper_base_url()}/model",
            json={"model": (data.get("model") or "").strip()},
            # Generous: switching model can mean downloading it first, and
            # large-v3 is around 3GB on a cold cache.
            timeout=(LOCAL_CONNECT_TIMEOUT, 900),
        )
        payload = response.json()
        return jsonify(payload), response.status_code
    except requests.exceptions.ConnectionError:
        return jsonify({"error": "Evora isn't reachable at that address."}), 502
    except Exception as e:
        return jsonify({"error": str(e)}), 502


# The labels ElevenLabs attaches to a voice, in the order they read best as
# a one-line summary. Only these are surfaced: the API also returns things
# like "featured" and internal flags, which are noise in a picker.
VOICE_LABEL_KEYS = ("gender", "age", "accent", "use_case", "description", "descriptive")

# ISO-639-1 to display name, for the language a voice is built for. Only the
# codes ElevenLabs actually returns are here; anything unrecognised falls
# through and is shown as the raw code rather than hidden, since a code is
# still more useful than nothing.
VOICE_LANGUAGE_NAMES = {
    "en": "English", "de": "German", "es": "Spanish", "fr": "French",
    "it": "Italian", "pt": "Portuguese", "nl": "Dutch", "pl": "Polish",
    "ru": "Russian", "uk": "Ukrainian", "cs": "Czech", "sk": "Slovak",
    "hr": "Croatian", "bg": "Bulgarian", "ro": "Romanian", "el": "Greek",
    "sv": "Swedish", "da": "Danish", "fi": "Finnish", "no": "Norwegian",
    "hu": "Hungarian", "tr": "Turkish", "ar": "Arabic", "hi": "Hindi",
    "ta": "Tamil", "id": "Indonesian", "ms": "Malay", "fil": "Filipino",
    "vi": "Vietnamese", "ja": "Japanese", "zh": "Chinese", "ko": "Korean",
}

# Accents that only exist in English. Used to fill in a language for the
# many premade voices that declare an accent but no language at all — the
# guess is marked as such so the UI can say where it came from.
ENGLISH_ACCENTS = {
    "american", "british", "english", "australian", "irish", "scottish",
    "canadian", "transatlantic", "us southern", "new york", "cockney",
    "received pronunciation", "rp", "us", "uk",
}


def voice_languages(v):
    """
    Which language(s) a voice is built for, newest source first.

    ElevenLabs reports this three different ways depending on how the voice
    was made: verified_languages on newer library voices, fine_tuning for
    professional clones, and occasionally a plain label. None of them is
    present on every voice, so all three are tried before giving up.
    """
    codes = []

    def add(code):
        code = (code or "").strip().lower()
        # Locales arrive as "en-US" on some voices and "en" on others.
        code = code.split("-")[0]
        if code and code not in codes:
            codes.append(code)

    for entry in v.get("verified_languages") or []:
        if isinstance(entry, dict):
            add(entry.get("language"))

    if not codes:
        add(((v.get("fine_tuning") or {}).get("language")))

    labels = v.get("labels") or {}
    if not codes:
        add(labels.get("language"))

    if codes:
        source = "declared"
    else:
        # Nothing declared. An accent that only exists in English is decent
        # evidence, and saying "English (from its accent)" is more useful
        # than a blank — as long as the UI doesn't present it as fact.
        accent = (labels.get("accent") or "").strip().lower()
        if accent in ENGLISH_ACCENTS:
            codes = ["en"]
            source = "accent"
        else:
            source = ""

    return (
        [{"code": c, "name": VOICE_LANGUAGE_NAMES.get(c, c.upper())} for c in codes],
        source,
    )


def voice_tag_fit(v):
    """
    NEW (1.5.0): how well an ElevenLabs voice takes voice tags, from what
    ElevenLabs reports about it (there's no "made for v3" flag):

      "made"    ElevenLabs lists v3 or v4 among the models this voice is
                high-quality or verified for
      "clone"   a voice clone or a designed voice: what ElevenLabs
                recommends for the expressive models
      "older"   a default voice from before v3 (Rachel and the rest), or
                one marked legacy: tags work, but it may not hold its
                accent with them
      ""        nothing to go on
    """
    models = set(v.get("high_quality_base_model_ids") or [])
    for entry in v.get("verified_languages") or []:
        if isinstance(entry, dict) and entry.get("model_id"):
            models.add(entry["model_id"])
    if any(str(m).startswith(("eleven_v3", "eleven_v4")) for m in models):
        return "made"
    if v.get("is_legacy"):
        return "older"
    category = (v.get("category") or "").lower()
    if category in ("cloned", "generated", "professional"):
        return "clone"
    if category == "premade":
        return "older"
    return ""


def tidy_voice(v):
    """
    Flattens one ElevenLabs voice into what the picker actually needs.

    The raw objects are large — samples, fine-tuning state, sharing metadata,
    settings — and sending all of it for several hundred voices makes the
    list slow to load for no benefit. Labels are lifted into a flat list so
    the front end can search and filter on them without knowing the schema.
    """
    labels = v.get("labels") or {}
    tags = []
    for key in VOICE_LABEL_KEYS:
        value = (labels.get(key) or "").strip()
        if value and value.lower() not in [t.lower() for t in tags]:
            # "use_case" values arrive underscored, e.g. "social_media"
            tags.append(value.replace("_", " "))

    languages, language_source = voice_languages(v)

    return {
        "voice_id": v["voice_id"],
        "name": v.get("name", "Unnamed"),
        "category": v.get("category", ""),
        "tags": tags,
        # Sent as its own field rather than left for the UI to dig out of
        # tags by position — the row shows exactly language and gender, and
        # relying on the order VOICE_LABEL_KEYS happens to be in would break
        # the moment a voice omits one of the earlier labels.
        "gender": (labels.get("gender") or "").strip(),
        # Only present on newer voices; ElevenLabs notes it "may not be
        # available for older voices". Null means the UI shouldn't offer to
        # sort by it rather than sorting by nothing.
        "created_at": v.get("created_at_unix"),
        "languages": languages,
        # "declared" | "accent" | "" — lets the UI show a guessed language
        # differently from one the voice actually states.
        "language_source": language_source,
        # Auditioning a voice from its preview costs nothing: it's a static
        # file ElevenLabs already generated, not a synthesis request.
        "preview_url": v.get("preview_url", ""),
        "description": (v.get("description") or "").strip(),
        # NEW (1.5.0): how well it takes voice tags, from what ElevenLabs says.
        "tag_fit": voice_tag_fit(v),
        # NEW (1.5.0): yours (a clone you made) or one added from the Voice
        # Library, for removing it from your ElevenLabs voices.
        "is_owner": v.get("is_owner") is True,
    }


def elevenlabs_problem(resp):
    """
    NEW (1.5.0): what ElevenLabs' refusal means, in words. A key made with
    only some permissions is refused with "missing_permissions", naming the
    one it lacks; a wrong or deleted key with "invalid_api_key".
    """
    status = getattr(resp, "status_code", 0)
    detail = {}
    try:
        body = resp.json()
        detail = body.get("detail") if isinstance(body.get("detail"), dict) else {"message": str(body.get("detail") or "")}
    except Exception:
        detail = {"message": (getattr(resp, "text", "") or "")[:200]}
    code = str(detail.get("status") or detail.get("code") or "")
    message = str(detail.get("message") or "")
    if code == "missing_permissions" or "permission" in message.lower():
        perm = re.search(r"permission[s]?\s+([a-z_]+)", message, re.I)
        what = perm.group(1) if perm else ""
        friendly = {"voices_read": "Voices (read)", "voices_write": "Voices (write)", "user_read": "User (read)",
                    "text_to_speech": "Text to Speech"}.get(what, what or "the permission it needs")
        return ("permission", f"This key isn't allowed {friendly}. On ElevenLabs › API keys, edit the key "
                              f"and allow it, or make a new key without restrictions.", message)
    if status == 401 or code in ("invalid_api_key", "unauthorized"):
        return ("invalid", "ElevenLabs doesn't accept this key. Check you copied all of it, or make a new one.", message)
    if status == 429:
        return ("busy", "ElevenLabs is rate-limiting this key for now. Try again in a minute.", message)
    return ("error", f"ElevenLabs said {status}{': ' + message if message else ''}.", message)


@app.route("/api/elevenlabs/check")
def elevenlabs_check():
    """
    NEW (1.5.0): actually tries the key: your voices (and how many are your
    own), and your account. "Connected" used to mean only that a key was
    saved.
    """
    key = CFG.get("elevenlabs_api_key")
    if not key:
        return jsonify({"state": "missing", "message": "No key saved."})
    out = {"state": "ok", "voices": None, "own_voices": None, "account": None, "problems": []}
    try:
        r = requests.get("https://api.elevenlabs.io/v1/voices", headers={"xi-api-key": key}, timeout=20)
        if r.status_code == 200:
            vs = r.json().get("voices") or []
            out["voices"] = len(vs)
            out["own_voices"] = sum(1 for v in vs if (v.get("category") or "") != "premade")
        else:
            kind, text, raw = elevenlabs_problem(r)
            out["problems"].append({"what": "voices", "kind": kind, "message": text, "raw": raw})
    except Exception as e:
        out["problems"].append({"what": "voices", "kind": "unreachable", "message": f"Couldn't reach ElevenLabs: {e}"})
    try:
        r = requests.get("https://api.elevenlabs.io/v1/user/subscription", headers={"xi-api-key": key}, timeout=20)
        if r.status_code == 200:
            sub = r.json()
            out["account"] = {"tier": sub.get("tier"), "used": sub.get("character_count"),
                              "limit": sub.get("character_limit")}
        else:
            kind, text, raw = elevenlabs_problem(r)
            out["problems"].append({"what": "account", "kind": kind, "message": text, "raw": raw})
    except Exception as e:
        out["problems"].append({"what": "account", "kind": "unreachable", "message": f"Couldn't reach ElevenLabs: {e}"})
    kinds = {p["kind"] for p in out["problems"]}
    if "invalid" in kinds:
        out["state"] = "invalid"
    elif "unreachable" in kinds and out["voices"] is None:
        out["state"] = "unreachable"
    elif any(p["what"] == "voices" for p in out["problems"]):
        out["state"] = "no_voices"
    elif out["problems"]:
        out["state"] = "partial"
    return jsonify(out)


@app.route("/api/voices")
def voices():
    # CHANGED (1.5.0): the free voices are always listed, and ElevenLabs'
    # are added when there's a key. No key is no longer an error — it just
    # means the free voices are the ones on offer.
    # CHANGED (1.5.0): Kokoro removed. A voice that's in use moves to its
    # newer copy first, so it's never listed twice.
    try:
        upgrade_desktop_voices()
    except Exception as e:
        log_server_event(f"Voices: couldn't move to the newer voices: {e!r}")
    free = piper_voice_entries() + windows_voice_entries()   # CHANGED (1.5.0): Frivo's voices first
    if not CFG["elevenlabs_api_key"]:
        return jsonify({"voices": free, "notice": "" if free else
                        "Add your ElevenLabs key in Settings to load voices."})
    try:
        resp = requests.get(
            "https://api.elevenlabs.io/v1/voices",
            headers={"xi-api-key": CFG["elevenlabs_api_key"]},
            timeout=30,
        )
        if resp.status_code != 200:   # CHANGED (1.5.0): why, in words
            _, text, raw = elevenlabs_problem(resp)
            log_server_event(f"Voices: ElevenLabs refused the voice list ({resp.status_code}): {raw}")
            return jsonify({"voices": free, "notice": f"Your ElevenLabs voices didn't load. {text}",
                            "eleven_problem": True})
        data = resp.json()
        return jsonify({"voices": [tidy_voice(v) for v in data.get("voices", [])] + free})
    except Exception as e:
        if free:
            return jsonify({"voices": free, "notice": f"ElevenLabs voices couldn't be loaded: {e}"})
        return jsonify({"error": str(e)}), 500


_EL_VOICE_ID_RE = re.compile(r"^[A-Za-z0-9]{8,40}$")


@app.route("/api/voices/elevenlabs/<voice_id>", methods=["DELETE"])
def elevenlabs_voice_remove(voice_id):
    """
    NEW (1.5.0): removes a voice from your ElevenLabs voices ("My Voices").
    A voice added from the Voice Library can be added back from there; a
    clone you made is deleted for good. ElevenLabs' default voices can't be
    removed. Refused while a profile (or the default) still uses the voice,
    so nothing is left pointing at a voice that's gone.
    """
    if not _EL_VOICE_ID_RE.match(voice_id or "") or tts_engine(voice_id) != "elevenlabs":
        return jsonify({"error": "That isn't an ElevenLabs voice."}), 400
    if not CFG.get("elevenlabs_api_key"):
        return jsonify({"error": "Add your ElevenLabs key first."}), 400
    users = [p["name"] for p in load_profiles() if p.get("voice_id") == voice_id]
    if CFG.get("voice_id") == voice_id:
        users.insert(0, "Default")
    if users:
        names = ", ".join(users[:4]) + (" and others" if len(users) > 4 else "")
        return jsonify({"error": f"It's the voice for {names}. Pick another voice there first, then remove it.",
                        "in_use": users}), 409
    try:
        resp = requests.delete(f"https://api.elevenlabs.io/v1/voices/{voice_id}",
                               headers={"xi-api-key": CFG["elevenlabs_api_key"]}, timeout=30)
    except Exception as e:
        return jsonify({"error": f"Couldn't reach ElevenLabs: {e}"}), 502
    if resp.status_code != 200:
        detail = ""
        try:
            body = resp.json()
            detail = (body.get("detail") or {}).get("message") if isinstance(body.get("detail"), dict) else body.get("detail")
        except Exception:
            detail = resp.text[:200]
        return jsonify({"error": f"ElevenLabs didn't remove it ({resp.status_code}){': ' + str(detail) if detail else ''}."}), 502
    # Its anchors go with it.
    with ANCHORS_LOCK:
        anchors = load_anchors()
        gone = [k for k in anchors if k.startswith(voice_id + "::")]
        for k in gone:
            entry = anchors.pop(k)
            if entry.get("file"):
                try:
                    os.remove(os.path.join(ANCHORS_DIR, entry["file"]))
                except OSError:
                    pass
        if gone:
            write_anchors(anchors)
    log_server_event(f"Voices: removed {voice_id} from your ElevenLabs voices")
    return jsonify({"ok": True})


# NEW (1.5.0): the free voices' state, for Settings.
# CHANGED (1.5.0): Windows voices only; Kokoro and its download are gone.
@app.route("/api/voices/free")
def free_voices_status():
    available = windows_voices_available()
    voices = list_windows_voices() if available else []
    with WINDOWS_VOICES_LOCK:
        error = WINDOWS_VOICES_CACHE["error"]
    return jsonify({"piper": piper_status(), "windows": {   # CHANGED (1.5.0): piper
        "available": available,
        "count": len(windows_voice_entries()) if available else 0,
        "newer": sum(1 for v in voices if v["kind"] == "onecore"),
        "error": error,
    }})


FREE_SAMPLE_LINES = {
    "en": "Hi there! This is how I sound. Nice to meet you.",
    "es": "¡Hola! Así es como sueno. Encantado de conocerte.",
    "fr": "Bonjour ! Voici ma voix. Ravi de vous rencontrer.",
    "it": "Ciao! Questa è la mia voce. Piacere di conoscerti.",
    "pt": "Olá! Esta é a minha voz. Prazer em conhecer você.",
    "de": "Hallo! So klinge ich. Schön, dich kennenzulernen.",
    "nl": "Hallo! Zo klink ik. Leuk je te ontmoeten.",
    "pl": "Cześć! Tak brzmi mój głos. Miło cię poznać.",
    "ru": "Привет! Вот так звучит мой голос. Приятно познакомиться.",
    "hi": "नमस्ते! मेरी आवाज़ ऐसी है। आपसे मिलकर ख़ुशी हुई।",
    "ja": "こんにちは。これが私の声です。よろしくお願いします。",
    "zh": "你好！这就是我的声音。很高兴认识你。",
    "ko": "안녕하세요! 제 목소리는 이렇습니다. 만나서 반가워요.",
}


# NEW (1.5.0): what a free voice sounds like. It's made on this PC once, then kept.
@app.route("/api/voices/preview")
def free_voice_preview():
    import hashlib

    voice_id = request.args.get("voice_id") or ""
    if tts_engine(voice_id) not in ("windows", "piper"):   # CHANGED (1.5.0): piper
        return jsonify({"error": "Not a free voice."}), 400
    problem = free_voice_problem(voice_id, None)   # CHANGED (1.5.0): a sample is in the voice's own language
    if problem:
        return jsonify({"error": problem}), 503
    # CHANGED (1.5.0): the sample is in the voice's own language.
    entry = next((e for e in piper_voice_entries() + windows_voice_entries() if e["voice_id"] == voice_id), None)
    code = (entry["languages"][0]["code"] if entry and entry["languages"] else "en")
    name = "preview-" + hashlib.sha1(voice_id.encode("utf-8")).hexdigest()[:16] + ".wav"
    path = os.path.join(AUDIO_DIR, name)
    if not os.path.isfile(path):
        try:
            made = free_tts_audio(FREE_SAMPLE_LINES.get(code, FREE_SAMPLE_LINES["en"]), voice_id, None)
            os.replace(os.path.join(AUDIO_DIR, made), path)
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    return send_from_directory(AUDIO_DIR, name)


# ElevenLabs reports the quota for the current billing period. The page
# polls this while it's open, so a short cache keeps a background poll and a
# post-reply refresh landing together from costing two upstream calls —
# without it being stale enough to matter.
# ---------- Daily usage ----------
# ElevenLabs reports usage for the billing period, which is the wrong unit
# for "am I overdoing it today". The subscription figure also can't be
# differenced reliably — other apps on the same key move it too — so what
# gets counted here is what THIS app actually sent, recorded per calendar
# day on the server so it survives a reload and reads the same on every
# device pointed at it.
#
# A plain dict of {"YYYY-MM-DD": credits} rather than a database: it's a
# handful of integers, and a file that can be read and corrected in a text
# editor is worth more here than anything cleverer.

USAGE_LOCK = threading.Lock()
USAGE_KEEP_DAYS = 90


def load_usage():
    if os.path.exists(USAGE_PATH):
        try:
            with open(USAGE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return {k: int(v) for k, v in data.items() if isinstance(v, (int, float))}
        except Exception:
            pass
    return {}


def usage_today_key():
    # Local server time: "today" means the day the person at the keyboard is
    # having, not UTC's.
    return time.strftime("%Y-%m-%d", time.localtime())


def record_usage(credits):
    """Add to today's total. Returns the new total for today."""
    credits = int(credits or 0)
    key = usage_today_key()
    with USAGE_LOCK:
        usage = load_usage()
        usage[key] = usage.get(key, 0) + max(0, credits)

        # Trim anything past the retention window, so the file can't grow
        # without bound on a long-running install.
        if len(usage) > USAGE_KEEP_DAYS:
            for old in sorted(usage.keys())[:-USAGE_KEEP_DAYS]:
                usage.pop(old, None)

        try:
            with open(USAGE_PATH, "w", encoding="utf-8") as f:
                json.dump(usage, f, indent=2, sort_keys=True)
        except Exception as e:
            log_server_event(f"Couldn't write usage.json: {e!r}")
        return usage[key]


def usage_today():
    with USAGE_LOCK:
        return load_usage().get(usage_today_key(), 0)


CREDITS_CACHE = {"data": None, "at": 0.0}
CREDITS_CACHE_SECONDS = 15
CREDITS_LOCK = threading.Lock()


@app.route("/api/credits")
def credits():
    if not CFG["elevenlabs_api_key"]:
        # No key still means a knowable answer for what this app spent — it
        # counted that itself.
        return jsonify({"error": "No ElevenLabs key set.", "used_today": usage_today()}), 400

    # Anything that just spent credits asks for a fresh read, since the
    # whole point of showing the number is watching it move.
    force = request.args.get("force") == "1"

    def cache_is_fresh():
        return (
            CREDITS_CACHE["data"]
            and time.time() - CREDITS_CACHE["at"] < CREDITS_CACHE_SECONDS
        )

    if not force and cache_is_fresh():
        return jsonify({**CREDITS_CACHE["data"], "used_today": usage_today(), "cached": True})

    # Serialize cache misses to avoid duplicate upstream requests.
    with CREDITS_LOCK:
        if not force and cache_is_fresh():
            return jsonify({**CREDITS_CACHE["data"], "used_today": usage_today(), "cached": True})

        try:
            resp = requests.get(
                "https://api.elevenlabs.io/v1/user/subscription",
                headers={"xi-api-key": CFG["elevenlabs_api_key"]},
                timeout=15,
            )
            resp.raise_for_status()
            sub = resp.json()
        except Exception as e:
            return jsonify({"error": str(e)}), 502

        used = int(sub.get("character_count") or 0)
        limit = int(sub.get("character_limit") or 0)
        data = {
            "used": used,
            "limit": limit,
            # Usage-based plans can exceed their included allowance.
            "remaining": max(0, limit - used),
            "over": max(0, used - limit),
            "tier": sub.get("tier", ""),
            "status": sub.get("status", ""),
            "reset_unix": sub.get("next_character_count_reset_unix"),
            "can_extend": bool(sub.get("can_extend_character_limit")),
            "cached": False,
        }
        CREDITS_CACHE["data"] = data
        CREDITS_CACHE["at"] = time.time()

    # Today's usage is read fresh for the response.
    return jsonify({**data, "used_today": usage_today()})


@app.route("/api/voice", methods=["POST"])
def set_active_voice():
    """
    Changes the voice in use right now, without touching anything else.

    Kept separate from form endpoints to update one value without overwriting
    other saved settings.

    With no profile_id this sets the default voice; with one it sets that
    profile's, which is what makes the voice switchable per profile from the
    main screen instead of only inside the profile editor.
    """
    data = request.get_json(force=True)
    voice_id = (data.get("voice_id") or "").strip()
    voice_name = (data.get("voice_name") or "").strip()
    profile_id = (data.get("profile_id") or "").strip()

    if not voice_id:
        return jsonify({"error": "No voice given."}), 400

    if not profile_id:
        CFG["voice_id"] = voice_id
        CFG["voice_name"] = voice_name
        save_config(CFG)
        return jsonify({"ok": True, "scope": "default"})

    with PROFILES_LOCK:
        all_profiles = load_profiles()
        match = next((p for p in all_profiles if p["id"] == profile_id), None)
        if not match:
            return jsonify({"error": "That profile no longer exists."}), 404
        match["voice_id"] = voice_id
        match["voice_name"] = voice_name
        save_profiles(all_profiles)

    return jsonify({"ok": True, "scope": "profile", "profile": match})


# =============================================================================
# FrivOSC — the VRChat bridge
# =============================================================================
# Frivo does not speak OSC. VRChat only ever sends and receives it on
# 127.0.0.1, so a server on another machine cannot take part; FrivOSC runs
# on the VRChat PC, where that loopback traffic already is, and talks to
# Frivo over HTTP instead.
#
# That leaves Frivo with the easy half. Outbound: queue text, and FrivOSC
# collects it. Inbound: FrivOSC reports the microphone. No ports, no
# addresses, no paging, no rate limits — all of that now lives on the side
# of the wire that can actually see VRChat.
#
# Everything here is in memory on purpose. A chatbox message that was not
# collected before a restart is stale by definition, and the mute state is
# only meaningful while a companion is connected to report it.

# Held briefly and only by FrivOSC, so a small queue is the right size. If
# it ever fills, the oldest go first: in a chatbox, a backlog nobody read
# is worth less than the line being said now.
FRIVOSC_OUTBOX_MAX = 20

# How long a report stays trustworthy. FrivOSC heartbeats every 5s, so
# three missed heartbeats means it is gone rather than quiet — and a
# crashed companion must not leave the UI believing the mic is live.
FRIVOSC_STALE_SECONDS = 15.0

FRIVOSC_STATE = {
    "connected_at": None,
    "last_seen": None,
    "version": "",
    "hostname": "",
    "muted": None,
    # NEW (typing): until when the browser last said you are responding.
    "typing_until": 0.0,
}

# NEW (typing): the browser re-says "typing" every couple of seconds while
# it is true. A page closed mid-sentence stops saying it, and the dots go
# away after this long rather than staying up over your head.
FRIVOSC_TYPING_HOLD = 4.0
FRIVOSC_OUTBOX = []
FRIVOSC_LOCK = threading.Lock()


def frivosc_touch(**fields):
    with FRIVOSC_LOCK:
        FRIVOSC_STATE["last_seen"] = time.time()
        FRIVOSC_STATE.update(fields)


def frivosc_status():
    """
    Connection state as the browser needs to reason about it.

    `muted` is None whenever there is nothing trustworthy to report — no
    companion, or one that has stopped heartbeating. That is deliberately
    not the same as False: reporting "unmuted" for a companion that died
    would have the UI enable dictation for a microphone it cannot see.
    """
    with FRIVOSC_LOCK:
        last_seen = FRIVOSC_STATE["last_seen"]
        fresh = last_seen is not None and (time.time() - last_seen) < FRIVOSC_STALE_SECONDS
        return {
            "connected": fresh,
            "version": FRIVOSC_STATE["version"] if fresh else "",
            "hostname": FRIVOSC_STATE["hostname"] if fresh else "",
            "last_seen": last_seen,
            "muted": FRIVOSC_STATE["muted"] if fresh else None,
        }


def frivosc_enqueue(text, speaking=True, unmute=False):
    """
    Queues work for FrivOSC to collect. Returns the message id.

    Text and unmute travel in the same queue because they are the same
    kind of thing — something to do on the VRChat PC, in order — and
    because an unmute is often wanted when the chatbox is switched off, so
    it cannot be a field on a chatbox message.
    """
    text = " ".join((text or "").split())
    if not text and not unmute:
        return None
    message = {
        "id": uuid.uuid4().hex,
        "text": text,
        "speaking": bool(speaking),
        "sfx": True,
        "unmute": bool(unmute),
        "queued_at": time.time(),
    }
    with FRIVOSC_LOCK:
        FRIVOSC_OUTBOX.append(message)
        while len(FRIVOSC_OUTBOX) > FRIVOSC_OUTBOX_MAX:
            FRIVOSC_OUTBOX.pop(0)
    return message["id"]


@app.route("/api/frivosc/hello", methods=["POST"])
def frivosc_hello():
    """First contact. Also what Setup's Test button calls to prove a route."""
    data = request.get_json(silent=True) or {}
    with FRIVOSC_LOCK:
        if FRIVOSC_STATE["connected_at"] is None:
            FRIVOSC_STATE["connected_at"] = time.time()
    frivosc_touch(
        version=str(data.get("version") or ""),
        hostname=str(data.get("hostname") or ""),
    )
    return jsonify({"ok": True, "server": APP_NAME, "poll_ms": 500})


@app.route("/api/frivosc/state", methods=["POST"])
def frivosc_state():
    """Mute state, sent on change and as a heartbeat."""
    data = request.get_json(silent=True) or {}
    muted = data.get("muted")
    frivosc_touch(muted=None if muted is None else bool(muted))
    return jsonify({"ok": True})


@app.route("/api/frivosc/outbox")
def frivosc_outbox():
    """
    Pending chatbox messages, handed over and cleared in one step.

    Polling this is also a heartbeat, so a companion that is connected but
    has heard nothing from VRChat yet still counts as present.
    """
    frivosc_touch()
    if not CFG.get("osc_enabled", False):
        # Switched off mid-session: drop anything already queued rather
        # than delivering it the moment it is switched back on.
        with FRIVOSC_LOCK:
            FRIVOSC_OUTBOX.clear()
        return jsonify({"messages": [], "enabled": False})
    with FRIVOSC_LOCK:
        messages = list(FRIVOSC_OUTBOX)
        FRIVOSC_OUTBOX.clear()
    # NEW (typing): carried on the reply FrivOSC already polls twice a
    # second, so the dots need no new connection. A FrivOSC from before
    # 1.2.0 ignores the field.
    return jsonify({"messages": messages, "enabled": True, "typing": frivosc_typing()})


def frivosc_typing():
    """NEW (typing): whether the dots should be up right now."""
    if not CFG.get("osc_enabled", False) or not CFG.get("osc_typing", True):
        return False
    with FRIVOSC_LOCK:
        return time.time() < FRIVOSC_STATE["typing_until"]


@app.route("/api/frivosc/typing", methods=["POST"])
def frivosc_typing_route():
    """
    NEW (typing): the browser saying whether you are responding. Sent when
    it changes and every couple of seconds while it is true; anything not
    refreshed for FRIVOSC_TYPING_HOLD seconds counts as stopped.
    """
    data = request.get_json(silent=True) or {}
    on = bool(data.get("typing"))
    with FRIVOSC_LOCK:
        FRIVOSC_STATE["typing_until"] = (time.time() + FRIVOSC_TYPING_HOLD) if on else 0.0
    return jsonify({"ok": True, "typing": frivosc_typing()})


@app.route("/api/frivosc/ack", methods=["POST"])
def frivosc_ack():
    """
    Acknowledgement that a message reached VRChat's chatbox.

    Nothing is retried on the strength of this — OSC is UDP and delivery
    was never observable. It exists so the page count can be reported back
    and so a companion that is working says so.
    """
    data = request.get_json(silent=True) or {}
    frivosc_touch()
    return jsonify({"ok": True, "id": data.get("id"), "pages": data.get("pages")})


@app.route("/api/frivosc/unmute", methods=["POST"])
def frivosc_unmute():
    """
    Asks FrivOSC to unmute the VRChat microphone, if it is muted.

    Only ever unmutes. There is no matching mute: VRChat exposes one
    virtual button rather than a settable state, and a bug that silences
    someone mid-conversation is far worse than one that fails to open
    their microphone.
    """
    if not CFG.get("osc_enabled", False):
        return jsonify({"error": "VRChat OSC is turned off in Settings."}), 400
    if not CFG.get("osc_unmute_on_send", False):
        return jsonify({"error": "Unmute on send is turned off."}), 400

    status = frivosc_status()
    if not status["connected"]:
        return jsonify({"error": "FrivOSC isn't connected."}), 503

    # Nothing to do, and saying so is more useful than queueing a no-op.
    if status["muted"] is False:
        return jsonify({"ok": True, "queued": False, "reason": "already unmuted"})

    message_id = frivosc_enqueue("", unmute=True)
    return jsonify({"ok": True, "queued": bool(message_id), "id": message_id})


@app.route("/api/frivosc/settings", methods=["POST"])
def frivosc_settings():
    """
    Saves just the OSC switches, on their own.

    These two live in the FrivOSC status panel in the sidebar, which has no
    Save button — Save belongs to the Settings sheet. Without this they
    flipped, were never persisted, and were then silently flipped back by
    the next status poll reading the unchanged value off the server. A
    switch that undoes itself a second later is worse than one that was
    never added.

    Deliberately not a partial POST to /api/settings. That would work
    today, but it handles thirty other fields, and a save that quietly
    depends on every one of them staying optional is a trap for later.
    """
    data = request.get_json(force=True) or {}
    for key in ("osc_enabled", "osc_mute_sync", "osc_unmute_on_send", "osc_typing"):   # CHANGED (typing)
        if key in data:
            CFG[key] = bool(data.get(key))
    save_config(CFG)
    return jsonify({
        "osc_enabled": bool(CFG.get("osc_enabled", False)),
        "osc_mute_sync": bool(CFG.get("osc_mute_sync", False)),
        "osc_unmute_on_send": bool(CFG.get("osc_unmute_on_send", False)),
        "osc_typing": bool(CFG.get("osc_typing", True)),   # NEW (typing)
    })


@app.route("/api/frivosc/status")
def frivosc_status_route():
    """Polled by the browser: is FrivOSC there, and what is the mic doing."""
    status = frivosc_status()
    status["enabled"] = bool(CFG.get("osc_enabled", False))
    status["mute_sync"] = bool(CFG.get("osc_mute_sync", False))
    status["unmute_on_send"] = bool(CFG.get("osc_unmute_on_send", False))
    status["typing_enabled"] = bool(CFG.get("osc_typing", True))   # NEW (typing)
    return jsonify(status)


@app.route("/api/osc/chatbox", methods=["POST"])
def osc_chatbox():
    """
    Kept at its original address so the front end did not have to change
    shape, but it now queues for FrivOSC instead of sending UDP itself.
    """
    if not CFG.get("osc_enabled", False):
        return jsonify({"error": "VRChat OSC is turned off in Settings."}), 400

    status = frivosc_status()
    if not status["connected"]:
        return jsonify({"error": "FrivOSC isn't connected. Start it on your VRChat PC."}), 503

    data = request.get_json(force=True)
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"error": "Nothing to send."}), 400

    message_id = frivosc_enqueue(text, speaking=bool(data.get("speaking")))
    if not message_id:
        return jsonify({"error": "Nothing to send."}), 400
    return jsonify({"ok": True, "id": message_id, "delivery": "queued"})


# ---------- Chatbox pages that follow the voice ----------
# NEW (1.5.0): FrivOSC pages a long message on a fixed 1.6-second timer,
# which is far quicker than anyone talks. A full page is about eight
# seconds of speech, so the chatbox raced ahead and the last page was up
# while the voice was still reading the first. A spoken reply is now paged
# here instead, and the page sends each one when the voice gets to it.
#
# FrivOSC doesn't need to change for this. A page is never longer than
# 144 characters, counter included, and FrivOSC passes on a message that
# fits exactly as it is, so every FrivOSC shows these pages as sent.

CHATBOX_LIMIT = 144

# Extra speaking time for a pause, as a number of characters' worth. Voices
# stop at the end of a sentence and slow down for a comma. Without this, a
# page full of short sentences was due before the voice got there.
CHATBOX_PAUSE_WEIGHTS = {".": 8, "!": 8, "?": 8, ",": 3, ";": 4, ":": 4}
_CHATBOX_COUNTER_RE = re.compile(r" \(\d+/\d+\)$")


# Copied unchanged from FrivOSC's chatbox_pages(), so a page Frivo makes
# here is one FrivOSC would have made itself.
def chatbox_pages(text, limit=CHATBOX_LIMIT):
    """
    Splits text into chatbox-sized pages, breaking at sentence ends where it
    can and word boundaries otherwise, so a page never ends mid-word.

    When there's more than one page each gets a " (1/3)" counter — without
    it a reader has no way to know the message they're looking at was the
    middle of something, since VRChat only ever shows the most recent one.
    """
    text = " ".join((text or "").split())
    if not text:
        return []
    if len(text) <= limit:
        return [text]

    def pack(budget):
        pages, current = [], ""
        # Two alternatives, not one: the first keeps end punctuation with
        # the sentence it closes, and the second catches a run of .!? that
        # isn't preceded by anything — a leading "!!!", or an ellipsis of
        # its own between two sentences. Without it the regex simply skips
        # over those characters and they vanish from the message.
        for sentence in re.findall(r"[^.!?]+[.!?]*|[.!?]+", text) or [text]:
            sentence = sentence.strip()
            while len(sentence) > budget:
                # One sentence longer than a whole page: break at the last
                # space that fits, or hard-cut if there isn't one.
                cut = sentence.rfind(" ", 0, budget + 1)
                if cut <= 0:
                    cut = budget
                if current:
                    pages.append(current)
                    current = ""
                pages.append(sentence[:cut].strip())
                sentence = sentence[cut:].strip()
            if not sentence:
                continue
            if not current:
                current = sentence
            elif len(current) + 1 + len(sentence) <= budget:
                current = f"{current} {sentence}"
            else:
                pages.append(current)
                current = sentence
        if current:
            pages.append(current)
        return pages

    pages = pack(limit)
    if len(pages) <= 1:
        return pages

    # Re-pack with room for the counter. Its width depends on the number of
    # pages, which depends on the packing — so pack, measure, pack again.
    # One pass is enough in practice; the loop guards the case where making
    # room for the suffix pushes the text into another page.
    #
    # The repacked list is adopted *before* the settled check, not after —
    # keeping the wider packing once the count happened to match is what
    # let a page come out at 150 characters with the counter attached.
    for _ in range(3):
        suffix = len(f" ({len(pages)}/{len(pages)})")
        repacked = pack(limit - suffix)
        settled = len(repacked) == len(pages)
        pages = repacked
        if settled:
            break
    total = len(pages)
    return [f"{p} ({i}/{total})" for i, p in enumerate(pages, 1)]


def _spoken_weight(text):
    return len(text) + sum(CHATBOX_PAUSE_WEIGHTS.get(ch, 0) for ch in text)


def chatbox_page_plan(text):
    """
    NEW (1.5.0): the reply as chatbox pages. Each page has a `start`, which
    is how far through the speech (0 to 1) the voice is when it reaches that
    page. The browser knows how long the audio really is and turns that
    into seconds.

    It's an estimate from the text: characters, plus a little for each
    pause. It's fixed at both ends (page 1 at the start, and nothing after
    the audio ends), so it can't drift by more than about a page.
    """
    pages = chatbox_pages(text)
    if len(pages) <= 1:
        return [{"text": p, "start": 0.0} for p in pages]
    weights = [_spoken_weight(_CHATBOX_COUNTER_RE.sub("", p)) for p in pages]
    total = float(sum(weights)) or 1.0
    plan, done = [], 0
    for page, weight in zip(pages, weights):
        plan.append({"text": page, "start": round(done / total, 4)})
        done += weight
    return plan


# ---------- Audio cache pruning ----------
# NEW (1.5.0): every spoken reply used to stay in audio_cache forever.
# Replies older than `audio_keep_days` are now deleted when Frivo starts
# and every six hours after that. Voice previews (preview-*.wav) are kept:
# there's one per voice, they're reused, and making one takes a while.

AUDIO_PRUNE_INTERVAL_SECONDS = 6 * 3600
# Windows-voice job files and page parts are deleted as soon as they're
# used. One that's left over is from a crash, so a day is plenty to keep it.
AUDIO_LEFTOVER_SECONDS = 24 * 3600
_AUDIO_REPLY_RE = re.compile(r"^[0-9a-f]{32}\.(mp3|wav)$")
# CHANGED (1.5.0): and the per-page parts a crashed Windows voice left.
_AUDIO_JOB_RE = re.compile(r"^[0-9a-f]{32}(\.json|-\d+\.part\.wav)$")


def prune_audio_cache(now=None):
    """Deletes old reply audio. Returns (files removed, bytes freed)."""
    try:
        keep_days = float(CFG.get("audio_keep_days", 7))
    except (TypeError, ValueError):
        keep_days = 7.0
    if keep_days <= 0:
        return 0, 0   # 0 means keep everything
    now = time.time() if now is None else now
    removed = freed = 0
    try:
        names = os.listdir(AUDIO_DIR)
    except OSError:
        return 0, 0
    for name in names:
        # Only names Frivo itself makes. Anything else in the folder is
        # left alone, whatever its age.
        if _AUDIO_REPLY_RE.match(name):
            cutoff = now - keep_days * 86400
        elif _AUDIO_JOB_RE.match(name):
            cutoff = now - AUDIO_LEFTOVER_SECONDS
        else:
            continue
        path = os.path.join(AUDIO_DIR, name)
        try:
            info = os.stat(path)
            if info.st_mtime >= cutoff:
                continue
            os.remove(path)
            removed += 1
            freed += info.st_size
        except OSError:
            continue
    if removed:
        log_server_event(f"Audio cache: deleted {removed} old file(s), {freed / 1048576:.1f} MB.")
    return removed, freed


def audio_prune_loop():
    while True:
        try:
            prune_audio_cache()
        except Exception as e:
            log_server_event(f"Audio cache: pruning failed: {e!r}")
        time.sleep(AUDIO_PRUNE_INTERVAL_SECONDS)


# ---------- Updates ----------
# NEW (updates): Frivo updates itself the way Clearspace does — it reads the
# releases on GitHub, offers a newer one, and installs it in one click; an
# earlier one can be installed the same way to go back.
#
# This half only decides and asks. Installing needs administrator rights,
# and the person clicking "Update now" is usually in a browser on another
# machine, so the work is done by the "Frivo Updater" scheduled task that
# setup registers (installer\Update-Frivo.ps1, running as SYSTEM). Frivo
# writes the wanted version to %ProgramData%\Frivo\Updates\request.json and
# starts the task; the task looks the version up on GitHub itself, checks
# the download's fingerprint, runs FrivoSetup.exe silently and reports in
# status.json. Update-Watch.ps1, started here as you, restarts Frivo after.
#
# What counts as an installable release, and how far back you may go, is
# decided here for what the page offers and again by the task for what it
# will actually run. Both read installer\update-policy.json and both are
# checked against the same sample in tests/fixtures/github-releases.json,
# so the two cannot quietly disagree.

UPDATE_TASK_NAME = "Frivo Updater"
UPDATE_FIRST_CHECK_SECONDS = 8
UPDATE_ACTIVE_STATES = ("starting", "checking", "downloading", "verifying", "installing")
# A request the task has not picked up in this long is reported as stuck.
UPDATE_PICKUP_SECONDS = 120

UPDATE_LOCK = threading.Lock()
UPDATE_WAKE = threading.Event()
UPDATE_STATE = {
    "releases": None,      # installable releases, newest first, from the last check
    "latest": None,        # the newest one when it is newer than this Frivo
    "checked_at": None,    # time.time() of the last check that reached GitHub
    "error": None,         # why the last check failed, if it did
    "pending": None,       # the install this server last asked for
    "support": None,       # (time, result) cache for update_support()
}

_VERSION_RE = re.compile(r"^[vV]?(\d{1,5})(?:\.(\d{1,5}))?(?:\.(\d{1,5}))?$")
_SHA256_RE = re.compile(r"^sha256:([0-9a-fA-F]{64})$")


def parse_version(text):
    """"v1.4.0", "1.4" and "V2.0.1" are versions; "nightly" is not.

    Always three parts, so 1.4 and 1.4.0 compare equal — the same rule as
    ConvertTo-FrivoVersion in Frivo.Update.psm1.
    """
    if not isinstance(text, str):
        return None
    match = _VERSION_RE.match(text.strip())
    if not match:
        return None
    return tuple(int(part) if part else 0 for part in match.groups())


def version_text(version):
    return "%d.%d.%d" % tuple(version)


def update_policy_path():
    """installer\\update-policy.json: beside app.py's installer folder when
    installed, one level up in the repository."""
    here = os.path.dirname(os.path.abspath(__file__))
    for candidate in (os.path.join(here, "installer", "update-policy.json"),
                      os.path.join(os.path.dirname(here), "installer", "update-policy.json")):
        if os.path.exists(candidate):
            return candidate
    return None


def load_update_policy(path=None):
    """The repository, installer name and oldest version to go back to.
    None when the file is missing or wrong — an updater that cannot say
    where updates come from must not guess."""
    path = path or update_policy_path()
    if not path:
        return None
    try:
        with open(path, "r", encoding="utf-8-sig") as handle:
            raw = json.load(handle)
    except (OSError, ValueError):
        return None
    repository = str(raw.get("repository") or "")
    asset = str(raw.get("asset") or "")
    oldest = parse_version(str(raw.get("oldest_rollback") or ""))
    if not re.match(r"^[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*$", repository):
        return None
    if not re.match(r"^[A-Za-z0-9][A-Za-z0-9_.-]*\.exe$", asset):
        return None
    if not oldest:
        return None
    try:
        hours = float(raw.get("check_hours", 6))
    except (TypeError, ValueError):
        hours = 6.0
    return {
        "repository": repository,
        "asset": asset,
        "oldest_rollback": oldest,
        "check_seconds": max(1.0, hours) * 3600,
        "releases_api": "https://api.github.com/repos/%s/releases?per_page=50" % repository,
        "releases_page": "https://github.com/%s/releases" % repository,
        "download_prefix": "https://github.com/%s/releases/download/" % repository,
    }


def parse_release(release, policy):
    """One release as GitHub describes it, or None when it is not something
    Frivo can install: a draft or pre-release, a tag that is not a version,
    or no installer from this repository. Mirrors ConvertFrom-FrivoRelease."""
    if not isinstance(release, dict):
        return None
    if release.get("draft") is True or release.get("prerelease") is True:
        return None
    tag = str(release.get("tag_name") or "")
    version = parse_version(tag)
    if not version:
        return None
    for asset in release.get("assets") or []:
        if not isinstance(asset, dict):
            continue
        if str(asset.get("name") or "").lower() != policy["asset"].lower():
            continue
        url = str(asset.get("browser_download_url") or "")
        if not url.lower().startswith(policy["download_prefix"].lower()):
            return None
        try:
            size = int(asset.get("size") or 0)
        except (TypeError, ValueError):
            size = 0
        digest = _SHA256_RE.match(str(asset.get("digest") or ""))
        page = str(release.get("html_url") or "")
        if not page.lower().startswith(policy["releases_page"].lower()):
            page = policy["releases_page"]
        return {
            "version": version_text(version),
            "tag": tag,
            "notes": str(release.get("body") or ""),
            "page_url": page,
            "download_url": url,
            "size": size,
            "sha256": digest.group(1).lower() if digest else None,
            "published": str(release.get("published_at") or ""),
        }
    return None


def parse_release_list(data, policy):
    """Installable releases, newest first, each version once."""
    found, seen = [], set()
    for release in data if isinstance(data, list) else []:
        info = parse_release(release, policy)
        if not info or info["version"] in seen:
            continue
        seen.add(info["version"])
        found.append(info)
    found.sort(key=lambda r: parse_version(r["version"]), reverse=True)
    return found


def fetch_releases(policy):
    response = requests.get(
        policy["releases_api"],
        headers={"User-Agent": "Frivo/%s" % APP_VERSION, "Accept": "application/vnd.github+json"},
        timeout=20,
    )
    if response.status_code == 404:
        return []   # nothing released yet
    response.raise_for_status()
    return parse_release_list(response.json(), policy)


def earlier_releases(releases, current, policy):
    """Older than this Frivo, but not older than the oldest version that can
    update itself — going further back would leave no way back up."""
    floor = policy["oldest_rollback"]
    return [r for r in releases
            if floor <= parse_version(r["version"]) < current]


def check_install_target(releases, wanted, current, policy):
    """The release to install, or raises ValueError with a reason someone
    can act on. Same rules, in the same order, as Select-FrivoUpdateTarget
    with -RequireFingerprint — which the task applies again regardless."""
    match = next((r for r in releases if r["version"] == version_text(wanted)), None)
    if not match:
        raise ValueError("Frivo %s is not a release on GitHub that has %s attached."
                         % (version_text(wanted), policy["asset"]))
    if wanted == current:
        raise ValueError("Frivo %s is already installed." % version_text(wanted))
    if wanted < policy["oldest_rollback"]:
        raise ValueError("Frivo %s is older than %s, the oldest version that can update "
                         "itself, so it cannot be installed from here."
                         % (version_text(wanted), version_text(policy["oldest_rollback"])))
    if not match["sha256"]:
        raise ValueError("GitHub publishes no SHA-256 fingerprint for %s in Frivo %s, so it "
                         "cannot be checked and will not be installed."
                         % (policy["asset"], version_text(wanted)))
    return match


def update_folder():
    root = os.environ.get("ProgramData") or r"C:\ProgramData"
    return os.path.join(root, "Frivo", "Updates")


def _installer_dir():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "installer")


def _hidden_run(args, timeout=15):
    flags = 0x08000000 if os.name == "nt" else 0   # CREATE_NO_WINDOW
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout, creationflags=flags)


def update_support(refresh=False):
    """Can this copy install updates, and how.

      task      the "Frivo Updater" task exists: no prompt, works from any device
      elevate   no task (setup could not register it): Windows asks for
                permission on the PC Frivo runs on, each time

    Cached for a minute — it costs a schtasks call.
    """
    with UPDATE_LOCK:
        cached = UPDATE_STATE["support"]
    if cached and not refresh and time.time() - cached[0] < 60:
        return cached[1]

    here = os.path.dirname(os.path.abspath(__file__))
    if os.name != "nt":
        result = {"ok": False, "mode": None,
                  "reason": "Frivo installs updates on Windows only."}
    elif not os.path.exists(os.path.join(here, ".frivo-install.json")):
        result = {"ok": False, "mode": None,
                  "reason": "This copy of Frivo runs from its source folder, so it can't "
                            "update itself. Install it with FrivoSetup.exe for in-app updates."}
    elif not os.path.exists(os.path.join(_installer_dir(), "Update-Frivo.ps1")):
        result = {"ok": False, "mode": None,
                  "reason": "The updater is missing from this install. Run FrivoSetup.exe "
                            "once to repair it."}
    else:
        try:
            found = _hidden_run(["schtasks", "/query", "/tn", UPDATE_TASK_NAME]).returncode == 0
        except Exception:
            found = False
        if found:
            result = {"ok": True, "mode": "task", "reason": ""}
        else:
            result = {"ok": True, "mode": "elevate",
                      "reason": "Windows will ask for administrator permission on the PC "
                                "Frivo runs on. Run FrivoSetup.exe once to stop it asking."}
    with UPDATE_LOCK:
        UPDATE_STATE["support"] = (time.time(), result)
    return result


def read_update_job():
    """status.json, as the task last wrote it. None when there is none."""
    try:
        with open(os.path.join(update_folder(), "status.json"), "r", encoding="utf-8-sig") as handle:
            job = json.load(handle)
        return job if isinstance(job, dict) else None
    except (OSError, ValueError):
        return None


def check_for_updates():
    """Asks GitHub. Never raises: a failed check is recorded, not thrown —
    being offline is not news."""
    policy = load_update_policy()
    if not policy:
        with UPDATE_LOCK:
            UPDATE_STATE["error"] = "The update policy file is missing from this copy of Frivo."
        return
    current = parse_version(APP_VERSION) or (0, 0, 0)
    try:
        releases = fetch_releases(policy)
    except Exception as exc:
        log_server_event("update check failed: %r" % (exc,))
        with UPDATE_LOCK:
            UPDATE_STATE["error"] = "GitHub couldn't be reached to look for a newer version."
        return
    newest = releases[0] if releases else None
    with UPDATE_LOCK:
        UPDATE_STATE["releases"] = releases
        UPDATE_STATE["latest"] = (newest if newest and parse_version(newest["version"]) > current
                                  else None)
        UPDATE_STATE["checked_at"] = time.time()
        UPDATE_STATE["error"] = None


def _public_release(r):
    if not r:
        return None
    return {k: r[k] for k in ("version", "notes", "page_url", "size", "published")} | {
        "verifiable": bool(r.get("sha256"))}


def update_payload():
    policy = load_update_policy()
    with UPDATE_LOCK:
        latest = UPDATE_STATE["latest"]
        checked_at = UPDATE_STATE["checked_at"]
        error = UPDATE_STATE["error"]
        pending = dict(UPDATE_STATE["pending"]) if UPDATE_STATE["pending"] else None
    skipped = str(CFG.get("update_skipped") or "")
    notify = latest if latest and latest["version"] != skipped else None
    return {
        "current": APP_VERSION,
        "latest": _public_release(latest),
        "notify": _public_release(notify),
        "checked_at": checked_at,
        "error": error,
        "auto_check": bool(CFG.get("update_auto_check", True)),
        "skipped": skipped,
        "oldest_rollback": version_text(policy["oldest_rollback"]) if policy else None,
        "releases_page": policy["releases_page"] if policy else None,
        "support": update_support(),
        "job": update_job_view(pending),
    }


def update_job_view(pending=None):
    """What the browser shows while an install it asked for runs: the task's
    own status once it has picked the request up, "queued" before that."""
    if pending is None:
        with UPDATE_LOCK:
            pending = dict(UPDATE_STATE["pending"]) if UPDATE_STATE["pending"] else None
    if not pending:
        return None
    job = read_update_job()
    if job and job.get("id") == pending["id"]:
        view = {k: job.get(k) for k in ("state", "message", "version", "from", "kind",
                                        "received", "total", "restart")}
    else:
        waited = time.time() - pending["requested_at"]
        if pending.get("error"):
            view = {"state": "failed", "message": pending["error"], "restart": False}
        elif waited > UPDATE_PICKUP_SECONDS:
            view = {"state": "failed", "restart": False,
                    "message": "The updater did not start. Check that the \"%s\" task exists "
                               "in Task Scheduler, or run FrivoSetup.exe once to set it up."
                               % UPDATE_TASK_NAME}
        else:
            view = {"state": "queued", "message": "Starting the updater.", "restart": False}
    view["id"] = pending["id"]
    view["target"] = pending["version"]
    view["mode"] = pending["mode"]
    return view


def _spawn_update_watcher(request_id):
    """Update-Watch.ps1, detached, as you: it starts Frivo again after setup
    has stopped it. Detached, so it outlives this process — which is exactly
    what setup is about to end."""
    root = os.environ.get("SystemRoot") or r"C:\Windows"
    powershell = os.path.join(root, "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
    args = [powershell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden",
            "-File", os.path.join(_installer_dir(), "Update-Watch.ps1"), "-RequestId", request_id]
    # CHANGED (restart): a hidden console (CREATE_NO_WINDOW), not none at all
    # (DETACHED_PROCESS). Windows PowerShell is a console program, and started
    # with no console it is not something to rely on. Either way the watcher
    # outlives this process: Windows does not end children with their parent.
    no_window, new_group, breakaway = 0x08000000, 0x00000200, 0x01000000
    for flags in (no_window | new_group | breakaway, no_window | new_group):
        try:
            subprocess.Popen(args, creationflags=flags, close_fds=True, cwd=root,
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
            return
        except OSError:
            continue   # not allowed to break away from a job; try without


def _start_update_task(mode):
    """Starts the updater. Returns None, or why it could not be started.

    The task route needs nothing from anyone. When the task cannot be
    started (missing, or this account was not allowed to), Windows is asked
    to run the updater elevated instead — which shows a permission prompt
    on this PC, so it is only the fallback.
    """
    if mode == "task":
        try:
            if _hidden_run(["schtasks", "/run", "/tn", UPDATE_TASK_NAME]).returncode == 0:
                return None
        except Exception:
            pass
    try:
        import ctypes

        root = os.environ.get("SystemRoot") or r"C:\Windows"
        powershell = os.path.join(root, "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
        params = ('-NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File "%s"'
                  % os.path.join(_installer_dir(), "Update-Frivo.ps1"))
        # Returns once the prompt is answered: above 32 means it started.
        code = ctypes.windll.shell32.ShellExecuteW(None, "runas", powershell, params,
                                                   _installer_dir(), 0)
        if code > 32:
            return None
        return "Windows did not give the updater permission to run."
    except Exception as exc:
        return "The updater could not be started: %s" % (exc,)


def _write_update_request(request_id, version):
    """request.json, written whole and then moved into place, so the task
    never reads half of one."""
    folder = update_folder()
    target = os.path.join(folder, "request.json")
    temp = os.path.join(folder, ".request-%s.tmp" % request_id)
    with open(temp, "w", encoding="utf-8") as handle:
        json.dump({"id": request_id, "version": version,
                   "requested_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}, handle)
    os.replace(temp, target)


def update_checker_loop():
    """The automatic check: a few seconds after Frivo starts, then every
    check_hours (6) while it runs, unless switched off in Settings. Quiet
    on purpose — a newer version only shows as a chip in the sidebar."""
    if UPDATE_WAKE.wait(UPDATE_FIRST_CHECK_SECONDS):
        UPDATE_WAKE.clear()
    while True:
        policy = load_update_policy()
        if CFG.get("update_auto_check", True):
            check_for_updates()
        interval = policy["check_seconds"] if policy else 6 * 3600
        if UPDATE_WAKE.wait(interval):
            UPDATE_WAKE.clear()


def start_update_checker():
    threading.Thread(target=update_checker_loop, name="update-check", daemon=True).start()


@app.route("/api/updates")
def updates_status():
    return jsonify(update_payload())


@app.route("/api/updates/check", methods=["POST"])
def updates_check():
    """Settings > Check for updates: checks now and answers with what it found."""
    check_for_updates()
    return jsonify(update_payload())


@app.route("/api/updates/earlier")
def updates_earlier():
    """The releases you can go back to, newest first. Asks GitHub when the
    last check is more than ten minutes old."""
    policy = load_update_policy()
    if not policy:
        return jsonify({"error": "The update policy file is missing from this copy of Frivo."}), 500
    with UPDATE_LOCK:
        releases = UPDATE_STATE["releases"]
        checked_at = UPDATE_STATE["checked_at"] or 0
    if releases is None or time.time() - checked_at > 600:
        check_for_updates()
        with UPDATE_LOCK:
            releases = UPDATE_STATE["releases"]
            error = UPDATE_STATE["error"]
        if releases is None:
            return jsonify({"error": error or "GitHub couldn't be reached."}), 502
    current = parse_version(APP_VERSION) or (0, 0, 0)
    return jsonify({
        "current": APP_VERSION,
        "oldest_rollback": version_text(policy["oldest_rollback"]),
        "releases": [_public_release(r) for r in earlier_releases(releases, current, policy)],
    })


@app.route("/api/updates/settings", methods=["POST"])
def updates_settings():
    """Saves itself, like the FrivOSC switches: these controls do not wait
    for the Settings sheet's Save button. Touches only its own two keys."""
    data = request.get_json(silent=True) or {}
    if "auto_check" in data:
        CFG["update_auto_check"] = bool(data.get("auto_check"))
        if CFG["update_auto_check"]:
            UPDATE_WAKE.set()   # check now rather than in up to six hours
    if "skip" in data:
        skip = parse_version(str(data.get("skip") or ""))
        CFG["update_skipped"] = version_text(skip) if skip else ""
    save_config(CFG)
    return jsonify(update_payload())


@app.route("/api/updates/install", methods=["POST"])
def updates_install():
    """Install a release: newer to update, older (not below
    oldest_rollback) to go back. Answers as soon as the updater is asked;
    the browser follows along through /api/updates/job."""
    data = request.get_json(silent=True) or {}
    wanted = parse_version(str(data.get("version") or ""))
    if not wanted:
        return jsonify({"error": "Choose a version to install."}), 400

    support = update_support(refresh=True)
    if not support["ok"]:
        return jsonify({"error": support["reason"]}), 409

    policy = load_update_policy()
    if not policy:
        return jsonify({"error": "The update policy file is missing from this copy of Frivo."}), 500

    # Looked up fresh rather than from the last automatic check: a release
    # can be edited or deleted on GitHub in six hours.
    try:
        releases = fetch_releases(policy)
    except Exception:
        return jsonify({"error": "GitHub couldn't be reached. Check the internet connection on "
                                 "the PC Frivo runs on, and try again."}), 502
    current = parse_version(APP_VERSION) or (0, 0, 0)
    try:
        release = check_install_target(releases, wanted, current, policy)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 409

    with UPDATE_LOCK:
        pending = UPDATE_STATE["pending"]
    if pending:
        view = update_job_view(pending)
        if view and view.get("state") in UPDATE_ACTIVE_STATES + ("queued",):
            return jsonify({"error": "An update is already running."}), 409

    request_id = uuid.uuid4().hex
    try:
        _write_update_request(request_id, release["version"])
    except OSError as exc:
        log_server_event("update request could not be written: %r" % (exc,))
        return jsonify({"error": "Frivo couldn't hand the request to the updater. Run "
                                 "FrivoSetup.exe once to repair the update folder."}), 500

    kind = "update" if wanted > current else "rollback"
    with UPDATE_LOCK:
        UPDATE_STATE["pending"] = {"id": request_id, "version": release["version"], "kind": kind,
                                   "mode": support["mode"], "requested_at": time.time(),
                                   "error": None}
    log_server_event("%s to %s requested (%s)" % (kind, release["version"], support["mode"]))

    _spawn_update_watcher(request_id)

    def start():
        problem = _start_update_task(support["mode"])
        if problem:
            log_server_event("updater did not start: " + problem)
            with UPDATE_LOCK:
                if UPDATE_STATE["pending"] and UPDATE_STATE["pending"]["id"] == request_id:
                    UPDATE_STATE["pending"]["error"] = problem

    # The elevated route waits on a permission prompt; the request must not.
    threading.Thread(target=start, name="update-start", daemon=True).start()
    return jsonify({"ok": True, "id": request_id, "version": release["version"], "kind": kind,
                    "mode": support["mode"]})


@app.route("/api/updates/job")
def updates_job():
    """Polled while an install runs. Small on purpose, and answers "which
    version is running" — the page knows the update landed when this says
    the version it asked for."""
    return jsonify({"current": APP_VERSION, "job": update_job_view()})


@app.route("/api/profiles", methods=["GET", "POST"])
def profiles():
    if request.method == "GET":
        return jsonify({"profiles": load_profiles()})

    data = request.get_json(force=True)
    name = (data.get("name") or "").strip()
    voice_id = (data.get("voice_id") or "").strip()
    voice_name = (data.get("voice_name") or "").strip()
    # No longer required — a blank personality falls back to the selected
    # preset at reply time.
    system_prompt = (data.get("system_prompt") or "").strip()
    response_style = normalize_response_style(data.get("response_style"), DEFAULT_RESPONSE_STYLE)
    personality_preset = normalize_personality_preset(data.get("personality_preset"), DEFAULT_PERSONALITY_PRESET)
    # A suggestion, not a rule: the app offers it as one click rather than
    # switching languages behind your back when you pick a profile.
    language = normalize_language(data.get("language")) or ""
    # NEW (1.5.0)
    follow_length = normalize_follow_length(data.get("follow_length"), response_style)
    # NEW (1.5.0)
    expressive_voice = data.get("expressive_voice") is True
    voice_delivery = normalize_voice_delivery(data.get("voice_delivery"))
    tag_shaping = data.get("tag_shaping") is True   # NEW (1.5.0)
    tag_amount = normalize_tag_amount(data.get("tag_amount"))   # NEW (1.5.0)

    if not name or not voice_id:
        return jsonify({"error": "Name and voice are both required."}), 400

    with PROFILES_LOCK:
        all_profiles = load_profiles()
        new_profile = {
            "id": uuid.uuid4().hex,
            "name": name,
            "voice_id": voice_id,
            "voice_name": voice_name,
            "system_prompt": system_prompt,
            "response_style": response_style,
            "personality_preset": personality_preset,
            "language": language,
            "follow_length": follow_length,  # NEW (1.5.0)
            "expressive_voice": expressive_voice,  # NEW (1.5.0)
            "voice_delivery": voice_delivery,      # NEW (1.5.0)
            "tag_shaping": tag_shaping,            # NEW (1.5.0)
            "tag_amount": tag_amount,              # NEW (1.5.0)
        }
        all_profiles.append(new_profile)
        save_profiles(all_profiles)

    return jsonify({"profile": new_profile})


@app.route("/api/profiles/<profile_id>", methods=["PUT", "DELETE"])
def profile_detail(profile_id):
    with PROFILES_LOCK:
        all_profiles = load_profiles()
        match = next((p for p in all_profiles if p["id"] == profile_id), None)
        if not match:
            return jsonify({"error": "That profile no longer exists."}), 404

        if request.method == "DELETE":
            all_profiles = [p for p in all_profiles if p["id"] != profile_id]
            save_profiles(all_profiles)
            with SESSIONS_LOCK:
                for key in list(SESSIONS.keys()):
                    if key.endswith(f"::{profile_id}"):
                        del SESSIONS[key]
            return jsonify({"ok": True})

        data = request.get_json(force=True)
        match["name"] = (data.get("name") or match["name"]).strip()
        match["voice_id"] = (data.get("voice_id") or match["voice_id"]).strip()
        match["voice_name"] = (data.get("voice_name") or match.get("voice_name", "")).strip()
        # Checked with "in data" rather than truthiness, so sending an empty
        # string actually clears it back to "use the preset" instead of being
        # silently ignored.
        if "system_prompt" in data:
            match["system_prompt"] = (data.get("system_prompt") or "").strip()
        if "response_style" in data:
            match["response_style"] = normalize_response_style(
                data.get("response_style"), match.get("response_style", DEFAULT_RESPONSE_STYLE)
            )
        # NEW (1.5.0)
        if "follow_length" in data:
            match["follow_length"] = normalize_follow_length(
                data.get("follow_length"), match.get("response_style", DEFAULT_RESPONSE_STYLE)
            )
        if "personality_preset" in data:
            match["personality_preset"] = normalize_personality_preset(
                data.get("personality_preset"), match.get("personality_preset", DEFAULT_PERSONALITY_PRESET)
            )
        # NEW (1.5.0)
        if "expressive_voice" in data:
            match["expressive_voice"] = data.get("expressive_voice") is True
        if "tag_shaping" in data:   # NEW (1.5.0)
            match["tag_shaping"] = data.get("tag_shaping") is True
        if "tag_amount" in data:    # NEW (1.5.0)
            match["tag_amount"] = normalize_tag_amount(data.get("tag_amount"))
        if "voice_delivery" in data:
            match["voice_delivery"] = normalize_voice_delivery(
                data.get("voice_delivery"), match.get("voice_delivery", DEFAULT_VOICE_DELIVERY))
        # Same "in data" treatment as the personality text: sending "" has
        # to be able to clear the recommendation, not be ignored as falsy.
        # An unrecognised name is a different case though — that's garbage
        # rather than intent, and dropping the existing setting on the
        # strength of it would lose a choice the user did make.
        if "language" in data:
            raw = (data.get("language") or "").strip()
            if not raw:
                match["language"] = ""
            else:
                match["language"] = normalize_language(raw) or match.get("language", "")
        save_profiles(all_profiles)
        return jsonify({"profile": match})


@app.route("/api/preview-prompt")
def preview_prompt():
    """
    Shows exactly what gets sent to the model as the system message, split
    into your own personality text and the length/formatting rules the app
    appends to it. Nothing here is hidden from you.
    """
    profile_id = request.args.get("profile_id") or None
    max_words = clamp_words(request.args.get("max_words"), CFG.get("max_words", 80))
    language = normalize_language(request.args.get("language")) or CFG.get("language", "English")

    if profile_id:
        profile = next((p for p in load_profiles() if p["id"] == profile_id), None)
        if not profile:
            return jsonify({"error": "That profile no longer exists."}), 400
        raw_prompt = profile.get("system_prompt", "")
        personality_preset = profile.get("personality_preset", DEFAULT_PERSONALITY_PRESET)
        response_style = normalize_response_style(profile.get("response_style"), DEFAULT_RESPONSE_STYLE)
        source = profile["name"]
        preview_voice = profile.get("voice_id", "")   # NEW (1.5.0)
    else:
        preview_voice = CFG.get("voice_id", "")       # NEW (1.5.0)
        raw_prompt = CFG.get("system_prompt", "")
        personality_preset = CFG.get("personality_preset", DEFAULT_PERSONALITY_PRESET)
        response_style = normalize_response_style(CFG.get("response_style"), DEFAULT_RESPONSE_STYLE)
        source = "Default (Settings)"

    # NEW (1.5.0): match chat() — Response with "Follow reply length" off
    # has no limit.
    follow_raw = (profile.get("follow_length") if profile_id else CFG.get("follow_length"))
    if response_style == "reply" and not normalize_follow_length(follow_raw, response_style):
        max_words = MAX_WORDS

    base_prompt = resolve_personality_text(raw_prompt, personality_preset)
    # NEW (1.5.0): with the voice rules chat() would add.
    full = build_system_prompt(base_prompt, max_words, language, response_style,
                               voice_style=(voice_style_of(profile if profile_id else None)
                                            if tts_engine(preview_voice) == "elevenlabs" else None))

    # CHANGED (1.5.0): Mimic replaces whatever personality text was resolved
    # above (see build_system_prompt) — mirror that here, so "your_prompt"
    # and the marker used to isolate "appended" both match what's actually
    # in `full`.
    displayed_prompt = MIMIC_PROFILE_TEXT if response_style == "mimic" else base_prompt

    # Isolate what the app added by removing the exact "PROFILE:\n...\n\n"
    # block the personality text was inserted into, rather than assuming
    # displayed_prompt sits at the front of the string.
    # CHANGED (1.5.0): the block's heading differs by style ("PROFILE:" or
    # "PROFILE (personality — ...):"), so it's matched rather than spelled out.
    profile_marker = re.search(r"PROFILE[^\n]*:\n" + re.escape(displayed_prompt) + r"\n\n", full)
    if profile_marker:
        appended = (full[: profile_marker.start()] + full[profile_marker.end():]).strip("\n")
    else:
        appended = full

    if response_style == "mimic":
        personality_source = (
            "Word for word — nothing is sent to the model in English"
            if language == "English"
            else "Word for word — personality ignored, literal translation only"
        )
    elif raw_prompt.strip():
        personality_source = "Your custom text"
    else:
        preset = PERSONALITY_PRESET_MAP.get(personality_preset, PERSONALITY_PRESET_MAP[DEFAULT_PERSONALITY_PRESET])
        personality_source = f"Preset: {preset['name']}"

    key = f"{request.args.get('session_id') or 'default'}::{profile_id or 'default'}"
    with SESSIONS_LOCK:
        turns = max(0, len(SESSIONS.get(key, [])) - 1)

    return jsonify(
        {
            "source": source,
            "your_prompt": displayed_prompt,
            "appended": appended,
            "full": full,
            "target_words": max_words,
            "language": language,
            "response_style": response_style,
            "personality_source": personality_source,
            "history_turns": turns,
            "model": CFG.get("model", RECOMMENDED_TEXT_MODEL),
        }
    )


# ---------- Ollama: three models to switch between ----------
# NEW (1.5.0): Fast, Balanced and Best. Only the one in use is kept loaded:
# switching unloads the others, so the graphics card has room for it (and for
# Evora, if it shares the card), and loads the new one straight away, so the
# next reply doesn't wait for it.

def _ollama_get(path):
    response = requests.get(f"{ollama_base_url()}{path}", timeout=LOCAL_CONNECT_TIMEOUT)
    response.raise_for_status()
    return response.json()


def _ollama_set_loaded(model, keep):
    """Loads (keep=True) or unloads a model, without asking it anything."""
    requests.post(f"{ollama_base_url()}/api/generate",
                  json={"model": model, "keep_alive": ollama_keep_alive() if keep else 0},   # CHANGED (1.5.0)
                  timeout=(LOCAL_CONNECT_TIMEOUT, LOCAL_READ_TIMEOUT))


def apply_ollama_idle_timer(wait=0):
    """
    NEW (1.5.0): gives whatever Ollama has loaded the idle time from
    Settings, straight away. Ollama sets a model's timer on each request, so
    a model loaded before an update (or before the setting changed) would
    otherwise keep its old timer, "forever" included, until the next reply.
    Only touches models that are already loaded: nothing is loaded by this.
    """
    if wait:
        time.sleep(wait)
    try:
        uses_ollama, _ = gpu_watch_targets()
        if not uses_ollama:
            return
        loaded = _ollama_get("/api/ps").get("models") or []
        for model in loaded:
            name = model.get("name") or model.get("model")
            if name:
                _ollama_set_loaded(name, keep=True)
    except Exception as e:
        log_server_event(f"Ollama idle timer: {e!r}")


def apply_evora_idle_timers(wait=0):
    """
    NEW (1.5.0): gives Evora the idle timers from Settings. Evora keeps them
    itself too, so it works the same without Frivo. Quiet when Evora isn't
    in use, isn't running, or is too old to have them.
    """
    if wait:
        time.sleep(wait)
    try:
        _, uses_evora = gpu_watch_targets()
        if not uses_evora:
            return
        listen = EVORA_IDLE_LISTEN.get(CFG.get("evora_idle_listen"), EVORA_IDLE_LISTEN[DEFAULT_EVORA_IDLE_LISTEN])
        speech = EVORA_IDLE_SPEECH.get(CFG.get("evora_idle_speech"), EVORA_IDLE_SPEECH[DEFAULT_EVORA_IDLE_SPEECH])
        response = requests.post(f"{whisper_base_url()}/idle", json={"listen_minutes": listen, "speech_minutes": speech},
                                 timeout=(LOCAL_CONNECT_TIMEOUT, 4))
        if response.status_code == 404:
            log_server_event("Evora idle timers: this Evora is too old to have them (update Evora)")
    except Exception as e:
        log_server_event(f"Evora idle timers: {e!r}")


def _same_model(a, b):
    """'gemma3:4b' and 'gemma3:4b', or 'llama3.1' and 'llama3.1:latest'."""
    norm = lambda name: name if ":" in name else name + ":latest"
    return norm(a or "") == norm(b or "")


def match_installed_model(name, installed):
    """
    NEW (1.5.0): (full name, suggestions) for a model name typed in Settings.
    A community model is "owner/model:tag" (huihui_ai/qwen3.5-abliterated:9b);
    typed without its owner it's found anyway when only one installed model
    fits. Typed as just the owner ("huihui_ai"), the owner's models are
    offered instead.
    """
    name = (name or "").strip()
    if not name:
        return None, []
    for m in installed:
        if _same_model(name, m):
            return m, []
    short = [m for m in installed if "/" in m and _same_model(name, m.split("/", 1)[1])]
    if len(short) == 1:
        return short[0], []
    owner = name.rstrip("/").lower()
    by_owner = [m for m in installed if m.lower().startswith(owner + "/")]
    base = name.split(":")[0].split("/")[-1].lower()
    similar = [m for m in installed if base and base in m.lower()]
    suggestions = list(dict.fromkeys(short + by_owner + similar))[:3]
    return None, suggestions


def fix_tier_model_names(installed):
    """NEW (1.5.0): a name typed without its owner is saved in full, once found."""
    changed = False
    for tier, key in OLLAMA_TIER_KEYS.items():
        typed = (CFG.get(key) or "").strip()
        full, _ = match_installed_model(typed, installed)
        if full and full != typed and not _same_model(full, typed):
            CFG[key] = full
            changed = True
            log_server_event(f"Ollama: '{typed}' is installed as '{full}'; {tier.title()} now uses the full name")
    if changed:
        try:
            save_config(CFG)
        except Exception:
            pass
    return changed


def ollama_tier_status():
    tiers = [{"id": t, "name": name, "model": tier_model(t)} for t, name in OLLAMA_TIERS]
    status = {"tier": ollama_tier(), "tiers": tiers, "reachable": False, "error": "",
              "chat_provider": resolve_provider("chat_provider", CHAT_PROVIDERS)}
    try:
        installed = [m.get("name", "") for m in (_ollama_get("/api/tags").get("models") or [])]
        loaded = _ollama_get("/api/ps").get("models") or []
        status["reachable"] = True
    except Exception as e:
        status["error"] = f"Ollama isn't reachable at {ollama_base_url()}."
        log_server_event(f"Ollama status: {e!r}")
        return status
    # NEW (1.5.0): "qwen3.5-abliterated:9b" typed for "huihui_ai/qwen3.5-abliterated:9b".
    if fix_tier_model_names(installed):
        for tier in tiers:
            tier["model"] = tier_model(tier["id"])
    for tier in tiers:
        tier["installed"] = any(_same_model(tier["model"], m) for m in installed)
        if not tier["installed"]:
            tier["suggest"] = match_installed_model(tier["model"], installed)[1]   # NEW (1.5.0)
        running = next((m for m in loaded if _same_model(tier["model"], m.get("name"))), None)
        tier["loaded"] = bool(running)
        if running and running.get("size"):
            # How much of it is on the graphics card. Under 100 means part
            # runs on the CPU, which is slower.
            tier["gpu_percent"] = round(100 * (running.get("size_vram") or 0) / running["size"])
    return status


# ---------------------------------------------------------------------------
# NEW (1.5.0): managing the models on the Ollama PC, from Settings > Ollama.
#
#   * What's installed (from Ollama), how big, which tier uses it, and
#     whether it's loaded. Removing one asks Ollama to delete it.
#   * Downloading: Ollama pulls it; Frivo follows the progress (and can stop
#     it). Several can run at once.
#   * Suggestions: a short list Frivo keeps (everyday, uncensored, small),
#     with each one's real download size from Ollama's library, and whether
#     it fits the graphics card (from Evora's card report) next to Evora.
#   * The drive: Ollama doesn't say how much space is left. Evora can, when
#     it runs on the same PC as Ollama (GET /disk).
# ---------------------------------------------------------------------------

OLLAMA_MODEL_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-/:]{0,159}$")
OLLAMA_REGISTRY = "https://registry.ollama.ai/v2"
OLLAMA_SUGGESTIONS = [
    # (group, name, what it's like)
    ("Everyday", "qwen3.5:4b", "Quick and capable. A good Balanced."),
    ("Everyday", "qwen3.5:9b", "Better replies; needs most of an 8 GB card."),
    ("Everyday", "gemma3:4b", "Quick and friendly. A good Fast."),
    ("Everyday", "llama3.1:8b", "A solid all-rounder."),
    ("Uncensored", "huihui_ai/qwen3.5-abliterated:4b", "Qwen 3.5 4B without the refusals."),
    ("Uncensored", "huihui_ai/qwen3.5-abliterated:9b", "Qwen 3.5 9B without the refusals."),
    ("Uncensored", "huihui_ai/gemma-4-abliterated:e4b", "Gemma 4 (small) without the refusals."),
    ("Uncensored", "hermes3:8b", "Stays in character; follows the personality closely."),
    ("Uncensored", "dolphin3:8b", "Follows the system prompt without moralising."),
    ("Uncensored", "mannix/llama3.1-8b-abliterated", "Llama 3.1 8B without the refusals."),
    ("Small and fast", "qwen3.5:2b", "Very quick; simple replies."),
    ("Small and fast", "llama3.2:3b", "Quick, light on memory."),
    ("Small and fast", "gemma3:1b", "The lightest; for the quickest tags and short replies."),
]
OLLAMA_SIZE_CACHE = {}          # name -> (when, bytes or None)
OLLAMA_SIZE_TTL = 6 * 3600
OLLAMA_PULLS = {}               # name -> progress
OLLAMA_PULLS_LOCK = threading.Lock()


def valid_model_name(name):
    name = (name or "").strip()
    return name if OLLAMA_MODEL_NAME_RE.match(name) and ".." not in name else ""


def registry_size(name):
    """
    The download size of a model in Ollama's library, in bytes, or None
    (not found, not in the library, or the library can't be reached).
    """
    name = valid_model_name(name)
    if not name or name.startswith(("hf.co/", "huggingface.co/")):
        return None
    cached = OLLAMA_SIZE_CACHE.get(name)
    if cached and time.time() - cached[0] < OLLAMA_SIZE_TTL:
        return cached[1]
    repo, _, tag = name.partition(":")
    if "/" not in repo:
        repo = "library/" + repo
    size = None
    try:
        response = requests.get(f"{OLLAMA_REGISTRY}/{repo}/manifests/{tag or 'latest'}",
                                headers={"Accept": "application/vnd.docker.distribution.manifest.v2+json"},
                                timeout=(4, 8))
        if response.status_code == 200:
            data = response.json()
            size = sum(int(layer.get("size") or 0) for layer in data.get("layers") or [])
            size += int((data.get("config") or {}).get("size") or 0)
        elif response.status_code != 404:
            return None   # don't cache a passing problem
    except Exception:
        return None
    OLLAMA_SIZE_CACHE[name] = (time.time(), size)
    return size


def ollama_card_room():
    """
    (card total MB, what Evora holds in MB) from the last GPU reading, when
    Evora shares the card with Ollama; (None, None) when unknown.
    """
    latest = _gpu_state.get("latest") or {}
    card = latest.get("card") or {}
    if not card.get("total_mb"):
        try:
            sample = gpu_sample()
            card = sample.get("card") or {}
            latest = sample
        except Exception:
            return None, None
    if not card.get("total_mb"):
        return None, None
    evora = int(((card.get("parts") or {}).get("evora_mb")) or 0) if latest.get("same_card") else 0
    return int(card["total_mb"]), evora


def model_fit(size_bytes, total_mb, evora_mb):
    """'fits', 'tight' (fits only without Evora) or 'big' (part runs on the CPU)."""
    if not size_bytes or not total_mb:
        return ""
    # Ollama needs room for the conversation as well as the model.
    need = size_bytes / (1024 * 1024) * 1.05 + 500
    if need <= total_mb - (evora_mb or 0):
        return "fits"
    if need <= total_mb:
        return "tight"
    return "big"


def ollama_drive():
    """Free space where Ollama keeps its models, from Evora, when it can say."""
    if not same_gpu_host(whisper_base_url(), ollama_base_url()):
        return {"ok": False, "reason": "Evora runs on a different PC from Ollama, so Frivo can't see that drive."}
    try:
        response = requests.get(f"{whisper_base_url()}/disk", timeout=(LOCAL_CONNECT_TIMEOUT, 4))
    except Exception:
        return {"ok": False, "reason": "Evora isn't reachable, so the drive's free space is unknown."}
    if response.status_code == 404:
        return {"ok": False, "reason": "Update Evora to see how much space is left on the Ollama PC's drive."}
    try:
        data = response.json()
    except ValueError:
        return {"ok": False, "reason": "Evora sent something Frivo couldn't read."}
    data["ok"] = bool(data.get("total_bytes"))
    return data


def ollama_installed_models():
    data = _ollama_get("/api/tags")
    loaded = set()
    try:
        loaded = {m.get("name") for m in (_ollama_get("/api/ps").get("models") or [])}
    except Exception:
        pass
    tiers = {t: tier_model(t) for t in OLLAMA_TIER_KEYS}
    out = []
    for m in data.get("models") or []:
        name = m.get("name") or m.get("model") or ""
        details = m.get("details") or {}
        out.append({
            "name": name,
            "size": int(m.get("size") or 0),
            "modified": m.get("modified_at") or "",
            "params": details.get("parameter_size") or "",
            "quant": details.get("quantization_level") or "",
            "family": details.get("family") or "",
            "tiers": [t for t, wanted in tiers.items() if _same_model(wanted, name)],
            "loaded": any(_same_model(name, l) for l in loaded),
        })
    out.sort(key=lambda m: m["name"].lower())
    return out


def pulls_snapshot():
    with OLLAMA_PULLS_LOCK:
        now = time.time()
        for name in [n for n, p in OLLAMA_PULLS.items() if p.get("finished") and now - p["finished"] > 600]:
            OLLAMA_PULLS.pop(name, None)
        return {name: {k: v for k, v in p.items() if not k.startswith("_")} for name, p in OLLAMA_PULLS.items()}


def _run_pull(name):
    progress = OLLAMA_PULLS[name]
    layers = {}
    try:
        with requests.post(f"{ollama_base_url()}/api/pull", json={"model": name, "name": name, "stream": True},
                           stream=True, timeout=(LOCAL_CONNECT_TIMEOUT, 120)) as response:
            progress["_response"] = response
            if response.status_code != 200:
                try:
                    message = response.json().get("error")
                except Exception:
                    message = response.text[:200]
                raise RuntimeError(message or f"Ollama said {response.status_code}")
            for line in response.iter_lines():
                if progress.get("_cancel"):
                    raise RuntimeError("Stopped.")
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if event.get("error"):
                    raise RuntimeError(event["error"])
                status = event.get("status") or ""
                if event.get("digest") and event.get("total"):
                    layers[event["digest"]] = (int(event.get("completed") or 0), int(event["total"]))
                done = sum(c for c, _ in layers.values())
                total = sum(t for _, t in layers.values())
                with OLLAMA_PULLS_LOCK:
                    progress.update(status=status.split(" sha256")[0][:60], completed=done, total=total)
                if status == "success":
                    with OLLAMA_PULLS_LOCK:
                        progress.update(state="done", finished=time.time(), status="Downloaded")
                    log_server_event(f"Ollama: downloaded {name}")
                    return
        raise RuntimeError("Ollama stopped before the download finished.")
    except Exception as e:
        stopped = progress.get("_cancel")
        with OLLAMA_PULLS_LOCK:
            progress.update(state="stopped" if stopped else "error", finished=time.time(),
                            error="" if stopped else (str(e) or "The download failed."))
        if not stopped:
            log_server_event(f"Ollama: couldn't download {name}: {e}")


@app.route("/api/ollama/models", methods=["GET", "DELETE"])
def ollama_models_route():
    if request.method == "DELETE":
        name = valid_model_name((request.get_json(silent=True) or {}).get("model"))
        if not name:
            return jsonify({"error": "Which model?"}), 400
        try:
            response = requests.delete(f"{ollama_base_url()}/api/delete", json={"model": name, "name": name},
                                       timeout=(LOCAL_CONNECT_TIMEOUT, 60))
        except Exception:
            return jsonify({"error": f"Ollama isn't reachable at {ollama_base_url()}."}), 502
        if response.status_code == 404:
            return jsonify({"error": f"{name} isn't on the Ollama PC."}), 404
        if response.status_code != 200:
            try:
                message = response.json().get("error")
            except Exception:
                message = ""
            return jsonify({"error": message or f"Ollama couldn't remove {name}."}), 502
        log_server_event(f"Ollama: removed {name}")
    try:
        installed = ollama_installed_models()
    except Exception:
        return jsonify({"reachable": False, "error": f"Ollama isn't reachable at {ollama_base_url()}.",
                        "pulls": pulls_snapshot()})
    total_mb, evora_mb = ollama_card_room()
    for m in installed:
        m["fit"] = model_fit(m["size"], total_mb, evora_mb)
    return jsonify({
        "reachable": True,
        "installed": installed,
        "used_bytes": sum(m["size"] for m in installed),
        "drive": ollama_drive(),
        "card": {"total_mb": total_mb, "evora_mb": evora_mb} if total_mb else None,
        "pulls": pulls_snapshot(),
    })


@app.route("/api/ollama/pull", methods=["GET", "POST", "DELETE"])
def ollama_pull_route():
    if request.method == "GET":
        return jsonify({"pulls": pulls_snapshot()})
    data = request.get_json(silent=True) or {}
    name = valid_model_name(data.get("model") or request.args.get("model"))
    if not name:
        return jsonify({"error": "Type a model name, like qwen3.5:4b or huihui_ai/qwen3.5-abliterated:4b."}), 400
    with OLLAMA_PULLS_LOCK:
        current = OLLAMA_PULLS.get(name)
        if request.method == "DELETE":
            if current and current.get("state") == "pulling":
                current["_cancel"] = True
                response = current.get("_response")
                if response is not None:
                    try:
                        response.close()
                    except Exception:
                        pass
            return jsonify({"ok": True})
        if current and current.get("state") == "pulling":
            return jsonify({"error": f"{name} is already downloading."}), 409
        OLLAMA_PULLS[name] = {"state": "pulling", "status": "Starting…", "completed": 0, "total": 0,
                              "started": time.time(), "expected": registry_size(name)}
    threading.Thread(target=_run_pull, args=(name,), daemon=True, name=f"ollama-pull-{name}").start()
    return jsonify({"ok": True, "pulls": pulls_snapshot()})


@app.route("/api/ollama/suggestions")
def ollama_suggestions_route():
    """The suggestions, with sizes from Ollama's library (looked up together)."""
    from concurrent.futures import ThreadPoolExecutor
    names = [s[1] for s in OLLAMA_SUGGESTIONS]
    extra = valid_model_name(request.args.get("lookup"))
    if extra and extra not in names:
        names.append(extra)
    with ThreadPoolExecutor(max_workers=8) as pool:
        sizes = dict(zip(names, pool.map(registry_size, names)))
    try:
        installed = [m["name"] for m in ollama_installed_models()]
    except Exception:
        installed = []
    total_mb, evora_mb = ollama_card_room()
    items = []
    for group, name, note in OLLAMA_SUGGESTIONS:
        size = sizes.get(name)
        if size is None and name in OLLAMA_SIZE_CACHE:
            continue   # the library doesn't have it (any more)
        items.append({"group": group, "name": name, "note": note, "size": size,
                      "installed": any(_same_model(name, m) for m in installed),
                      "fit": model_fit(size, total_mb, evora_mb)})
    lookup = None
    if extra:
        size = sizes.get(extra)
        lookup = {"name": extra, "size": size, "found": size is not None or extra.startswith("hf.co/"),
                  "installed": any(_same_model(extra, m) for m in installed),
                  "fit": model_fit(size, total_mb, evora_mb)}
    return jsonify({"suggestions": items, "lookup": lookup,
                    "card": {"total_mb": total_mb, "evora_mb": evora_mb} if total_mb else None})


@app.route("/api/ollama/status")
def ollama_status_route():
    return jsonify(ollama_tier_status())


@app.route("/api/ollama/tier", methods=["POST"])
def set_ollama_tier():
    data = request.get_json(silent=True) or {}
    tier = data.get("tier")
    if tier not in OLLAMA_TIER_KEYS:
        return jsonify({"error": "Pick Fast, Balanced or Best."}), 400
    CFG["ollama_tier"] = tier
    save_config(CFG)
    wanted = tier_model(tier)
    others = {tier_model(t) for t in OLLAMA_TIER_KEYS if t != tier} - {wanted}

    def swap():
        for model in others:
            try:
                _ollama_set_loaded(model, keep=False)
            except Exception:
                pass
        try:
            _ollama_set_loaded(wanted, keep=True)
        except Exception as e:
            log_server_event(f"Ollama: couldn't load {wanted}: {e!r}")

    # In the background: loading a model can take a few seconds, and the
    # switch shouldn't wait for it.
    threading.Thread(target=swap, name="ollama-swap", daemon=True).start()
    return jsonify({"ok": True, "tier": tier, "model": wanted})


# ---------------------------------------------------------------------------
# NEW (1.5.0): graphics-card memory graph
#
# Ollama and Evora usually share one graphics card, on another PC. Frivo
# can't see that card itself, so Evora reports it (GET /gpu: the card's
# memory, and how much of it is Ollama, Evora and everything else) and
# Frivo keeps the last ten minutes for the graph in the status popover.
#
# Without Evora, Ollama's own /api/ps still says how much of each loaded
# model is on its graphics card, so there is still something to show, just
# not the whole card.
#
# Sampled in the background whenever a local service is selected — every
# few seconds is two tiny LAN requests — so the graph already has history
# the moment you open it. Faster while someone is looking at it.
# ---------------------------------------------------------------------------

GPU_HISTORY_SECONDS = 600
GPU_SAMPLE_SECONDS = 5
GPU_SAMPLE_SECONDS_VIEWED = 2
GPU_VIEWED_FOR = 30            # seconds a look at the graph counts as "watching"
_GPU_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "evora.local", "frivo.local"}

_gpu_lock = threading.Lock()
_gpu_state = {"latest": None, "viewed": 0.0, "history": collections.deque()}


def gpu_watch_targets():
    """(uses Ollama, uses Evora) — only selected services are sampled."""
    chat = resolve_provider("chat_provider", CHAT_PROVIDERS)
    translation = resolve_provider("translation_provider", TRANSLATION_PROVIDERS)
    transcription = resolve_provider("transcription_provider", TRANSCRIPTION_PROVIDERS)
    return "ollama" in (chat, translation), transcription == "local_whisper"


def same_gpu_host(first_url, second_url):
    """Whether two service addresses are the same PC (so the same card)."""
    a = (urlsplit(first_url).hostname or "").lower()
    b = (urlsplit(second_url).hostname or "").lower()
    if not a or not b:
        return False
    return a == b or (a in _GPU_LOCAL_HOSTS and b in _GPU_LOCAL_HOSTS)


def read_evora_gpu():
    """(card report, problem). The report is Evora's /gpu, or None."""
    try:
        response = requests.get(f"{whisper_base_url()}/gpu", timeout=(LOCAL_CONNECT_TIMEOUT, 4))
    except Exception:
        return None, f"Evora isn't reachable at {whisper_base_url()}."
    if response.status_code == 404:
        return None, "This version of Evora can't report the graphics card. Update Evora to see it."
    try:
        data = response.json()
    except ValueError:
        return None, "Evora sent something Frivo couldn't read."
    if not data.get("ok"):
        return None, data.get("reason") or "Evora couldn't read the graphics card."
    return data, None


def seconds_until_stamp(stamp):
    """
    NEW (1.5.0): seconds from now until an Ollama timestamp such as
    "2026-10-18T23:27:01.123456789-05:00" (nanoseconds and all), or None.
    """
    import datetime
    match = re.match(r"^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(\.\d+)?(Z|[+-]\d\d:\d\d)?$", (stamp or "").strip())
    if not match:
        return None
    zone = match.group(3) or "+00:00"
    text = match.group(1) + (match.group(2) or "")[:7] + ("+00:00" if zone == "Z" else zone)
    try:
        when = datetime.datetime.fromisoformat(text)
    except ValueError:
        return None
    return (when - datetime.datetime.now(datetime.timezone.utc)).total_seconds()


# NEW (1.5.0): "Never" asks Ollama to keep a model forever, which it reports
# as a date centuries away. Anything past ten years counts as that.
OLLAMA_FOREVER_SECONDS = 10 * 365 * 24 * 3600


def read_ollama_gpu():
    """
    ([{name, vram_mb, size_mb, unload_in, forever}], problem) for the models
    Ollama has loaded. CHANGED (1.5.0): unload_in is how many seconds until
    Ollama frees the graphics card of it (None if Ollama didn't say).
    """
    try:
        loaded = _ollama_get("/api/ps").get("models") or []
    except Exception:
        return [], f"Ollama isn't reachable at {ollama_base_url()}."
    models = []
    for model in loaded:
        size = int(model.get("size") or 0)
        vram = int(model.get("size_vram") or 0)
        left = seconds_until_stamp(model.get("expires_at"))
        forever = left is not None and left > OLLAMA_FOREVER_SECONDS
        models.append({"name": model.get("name") or model.get("model") or "model",
                       "vram_mb": round(vram / 1048576), "size_mb": round(size / 1048576),
                       "unload_in": None if left is None or forever else max(0, round(left)),
                       "forever": forever})
    return models, None


def gpu_sample():
    """One reading of everything the graph shows."""
    uses_ollama, uses_evora = gpu_watch_targets()
    card, card_problem = read_evora_gpu() if uses_evora else (None, None)
    models, ollama_problem = read_ollama_gpu() if uses_ollama else ([], None)
    ollama_vram = sum(m["vram_mb"] for m in models)

    same_card = False
    if card:
        parts = card.get("parts")
        if parts and parts.get("ollama_mb"):
            same_card = True     # Evora saw Ollama on its own card: settled
        elif uses_ollama:
            same_card = same_gpu_host(whisper_base_url(), ollama_base_url())
        if not parts:
            # Windows didn't say who uses the card. When Ollama is on it,
            # Ollama's own figure still splits the total; Evora counts as
            # "other" then, and the graph says so.
            used = int(card.get("used_mb") or 0)
            ollama = min(used, ollama_vram) if same_card else 0
            card["parts"] = {"ollama_mb": ollama, "evora_mb": 0, "other_mb": used - ollama,
                             "estimated": True}

    return {
        "t": time.time(),
        "uses_ollama": uses_ollama,
        "uses_evora": uses_evora,
        "card": card,
        "card_problem": card_problem,
        "same_card": same_card,
        "ollama_models": models,
        "ollama_problem": ollama_problem,
        # NEW (1.5.0): Evora's idle countdowns, when it has them.
        "evora_idle": (card or {}).pop("idle", None) if card else None,
    }


def gpu_history_point(sample):
    """What one sample adds to the graph."""
    card = sample.get("card")
    if card:
        parts = card.get("parts") or {}
        return {"t": round(sample["t"], 1), "total": card.get("total_mb"), "used": card.get("used_mb"),
                "ollama": parts.get("ollama_mb", 0), "evora": parts.get("evora_mb", 0),
                "other": parts.get("other_mb", 0)}
    if sample.get("ollama_models"):
        return {"t": round(sample["t"], 1), "total": None, "used": None,
                "ollama": sum(m["vram_mb"] for m in sample["ollama_models"]), "evora": 0, "other": 0}
    return None


def record_gpu_sample(sample):
    point = gpu_history_point(sample)
    with _gpu_lock:
        _gpu_state["latest"] = sample
        history = _gpu_state["history"]
        if point:
            history.append(point)
        cutoff = sample["t"] - GPU_HISTORY_SECONDS
        while history and history[0]["t"] < cutoff:
            history.popleft()


def gpu_sampler_loop():
    while True:
        uses_ollama, uses_evora = gpu_watch_targets()
        if uses_ollama or uses_evora:
            try:
                record_gpu_sample(gpu_sample())
            except Exception as e:
                log_server_event(f"GPU graph: {e!r}")
        watched = time.time() - _gpu_state["viewed"] < GPU_VIEWED_FOR
        time.sleep(GPU_SAMPLE_SECONDS_VIEWED if watched else GPU_SAMPLE_SECONDS)


@app.route("/api/gpu")
def gpu_route():
    """The latest reading and the last ten minutes, for the status popover."""
    uses_ollama, uses_evora = gpu_watch_targets()
    _gpu_state["viewed"] = time.time()
    if not (uses_ollama or uses_evora):
        return jsonify({"enabled": False})
    latest = _gpu_state["latest"]
    stale = (latest is None or time.time() - latest["t"] > GPU_SAMPLE_SECONDS * 2
             or latest.get("uses_ollama") != uses_ollama or latest.get("uses_evora") != uses_evora)
    if stale:
        # First look, or the sampler isn't running (tests): read it now.
        record_gpu_sample(gpu_sample())
    with _gpu_lock:
        latest = dict(_gpu_state["latest"])
        history = list(_gpu_state["history"])
    latest["enabled"] = True
    latest["history"] = history
    latest["history_seconds"] = GPU_HISTORY_SECONDS
    latest["now"] = time.time()
    return jsonify(latest)


@app.route("/api/translate", methods=["POST"])
def translate():
    """
    On-demand English translation for the hover tooltip on non-English replies.
    """
    # As in /api/transcribe: a key is only required when OpenAI is the one
    # doing the work, so translation can run entirely on a local model.
    if (
        resolve_provider("translation_provider", TRANSLATION_PROVIDERS) == "openai"
        and not CFG["openai_api_key"]
    ):
        return jsonify({"error": "Add your OpenAI key in Settings first."}), 400

    data = request.get_json(force=True)
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"error": "No text to translate."}), 400

    try:
        client = make_openai_client()
        response = create_chat_completion(
            client,
            provider=resolve_provider("translation_provider", TRANSLATION_PROVIDERS),
            ollama_model=CFG.get("ollama_translation_model")
            or active_ollama_model(),   # CHANGED (1.5.0)
            model=CFG.get("translation_model", RECOMMENDED_TRANSLATION_MODEL),
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Translate the following into natural, idiomatic English — "
                        "the way a fluent English speaker would actually phrase it, "
                        "not a stiff literal translation. Keep the same tone (sarcastic "
                        "stays sarcastic, casual stays casual). Reply with only the "
                        "translation, nothing else.\n\n" + text
                    ),
                }
            ],
            max_tokens=min(600, len(text) + 80),
        )
        translation = response.choices[0].message.content.strip()
        return jsonify({"translation": translation})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/transcribe", methods=["POST"])
def transcribe_audio():
    """
    Speech-to-text for the dictation button. The browser records a short
    clip with MediaRecorder and uploads it here as multipart/form-data;
    this hands it to OpenAI's transcription API and returns plain text to
    drop into the message box. Uses your existing OpenAI key — no separate
    speech service or key needed.
    """
    transcription_provider = resolve_provider(
        "transcription_provider", TRANSCRIPTION_PROVIDERS
    )
    # Local Whisper does not require an OpenAI key.
    if transcription_provider == "openai" and not CFG["openai_api_key"]:
        return jsonify({"error": "Add your OpenAI key in Settings first."}), 400

    audio_file = request.files.get("audio")
    if not audio_file or not audio_file.filename:
        return jsonify({"error": "No audio received."}), 400

    audio_bytes = audio_file.read()
    if not audio_bytes:
        return jsonify({"error": "No audio received — try holding the mic button a little longer."}), 400

    # Keep uploaded audio in memory so it can be retried with a fallback.
    file_tuple = (audio_file.filename, audio_bytes, audio_file.mimetype or "audio/webm")

    # Pass an ISO language hint to improve short-clip transcription accuracy.
    spoken_language = (request.form.get("language") or "").strip().lower()
    extra = {}
    if spoken_language and 2 <= len(spoken_language) <= 3 and spoken_language.isalpha():
        extra["language"] = spoken_language

    # Use the selected local provider before optional OpenAI fallback.
    if transcription_provider == "local_whisper":
        try:
            text = local_whisper_transcribe(file_tuple, extra.get("language"))
            return jsonify({"text": text, "provider": "local_whisper"})
        except Exception as e:
            if not fallback_allowed():
                log_server_event(f"Local Whisper unavailable ({e!r}) — fallback off, failing.")
                return jsonify({
                    "error": (
                        "Evora isn't reachable, so nothing was transcribed. "
                        "Open Evora, or switch Transcription to OpenAI "
                        "in Settings. Automatic fallback is off, so no audio was "
                        "sent to a paid service."
                    )
                }), 503

            log_server_event(f"Local Whisper unavailable ({e!r}) — falling back to OpenAI.")
            if not CFG["openai_api_key"]:
                return jsonify({
                    "error": (
                        "Evora isn't reachable and there's no OpenAI key to fall "
                        "back on. Open Evora, or set an OpenAI key."
                    )
                }), 502

    try:
        client = make_openai_client()
        try:
            result = client.audio.transcriptions.create(
                model=TRANSCRIBE_MODEL, file=file_tuple, **extra
            )
        except Exception:
            # Same defensive fallback as the chat models: if the primary
            # transcription model isn't available on this account/region,
            # retry once with the long-established whisper-1 instead of
            # just failing.
            if TRANSCRIBE_MODEL == TRANSCRIBE_FALLBACK_MODEL:
                raise
            result = client.audio.transcriptions.create(
                model=TRANSCRIBE_FALLBACK_MODEL, file=file_tuple, **extra
            )

        text = (getattr(result, "text", "") or "").strip()
        return jsonify({"text": text})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/chat", methods=["POST"])
def chat():
    data = request.get_json(force=True)
    message = (data.get("message") or "").strip()
    session_id = data.get("session_id") or "default"
    profile_id = data.get("profile_id")
    max_words = clamp_words(data.get("max_words"), CFG.get("max_words", 80))
    language = normalize_language(data.get("language")) or CFG.get("language", "English")
    # Absent means yes: an older page, or anything else calling this
    # endpoint, keeps the original speak-everything behaviour.
    speak = data.get("speak", True) is not False
    # NEW (1.5.0): Auto tags (the ✦ menu): the AI adds voice tags to every
    # message you send, and to its own replies, before the voice gets it.
    auto_tags = data.get("auto_tags") is True

    if not message:
        return jsonify({"error": "Type something first."}), 400

    if profile_id:
        profile = next((p for p in load_profiles() if p["id"] == profile_id), None)
        if not profile:
            return jsonify({"error": "That profile no longer exists."}), 400
        voice_id = profile["voice_id"]
        base_prompt = resolve_personality_text(
            profile.get("system_prompt", ""), profile.get("personality_preset", DEFAULT_PERSONALITY_PRESET)
        )
        response_style = normalize_response_style(profile.get("response_style"), DEFAULT_RESPONSE_STYLE)
        follow_length = normalize_follow_length(profile.get("follow_length"), response_style)  # NEW (1.5.0)
        voice_style = voice_style_of(profile)   # NEW (1.5.0)
    else:
        voice_id = CFG["voice_id"]
        base_prompt = resolve_personality_text(
            CFG.get("system_prompt", ""), CFG.get("personality_preset", DEFAULT_PERSONALITY_PRESET)
        )
        response_style = normalize_response_style(CFG.get("response_style"), DEFAULT_RESPONSE_STYLE)
        follow_length = normalize_follow_length(CFG.get("follow_length"), response_style)  # NEW (1.5.0)
        voice_style = voice_style_of(None)   # NEW (1.5.0)

    # NEW (1.5.0): "Follow reply length" off — Response isn't held to the
    # slider either (Echo and Mimic never are, unless it's on; see below).
    if response_style == "reply" and not follow_length:
        max_words = MAX_WORDS

    # NEW (1.5.0): Mimic in English never touches the model — it says what
    # you typed, character for character.
    verbatim = response_style == "mimic" and language == "English"

    # CHANGED (1.5.0): the profile is looked up first, so a Mimic message
    # that never calls the model doesn't need an OpenAI key.
    # CHANGED (1.5.0): only when OpenAI writes the reply. With Ollama chosen
    # for Chat replies, every step of a reply goes to Ollama.
    if (not verbatim and not CFG["openai_api_key"]
            and resolve_provider("chat_provider", CHAT_PROVIDERS) == "openai"):
        return jsonify({"error": "Add your OpenAI key in Settings before sending."}), 400
    # Only demanded when something is actually going to be spoken, so
    # text-only replies work on an OpenAI key alone. CHANGED (1.5.0): and
    # only for an ElevenLabs voice — the free voices need no key at all.
    voice_engine = tts_engine(voice_id)
    if speak and voice_engine == "elevenlabs" and not CFG["elevenlabs_api_key"]:
        return jsonify({"error": "Add your ElevenLabs key in Settings, pick a free voice, or turn Speak off."}), 400
    if speak and voice_engine != "elevenlabs":
        problem = free_voice_problem(voice_id, language)
        if problem:
            return jsonify({"error": problem}), 400

    # NEW (1.5.0): Expressive voice and Delivery are for ElevenLabs voices.
    # A free voice can't perform tags, so any you typed are taken out.
    if voice_engine == "elevenlabs":
        g.voice_style = dict(voice_style, language=language)   # CHANGED (1.5.0): and the language, for v3
        # NEW (1.5.0): stays on v3 if this conversation was just using it.
        sticky_key = f"{session_id}::{profile_id or 'default'}"
        if time.time() - V3_LAST_USED.get(sticky_key, 0) < V3_STICKY_SECONDS:
            g.voice_style["stay_on_v3"] = True
        g.speech_thread = speech_thread_key(session_id, profile_id, voice_id, ELEVEN_V3_MODEL)
        g.speech_voice = voice_id   # NEW (1.5.0): for the anchor
        prompt_voice_style = voice_style
    else:
        g.voice_style = {"expressive": False, "delivery": DEFAULT_VOICE_DELIVERY}
        prompt_voice_style = None
        message = strip_audio_tags(message) or message
    message = tidy_audio_tags(message)
    typed_tags = [t for _, t in audio_tag_positions(message)]   # NEW (1.5.0): never removed by the rules
    tag_profile = profile if profile_id else None
    auto_tagged = False
    tag_seconds = 0.0
    # NEW (1.5.0): Shape words for tags, for a Clean up profile with an
    # ElevenLabs voice: the clean-up itself adds the tags and shapes the
    # words around them, so Auto tags doesn't need its own call.
    shaping = bool(voice_style.get("shaping")) and response_style == "echo" and voice_engine == "elevenlabs"
    if prompt_voice_style is not None:
        prompt_voice_style = dict(prompt_voice_style, shaping=shaping)
        if shaping:
            g.voice_style["expressive"] = True
    if auto_tags and speak and voice_engine == "elevenlabs" and response_style != "reply" and not shaping \
            and strip_audio_tags(message):
        # Your own words, tagged on their way to the voice. One extra AI
        # call; if it can't, the message goes as typed.
        tag_start = time.perf_counter()
        try:
            tagged = tag_message_with_ai(message, voice_style["delivery"],
                                         tag_context(tag_profile, session_id, profile_id), voice_style["amount"])
            if has_audio_tags(tagged):
                message = tagged
                auto_tagged = True
        except Exception as e:
            log_server_event(f"Auto tags: {e}")
        tag_seconds = time.perf_counter() - tag_start
    if auto_tags and voice_engine == "elevenlabs" and response_style == "reply" and prompt_voice_style:
        # For a Reply profile, Auto tags is Expressive voice for this message.
        prompt_voice_style = dict(prompt_voice_style, expressive=True)
        g.voice_style["expressive"] = True
        auto_tagged = True

    system_prompt = build_system_prompt(base_prompt, max_words, language, response_style,
                                        voice_style=prompt_voice_style)
    history = get_history(session_id, profile_id, system_prompt)

    if response_style == "reply":
        # The opposite framing from the transform modes below: this explicitly
        # asks the model to answer/react, matching the REPLY RULES in the
        # system prompt instead of contradicting them.
        source_message = (
            "SOURCE TEXT (said to you):\n"
            "<SOURCE_TEXT>\n"
            f"{message}\n"
            "</SOURCE_TEXT>\n\n"
            "Reply to this in character, following the system instructions. "
            f"Write your reply in {language}, whatever language the source text "
            f"or any earlier messages were in. "
            "Output only your reply."
        )
    elif response_style == "echo":
        source_message = (
            "SOURCE TEXT TO CLEAN UP:\n"
            "<SOURCE_TEXT>\n"
            f"{message}\n"
            "</SOURCE_TEXT>\n\n"
            + (
                "Output what this means, with the mistakes fixed. "
                if language == "English"
                else f"Translate what this means into {language}, with the mistakes fixed. "
            )
            + "Add nothing that isn't in it. "
            "Do not answer it, react to it, acknowledge it, or continue the conversation. "
            "Output only the result."
        )
    else:
        source_message = (
            "SOURCE TEXT TO TRANSLATE:\n"
            "<SOURCE_TEXT>\n"
            f"{message}\n"
            "</SOURCE_TEXT>\n\n"
            f"Translate this into {language} word for word. "
            "Do not answer it, react to it, acknowledge it, or continue the conversation. "
            "Output only the translation."
        )

    try:
        was_condensed = False
        was_repaired = False
        hit_ceiling = False
        text_seconds = 0.0
        english = ""
        # NEW (1.5.0): set when Echo reworded something and was put back.
        kept_exact = False

        if response_style == "reply":
            history.append({"role": "user", "content": source_message})
            reply, english, was_condensed, hit_ceiling, text_seconds = get_chat_reply(history, max_words, language)
            spoken, was_repaired = repair_if_clipped(reply)
        elif verbatim:
            spoken = message
            history.append({"role": "user", "content": source_message})
        else:
            # NEW (1.5.0): Echo and Mimic see only this message. Earlier turns
            # are something to imitate or carry on from, which is exactly how
            # they used to drift away from what you typed.
            budget = max(max_words, count_words(message, language) + 15)
            one_off = [{"role": "system", "content": system_prompt}, {"role": "user", "content": source_message}]
            reply, english, _, hit_ceiling, text_seconds = get_chat_reply(
                one_off, budget, language, condense=False,
                temperature=0.0 if response_style == "mimic" else None,
            )
            spoken = reply.strip()

            # NEW (1.5.0): don't take Echo's word for it — check.
            # CHANGED (1.5.0): Shape words for tags has its own, slightly
            # looser check, and keeps its tags when it falls back.
            stays = tag_shaping_stays_on_message if shaping else cleanup_stays_on_message
            if (response_style == "echo" and language == "English"
                    and not stays(strip_audio_tags(message), strip_audio_tags(spoken))):
                plain = build_system_prompt(PERSONALITY_PRESET_MAP[DEFAULT_PERSONALITY_PRESET]["prompt"],
                                            budget, language, "echo", voice_style=prompt_voice_style)
                retry, _, _, hit_ceiling, retry_seconds = get_chat_reply(
                    [{"role": "system", "content": plain}, {"role": "user", "content": source_message}],
                    budget, language, condense=False, temperature=0.0,
                )
                text_seconds += retry_seconds
                spoken = retry.strip()
                if not stays(strip_audio_tags(message), strip_audio_tags(spoken)):
                    spoken = message
                    hit_ceiling = False
                    if shaping:
                        # Your words, with tags only (no shaping).
                        try:
                            tagged = tag_message_with_ai(message, voice_style["delivery"],
                                                         tag_context(tag_profile, session_id, profile_id),
                                                         voice_style["amount"])
                            if has_audio_tags(tagged):
                                spoken = tagged
                        except Exception as e:
                            log_server_event(f"Shape words for tags: {e}")
                kept_exact = True

            # Cut off by the token ceiling: what you typed beats half of it.
            if hit_ceiling or not spoken:
                if language == "English":
                    spoken = message
                else:
                    spoken, was_repaired = repair_if_clipped(spoken or message)
                hit_ceiling = False

            history.append({"role": "user", "content": source_message})

        # NEW (1.5.0): "Follow reply length" on — Clean up and Word for word
        # summarize a message that's too long to fit, in your voice. Only
        # when that isn't possible (no model to ask, or the summary added
        # things you didn't say) does it keep whole sentences instead. The
        # English translation was of the whole thing, so it's dropped and the
        # page asks for a fresh one when you hover.
        if response_style != "reply" and follow_length and count_words(spoken, language) > max_words:
            summary, summary_seconds = summarize_to_length(spoken, max_words, language)
            text_seconds += summary_seconds
            if summary and count_words(summary, language) <= max_words:
                spoken = summary
                was_condensed = True
            else:
                spoken, _ = fit_to_length(summary or spoken, max_words, language)
                if summary:
                    was_condensed = True
                else:
                    was_repaired = True
            english = ""

        # NEW (1.5.0): the voice gets the reply with its audio tags
        # ("voiced"); everything else gets it without. A free voice gets
        # no tags at all.
        if voice_engine == "elevenlabs":
            voiced = tidy_audio_tags(spoken)
            if shaping:
                voiced = replace_text_speak(voiced)   # NEW (1.5.0): no "lol" read out
            if not ACCENT_TAG_RE.search(message):   # NEW (1.5.0): not one you typed
                voiced = ACCENT_TAG_RE.sub("", voiced).strip()
            if voice_style["delivery"] == "calm":
                voiced = re.sub(r"\[(?:shouts|shouting|yells|yelling|screams)\]\s*", "", voiced, flags=re.I)
            # NEW (1.5.0): the rules for the AI's tags (yours are kept).
            voiced = refine_tags(voiced, protected=typed_tags, amount=voice_style["amount"])
            # NEW (1.5.0): "lol" on its own became [laughs], which ElevenLabs
            # won't say by itself: it's said as "[laughs] Haha!".
            voiced = ensure_spoken_words(voiced)
        else:
            voiced = strip_audio_tags(spoken)
        spoken = strip_audio_tags(voiced) or voiced
        english = strip_audio_tags(english)
        if not has_audio_tags(voiced):
            voiced = spoken

        # Only the reply goes into history — the translation is tooltip
        # metadata, not part of the conversation.
        # CHANGED (1.5.0): with its tags, so the AI sees how it used them.
        history.append({"role": "assistant", "content": voiced})

        # Text-only mode. With the reply going to the VRChat chatbox there
        # are plenty of times the spoken version isn't wanted, and skipping
        # it is the difference between a reply costing ElevenLabs
        # characters and costing nothing at all.
        #
        # Defaults to True so an older page — or any other client — behaves
        # exactly as before rather than falling silent.
        audio_filename = None
        audio_seconds = 0.0
        chatbox_plan = chatbox_page_plan(spoken)   # NEW (1.5.0)
        page_ends = None                           # NEW (1.5.0)
        word_times = None                          # NEW (1.5.0)
        stream = None                              # NEW (1.5.0): streaming
        if speak and voice_engine == "elevenlabs" and elevenlabs_streaming_on():
            # NEW (1.5.0): the reply goes back now and the voice follows as
            # ElevenLabs makes it (see SpeechStream).
            audio_start = time.perf_counter()
            stream = start_speech_stream(spoken, voiced, voice_id, language, chatbox_plan)
            if is_expressive_model(_elevenlabs_payload(voiced)["model_id"]):
                V3_LAST_USED[f"{session_id}::{profile_id or 'default'}"] = time.time()
            audio_seconds = time.perf_counter() - audio_start
        elif speak:
            audio_start = time.perf_counter()
            # CHANGED (1.5.0): also says when the voice finishes each page.
            # CHANGED (1.5.0): speak_reply() also says when each word is spoken.
            audio_filename, page_ends, word_times = speak_reply(spoken, voice_id, language, chatbox_plan,
                                                                voiced=voiced)
            # NEW (1.5.0): remembered, so the next message keeps the same model.
            if voice_engine == "elevenlabs" and is_expressive_model(_elevenlabs_payload(voiced)["model_id"]):
                V3_LAST_USED[f"{session_id}::{profile_id or 'default'}"] = time.time()
            audio_seconds = time.perf_counter() - audio_start
    except Exception as e:
        if history and history[-1].get("role") == "user":
            history.pop()
        return jsonify({"error": str(e)}), 500

    # Recorded here rather than inside get_tts_audio(), so a synthesis that
    # threw partway through isn't billed to the day's total.
    # CHANGED (1.5.0): free voices cost nothing, so count nothing.
    # CHANGED (1.5.0): tags are characters ElevenLabs is sent, so they count.
    credits_spent = len(voiced) if speak and voice_engine == "elevenlabs" else 0

    # NEW (1.5.0): exact timing, when there is some. Page 1 shows when the
    # voice starts, and each page after it when the voice finishes the last
    # word of the page before.
    if page_ends and len(page_ends) == len(chatbox_plan):
        for i, page in enumerate(chatbox_plan):
            page["at"] = 0.0 if i == 0 else round(page_ends[i - 1], 3)
    if credits_spent and not stream:   # CHANGED (1.5.0): a stream counts its own, once spoken
        record_usage(credits_spent)

    return jsonify(
        {
            "reply": spoken,
            # NEW (1.5.0): the reply with its audio tags, for the page to
            # show; the same as "reply" when it has none.
            "voiced": voiced,
            # NEW (1.5.0): Auto tags added some (your message, or its reply).
            "auto_tagged": auto_tagged and has_audio_tags(voiced),
            "tag_shaped": shaping and not kept_exact and has_audio_tags(voiced),   # NEW (1.5.0)
            # NEW (1.5.0): a model refused and stepped down from, in words.
            "voice_notice": getattr(g, "voice_notice", "") or "",
            # NEW (1.5.0): which ElevenLabs model spoke it, when one did.
            "voice_model": (_elevenlabs_payload(voiced)["model_id"]
                            if speak and voice_engine == "elevenlabs" else ""),
            # NEW (1.5.0): how it was spoken, in words, so a saved clip can
            # say which settings made it ("v3 · Natural · accent held").
            "voice_how": voice_how(voiced) if speak and voice_engine == "elevenlabs" else "",
            "english": english,
            # Null rather than a dead path when nothing was synthesised, so
            # the page has something unambiguous to branch on.
            "audio_url": (f"/audio/{audio_filename}" if audio_filename
                          else f"/audio/stream/{stream.id}" if stream else None),
            # NEW (1.5.0): streaming: where the timings and the saved file
            # come from once the voice is finished.
            "stream": {"id": stream.id, "timing_url": f"/api/speech-stream/{stream.id}"} if stream else None,
            "spoke": speak,
            "word_count": count_words(spoken, language),
            "char_count": len(spoken),
            # Track billed speech characters separately from reply length.
            "credits": credits_spent,
            "target_words": max_words,
            "language": language,
            "response_style": response_style,
            "condensed": was_condensed,
            "repaired": was_repaired or hit_ceiling,
            # NEW (1.5.0): Echo reworded it, so your words were used instead.
            "kept_exact": kept_exact,
            "follow_length": follow_length,  # NEW (1.5.0)
            "voice_engine": voice_engine,  # NEW (1.5.0)
            # NEW (1.5.0): which AI wrote it ("Ollama · gemma3:4b",
            # "OpenAI · gpt-4o-mini"), or empty when none was needed.
            "text_engine_name": ", ".join(g.get("text_engines", [])),
            "voice_engine_name": TTS_ENGINE_NAMES[voice_engine],
            # NEW (1.5.0): the reply as chatbox pages, each timed to where
            # the voice reaches it. Pages are only sent one at a time while
            # the reply is spoken. Text-only replies still go as one message.
            "chatbox_pages": chatbox_plan,   # CHANGED (1.5.0): may carry exact "at" times
            # NEW (1.5.0): [[start, end], ...] seconds for each word of the
            # reply (split on spaces), only when the timing is exact. The
            # page highlights the word being spoken from these.
            "word_times": word_times,
            # Measured text and audio generation times for the UI.
            "text_seconds": round(text_seconds + tag_seconds, 2),
            "audio_seconds": round(audio_seconds, 2),
            "total_seconds": round(text_seconds + tag_seconds + audio_seconds, 2),
        }
    )


@app.route("/api/reset", methods=["POST"])
def reset():
    data = request.get_json(force=True)
    session_id = data.get("session_id") or "default"
    profile_id = data.get("profile_id")

    # History is stored per profile, so a conversation that moved between
    # profiles has several of them behind it. Clearing the window while
    # leaving those in place would look like it worked and then have the
    # model still remember — hence the "all" scope.
    if data.get("all"):
        prefix = f"{session_id}::"
        with SESSIONS_LOCK:
            for key in [k for k in SESSIONS if k.startswith(prefix)]:
                del SESSIONS[key]
        return jsonify({"ok": True})

    key = f"{session_id}::{profile_id or 'default'}"
    with SESSIONS_LOCK:
        SESSIONS.pop(key, None)
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# NEW (1.5.0): streaming ElevenLabs replies ("Start speaking sooner").
#
# Frivo used to ask ElevenLabs for the whole clip and play it once it was
# all there. With streaming on (Settings > Voices), the reply's audio is
# relayed to the page as ElevenLabs makes it, so the voice starts after the
# first fraction of a second. Same request, same credits; it's ElevenLabs'
# /stream/with-timestamps endpoint, which sends each piece of audio with its
# character timings.
#
#   GET /audio/stream/<id>        the audio, as it arrives (then from disk)
#   GET /api/speech-stream/<id>   whether it's finished, the saved file, and
#                                 the timings (word highlight, chatbox pages)
#
# A refusal before any audio (a model, an extra) falls back to the usual
# whole-clip request, with its step-down, so a reply is never lost. The
# finished audio is saved like any other reply (Save, replay, the 7 days).
# ---------------------------------------------------------------------------

SPEECH_STREAMS = {}
SPEECH_STREAMS_LOCK = threading.Lock()
SPEECH_STREAM_KEEP = 15 * 60
MP3_BYTES_PER_SECOND = 128000 / 8   # mp3_44100_128, ElevenLabs' default
_STREAM_ID_RE = re.compile(r"^[0-9a-f]{32}$")


def elevenlabs_streaming_on():
    return CFG.get("elevenlabs_streaming", True) is not False


class SpeechStream:
    """One reply being spoken: its audio so far, and its timings once done."""

    def __init__(self, spoken, voiced, pages, language, voice_id):
        self.id = uuid.uuid4().hex
        self.spoken = spoken
        self.voiced = voiced
        self.pages = pages
        self.language = language
        self.voice_id = voice_id
        self.chunks = []
        self.size = 0
        self.cond = threading.Condition()
        self.done = False
        self.error = ""
        self.notice = ""
        self.fell_back = False
        self.word_times = None
        self.page_ends = None
        self.duration = None
        self.filename = f"{self.id}.mp3"
        self.created = time.time()
        self.first_audio = None
        self.chars = []
        self.starts = []
        self.ends = []

    def push(self, data):
        if not data:
            return
        with self.cond:
            if self.first_audio is None:
                self.first_audio = time.time() - self.created
            self.chunks.append(data)
            self.size += len(data)
            self.cond.notify_all()

    def add_timings(self, alignment, offset):
        """One piece's character timings. Some come relative to the piece,
        some to the whole reply; relative ones are moved along."""
        if not isinstance(alignment, dict):
            return
        chars = alignment.get("characters") or []
        starts = alignment.get("character_start_times_seconds") or []
        ends = alignment.get("character_end_times_seconds") or []
        if not chars or len(chars) != len(starts) or len(chars) != len(ends):
            return
        shift = 0.0
        if self.ends and starts and float(starts[0]) + 0.05 < self.ends[-1]:
            shift = max(offset, self.ends[-1])   # the audio so far, or at least the last timing
        self.chars.extend(str(c) for c in chars)
        self.starts.extend(float(s) + shift for s in starts)
        self.ends.extend(float(e) + shift for e in ends)

    def finish(self, error=""):
        with self.cond:
            self.done = True
            self.error = error
            self.cond.notify_all()

    def timing(self):
        return {
            "done": self.done,
            "error": self.error,
            "notice": self.notice,
            "audio_url": f"/audio/{self.filename}" if self.done and not self.error and self.size else None,
            "word_times": self.word_times,
            "page_ends": self.page_ends,
            "duration": self.duration,
            "fell_back": self.fell_back,
            "first_audio_seconds": round(self.first_audio, 2) if self.first_audio is not None else None,
        }


def _stream_speech(job, payload, carried):
    """Runs in its own thread: ElevenLabs' stream, relayed and saved."""
    import base64
    with app.test_request_context():
        for key, value in carried.items():
            setattr(g, key, value)
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{job.voice_id}/stream/with-timestamps"
        headers = {"xi-api-key": CFG["elevenlabs_api_key"], "Content-Type": "application/json",
                   "Accept": "application/json"}
        try:
            resp = requests.post(url, headers=headers, json=payload, stream=True, timeout=(10, 60))
            if resp.status_code != 200:
                reason = _refusal_message(resp)
                resp.close()
                raise TimedSpeechUnavailable(f"ElevenLabs stream {resp.status_code}: {reason}")
            for line in resp.iter_lines():
                if not line:
                    continue
                try:
                    piece = json.loads(line)
                except ValueError:
                    continue
                offset = job.size / MP3_BYTES_PER_SECOND
                audio = piece.get("audio_base64")
                if audio:
                    job.push(base64.b64decode(audio))
                job.add_timings(piece.get("alignment"), offset)
            if not job.size:
                raise TimedSpeechUnavailable("ElevenLabs' stream had no audio")
            if is_expressive_model(payload.get("model_id")):
                remember_speech(resp, payload["text"])
            with open(os.path.join(AUDIO_DIR, job.filename), "wb") as f:
                f.write(b"".join(job.chunks))
            alignment = {"characters": job.chars, "character_start_times_seconds": job.starts,
                         "character_end_times_seconds": job.ends}
            fixed = alignment_without_tags(job.voiced, job.spoken, alignment) if job.chars else None
            if fixed:
                job.word_times = word_times_from_alignment(job.spoken, fixed)
                ends = page_ends_from_alignment([_CHATBOX_COUNTER_RE.sub("", p["text"]) for p in job.pages], fixed) \
                    if len(job.pages) > 1 else None
                job.page_ends = ends
            job.duration = round(job.ends[-1], 3) if job.ends else round(job.size / MP3_BYTES_PER_SECOND, 3)
            record_usage(len(payload.get("text") or ""))
            job.notice = getattr(g, "voice_notice", "") or ""
            job.finish()
        except Exception as e:
            if job.size:
                # Cut off partway: what was heard is kept.
                try:
                    with open(os.path.join(AUDIO_DIR, job.filename), "wb") as f:
                        f.write(b"".join(job.chunks))
                except OSError:
                    pass
                log_server_event(f"Streaming: cut off after {job.size} bytes: {e!r}")
                job.finish(error="The voice was cut off partway.")
                return
            # Nothing was heard yet: the usual whole-clip request, with its
            # step-down through the models. Its audio goes out the same way.
            log_server_event(f"Streaming: falling back to the whole-clip request: {e}")
            job.fell_back = True
            try:
                filename, ends, words = speak_reply(job.spoken, job.voice_id, job.language, job.pages, voiced=job.voiced)
                path = os.path.join(AUDIO_DIR, filename)
                with open(path, "rb") as f:
                    data = f.read()
                if filename != job.filename:
                    job.filename = filename
                job.word_times = words
                job.page_ends = ends
                job.push(data)
                record_usage(len(job.voiced))
                job.notice = getattr(g, "voice_notice", "") or ""
                job.finish()
            except Exception as e2:
                job.finish(error=str(e2) or "ElevenLabs couldn't speak this reply.")


def start_speech_stream(spoken, voiced, voice_id, language, pages):
    """Starts speaking a reply and returns its SpeechStream at once."""
    job = SpeechStream(spoken, voiced, pages, language, voice_id)
    payload = _elevenlabs_payload(voiced)   # with this request's voice settings
    carried = {key: getattr(g, key) for key in ("voice_style", "speech_thread", "speech_voice")
               if hasattr(g, key)}
    with SPEECH_STREAMS_LOCK:
        now = time.time()
        for old in [k for k, s in SPEECH_STREAMS.items() if s.done and now - s.created > SPEECH_STREAM_KEEP]:
            SPEECH_STREAMS.pop(old, None)
        SPEECH_STREAMS[job.id] = job
    threading.Thread(target=_stream_speech, args=(job, payload, carried), daemon=True,
                     name=f"speech-stream-{job.id[:8]}").start()
    return job


@app.route("/audio/stream/<stream_id>")
def audio_stream(stream_id):
    if not _STREAM_ID_RE.match(stream_id or ""):
        return jsonify({"error": "Not a reply."}), 404
    with SPEECH_STREAMS_LOCK:
        job = SPEECH_STREAMS.get(stream_id)
    if job is None:
        # Finished long ago (or Frivo restarted): the saved file, if kept.
        for ext in ("mp3", "wav"):
            if os.path.isfile(os.path.join(AUDIO_DIR, f"{stream_id}.{ext}")):
                return send_from_directory(AUDIO_DIR, f"{stream_id}.{ext}")
        return jsonify({"error": "That reply's audio has been cleaned up."}), 404

    def relay():
        sent = 0
        while True:
            with job.cond:
                while sent >= len(job.chunks) and not job.done:
                    job.cond.wait(timeout=30)
                    if sent >= len(job.chunks) and not job.done and time.time() - job.created > 120:
                        return
                pending = job.chunks[sent:]
                sent = len(job.chunks)
                finished = job.done
            for piece in pending:
                yield piece
            if finished and sent >= len(job.chunks):
                return

    return Response(relay(), mimetype="audio/mpeg",
                    headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


@app.route("/api/speech-stream/<stream_id>")
def speech_stream_timing(stream_id):
    with SPEECH_STREAMS_LOCK:
        job = SPEECH_STREAMS.get(stream_id or "")
    if job is None:
        return jsonify({"error": "Not found."}), 404
    wait = min(float(request.args.get("wait") or 0), 10.0)
    if wait and not job.done:
        with job.cond:
            job.cond.wait_for(lambda: job.done, timeout=wait)
    return jsonify(job.timing())


@app.route("/audio/<filename>")
def audio(filename):
    return send_from_directory(AUDIO_DIR, filename)


# ---------------------------------------------------------------------------
# NEW (1.5.0): saved replies
#
# A spoken reply can be saved, then played again later exactly as it was:
# the same audio, the same chatbox pages timed to the voice, the same
# glowing words. Playing one costs nothing and asks no AI anything.
#
# Kept in %APPDATA%\Frivo\saved\: a copy of each reply's audio, and
# saved.json listing them. Separate from audio_cache, so the 7-day clean-up
# never touches them; deleting one from the Saved list is the only way they
# go (and uninstalling with "remove my data").
# ---------------------------------------------------------------------------

SAVED_DIR = os.path.join(DATA_DIR, "saved")
SAVED_INDEX = os.path.join(SAVED_DIR, "saved.json")
SAVED_LOCK = threading.Lock()
_SAVED_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_SAVED_FILE_RE = re.compile(r"^[0-9a-f]{32}\.(mp3|wav)$")
SAVED_MAX_ITEMS = 1000
SAVED_MAX_TEXT = 5000


def load_saved():
    try:
        with open(SAVED_INDEX, "r", encoding="utf-8") as f:
            items = json.load(f)
        return [item for item in items if isinstance(item, dict) and _SAVED_ID_RE.match(str(item.get("id", "")))]
    except (OSError, ValueError, TypeError):
        return []


def write_saved(items):
    os.makedirs(SAVED_DIR, exist_ok=True)
    temp = SAVED_INDEX + ".tmp"
    with open(temp, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=1)
    os.replace(temp, SAVED_INDEX)


def _clean_word_times(value):
    """[[start, end], ...] of numbers, or None."""
    if not isinstance(value, list) or not value or len(value) > 5000:
        return None
    out = []
    for pair in value:
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            return None
        try:
            out.append([round(float(pair[0]), 3), round(float(pair[1]), 3)])
        except (TypeError, ValueError):
            return None
    return out


def _clean_pages(value):
    """The chatbox pages: [{text, start, at?}, ...], or []."""
    if not isinstance(value, list):
        return []
    pages = []
    for page in value[:200]:
        if not isinstance(page, dict) or not isinstance(page.get("text"), str):
            return []
        clean = {"text": page["text"][:CHATBOX_LIMIT + 20]}
        for key in ("start", "at"):
            if isinstance(page.get(key), (int, float)):
                clean[key] = float(page[key])
        clean.setdefault("start", 0.0)
        pages.append(clean)
    return pages


def saved_public(item):
    """What the page gets for one saved reply."""
    out = dict(item)
    out["audio_url"] = f"/saved-audio/{item['file']}"
    out.pop("source", None)
    return out


@app.route("/api/saved", methods=["GET"])
def saved_list():
    with SAVED_LOCK:
        items = load_saved()
    items.sort(key=lambda item: item.get("saved_at", 0), reverse=True)
    return jsonify({"items": [saved_public(item) for item in items]})


@app.route("/api/saved", methods=["POST"])
def saved_add():
    data = request.get_json(force=True) or {}
    audio_url = str(data.get("audio_url") or "")
    # NEW (1.5.0): a streamed reply is saved from its finished file.
    if audio_url.startswith("/audio/stream/"):
        stem = audio_url.rsplit("/", 1)[-1]
        with SPEECH_STREAMS_LOCK:
            job = SPEECH_STREAMS.get(stem)
        audio_url = f"/audio/{job.filename}" if job and job.done else f"/audio/{stem}.mp3"
    source = audio_url.rsplit("/", 1)[-1]
    text = str(data.get("text") or "").strip()
    if not audio_url.startswith("/audio/") or not _AUDIO_REPLY_RE.match(source):
        return jsonify({"error": "Only a spoken reply can be saved."}), 400
    if not text:
        return jsonify({"error": "That reply has no text to save."}), 400
    source_path = os.path.join(AUDIO_DIR, source)
    with SAVED_LOCK:
        items = load_saved()
        existing = next((item for item in items if item.get("source") == source), None)
        if existing:
            return jsonify({"ok": True, "item": saved_public(existing), "already": True})
        if not os.path.isfile(source_path):
            return jsonify({"error": "That reply's audio has already been cleaned up, so it can't be saved."}), 410
        if len(items) >= SAVED_MAX_ITEMS:
            return jsonify({"error": f"You have {SAVED_MAX_ITEMS} saved replies. Delete some to save more."}), 400
        ident = uuid.uuid4().hex
        filename = ident + os.path.splitext(source)[1]
        os.makedirs(SAVED_DIR, exist_ok=True)
        shutil.copyfile(source_path, os.path.join(SAVED_DIR, filename))
        item = {
            "id": ident,
            "file": filename,
            "source": source,
            "text": text[:SAVED_MAX_TEXT],
            # NEW (1.5.0): with its audio tags, to show them again.
            "voiced": str(data.get("voiced") or text)[:SAVED_MAX_TEXT + 600],
            "english": str(data.get("english") or "")[:SAVED_MAX_TEXT],
            "language": str(data.get("language") or "English")[:60],
            "voice_name": str(data.get("voice_name") or "")[:120],
            "voice_engine": str(data.get("voice_engine") or "")[:20],
            "voice_engine_name": str(data.get("voice_engine_name") or "")[:60],
            "voice_how": str(data.get("voice_how") or "")[:80],   # NEW (1.5.0)
            "profile_id": str(data.get("profile_id") or "")[:80],
            "profile_name": str(data.get("profile_name") or "")[:120],
            "word_times": _clean_word_times(data.get("word_times")),
            "chatbox_pages": _clean_pages(data.get("chatbox_pages")),
            "saved_at": time.time(),
        }
        items.append(item)
        write_saved(items)
    return jsonify({"ok": True, "item": saved_public(item)})


@app.route("/api/saved/<ident>", methods=["DELETE"])
def saved_delete(ident):
    if not _SAVED_ID_RE.match(ident or ""):
        return jsonify({"error": "Not found."}), 404
    with SAVED_LOCK:
        items = load_saved()
        item = next((i for i in items if i["id"] == ident), None)
        if not item:
            return jsonify({"error": "Not found."}), 404
        items = [i for i in items if i["id"] != ident]
        write_saved(items)
    try:
        if _SAVED_FILE_RE.match(item.get("file", "")):
            os.remove(os.path.join(SAVED_DIR, item["file"]))
    except OSError:
        pass
    return jsonify({"ok": True})


@app.route("/api/saved/<ident>/play", methods=["POST"])
def saved_play(ident):
    """
    A saved reply is about to be played. Nothing is generated or billed.
    It joins the conversation the AI remembers, as if it had just said it,
    when there's a conversation going for that profile.
    """
    if not _SAVED_ID_RE.match(ident or ""):
        return jsonify({"error": "Not found."}), 404
    with SAVED_LOCK:
        item = next((i for i in load_saved() if i["id"] == ident), None)
    if not item or not os.path.isfile(os.path.join(SAVED_DIR, item["file"])):
        return jsonify({"error": "That saved reply's audio is missing."}), 404
    data = request.get_json(silent=True) or {}
    key = f"{data.get('session_id') or 'default'}::{data.get('profile_id') or 'default'}"
    with SESSIONS_LOCK:
        if key in SESSIONS:
            SESSIONS[key].append({"role": "assistant", "content": item["text"]})
    return jsonify({"ok": True, "item": saved_public(item)})


def _saved_download_name(item, used=None):
    """A file name for a saved reply: who said it and its first words."""
    words = re.sub(r"[^\w\s'-]", "", strip_audio_tags(item.get("text", "")), flags=re.U).split()
    head = " ".join(words[:7]) or "reply"
    who = (item.get("profile_name") or item.get("voice_name") or "").strip()
    name = f"{who} - {head}" if who else head
    name = re.sub(r"[\\/:*?\"<>|]+", "", name).strip()[:90] or "reply"
    ext = os.path.splitext(item.get("file", ""))[1] or ".mp3"
    full = name + ext
    if used is not None:
        n = 2
        while full in used:
            full = f"{name} ({n}){ext}"
            n += 1
        used.add(full)
    return full


@app.route("/api/voice-anchor", methods=["GET", "POST", "DELETE"])
def voice_anchor_route():
    """
    NEW (1.5.0): the anchor for a voice (the default profile's, or
    ?voice_id=): GET says whether there is one and where to hear it; POST
    makes one now (or a new one, replacing the old); DELETE forgets it.
    """
    voice_id = (request.args.get("voice_id") or (request.get_json(silent=True) or {}).get("voice_id")
                or CFG.get("voice_id") or "").strip()
    language = normalize_language(request.args.get("language") or (request.get_json(silent=True) or {}).get("language")) \
        or CFG.get("language", "English")
    code = language_iso(language) or "en"
    if not voice_id or tts_engine(voice_id) != "elevenlabs":
        return jsonify({"error": "Anchors are for ElevenLabs voices."}), 400
    if request.method == "DELETE":
        forget_anchor(voice_id, code)
        return jsonify({"ok": True})
    if request.method == "POST":
        if not CFG.get("elevenlabs_api_key"):
            return jsonify({"error": "Add your ElevenLabs key first."}), 400
        forget_anchor(voice_id, code)
        delivery = DELIVERY_SETTINGS[normalize_voice_delivery(CFG.get("voice_delivery"))]["v3"]
        anchor = voice_anchor(voice_id, code, delivery)
        if not anchor:
            return jsonify({"error": "ElevenLabs didn't make the anchor. Check the server log; your account may not have v3."}), 502
    else:
        with ANCHORS_LOCK:
            anchor = load_anchors().get(anchor_key(voice_id, code))
    if not anchor:
        return jsonify({"anchor": None, "voice_id": voice_id, "language": code})
    return jsonify({"anchor": {
        "text": anchor.get("text", ""), "accent": anchor.get("accent", "auto"), "at": anchor.get("at", 0),
        "audio_url": f"/anchor-audio/{anchor['file']}" if anchor.get("file") else None,
    }, "voice_id": voice_id, "language": code})


@app.route("/anchor-audio/<filename>")
def anchor_audio(filename):
    if not re.match(r"^[0-9a-f]{32}\.mp3$", filename or ""):
        return jsonify({"error": "Not found."}), 404
    return send_from_directory(ANCHORS_DIR, filename)


@app.route("/api/saved/<ident>/download")
def saved_download(ident):
    """NEW (1.5.0): one saved reply's audio, as a file to keep."""
    if not _SAVED_ID_RE.match(ident or ""):
        return jsonify({"error": "Not found."}), 404
    with SAVED_LOCK:
        item = next((i for i in load_saved() if i["id"] == ident), None)
    if not item or not _SAVED_FILE_RE.match(item.get("file", "")) \
            or not os.path.isfile(os.path.join(SAVED_DIR, item["file"])):
        return jsonify({"error": "That saved reply's audio is missing."}), 404
    return send_from_directory(SAVED_DIR, item["file"], as_attachment=True,
                               download_name=_saved_download_name(item))


@app.route("/api/saved/export.zip")
def saved_export():
    """
    NEW (1.5.0): every saved reply in one zip: the audio files, named by who
    said them and their first words, and a saved.txt listing each one's full
    text, voice and date.
    """
    import io
    import zipfile
    with SAVED_LOCK:
        items = list(load_saved())
    items = [i for i in items if _SAVED_FILE_RE.match(i.get("file", ""))
             and os.path.isfile(os.path.join(SAVED_DIR, i["file"]))]
    if not items:
        return jsonify({"error": "Nothing saved yet."}), 404
    buf = io.BytesIO()
    used = set()
    lines = []
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for item in sorted(items, key=lambda i: i.get("saved_at", 0)):
            name = _saved_download_name(item, used)
            z.write(os.path.join(SAVED_DIR, item["file"]), name)
            when = time.strftime("%Y-%m-%d %H:%M", time.localtime(item.get("saved_at", 0))) if item.get("saved_at") else ""
            lines.append(f"{name}\n  {item.get('voiced') or item.get('text', '')}\n  "
                         + " · ".join(x for x in (item.get("voice_name"), item.get("profile_name"), when) if x)
                         + (f"\n  spoken as: {item['voice_how']}" if item.get("voice_how") else ""))
        z.writestr("saved.txt", "Frivo saved replies\n\n" + "\n\n".join(lines) + "\n")
    buf.seek(0)
    from flask import send_file
    return send_file(buf, mimetype="application/zip", as_attachment=True,
                     download_name=time.strftime("Frivo saved replies %Y-%m-%d.zip"))


# ---------------------------------------------------------------------------
# NEW (1.5.0): back up and restore (Settings > Updates & about).
#
# A backup is one zip with everything that makes Frivo yours:
#   frivo-backup.json    what's in it, and when it was made
#   data/config.json     your settings (API keys only if you ask)
#   data/profiles.json   your profiles
#   data/saved/...       your saved replies, with their audio
#   data/tag_taste.json  your tag taste
#   data/voice_anchors.json, data/anchors/...   Hold the accent anchors
#   data/voices/...      voices you added (only if you ask: they're big)
#   browser.json         what this browser keeps: favourite voices, your
#                        tags, recent voices and languages, the switches
#
# Restoring adds to what's here rather than wiping it: profiles and saved
# replies that aren't here yet are added (a profile with the same id is
# replaced by the backup's), settings are restored, except this server's
# own addresses (Ollama, Evora) and keys you already have.
#
# It also takes the zip of an older Frivo's data folder (the folder with
# config.json, profiles.json and saved\ in it, from before backups
# existed), and the "Export all" zip of saved replies.
# ---------------------------------------------------------------------------

BACKUP_FORMAT = 1
BACKUP_MAX_BYTES = 2 * 1024 ** 3
# Settings that belong to this server, not to you: kept as they are here.
BACKUP_KEEP_HERE = {"ollama_url", "whisper_url", "_moved_to_v4", "_evora_idle_off"}
BACKUP_SECRET_KEYS = {"openai_api_key", "elevenlabs_api_key"}
# What the page keeps in the browser that's worth carrying over.
BACKUP_BROWSER_PREFIXES = ("voice_console_", "frivo_")
BACKUP_BROWSER_SKIP = {"voice_console_session", "frivo_transcript_v1", "voice_console_mic_device_id",
                       "voice_console_listen_device"}
_ANCHOR_FILE_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,120}\.(mp3|wav)$")


def _read_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


@app.route("/api/backup", methods=["POST"])
def backup_make():
    import io
    import zipfile
    data = request.get_json(silent=True) or {}
    with_keys = data.get("include_keys") is True
    with_voices = data.get("include_voices") is True
    browser = data.get("browser") if isinstance(data.get("browser"), dict) else {}
    browser = {k: str(v)[:200000] for k, v in browser.items()
               if isinstance(k, str) and k.startswith(BACKUP_BROWSER_PREFIXES) and k not in BACKUP_BROWSER_SKIP}
    cfg = dict(CFG)
    if not with_keys:
        for key in BACKUP_SECRET_KEYS:
            cfg.pop(key, None)
    counts = {"profiles": 0, "saved": 0, "voices": 0}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("data/config.json", json.dumps(cfg, indent=2))
        profiles = load_profiles()
        counts["profiles"] = len(profiles)
        z.writestr("data/profiles.json", json.dumps(profiles, indent=2))
        with SAVED_LOCK:
            saved = load_saved()
        kept = []
        for item in saved:
            path = os.path.join(SAVED_DIR, item.get("file", ""))
            if _SAVED_FILE_RE.match(item.get("file", "")) and os.path.isfile(path):
                z.write(path, f"data/saved/{item['file']}")
                kept.append(item)
        z.writestr("data/saved/saved.json", json.dumps(kept, ensure_ascii=False, indent=1))
        counts["saved"] = len(kept)
        if os.path.isfile(TAG_TASTE_PATH):
            z.write(TAG_TASTE_PATH, "data/tag_taste.json")
        if os.path.isfile(ANCHORS_FILE):
            z.write(ANCHORS_FILE, "data/voice_anchors.json")
            if os.path.isdir(ANCHORS_DIR):
                for name in os.listdir(ANCHORS_DIR):
                    if _ANCHOR_FILE_RE.match(name):
                        z.write(os.path.join(ANCHORS_DIR, name), f"data/anchors/{name}")
        if with_voices:
            voices = load_custom_voices()
            z.writestr("data/voices/voices.json", json.dumps(voices, ensure_ascii=False, indent=1))
            for voice in voices:
                folder = os.path.join(CUSTOM_VOICES_DIR, voice["key"])
                for root, _, files in os.walk(folder):
                    for name in files:
                        full = os.path.join(root, name)
                        rel = os.path.relpath(full, CUSTOM_VOICES_DIR).replace(os.sep, "/")
                        z.write(full, f"data/voices/{rel}")
            counts["voices"] = len(voices)
        z.writestr("browser.json", json.dumps(browser, ensure_ascii=False, indent=1))
        z.writestr("frivo-backup.json", json.dumps({
            "format": BACKUP_FORMAT, "app": "Frivo", "version": APP_VERSION if "APP_VERSION" in globals() else "",
            "made": time.strftime("%Y-%m-%d %H:%M"), "keys": with_keys, "voices": with_voices, "counts": counts,
        }, indent=1))
    buf.seek(0)
    from flask import send_file
    return send_file(buf, mimetype="application/zip", as_attachment=True,
                     download_name=time.strftime("Frivo backup %Y-%m-%d.zip"))


def _backup_root(names):
    """Where the data is inside the zip: 'data/' in a backup, or the folder
    holding config.json / profiles.json / saved/ in a zipped data folder."""
    if "frivo-backup.json" in names:
        return "data/", "backup"
    for marker in ("config.json", "profiles.json", "saved/saved.json"):
        hits = sorted((n for n in names if n == marker or n.endswith("/" + marker)), key=len)
        if hits:
            return hits[0][: len(hits[0]) - len(marker)], "folder"
    if any(n.endswith("saved.txt") for n in names):
        return "", "saved-export"
    return None, None


def _import_saved_export(z, names, report):
    """The 'Export all' zip: audio files plus saved.txt with their text."""
    text = ""
    listing = next((n for n in names if n.endswith("saved.txt")), None)
    if listing:
        text = z.read(listing).decode("utf-8", "replace")
    blocks = {}
    for block in text.split("\n\n"):
        lines = block.strip("\n").split("\n")
        if len(lines) >= 2:
            blocks[lines[0].strip()] = {"text": lines[1].strip(), "meta": (lines[2].strip() if len(lines) > 2 else "")}
    with SAVED_LOCK:
        items = load_saved()
        for name in names:
            if not re.search(r"\.(mp3|wav)$", name, re.I) or len(items) >= SAVED_MAX_ITEMS:
                continue
            info = blocks.get(name.split("/")[-1]) or blocks.get(name) or {}
            voiced = info.get("text") or os.path.splitext(name.split("/")[-1])[0]
            new_id = uuid.uuid4().hex
            ext = name.rsplit(".", 1)[-1].lower()
            os.makedirs(SAVED_DIR, exist_ok=True)
            with open(os.path.join(SAVED_DIR, f"{new_id}.{ext}"), "wb") as f:
                f.write(z.read(name))
            meta = [m.strip() for m in info.get("meta", "").split("·")]
            items.append({"id": new_id, "file": f"{new_id}.{ext}", "text": strip_audio_tags(voiced) or voiced,
                          "voiced": voiced[:SAVED_MAX_TEXT + 600], "voice_name": meta[0] if meta else "",
                          "profile_name": meta[1] if len(meta) > 1 else "", "saved_at": time.time()})
            report["saved"] += 1
        write_saved(items)


@app.route("/api/backup/restore", methods=["POST"])
def backup_restore():
    import zipfile
    upload = request.files.get("file")
    if not upload:
        return jsonify({"error": "Choose a backup (.zip) to restore."}), 400
    try:
        z = zipfile.ZipFile(upload.stream)
        names = [n for n in z.namelist() if not n.endswith("/") and ".." not in n and not n.startswith("/")]
    except zipfile.BadZipFile:
        return jsonify({"error": "That isn't a zip file. Choose a Frivo backup (.zip)."}), 400
    root, kind = _backup_root(names)
    if kind is None:
        return jsonify({"error": "That zip has no Frivo settings, profiles or saved replies in it."}), 400
    report = {"kind": kind, "settings": 0, "profiles": 0, "saved": 0, "voices": 0, "anchors": 0, "taste": False,
              "keys": 0, "browser": {}}
    if kind == "saved-export":
        _import_saved_export(z, names, report)
        return jsonify(report)

    def member(rel):
        return root + rel if root + rel in names else None

    # Settings: yours, but this server's addresses and keys already here stay.
    path = member("config.json")
    if path:
        try:
            incoming = json.loads(z.read(path).decode("utf-8"))
        except ValueError:
            incoming = {}
        if isinstance(incoming, dict):
            for key, value in incoming.items():
                if key in BACKUP_KEEP_HERE or not isinstance(key, str):
                    continue
                if key in BACKUP_SECRET_KEYS:
                    if value and not CFG.get(key):
                        CFG[key] = value
                        report["keys"] += 1
                    continue
                if CFG.get(key) != value:
                    report["settings"] += 1
                CFG[key] = value
            save_config(CFG)
    # Profiles: added, or replaced when the backup has the same one.
    path = member("profiles.json")
    if path:
        try:
            incoming = json.loads(z.read(path).decode("utf-8"))
        except ValueError:
            incoming = []
        if isinstance(incoming, list):
            current = load_profiles()
            by_id = {p.get("id"): i for i, p in enumerate(current) if isinstance(p, dict)}
            for p in incoming:
                if not isinstance(p, dict) or not p.get("id"):
                    continue
                if p["id"] in by_id:
                    current[by_id[p["id"]]] = p
                else:
                    current.append(p)
                report["profiles"] += 1
            save_profiles(current)
    # Saved replies: the ones not here yet, with their audio.
    path = member("saved/saved.json")
    if path:
        try:
            incoming = json.loads(z.read(path).decode("utf-8"))
        except ValueError:
            incoming = []
        with SAVED_LOCK:
            items = load_saved()
            have = {i.get("id") for i in items}
            for item in incoming if isinstance(incoming, list) else []:
                if not isinstance(item, dict) or item.get("id") in have or not _SAVED_ID_RE.match(str(item.get("id", ""))):
                    continue
                audio = member(f"saved/{item.get('file', '')}")
                if not audio or not _SAVED_FILE_RE.match(item.get("file", "")) or len(items) >= SAVED_MAX_ITEMS:
                    continue
                os.makedirs(SAVED_DIR, exist_ok=True)
                with open(os.path.join(SAVED_DIR, item["file"]), "wb") as f:
                    f.write(z.read(audio))
                items.append(item)
                report["saved"] += 1
            write_saved(items)
    # Tag taste: the counts added together.
    path = member("tag_taste.json")
    if path:
        try:
            incoming = json.loads(z.read(path).decode("utf-8"))
        except ValueError:
            incoming = {}
        if isinstance(incoming, dict):
            with TAG_TASTE_LOCK:
                taste = load_tag_taste()
                for tag, e in incoming.items():
                    if not isinstance(e, dict):
                        continue
                    mine = taste.setdefault(tag, {"kept": 0, "removed": 0, "added": 0})
                    for k in ("kept", "removed", "added"):
                        mine[k] = int(mine.get(k, 0)) + int(e.get(k, 0) or 0)
                    mine["at"] = max(float(mine.get("at", 0)), float(e.get("at", 0) or 0))
                os.makedirs(DATA_DIR, exist_ok=True)
                with open(TAG_TASTE_PATH, "w", encoding="utf-8") as f:
                    json.dump(taste, f, indent=1)
                report["taste"] = True
    # Hold the accent anchors: the ones not here yet.
    path = member("voice_anchors.json")
    if path:
        try:
            incoming = json.loads(z.read(path).decode("utf-8"))
        except ValueError:
            incoming = {}
        if isinstance(incoming, dict):
            with ANCHORS_LOCK:
                anchors = load_anchors()
                for key, entry in incoming.items():
                    if key in anchors or not isinstance(entry, dict):
                        continue
                    audio = member(f"anchors/{entry.get('file', '')}") if entry.get("file") else None
                    if audio and _ANCHOR_FILE_RE.match(entry["file"]):
                        os.makedirs(ANCHORS_DIR, exist_ok=True)
                        with open(os.path.join(ANCHORS_DIR, entry["file"]), "wb") as f:
                            f.write(z.read(audio))
                    anchors[key] = entry
                    report["anchors"] += 1
                write_anchors(anchors)
    # Voices you added: the ones not here yet.
    path = member("voices/voices.json")
    if path:
        try:
            incoming = json.loads(z.read(path).decode("utf-8"))
        except ValueError:
            incoming = []
        with CUSTOM_VOICES_LOCK:
            voices = load_custom_voices()
            have = {v["key"] for v in voices}
            for voice in incoming if isinstance(incoming, list) else []:
                key = str((voice or {}).get("key", ""))
                if not _CUSTOM_KEY_RE.match(key) or key in have or len(voices) >= CUSTOM_VOICE_MAX_COUNT:
                    continue
                prefix = f"{root}voices/{key}/"
                files = [n for n in names if n.startswith(prefix)]
                if not files:
                    continue
                for n in files:
                    rel = n[len(prefix):]
                    if not rel or "/" in rel or not re.match(r"^[A-Za-z0-9_.\-]{1,120}$", rel):
                        continue
                    os.makedirs(os.path.join(CUSTOM_VOICES_DIR, key), exist_ok=True)
                    with open(os.path.join(CUSTOM_VOICES_DIR, key, rel), "wb") as f:
                        f.write(z.read(n))
                voices.append(voice)
                report["voices"] += 1
            write_custom_voices(voices)
    # What the browser keeps: sent back, for the page to put in place.
    if "browser.json" in names:
        try:
            browser = json.loads(z.read("browser.json").decode("utf-8"))
        except ValueError:
            browser = {}
        if isinstance(browser, dict):
            report["browser"] = {k: v for k, v in browser.items()
                                 if isinstance(k, str) and k.startswith(BACKUP_BROWSER_PREFIXES)
                                 and k not in BACKUP_BROWSER_SKIP and isinstance(v, str)}
    log_server_event(f"Restored a backup ({kind}): {report['profiles']} profiles, {report['saved']} saved replies, "
                     f"{report['settings']} settings, {report['voices']} voices")
    return jsonify(report)


@app.route("/saved-audio/<filename>")
def saved_audio(filename):
    if not _SAVED_FILE_RE.match(filename or ""):
        return jsonify({"error": "Not found."}), 404
    return send_from_directory(SAVED_DIR, filename)


def local_ip_addresses():
    """
    Best-effort list of this machine's LAN IPv4 addresses, so the
    self-signed certificate below can cover whatever address other devices
    on the network actually use to reach it. The UDP "connect" doesn't send
    any real traffic — it's just how the OS is asked which local interface
    a connection to that address would go out on.
    """
    ips = {"127.0.0.1"}
    try:
        hostname_ip = socket.gethostbyname(socket.gethostname())
        if hostname_ip and not hostname_ip.startswith("127."):
            ips.add(hostname_ip)
    except Exception:
        pass
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            ips.add(s.getsockname()[0])
        finally:
            s.close()
    except Exception:
        pass
    return sorted(ips)


LOCAL_HOSTNAME = "frivo.local"

# Names the server certificate must answer to. "localhost" is what the
# machine itself uses; "frivo.local" is the friendly name the installer
# points at 127.0.0.1 via the hosts file, and only resolves on the PC
# Frivo is installed on. Other devices on the LAN reach it by IP, which is
# why every local IP address also lands in the SAN list below.
CERT_HOSTNAMES = ("localhost", LOCAL_HOSTNAME, "frivo")


def local_hostname_available():
    """
    True when frivo.local resolves back to this machine.

    The installer writes "127.0.0.1 frivo.local" into the Windows hosts
    file, which makes the friendly name work on the PC Frivo is installed
    on and nowhere else — hosts files are per-machine, so another device on
    the LAN has no way to resolve it and must use the IP address instead.
    Checking rather than assuming keeps the printed address list honest
    when the app is run from a copy that was never installed.
    """
    try:
        return socket.gethostbyname(LOCAL_HOSTNAME).startswith("127.")
    except Exception:
        return False


def _cert_files_are_current():
    """
    True only if the certificate pair on disk was made by this version of
    the app AND still covers every address this machine answers on.

    Four things make an old cert worth throwing away:

    1. There's no separate CA file — it predates the split below, so it's a
       single self-signed certificate. Chrome will not accept one of those
       as a server certificate no matter what store it's installed into.
    2. The server certificate wasn't issued by the CA currently on disk, so
       a device that trusts the CA still won't trust the server.
    3. This machine's LAN IP changed (DHCP lease moved, docked to a
       different network, a VPN adapter appeared). A certificate whose SAN
       list doesn't include the address the browser typed is rejected
       outright, and if that browser also has the "Proceed anyway" link
       disabled by policy it becomes an unfixable-looking dead end.
    """
    needed = (CERT_PATH, KEY_PATH, CA_CERT_PATH, CA_KEY_PATH)
    if not all(os.path.exists(p) for p in needed):
        return False

    try:
        import ipaddress

        from cryptography import x509
    except ImportError:
        # Can't inspect them, but they exist — better to reuse than to fail.
        return True

    try:
        with open(CERT_PATH, "rb") as f:
            leaf = x509.load_pem_x509_certificate(f.read())
        with open(CA_CERT_PATH, "rb") as f:
            ca = x509.load_pem_x509_certificate(f.read())

        # The leaf must be an end-entity certificate, not a CA.
        if leaf.extensions.get_extension_for_class(x509.BasicConstraints).value.ca:
            return False

        # ...and must actually have been issued by the CA sitting next to it.
        if leaf.issuer != ca.subject:
            return False

        san = leaf.extensions.get_extension_for_class(x509.SubjectAlternativeName)

        # 4. The cert predates frivo.local (or any other name added since),
        #    so typing that address would trip a name-mismatch warning.
        names = {n.lower() for n in san.value.get_values_for_type(x509.DNSName)}
        for host in CERT_HOSTNAMES:
            if host.lower() not in names:
                return False

        covered = set(san.value.get_values_for_type(x509.IPAddress))
        for ip in local_ip_addresses():
            try:
                if ipaddress.ip_address(ip) not in covered:
                    return False
            except ValueError:
                pass
    except Exception:
        return False

    return True


def ensure_self_signed_cert():
    """
    Creates a small local certificate authority and a server certificate
    signed by it, then reuses both on later runs.

    Browsers require HTTPS before they allow microphone access on a LAN
    address. A local CA is used because public authorities do not issue
    certificates for private LAN IP addresses.

    The CA and server certificate are separate because browsers cannot use a
    CA certificate as a server certificate:

      ca.pem   — the authority. ca=TRUE, signs certificates, is never
                 presented to a browser. This is the file to install on
                 other devices, once.
      cert.pem — the server certificate. ca=FALSE, carries the SAN list of
                 this machine's addresses, signed by the CA above. This is
                 what the server presents. Never installed anywhere.

    The CA is retained for 10 years and server certificates for 2 years.

    Returns (None, None) if the optional `cryptography` package isn't
    installed, so plain HTTP still works — it just won't unlock the mic on
    devices other than this one.
    """
    if _cert_files_are_current():
        return CERT_PATH, KEY_PATH

    try:
        import datetime
        import ipaddress

        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
    except ImportError:
        return None, None

    now = datetime.datetime.now(datetime.timezone.utc)
    pem = serialization.Encoding.PEM

    def write_key(path, key_obj):
        with open(path, "wb") as f:
            f.write(
                key_obj.private_bytes(
                    encoding=pem,
                    format=serialization.PrivateFormat.TraditionalOpenSSL,
                    encryption_algorithm=serialization.NoEncryption(),
                )
            )

    # --- The authority -------------------------------------------------
    # Reused if one already exists, so installing it on a device is a
    # one-time job even when the server certificate is later reissued.
    ca_exists = os.path.exists(CA_CERT_PATH) and os.path.exists(CA_KEY_PATH)
    if ca_exists:
        try:
            with open(CA_CERT_PATH, "rb") as f:
                ca_cert = x509.load_pem_x509_certificate(f.read())
            with open(CA_KEY_PATH, "rb") as f:
                ca_key = serialization.load_pem_private_key(f.read(), password=None)
        except Exception:
            ca_exists = False

    if not ca_exists:
        ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        ca_name = x509.Name(
            [
                x509.NameAttribute(NameOID.COMMON_NAME, "Frivo Local CA"),
                x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Frivo"),
            ]
        )
        ca_cert = (
            x509.CertificateBuilder()
            .subject_name(ca_name)
            .issuer_name(ca_name)
            .public_key(ca_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=3650))
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .add_extension(
                x509.KeyUsage(
                    digital_signature=True,
                    key_cert_sign=True,
                    crl_sign=True,
                    key_encipherment=False,
                    content_commitment=False,
                    data_encipherment=False,
                    key_agreement=False,
                    encipher_only=False,
                    decipher_only=False,
                ),
                critical=True,
            )
            .add_extension(
                x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()),
                critical=False,
            )
            .sign(ca_key, hashes.SHA256())
        )

        ca_bytes = ca_cert.public_bytes(pem)
        with open(CA_CERT_PATH, "wb") as f:
            f.write(ca_bytes)
        # Same bytes, second extension: Windows only offers "Install
        # Certificate" on the right-click menu for .crt, not .pem.
        with open(CA_CERT_CRT_PATH, "wb") as f:
            f.write(ca_bytes)
        write_key(CA_KEY_PATH, ca_key)

    # --- The server certificate ----------------------------------------
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    san_entries = [x509.DNSName(host) for host in CERT_HOSTNAMES]
    for ip in local_ip_addresses():
        try:
            san_entries.append(x509.IPAddress(ipaddress.ip_address(ip)))
        except ValueError:
            pass

    leaf = (
        x509.CertificateBuilder()
        .subject_name(
            x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Frivo")])
        )
        .issuer_name(ca_cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        # Browsers reject leaf certificates valid for more than 825 days.
        .not_valid_after(now + datetime.timedelta(days=730))
        .add_extension(x509.SubjectAlternativeName(san_entries), critical=False)
        # The server certificate must be an end-entity certificate.
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_encipherment=True,
                key_cert_sign=False,
                crl_sign=False,
                content_commitment=False,
                data_encipherment=False,
                key_agreement=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),
            critical=False,
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(key.public_key()),
            critical=False,
        )
        # Ties the leaf to the CA that signed it, so a browser holding the
        # CA can find the path from one to the other.
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )

    # Leaf first, then the CA: serving the full chain lets clients that
    # already trust the CA verify without needing to look anything up.
    with open(CERT_PATH, "wb") as f:
        f.write(leaf.public_bytes(pem))
        f.write(ca_cert.public_bytes(pem))
    write_key(KEY_PATH, key)

    return CERT_PATH, KEY_PATH


def serve(host, port, cert_path, key_path):
    """
    Serves the app, preferring cheroot over Flask's built-in dev server.

    This matters far more than it looks. Werkzeug's development server is
    fine for plain HTTP on one machine, but its TLS support is a thin
    ssl.wrap_socket around a server that was never designed for it: the
    handshake happens inline on the accept path, so a slow or aborted
    handshake stalls every other pending connection, and a handshake that
    errors (which browsers cause routinely — TLS probes, prefetch
    connections opened then dropped, favicon requests racing the page) can
    take the whole process down. The symptoms are exactly "loads sometimes",
    "runs like crap", and "Ctrl+C doesn't respond" — because the server is
    already wedged or dead, not busy.

    cheroot is the HTTP server CherryPy uses. It's pure Python (so it
    installs on Windows with no compiler), it's threaded with a real
    connection queue, and its SSL adapter treats failed handshakes as
    ordinary dropped connections instead of fatal errors. Same app, same
    cert — just a server that can actually hold up under a browser.

    Falls back to Werkzeug if cheroot isn't installed, so the app still
    runs; it just prints how to make it good.
    """
    global SERVER_BACKEND

    # NEW (updates): only a running server checks for updates — importing
    # app.py (the tests do) must not start talking to GitHub.
    start_update_checker()
    # NEW (1.5.0): start the Windows speech helper in the background.
    # CHANGED (1.5.0): and move anything off the removed Kokoro voices.
    threading.Thread(target=warm_free_voices, name="free-voices-warm", daemon=True).start()
    # NEW (1.5.0): delete old reply audio now, and every six hours after.
    threading.Thread(target=audio_prune_loop, name="audio-prune", daemon=True).start()
    # NEW (1.5.0): keep the last ten minutes of graphics-card memory for the graph.
    threading.Thread(target=gpu_sampler_loop, name="gpu-graph", daemon=True).start()
    # NEW (1.5.0): and puts the idle timer on a model loaded before this start.
    threading.Thread(target=apply_ollama_idle_timer, kwargs={"wait": 5}, name="ollama-idle", daemon=True).start()
    # NEW (1.5.0): and Evora's, in case they were changed while it was off.
    threading.Thread(target=apply_evora_idle_timers, kwargs={"wait": 6}, name="evora-idle", daemon=True).start()

    try:
        import cheroot
        from cheroot.wsgi import Server as CherootServer
    except ImportError:
        cheroot = None
        CherootServer = None

    scheme = "https" if (cert_path and key_path) else "http"

    if CherootServer is None:
        SERVER_BACKEND = "Flask development server (DEGRADED)"
        print("-" * 70)
        print(">> Server: Flask development server — NOT RECOMMENDED")
        print("This is the cause of slow loads, dropped connections and the server")
        print("falling over under HTTPS. cheroot is a drop-in replacement:")
        print(f'  & "{sys.executable}" -m pip install cheroot')
        print("Restart afterwards; this block should be gone and the line above")
        print("should read 'Server: cheroot'.")
        print("-" * 70)
        app.run(
            host=host,
            port=port,
            debug=False,
            threaded=True,
            ssl_context=(cert_path, key_path) if scheme == "https" else None,
        )
        return

    SERVER_BACKEND = f"cheroot {getattr(cheroot, '__version__', '?')}"
    print(f">> Server: {SERVER_BACKEND}")

    class QuietServer(CherootServer):
        """
        Same server, minus the console spam.

        Browsers routinely open TLS connections they never finish: prefetch
        sockets opened and dropped, connection races when several requests
        start at once, and — with a self-signed cert — an aborted handshake
        every time someone lands on the warning page. Each one logs a
        multi-line SSL error by default. None of them are actionable, and a
        wall of red scrolling past is what makes a working server look
        broken. Genuine errors still print.
        """

        BENIGN = (
            "plain HTTP into a TCP connection",
            "peer dropped the TLS connection",
            "WRONG_VERSION_NUMBER",
            "UNEXPECTED_EOF_WHILE_READING",
            "HTTP_REQUEST",
            "CERTIFICATE_UNKNOWN",
            "CERTIFICATE_VERIFY_FAILED",
            "UNKNOWN_CA",
            "TLSV1_ALERT",
            "SSLV3_ALERT",
            "ConnectionResetError",
            "ConnectionAbortedError",
            # The client hung up mid-response: closed the tab, navigated
            # away, or dropped off wifi. Routine, and the traceback is about
            # our own socket rather than anything actionable.
            "BrokenPipeError",
            "Broken pipe",
            "socket.error",
            "EPIPE",
        )

        def error_log(self, msg="", level=20, traceback=False):
            # Everything, filtered or not, goes to the log file. The console
            # gets the short list. When something is actually wrong, the
            # file is the thing worth reading.
            log_server_event(msg)
            if any(marker in msg for marker in self.BENIGN):
                return
            super().error_log(msg, level, traceback)

    server = QuietServer(
        (host, port),
        app,
        server_name="voice-console",
        # Generous for a personal LAN app. Each in-flight request holds one
        # thread for its whole duration, and a single reply here can occupy
        # one for 30+ seconds while OpenAI and ElevenLabs are called. Too
        # few threads and a couple of slow replies stall every other
        # request, which from the browser is indistinguishable from the
        # server having dropped.
        numthreads=30,
        # Queue depth for connections waiting on a free thread. Generous so
        # a burst of parallel browser connections queues instead of being
        # refused, which is what shows up as a page half-loading.
        request_queue_size=100,
    )
    # Idle socket timeout. Long enough that a slow OpenAI/ElevenLabs round
    # trip is never cut off mid-reply, short enough that genuinely dead
    # connections release their thread.
    server.timeout = 180
    # Keep-alive connections cost almost nothing here and save a full TLS
    # handshake per request. Raising this matters on a LAN with a browser
    # that opens several parallel connections per page.
    server.keep_alive_conn_limit = 100

    if scheme == "https":
        from cheroot.ssl.builtin import BuiltinSSLAdapter

        server.ssl_adapter = BuiltinSSLAdapter(cert_path, key_path)

    if local_hostname_available():
        print(f"  {scheme}://{LOCAL_HOSTNAME}:{port}   <- this PC only")
    for ip in local_ip_addresses():
        print(f"  {scheme}://{ip}:{port}")
    print("Press CTRL+C to quit")

    # Run the server on a worker thread so Ctrl+C can request a bounded shutdown.
    stopping = threading.Event()

    def request_shutdown(signum, frame):
        stopping.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, request_shutdown)
        except (ValueError, AttributeError, OSError):
            # Not on the main thread, or the platform lacks this signal.
            pass

    log_server_event(f"--- started on {scheme}://{host}:{port} via {SERVER_BACKEND} ---")

    def run_server():
        try:
            server.start()
        except Exception as exc:
            log_server_event(f"SERVER THREAD DIED: {exc!r}")
            import traceback as tb

            log_server_event(tb.format_exc())

    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()

    # Supervisor. If the accept loop ever dies — an unexpected exception, a
    # socket the OS took away — bring it back rather than leaving a process
    # that's running but answering nothing. That state is the worst one to
    # debug from the browser side, because it looks exactly like the network
    # dropped. Restarts are recorded in server.log with a reason.
    restarts = 0
    try:
        while not stopping.is_set():
            stopping.wait(0.5)
            if stopping.is_set():
                break
            if not server_thread.is_alive():
                restarts += 1
                if restarts > 5:
                    print("Server keeps failing to stay up — see server.log. Exiting.")
                    log_server_event("gave up after 5 restart attempts")
                    break
                msg = f"accept loop stopped unexpectedly — restarting ({restarts}/5)"
                print(msg)
                log_server_event(msg)
                time.sleep(1)
                server_thread = threading.Thread(target=run_server, daemon=True)
                server_thread.start()
    except KeyboardInterrupt:
        pass

    print("\nShutting down…")

    stopper = threading.Thread(target=server.stop, daemon=True)
    stopper.start()
    stopper.join(5)

    # Anything still holding on after a graceful stop is a stuck socket, not
    # work worth waiting for. Exit rather than leaving a process that has to
    # be killed from Task Manager.
    sys.stdout.flush()
    os._exit(0)


if __name__ == "__main__":
    # host="0.0.0.0" makes it reachable from other devices on your network.
    # Change to "127.0.0.1" to restrict it to this machine only.
    #
    # HTTPS (self-signed) is used by default so the dictation mic button
    # works from other devices on the network, not just from localhost on
    # this machine — see ensure_self_signed_cert() above for why. It also
    # means your API keys travel encrypted between browser and server
    # instead of in plain HTTP. Set VOICE_CONSOLE_HTTP=1 to force plain
    # HTTP instead (dictation will then only work when the app is opened
    # as http://localhost:5000 on this machine).
    # Without this, startup messages sit in a buffer and don't appear until
    # the process exits whenever stdout isn't a live console — piping to a
    # log file, running under a service wrapper, or launching from a script.
    # Those are exactly the situations where seeing which mode it started in
    # matters most, so flush as we go.
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass

    if "--prepare-certs" in sys.argv:
        # Used by the installer: create (or refresh) the CA and server
        # certificate without starting the server, so setup can import
        # ca.crt into the Windows trusted-root store in the same run. Exits
        # non-zero on failure so setup notices instead of importing an old
        # or missing file.
        try:
            cp, kp = ensure_self_signed_cert()
        except Exception as exc:
            print(f"certificate generation failed: {exc}")
            sys.exit(1)
        if not (cp and kp and os.path.exists(CA_CERT_CRT_PATH)):
            print("certificate generation did not produce the expected files")
            sys.exit(1)
        print(CA_CERT_CRT_PATH)
        sys.exit(0)

    forced_http = bool(os.environ.get("VOICE_CONSOLE_HTTP"))

    cert_path = key_path = None
    if not forced_http:
        cert_path, key_path = ensure_self_signed_cert()

    if cert_path and key_path:
        print("Starting with HTTPS (self-signed) so dictation works from other devices.")
        print("First connect from each device shows a security warning — click")
        print("'Advanced' then 'Proceed'. That's expected for a self-signed")
        print("certificate on a private network.")
        print()
        print("To remove the warning on a device for good — and the only option if")
        print("that browser won't let you click 'Proceed', which some managed")
        print("Chrome and Edge profiles block by policy — copy this ONE file to it:")
        print(f"  {CA_CERT_CRT_PATH}")
        print("  Double-click it -> Install Certificate -> Local Machine ->")
        print("  Place all certificates in the following store ->")
        print("  Trusted Root Certification Authorities -> Finish.")
        print("  Then fully quit and reopen the browser.")
        print()
        print("Install ca.crt, never cert.pem — cert.pem is the server's own")
        print("certificate and browsers reject it as a trusted root by design.")
        print()
        serve("0.0.0.0", 5000, cert_path, key_path)
    elif forced_http:
        # Deliberate, via VOICE_CONSOLE_HTTP=1 — so state the trade-off
        # plainly rather than shouting about a missing package that isn't
        # actually the problem here.
        print("Starting with plain HTTP (VOICE_CONSOLE_HTTP is set).")
        print("Dictation will only work at http://localhost:5000 on this machine —")
        print("browsers block microphone access over plain HTTP everywhere else.")
        print("Unset VOICE_CONSOLE_HTTP to go back to HTTPS.")
        print()
        serve("0.0.0.0", 5000, None, None)
    else:
        # Loud and impossible to scroll past — this exact situation (the
        # 'cryptography' package installed, but for a *different* Python
        # than the one running this file — e.g. a venv vs system Python on
        # Windows) is what silently drops the app back to plain HTTP. If a
        # browser is then pointed at https://, Werkzeug ends up trying to
        # parse raw TLS handshake bytes as plaintext HTTP and floods the
        # console with "Bad request version" errors that look unrelated to
        # this — so this message names the actual interpreter to fix it
        # with, not just the package name.
        banner = "!" * 70
        print(banner)
        print("Starting with plain HTTP — the 'cryptography' package isn't installed")
        print(f"for THIS Python: {sys.executable}")
        print("Dictation will only work when this app is opened as")
        print("http://localhost:5000 on this machine; browsers block microphone")
        print("access over plain HTTP on any other address, and pointing a browser")
        print("at an https:// URL against a plain-HTTP server floods this console")
        print('with "Bad request version" errors — that\'s this, not a real attack.')
        print()
        print("Fix — install it for the exact interpreter running this file:")
        print(f'  "{sys.executable}" -m pip install cryptography')
        print(banner)
        serve("0.0.0.0", 5000, None, None)
