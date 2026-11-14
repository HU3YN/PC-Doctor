"""How fast is the model? PyTorch vs ONNX Runtime, CPU (and GPU when there is one).

    python benchmark.py                   # batch sizes 1, 8, 64, 256
    python benchmark.py --repeats 200     # steadier numbers, takes longer

For every engine and batch size it runs the model ``--repeats`` times after a
few warm-up runs and records the median and the 95th percentile (p95) of the
time per call. The median is the typical call; p95 is a slow-but-normal call
(1 call in 20 is slower than this).

Writes ``out/benchmark.json``. The machine is described by its hardware only
(CPU model, core count, RAM, GPU model) - never by computer name or user
name, so the file can be shared and committed safely.

Numbers from the build machine (a shared cloud VM) are a PLUMBING CHECK: they
prove the script works. Measure on the machine that matters before quoting.
"""

from __future__ import annotations

import argparse
import ctypes
import datetime as dt
import json
import os
import platform
import statistics
import subprocess
import tempfile
import time
from pathlib import Path

import numpy as np
import torch

import model as frame_model
from dataset import WINDOW, make_synthetic, to_windows

HERE = Path(__file__).resolve().parent
DEFAULT_OUT = HERE / "out"
BATCH_SIZES = (1, 8, 64, 256)


# ------------------------------------------------------------- the machine


def cpu_model() -> str:
    """The CPU's marketing name, e.g. 'AMD Ryzen 7 5800X3D 8-Core Processor'."""
    system = platform.system()
    try:
        if system == "Linux":
            for line in Path("/proc/cpuinfo").read_text().splitlines():
                if line.startswith("model name"):
                    return line.split(":", 1)[1].strip()
        elif system == "Darwin":
            out = subprocess.run(
                ["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True, text=True
            )
            if out.stdout.strip():
                return out.stdout.strip()
        elif system == "Windows":
            import winreg

            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"
            )
            return str(winreg.QueryValueEx(key, "ProcessorNameString")[0]).strip()
    except (OSError, ValueError):
        pass
    return platform.processor() or "unknown"


def physical_cores() -> int | None:
    """Physical cores (logical / 2 on a CPU with SMT), Linux only; None elsewhere."""
    try:
        pairs = set()
        core = phys = None
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.startswith("physical id"):
                phys = line.split(":")[1].strip()
            elif line.startswith("core id"):
                core = line.split(":")[1].strip()
            elif not line.strip() and core is not None:
                pairs.add((phys, core))
                core = phys = None
        if core is not None:
            pairs.add((phys, core))
        return len(pairs) or None
    except OSError:
        return None


def ram_gb() -> float | None:
    """Installed RAM in GB."""
    try:
        if platform.system() == "Linux":
            for line in Path("/proc/meminfo").read_text().splitlines():
                if line.startswith("MemTotal:"):
                    return round(int(line.split()[1]) / 1024**2, 1)
        if platform.system() == "Windows":

            class MemoryStatus(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            status = MemoryStatus()
            status.dwLength = ctypes.sizeof(MemoryStatus)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
            return round(status.ullTotalPhys / 1024**3, 1)
        if platform.system() == "Darwin":
            out = subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True)
            return round(int(out.stdout) / 1024**3, 1)
    except (OSError, ValueError, AttributeError):
        pass
    return None


def machine() -> dict:
    """Hardware only. Deliberately no platform.node(), no user name, no paths."""
    gpu = torch.cuda.get_device_name(0) if torch.cuda.is_available() else None
    return {
        "cpu_model": cpu_model(),
        "logical_cores": os.cpu_count(),
        "physical_cores": physical_cores(),
        "ram_gb": ram_gb(),
        "gpu_model": gpu,
        "os": platform.system(),  # "Linux" / "Windows" - the family, not the build
        "arch": platform.machine(),
    }


# ------------------------------------------------------------- the timing


def time_calls(call, repeats: int, warmup: int = 5) -> dict:
    """Median and p95 wall time of ``call()`` in milliseconds."""
    for _ in range(warmup):  # first calls are slow (memory allocation, caches)
        call()
    times = []
    for _ in range(repeats):
        start = time.perf_counter()
        call()
        times.append((time.perf_counter() - start) * 1000.0)
    times.sort()
    p95 = times[min(len(times) - 1, int(round(0.95 * (len(times) - 1))))]
    return {
        "median_ms": round(statistics.median(times), 4),
        "p95_ms": round(p95, 4),
        "repeats": repeats,
    }


def bench_torch(net, data: np.ndarray, batch: int, device: str, repeats: int, threads: int) -> dict:
    torch.set_num_threads(threads)  # CPU threads PyTorch may use inside one call
    net = net.to(device).eval()
    x = torch.as_tensor(data[:batch]).to(device)

    def call():
        with torch.no_grad():
            net(x)
        if device == "cuda":
            torch.cuda.synchronize()  # GPU work is asynchronous: wait for it to finish

    return time_calls(call, repeats)


def bench_onnx(
    path: Path, data: np.ndarray, batch: int, provider: str, repeats: int, threads: int
) -> dict:
    import onnxruntime as ort

    options = ort.SessionOptions()
    options.intra_op_num_threads = threads  # CPU threads ONNX Runtime may use in one call
    session = ort.InferenceSession(str(path), options, providers=[provider])
    x = data[:batch].astype(np.float32)
    return time_calls(lambda: session.run(["logit"], {"frames_ms": x}), repeats)


def run(
    out_dir: Path,
    batch_sizes=BATCH_SIZES,
    repeats: int = 50,
    threads: list[int] | None = None,
    log=print,
) -> dict:
    import onnxruntime as ort

    weights = out_dir / "model.pt"
    if weights.is_file():
        net, trained = frame_model.load(str(weights)), True
    else:  # speed does not depend on the weights' values
        torch.manual_seed(0)
        net, trained = frame_model.FrameCNN(), False
    onnx_path = out_dir / "model.onnx"
    tmp = None
    if not onnx_path.is_file():
        from export_onnx import export

        tmp = tempfile.TemporaryDirectory()
        onnx_path = Path(tmp.name) / "model.onnx"
        export(net, onnx_path)

    # Real-looking input: synthetic windows, enough for the biggest batch.
    need = max(batch_sizes)
    n_series = need // 8 + 1
    data = to_windows(make_synthetic(n_series, seed=7, n_frames=WINDOW * 8), WINDOW).frames
    data = data[:need]

    # On the CPU each engine runs twice: with one thread, and with one thread
    # per logical core. For a model this small, more threads can be *slower*:
    # splitting tiny work across threads costs more than it saves, and on a
    # shared cloud VM the other "cores" may be busy. Measuring both shows it.
    cores = os.cpu_count() or 1
    cpu_threads = sorted(set(threads or [1, cores]))
    engines = [("pytorch", "cpu", n) for n in cpu_threads]
    if torch.cuda.is_available():
        engines.append(("pytorch", "cuda", 1))
    engines += [("onnxruntime", "CPUExecutionProvider", n) for n in cpu_threads]
    if "CUDAExecutionProvider" in ort.get_available_providers():
        engines.append(("onnxruntime", "CUDAExecutionProvider", 1))

    default_threads = torch.get_num_threads()
    results = []
    for engine, device, threads in engines:
        for batch in batch_sizes:
            if engine == "pytorch":
                timing = bench_torch(net, data, batch, device, repeats, threads)
            else:
                timing = bench_onnx(onnx_path, data, batch, device, repeats, threads)
            timing.update(
                {
                    "engine": engine,
                    "device": device,
                    "threads": threads,
                    "batch": batch,
                    "median_ms_per_window": round(timing["median_ms"] / batch, 5),
                }
            )
            results.append(timing)
            log(
                f"{engine:<12} {device:<21} {threads:2d} thr  batch {batch:4d}: "
                f"median {timing['median_ms']:8.3f} ms  p95 {timing['p95_ms']:8.3f} ms  "
                f"({timing['median_ms_per_window']:.4f} ms/window)"
            )
    torch.set_num_threads(default_threads)
    if tmp:
        tmp.cleanup()

    report = {
        "PLUMBING_CHECK": (
            "Timings from whatever machine ran this. From the build VM they only prove the "
            "script works; they are not a result for any real PC."
        ),
        "date": dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "machine": machine(),
        "software": {
            "python": platform.python_version(),
            "torch": torch.__version__,
            "onnxruntime": ort.__version__,
            "torch_default_threads": default_threads,
        },
        "model": {
            "trained_weights": trained,
            "window_frames": WINDOW,
            "parameters": frame_model.count_parameters(net),
        },
        "gpu_tested": any(device in ("cuda", "CUDAExecutionProvider") for _, device, _ in engines),
        "results": results,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "benchmark.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    log(
        f"wrote {out_dir / 'benchmark.json'}"
        + ("" if report["gpu_tested"] else "  (no GPU found: CPU only)")
    )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--repeats", type=int, default=50)
    parser.add_argument("--batch-sizes", type=int, nargs="+", default=list(BATCH_SIZES))
    parser.add_argument(
        "--threads", type=int, nargs="+", help="CPU thread counts to try (default: 1 and all cores)"
    )
    args = parser.parse_args(argv)
    run(args.out, args.batch_sizes, args.repeats, args.threads)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
