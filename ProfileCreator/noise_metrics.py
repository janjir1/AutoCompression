"""Run siti, bitplanenoise, blurdetect and blockdetect on every .mkv in a folder.

siti / blurdetect / blockdetect: the file is split into THREADS time blocks that run
at the same time (one ffmpeg process per block); the per-frame values are joined in order.
bitplanenoise: runs once on the whole file (not split).

Edit the settings below, then run:  python noise_metrics.py

CSV: one block per .mkv with filesize, framecount, bits per frame and, for every
per-frame metric, average / median / std_dev.
"""
import csv
import re
import statistics
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import math

# ==========================================
# Settings - edit these
# ==========================================
FOLDER = Path(r"D:\Files\Projects\AutoCompression\input\denoise")  # <-- folder with the .mkv files
RECURSIVE = True                    # True = also search subfolders
OUTPUT_CSV = FOLDER / "noise_metrics.csv"
THREADS = 8                         # number of blocks / parallel ffmpeg processes per split test
PIX_FMT = "yuv420p"                  # converted before every test; None = native format
BITPLANE = 1                         # bitplane option of bitplanenoise
FFMPEG = "ffmpeg"
FFPROBE = "ffprobe"
# ==========================================

RE_VALUE = re.compile(r"^(lavfi\.[\w.]+)=\s*(\S+)\s*$")
SPLIT_TESTS = {"siti": "siti", "blurdetect": "blurdetect", "blockdetect": "blockdetect"}
BITPLANE_FILTER = f"bitplanenoise=bitplane={BITPLANE}:filter=0"


def probe_duration(path):
    out = subprocess.run(
        [FFPROBE, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True)
    return float(out.stdout.strip())


def run_ffmpeg(path, test_filter, start=None, length=None):
    """One ffmpeg run -> ({metadata key: [per-frame values]}, error text)."""
    chain = ([f"format={PIX_FMT}"] if PIX_FMT else []) + [test_filter, "metadata=mode=print:file=-"]
    cmd = [FFMPEG, "-hide_banner", "-nostats", "-loglevel", "error"]
    if start is not None:
        cmd += ["-ss", str(start)]
    if length is not None:
        cmd += ["-t", str(length)]
    cmd += ["-i", str(path), "-an", "-sn", "-dn", "-vf", ",".join(chain), "-f", "null", "-"]
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    values = {}
    for line in p.stdout.splitlines():
        m = RE_VALUE.match(line.strip())
        if m:
            try:
                values.setdefault(m[1], []).append(float(m[2]))
            except ValueError:
                pass
    error = f"ffmpeg exit {p.returncode}: {p.stderr.strip()[-200:]}" if p.returncode != 0 else ""
    return values, error


def run_split(path, test_filter, duration):
    """Split into THREADS time blocks, run all blocks at the same time, join in order."""
    step = duration / THREADS
    blocks = [(i * step, step if i < THREADS - 1 else None) for i in range(THREADS)]
    with ThreadPoolExecutor(max_workers=THREADS) as pool:
        results = list(pool.map(lambda b: run_ffmpeg(path, test_filter, b[0], b[1]), blocks))
    merged, errors = {}, []
    for values, error in results:
        if error:
            errors.append(error)
        for key, vals in values.items():
            merged.setdefault(key, []).extend(vals)
    return merged, errors


def stats(vals):
    good = [v for v in vals if math.isfinite(v)]
    skipped = len(vals) - len(good)
    if not good:
        return "", "", "", skipped
    sd = statistics.stdev(good) if len(good) > 1 else 0.0
    return statistics.mean(good), statistics.median(good), sd, skipped


def main():
    files = sorted(p for p in FOLDER.glob("**/*.mkv" if RECURSIVE else "*.mkv") if p.is_file())
    if not files:
        raise SystemExit(f"No .mkv files found in {FOLDER}")

    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        for i, path in enumerate(files, 1):

            t0 = time.perf_counter()
            problems, metrics = [], {}

            duration = probe_duration(path)
            print(f"[{i}/{len(files)}] {path.name} - Bitplane Noise", flush=True)
            # bitplanenoise: whole file, one process -> also gives the frame count
            bp, err = run_ffmpeg(path, BITPLANE_FILTER)
            if err:
                problems.append("bitplanenoise: " + err)
            metrics.update(bp)
            framecount = max((len(v) for v in bp.values()), default=0)

            # the other tests: THREADS blocks at the same time
            for name, test_filter in SPLIT_TESTS.items():
                print(f"[{i}/{len(files)}] {path.name} - {test_filter}", flush=True)
                vals, errs = run_split(path, test_filter, duration)
                problems += [f"{name}: {e}" for e in errs]
                if not vals:
                    problems.append(f"{name}: no per-frame values found")
                metrics.update(vals)

            size = path.stat().st_size
            w.writerow(["# file", str(path.relative_to(FOLDER))])
            w.writerow(["filesize_bytes", size])
            w.writerow(["framecount", framecount])
            w.writerow(["bits_per_frame", round(size * 8 / framecount, 1) if framecount else ""])
            w.writerow(["duration_s", round(duration, 3)])
            w.writerow(["analysis_seconds", round(time.perf_counter() - t0, 1)])
            w.writerow(["metric", "average", "median", "std_dev", "skipped_nan_inf"])
            for key in sorted(metrics):
                avg, med, sd, skipped = stats(metrics[key])
                w.writerow([key.replace("lavfi.", ""),
                            round(avg, 6) if avg != "" else "",
                            round(med, 6) if med != "" else "",
                            round(sd, 6) if sd != "" else "",
                            skipped])
            for p in problems:
                w.writerow(["# problem", p])
            w.writerow([])
            w.writerow([])
            f.flush()

    print(f"Done -> {OUTPUT_CSV}")


if __name__ == "__main__":
    main()