from . import Transcript, TranscriptLine, LOADS, CLOSED
import os

MOONSHINE_FLAG_FORCE_UPDATE = 1 << 0
WORD_SECONDS = 0.5
PAUSE_SECONDS = 0.6
LOUD = 0.05


class Stream:
    def __init__(self, transcriber):
        self.t = transcriber
        self.lines = []          # [id, words, complete]
        self.loud = 0.0
        self.quiet = 0.0
        self.next_id = 1
        self.closed = False

    def start(self):
        pass

    def add_audio(self, samples, sample_rate=16000):
        if self.closed:
            raise RuntimeError("stream closed")
        step = 160
        for i in range(0, len(samples), step):
            part = samples[i:i + step]
            level = max(abs(x) for x in part) if part else 0.0
            secs = len(part) / sample_rate
            if level > LOUD:
                self.quiet = 0.0
                if not self.lines or self.lines[-1][2]:
                    self.lines.append([self.next_id, 0, False])
                    self.next_id += 1
                self.loud += secs
                while self.loud >= WORD_SECONDS:
                    self.loud -= WORD_SECONDS
                    self.lines[-1][1] += 1
            else:
                self.quiet += secs
                if self.lines and not self.lines[-1][2] and self.quiet >= PAUSE_SECONDS:
                    if self.lines[-1][1] == 0 and self.loud > 0.05:
                        self.lines[-1][1] = 1
                    self.lines[-1][2] = True
                    self.loud = 0.0

    def _transcript(self):
        out = []
        for line_id, words, complete in self.lines:
            text = " ".join(f"word{line_id}_{n + 1}" for n in range(words))
            out.append(TranscriptLine(line_id, text, complete))
        return Transcript(out)

    def update_transcription(self, flags=0):
        return self._transcript()

    def stop(self):
        if self.lines and not self.lines[-1][2]:
            if self.lines[-1][1] == 0 and self.loud > 0.05:
                self.lines[-1][1] = 1
            self.lines[-1][2] = True
        return self._transcript()

    def close(self):
        self.closed = True


class Transcriber:
    def __init__(self, model_path, model_arch=None, update_interval=0.5, options=None, spelling_model_path=None):
        if not os.path.isfile(os.path.join(str(model_path), "encoder.ort")):
            raise RuntimeError("Failed to load transcriber: no encoder.ort")
        LOADS.append((str(model_path), model_arch))

    def create_stream(self, update_interval=None, flags=0, transcribe_flags=0):
        return Stream(self)

    def transcribe_without_streaming(self, audio_data, sample_rate=16000, flags=0):
        return Transcript([TranscriptLine(1, "the sample speech", True)])

    def close(self):
        CLOSED.append(1)
