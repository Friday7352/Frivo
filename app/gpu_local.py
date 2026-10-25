"""
NEW (2.0.0): the graphics card, read by Frivo itself (gpu_local.py).

Taken from Evora's evora_gpu.py (same author, MIT), for a Frivo that runs on
the PC with the graphics card: built-in dictation's Large model uses it, and
Evora may not be there at all. Same sources, nothing to install:

  * The card (name, memory used and total, how busy, temperature): NVIDIA's
    NVML library from the driver, or nvidia-smi.
  * Who uses it: Windows' "GPU Process Memory" counters, the ones Task
    Manager reads (NVML says "N/A" per process on Windows).

What's different from Evora's: the parts are Ollama, Evora, Dictation (this
Frivo's own process, which is where built-in dictation runs) and Other.
Evora is told apart by its program's path (it runs from its own folder).

Everything fails soft: no NVIDIA card gives {"ok": false} and a reason.
"""

import ctypes
import ntpath   # splits on \ and /, whatever OS runs the tests
import os
import re
import shutil
import subprocess
import sys
import threading
import time

MB = 1024 * 1024
CACHE_SECONDS = 1.0          # Frivo polls every few seconds; several Frivos may poll
QUERY_REBUILD_SECONDS = 60   # pick up processes that started since the query was built

_lock = threading.Lock()
_cache = {"at": 0.0, "value": None}


# ---------------------------------------------------------------------------
# Who a process is
# ---------------------------------------------------------------------------

def classify(name, pid, own_pid=None):
    """'dictation' (this Frivo), 'evora', 'ollama' or 'other' for one process
    using the card."""
    own_pid = os.getpid() if own_pid is None else own_pid
    if pid == own_pid:
        return "dictation"
    if "evora" in (name or "").lower():
        return "evora"
    base = ntpath.basename(name or "").lower()
    # ollama.exe serves and runs models; older builds ran them in
    # ollama_llama_server.exe, and some setups use llama-server.exe.
    if "ollama" in base or base.startswith("llama"):
        return "ollama"
    return "other"


def friendly_name(name):
    base = ntpath.basename(name or "")
    return base[:-4] if base.lower().endswith(".exe") else base


# ---------------------------------------------------------------------------
# The card: NVML, then nvidia-smi
# ---------------------------------------------------------------------------

class _NvmlMemory(ctypes.Structure):
    _fields_ = [("total", ctypes.c_ulonglong),
                ("free", ctypes.c_ulonglong),
                ("used", ctypes.c_ulonglong)]


class _NvmlUtilization(ctypes.Structure):
    _fields_ = [("gpu", ctypes.c_uint), ("memory", ctypes.c_uint)]


class _Nvml:
    def __init__(self):
        self.lib = None
        self.handle = None
        self.error = None

    def _load(self):
        if sys.platform == "win32":
            candidates = [
                "nvml.dll",
                os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "System32", "nvml.dll"),
                os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"),
                             "NVIDIA Corporation", "NVSMI", "nvml.dll"),
            ]
            loader = ctypes.WinDLL
        else:
            candidates = ["libnvidia-ml.so.1", "libnvidia-ml.so"]
            loader = ctypes.CDLL
        for path in candidates:
            try:
                return loader(path)
            except OSError:
                continue
        return None

    def ready(self):
        if self.handle is not None:
            return True
        if self.error:
            return False
        lib = self._load()
        if lib is None:
            self.error = "NVIDIA's driver library (nvml) isn't on this PC"
            return False
        try:
            if lib.nvmlInit_v2() != 0:
                self.error = "NVIDIA's driver library wouldn't start"
                return False
            count = ctypes.c_uint(0)
            if lib.nvmlDeviceGetCount_v2(ctypes.byref(count)) != 0 or count.value == 0:
                self.error = "No NVIDIA graphics card found"
                return False
            handle = ctypes.c_void_p()
            if lib.nvmlDeviceGetHandleByIndex_v2(0, ctypes.byref(handle)) != 0:
                self.error = "Couldn't open the graphics card"
                return False
        except AttributeError:
            self.error = "NVIDIA's driver library is too old"
            return False
        self.lib, self.handle = lib, handle
        return True

    def read(self):
        lib, handle = self.lib, self.handle
        memory = _NvmlMemory()
        if lib.nvmlDeviceGetMemoryInfo(handle, ctypes.byref(memory)) != 0:
            return None
        name = ctypes.create_string_buffer(96)
        lib.nvmlDeviceGetName(handle, name, 96)
        util = _NvmlUtilization()
        busy = None
        if lib.nvmlDeviceGetUtilizationRates(handle, ctypes.byref(util)) == 0:
            busy = int(util.gpu)
        temp = ctypes.c_uint(0)
        temp_c = int(temp.value) if lib.nvmlDeviceGetTemperature(handle, 0, ctypes.byref(temp)) == 0 else None
        return {
            "name": name.value.decode("utf-8", "replace") or "NVIDIA graphics card",
            "total_bytes": int(memory.total),
            "used_bytes": int(memory.used),
            "util_pct": busy,
            "temp_c": temp_c,
        }


_nvml = _Nvml()


def parse_nvidia_smi(text):
    """One CSV line from nvidia-smi into the same shape NVML gives."""
    line = (text or "").strip().splitlines()[0] if (text or "").strip() else ""
    parts = [p.strip() for p in line.split(",")]
    if len(parts) < 5:
        return None

    def number(value):
        try:
            return float(value)
        except ValueError:
            return None   # "[N/A]"

    used, total = number(parts[1]), number(parts[2])
    if used is None or total is None:
        return None
    util, temp = number(parts[3]), number(parts[4])
    return {
        "name": parts[0] or "NVIDIA graphics card",
        "total_bytes": int(total * MB),
        "used_bytes": int(used * MB),
        "util_pct": None if util is None else int(util),
        "temp_c": None if temp is None else int(temp),
    }


def _nvidia_smi():
    exe = shutil.which("nvidia-smi")
    if not exe and sys.platform == "win32":
        guess = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "System32", "nvidia-smi.exe")
        exe = guess if os.path.exists(guess) else None
    if not exe:
        return None
    try:
        out = subprocess.run(
            [exe, "--id=0", "--query-gpu=name,memory.used,memory.total,utilization.gpu,temperature.gpu",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=4,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return parse_nvidia_smi(out.stdout) if out.returncode == 0 else None


def read_card():
    """(card, source, reason). card is None when there's nothing to report."""
    if _nvml.ready():
        try:
            card = _nvml.read()
        except OSError:
            card = None
        if card:
            return card, "nvml", None
    card = _nvidia_smi()
    if card:
        return card, "nvidia-smi", None
    return None, None, _nvml.error or "No NVIDIA graphics card found"


# ---------------------------------------------------------------------------
# Who uses it: Windows performance counters (PDH)
# ---------------------------------------------------------------------------

_PROC_RE = re.compile(r"pid_(\d+)_luid_(0x[0-9a-f]+_0x[0-9a-f]+)_phys_(\d+)", re.I)
_ADAPTER_RE = re.compile(r"luid_(0x[0-9a-f]+_0x[0-9a-f]+)_phys_(\d+)", re.I)


def parse_process_instances(items):
    """[(instance name, bytes)] -> {(luid, phys): {pid: bytes}}"""
    out = {}
    for name, value in items:
        match = _PROC_RE.search(name or "")
        if not match or value is None or value <= 0:
            continue
        key = (match.group(2).lower(), match.group(3))
        pid = int(match.group(1))
        bucket = out.setdefault(key, {})
        bucket[pid] = bucket.get(pid, 0) + int(value)
    return out


def parse_adapter_instances(items):
    """[(instance name, bytes)] -> {(luid, phys): bytes}"""
    out = {}
    for name, value in items:
        match = _ADAPTER_RE.search(name or "")
        if match and value is not None:
            out[(match.group(1).lower(), match.group(2))] = int(value)
    return out


def pick_adapter(adapters, card_used_bytes):
    """
    The counters list every adapter, including a CPU's built-in graphics.
    The NVIDIA one is whichever is using about as much memory as NVML says
    the card is using.
    """
    if not adapters:
        return None
    if card_used_bytes is None:
        return max(adapters, key=adapters.get)
    return min(adapters, key=lambda key: abs(adapters[key] - card_used_bytes))


if sys.platform == "win32":
    from ctypes import wintypes

    class _PdhValue(ctypes.Structure):
        # PDH_FMT_COUNTERVALUE: a DWORD status, then an 8-byte union. ctypes
        # aligns the c_longlong to offset 8, exactly as the C struct does.
        _fields_ = [("CStatus", wintypes.DWORD), ("largeValue", ctypes.c_longlong)]

    class _PdhItem(ctypes.Structure):
        _fields_ = [("szName", ctypes.c_wchar_p), ("FmtValue", _PdhValue)]


class _ProcessCounters:
    PDH_FMT_LARGE = 0x00000400
    PDH_MORE_DATA = 0x800007D2

    def __init__(self):
        self.pdh = None
        self.query = None
        self.counters = {}
        self.built_at = 0.0
        self.error = None
        self.names = {}

    def _build(self):
        self.close()
        if self.pdh is None:
            self.pdh = ctypes.WinDLL("pdh.dll")
        query = ctypes.c_void_p()
        if self.pdh.PdhOpenQueryW(None, None, ctypes.byref(query)) != 0:
            raise OSError("PdhOpenQuery failed")
        self.query = query
        for key, path in (("process", r"\GPU Process Memory(*)\Dedicated Usage"),
                          ("adapter", r"\GPU Adapter Memory(*)\Dedicated Usage")):
            counter = ctypes.c_void_p()
            status = self.pdh.PdhAddEnglishCounterW(query, ctypes.c_wchar_p(path), None, ctypes.byref(counter))
            if status != 0:
                raise OSError(f"this version of Windows has no '{path}' counter")
            self.counters[key] = counter
        self.built_at = time.monotonic()

    def close(self):
        if self.query is not None and self.pdh is not None:
            self.pdh.PdhCloseQuery(self.query)
        self.query = None
        self.counters = {}

    def _array(self, counter):
        size = wintypes.DWORD(0)
        count = wintypes.DWORD(0)
        status = self.pdh.PdhGetFormattedCounterArrayW(
            counter, self.PDH_FMT_LARGE, ctypes.byref(size), ctypes.byref(count), None)
        if (status & 0xFFFFFFFF) != self.PDH_MORE_DATA or size.value == 0:
            return []
        buffer = ctypes.create_string_buffer(size.value)
        status = self.pdh.PdhGetFormattedCounterArrayW(
            counter, self.PDH_FMT_LARGE, ctypes.byref(size), ctypes.byref(count), buffer)
        if status != 0:
            return []
        items = ctypes.cast(buffer, ctypes.POINTER(_PdhItem))
        out = []
        for i in range(count.value):
            item = items[i]
            if item.FmtValue.CStatus in (0, 1):   # valid / new data
                out.append((item.szName, int(item.FmtValue.largeValue)))
        return out

    def read(self):
        """(per-process items, adapter items), or None if unavailable."""
        if sys.platform != "win32" or self.error:
            return None
        try:
            if self.query is None or time.monotonic() - self.built_at > QUERY_REBUILD_SECONDS:
                self._build()
            if self.pdh.PdhCollectQueryData(self.query) != 0:
                return None
            return self._array(self.counters["process"]), self._array(self.counters["adapter"])
        except OSError as exc:
            self.error = str(exc)
            self.close()
            return None

    def process_name(self, pid):
        if pid in self.names:
            return self.names[pid]
        name = ""
        if sys.platform == "win32":
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.OpenProcess.restype = ctypes.c_void_p
            kernel32.QueryFullProcessImageNameW.argtypes = [
                ctypes.c_void_p, wintypes.DWORD, ctypes.c_wchar_p, ctypes.POINTER(wintypes.DWORD)]
            kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
            handle = kernel32.OpenProcess(0x1000, False, pid)   # PROCESS_QUERY_LIMITED_INFORMATION
            if handle:
                try:
                    buf = ctypes.create_unicode_buffer(1024)
                    size = wintypes.DWORD(1024)
                    if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                        name = buf.value
                finally:
                    kernel32.CloseHandle(handle)
        if len(self.names) > 500:
            self.names.clear()
        self.names[pid] = name
        return name


_processes = _ProcessCounters()


def breakdown(card_used_bytes, process_items, adapter_items, name_of, own_pid=None):
    """
    Split the card's used memory into Ollama, Evora, dictation and other.

    Returns (parts, top processes) or (None, []) when the counters don't
    cover this card.
    """
    per_adapter = parse_process_instances(process_items)
    adapters = parse_adapter_instances(adapter_items)
    key = pick_adapter(adapters, card_used_bytes)
    if key is None:
        return None, []
    usage = per_adapter.get(key, {})
    totals = {"ollama": 0, "evora": 0, "dictation": 0}
    rows = []
    for pid, used in usage.items():
        name = name_of(pid)
        app_id = classify(name, pid, own_pid)
        if app_id in totals:
            totals[app_id] += used
        label = {"evora": "Evora", "dictation": "Frivo (dictation)"}.get(app_id) or friendly_name(name) or f"process {pid}"
        rows.append({"name": label, "app": app_id,
                     "used_mb": round(used / MB)})
    used_total = card_used_bytes if card_used_bytes is not None else adapters.get(key, 0)
    other = max(0, used_total - totals["ollama"] - totals["evora"] - totals["dictation"])
    rows.sort(key=lambda row: row["used_mb"], reverse=True)
    parts = {
        "ollama_mb": round(totals["ollama"] / MB),
        "evora_mb": round(totals["evora"] / MB),
        "dictation_mb": round(totals["dictation"] / MB),
        "other_mb": round(other / MB),
    }
    return parts, rows[:8]


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------

def _measure(device):
    card, source, reason = read_card()
    if card is None:
        return {"ok": False, "reason": reason, "time": time.time()}
    parts, rows = None, []
    counters = _processes.read()
    if counters is not None:
        parts, rows = breakdown(card["used_bytes"], counters[0], counters[1], _processes.process_name)
    return {
        "ok": True,
        "source": source,
        "name": card["name"],
        "total_mb": round(card["total_bytes"] / MB),
        "used_mb": round(card["used_bytes"] / MB),
        "util_pct": card["util_pct"],
        "temp_c": card["temp_c"],
        "parts": parts,
        "processes": rows,
        "parts_reason": None if parts else (_processes.error or "Windows didn't say which apps use the card"),
        "time": time.time(),
    }


def snapshot(device="cpu"):
    """The report, at most once a second however many callers ask."""
    with _lock:
        now = time.monotonic()
        if _cache["value"] is None or now - _cache["at"] >= CACHE_SECONDS:
            try:
                _cache["value"] = _measure(device)
            except Exception as exc:   # never take the route down
                _cache["value"] = {"ok": False, "reason": f"Couldn't read the graphics card: {exc}",
                                   "time": time.time()}
            _cache["at"] = now
        return dict(_cache["value"])


def used_mb():
    """The card's used memory in MB, now (not cached), or None without a card.
    Built-in dictation reads it before and after loading a model."""
    try:
        card, _, _ = read_card()
    except Exception:
        return None
    return None if card is None else round(card["used_bytes"] / MB)


if __name__ == "__main__":
    # python gpu_local.py  -> prints what Frivo's GPU graph would get, for checking by hand.
    import json
    print(json.dumps(snapshot(), indent=2))
