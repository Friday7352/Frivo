"""Exercise production route functions without starting unrelated providers."""
import ast
import io
import re
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests
from flask import Flask, jsonify, request, redirect
from urllib.parse import urlsplit


@pytest.fixture
def backend():
    source = Path(__file__).parents[1] / "app" / "app.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    names = {"group_listen_segments", "local_whisper_transcribe_verbose", "listen", "listen_session", "evora_speaker_settings"}
    functions = ast.Module(body=[n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names], type_ignores=[])
    env = dict(app=Flask(__name__), requests=requests, request=request, jsonify=jsonify, time=time, re=re, redirect=redirect, urlsplit=urlsplit,
               EVORA_TRANSCRIPTION_LOCK=threading.Lock(), LOCAL_CONNECT_TIMEOUT=2, LOCAL_READ_TIMEOUT=5,
               whisper_base_url=lambda: "http://evora.test:9000", normalize_language=lambda x: x,
               language_iso=lambda x: x, resolve_provider=lambda *_: "local_whisper", TRANSCRIPTION_PROVIDERS=[],
               fallback_allowed=lambda: False, log_server_event=lambda *_: None)
    exec(compile(functions, str(source), "exec"), env)
    return env


def test_speaker_setup_uses_configured_remote_evora(backend):
    response = backend["app"].test_client().get("/api/evora-speaker-settings")
    assert response.status_code == 302
    assert response.headers["Location"] == "http://evora.test:9000/speaker-settings"
    backend["whisper_base_url"] = lambda: "javascript:alert(1)"
    assert backend["app"].test_client().get("/api/evora-speaker-settings").status_code == 400


def test_simultaneous_tracks_translate_separately(backend, monkeypatch):
    segments = [{"start": start, "end": start + .3, "text": word,
                 "speaker": {"id": speaker, "confirmed": True}, "source": "separated", "overlapping": True}
                for start, speaker, word in [(0, 1, " Hello"), (0, 2, " Good"), (.5, 1, " Alice"), (.5, 2, " morning")]]
    payload = {"text": "mixed", "language": "en", "segments": segments,
               "speaker_status": {"state": "ready"}}
    sent = []
    def post(url, **kw):
        sent.append(kw)
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: payload)
    monkeypatch.setattr(requests, "post", post)
    translated = []
    backend["translate_text"] = lambda text, lang: translated.append(text) or "translated:" + text
    result = backend["app"].test_client().post("/api/listen", data={
        "audio": (io.BytesIO(b"audio"), "clip.wav"), "target_language": "de", "listening_session": "session123"})
    assert result.status_code == 200
    assert translated == ["Hello Alice", "Good morning"]
    assert [s["speaker"]["id"] for s in result.json["segments"]] == [1, 2]
    assert sent[0]["data"]["listening_session"] == "session123"


def test_quick_turns_are_not_combined_across_other_speakers(backend):
    rows = backend["group_listen_segments"]([
        {"start": i * .4, "end": i * .4 + .3, "text": " hi", "speaker": {"id": ident}, "source": "clean"}
        for i, ident in enumerate((1, 2, 1))])
    assert [r["speaker"]["id"] for r in rows] == [1, 2, 1]


def test_unknown_overlap_is_kept_separate_from_known_voice(backend):
    rows = backend["group_listen_segments"]([
        {"start": 0, "end": 1, "text": " hello", "speaker": {"id": 1}, "source": "clean"},
        {"start": 1, "end": 2, "text": " mixed", "speaker": None, "source": "overlap", "overlapping": True}])
    assert len(rows) == 2 and rows[1]["speaker"] is None and rows[1]["overlapping"]


def test_overlap_language_is_translated_independently(backend, monkeypatch):
    payload = {"text": "Hello Bonjour", "language": "en", "segments": [
        {"start":0,"end":1,"text":"Hello","source":"separated","language":"en","track":"a"},
        {"start":0,"end":1,"text":"Bonjour","source":"separated","language":"fr","track":"b",
         "voice_track":{"id":"track-b","label":"Voice track 1","verified":False}}]}
    monkeypatch.setattr(requests, 'post', lambda *a, **k: SimpleNamespace(raise_for_status=lambda: None, json=lambda: payload))
    translated = []
    backend['translate_text'] = lambda text, lang: translated.append(text) or 'Hello'
    response = backend['app'].test_client().post('/api/listen', data={
        'audio':(io.BytesIO(b'audio'),'clip.wav'),'target_language':'en'})
    assert response.status_code == 200
    assert translated == ['Bonjour']
    assert [r['detected_language'] for r in response.json['segments']] == ['en','fr']
    assert response.json['segments'][1]['voice_track']['id'] == 'track-b'
