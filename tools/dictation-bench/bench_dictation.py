"""
Frivo dictation speed test: Moonshine Streaming Small and Medium, on this PC's CPU.

Plays speech into each model the way live dictation would (a tenth of a
second at a time, in real time order) and measures:

  * download and load time, and memory
  * how long each live update takes to compute (what you'd wait for words)
  * how long after you stop talking the final text is ready
  * how much of one CPU core it keeps busy while you talk
  * what it heard

Uses the speech clips that come with Moonshine, plus any .wav files given
on the command line (16-bit or 24-bit PCM; any sample rate).

    python bench_dictation.py [your.wav ...]

Nothing is installed outside the folder Bench-Dictation.bat makes, and
nothing is sent anywhere except the model downloads from moonshine.ai.
"""

import os
import platform
import sys
import time

import moonshine_voice as mv
from moonshine_voice.transcriber import MOONSHINE_FLAG_FORCE_UPDATE

try:
    import psutil
except ImportError:
    psutil = None

CHUNK_SECONDS = 0.1          # how often the microphone hands over audio
UPDATE_SECONDS = 0.2         # how often Frivo would ask for new words
MODELS = [
    ("Moonshine Streaming Small", mv.ModelArch.SMALL_STREAMING),
    ("Moonshine Streaming Medium", mv.ModelArch.MEDIUM_STREAMING),
]


def cpu_name():
    name = platform.processor() or ""
    if sys.platform == "win32":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as key:
                name = winreg.QueryValueEx(key, "ProcessorNameString")[0].strip()
        except OSError:
            pass
    return name or "unknown CPU"


def rss_mb():
    if psutil:
        return psutil.Process().memory_info().rss / 1048576
    return float("nan")


def to_16k(samples, rate):
    """Plain linear resampling to 16 kHz, which is what Frivo would do."""
    if rate == 16000:
        return list(samples)
    ratio = rate / 16000.0
    n = int(len(samples) / ratio)
    out = []
    for i in range(n):
        pos = i * ratio
        j = int(pos)
        frac = pos - j
        a = samples[j]
        b = samples[j + 1] if j + 1 < len(samples) else a
        out.append(a + (b - a) * frac)
    return out


def clips(extra):
    assets = mv.get_assets_path() if hasattr(mv, "get_assets_path") else os.path.join(os.path.dirname(mv.__file__), "assets")
    found = []
    for name in ("two_cities.wav", "beckett.wav"):
        path = os.path.join(assets, name)
        if os.path.exists(path):
            found.append(path)
    found.extend(extra)
    out = []
    for path in found:
        try:
            samples, rate = mv.load_wav_file(path)
        except Exception as e:
            print(f"  (skipped {path}: {e})")
            continue
        if samples and isinstance(samples[0], (list, tuple)):
            samples = [s[0] for s in samples]
        out.append((os.path.basename(path), to_16k(samples, rate)))
    return out


def line_text(transcript):
    return " ".join(l.text.strip() for l in (transcript.lines or []) if l.text and l.text.strip())


def run_clip(transcriber, audio):
    """One clip, streamed. Returns timings and the text."""
    stream = transcriber.create_stream(update_interval=1e6)   # one pass per update, as Frivo does
    stream.start()
    chunk = int(16000 * CHUNK_SECONDS)
    updates = []
    first_words_at = None
    cpu0 = time.process_time()
    since_update = 0.0
    for i in range(0, len(audio), chunk):
        piece = audio[i:i + chunk]
        stream.add_audio(piece, 16000)
        since_update += len(piece) / 16000
        if since_update >= UPDATE_SECONDS:
            since_update = 0.0
            t = time.perf_counter()
            transcript = stream.update_transcription(MOONSHINE_FLAG_FORCE_UPDATE)
            updates.append(time.perf_counter() - t)
            if first_words_at is None and line_text(transcript):
                first_words_at = (i + len(piece)) / 16000
    t = time.perf_counter()
    final = stream.stop()
    final_latency = time.perf_counter() - t
    cpu = time.process_time() - cpu0
    duration = len(audio) / 16000
    try:
        stream.close()
    except Exception:
        pass
    updates.sort()
    return {
        "duration": duration,
        "update_avg": sum(updates) / len(updates) if updates else 0.0,
        "update_p95": updates[int(len(updates) * 0.95) - 1] if updates else 0.0,
        "update_max": updates[-1] if updates else 0.0,
        "final": final_latency,
        "cpu_share": cpu / duration if duration else 0.0,
        "first_words": first_words_at,
        "text": line_text(final) if final is not None else "",
    }


class Tee:
    """Prints, and keeps a copy in results.txt beside this script."""

    def __init__(self, stream, path):
        self.stream = stream
        self.file = open(path, "w", encoding="utf-8")

    def write(self, text):
        self.stream.write(text)
        self.stream.flush()
        self.file.write(text)
        self.file.flush()

    def flush(self):
        self.stream.flush()
        self.file.flush()


def main():
    sys.stdout = Tee(sys.stdout, os.path.join(os.path.dirname(os.path.abspath(__file__)), "results.txt"))
    print("Frivo dictation speed test")
    print(f"CPU: {cpu_name()} ({os.cpu_count()} threads)")
    print(f"Python {platform.python_version()}, moonshine-voice {getattr(mv, '__version__', '?')}")
    print()
    audio_clips = clips(sys.argv[1:])
    if not audio_clips:
        print("No speech clips found.")
        return 1

    for label, arch in MODELS:
        print(f"=== {label} ===")
        t = time.perf_counter()
        try:
            path, arch = mv.get_model_for_language("en", arch)
        except Exception as e:
            print(f"  couldn't download it: {e}")
            continue
        download = time.perf_counter() - t
        size = sum(os.path.getsize(os.path.join(dp, f)) for dp, _, fs in os.walk(path) for f in fs) / 1048576
        before = rss_mb()
        t = time.perf_counter()
        try:
            transcriber = mv.Transcriber(path, arch, update_interval=UPDATE_SECONDS)
        except Exception as e:
            print(f"  couldn't load it: {e}")
            continue
        load = time.perf_counter() - t
        print(f"  download {download:.1f} s (cached after the first time), {size:.0f} MB on disk")
        print(f"  load {load:.2f} s, memory +{rss_mb() - before:.0f} MB")
        try:
            run_clip(transcriber, audio_clips[0][1][:16000 * 3])   # warm up
        except Exception as e:
            print(f"  warm-up failed: {e}")
        for name, audio in audio_clips:
            try:
                r = run_clip(transcriber, audio)
            except Exception as e:
                print(f"  -- {name}: failed: {e}")
                continue
            print(f"  -- {name} ({r['duration']:.1f} s of speech)")
            print(f"     live update: {r['update_avg'] * 1000:.0f} ms average, {r['update_p95'] * 1000:.0f} ms at worst 1 in 20, {r['update_max'] * 1000:.0f} ms max")
            print(f"     final text ready {r['final'] * 1000:.0f} ms after the speech ends")
            if r["first_words"] is not None:
                print(f"     first words on screen after {r['first_words']:.1f} s of speech")
            print(f"     CPU while talking: {r['cpu_share'] * 100:.0f}% of one thread")
            print(f"     heard: {r['text'][:400]}")
        transcriber.close()
        print()
    print("Done. Send this whole window's text back to Claude.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
