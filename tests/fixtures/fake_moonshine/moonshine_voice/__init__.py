"""A stand-in for moonshine-voice, for Frivo's tests (tests/test-builtin-dictation.py).

Same names and shapes as the parts of moonshine-voice 0.1.5 that
app/builtin_dictation.py uses, with no native library and no model: a
"model" is a set of small files served by the test, and the transcriber
turns each half second of loud audio into a word and ends a line after a
pause, the way Moonshine's streaming models behave.
"""
import enum
import os

__version__ = "fake"


class ModelArch(enum.IntEnum):
    TINY = 0
    BASE = 1
    TINY_STREAMING = 2
    BASE_STREAMING = 3
    SMALL_STREAMING = 4
    MEDIUM_STREAMING = 5


class TranscriptLine:
    def __init__(self, line_id, text, complete):
        self.line_id = line_id
        self.text = text
        self.is_complete = complete


class Transcript:
    def __init__(self, lines):
        self.lines = lines


LOADS = []          # (path, arch) for every Transcriber made, so tests can count loads
CLOSED = []


def load_wav_file(path):
    return [0.2 if (i // 800) % 2 else -0.2 for i in range(16000 * 6)], 16000


from .transcriber import Transcriber  # noqa: E402,F401
from . import download  # noqa: E402,F401
