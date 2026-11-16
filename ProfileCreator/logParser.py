"""Parse app.log (+ VPC.txt) from every immediate subfolder of ROOT_DIR into one CSV.
Edit the two settings below, then run:  python parse_logs.py"""
import csv, re
from pathlib import Path

ROOT_DIR = Path(r"D:\Files\Projects\AutoCompression\workspace\denoise_tests_leftout")            # <-- folder that contains AlvinChipmunks2, AvengersEndgame_HQ, ...
OUTPUT_CSV = ROOT_DIR / "denoise_tests_leftout.csv"   # <-- where the CSV is written

RE_GET   = re.compile(r"\[DEBUG\] Getting VMAF result for:\s*(\d+)_(\d+)")
RE_VMAF  = re.compile(r"\[DEBUG\] VMAF Score:\s*([-\d.eE+]+)")
RE_CQ    = re.compile(r"\[INFO\] Calculated CQ:\s*([-\d.eE+]+)")
RE_VQA   = re.compile(r"\[DEBUG\] Calculated VQA for (\d+)_(\d+)_cq\w*:\s*([-\d.eE+]+)")
RE_SLOPE = re.compile(r"\[DEBUG\] average slope is:\s*([-\d.eE+]+)")
RE_TRES  = re.compile(r"\[INFO\] Original resolution:\s*\d+,\s*Target resolution:\s*(\d+)")
VPC_KEYS = ("orig_h_res", "HDR_type")   # keys copied from VPC.txt into the header

def parse_vpc(path):
    info = {k: None for k in VPC_KEYS}
    if path.is_file():
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            key, sep, val = line.partition(":")
            if sep and key.strip() in info:
                info[key.strip()] = val.strip()
    return info

def parse_log(path):
    r = {"vmaf": [], "vqa": [], "cq": None, "slope": None, "target_res": None}
    pending = None  # scene/cq from the most recent "Getting VMAF result" line
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            if m := RE_GET.search(line):
                pending = (int(m[1]), int(m[2]))
            elif m := RE_VMAF.search(line):
                scene, cq = pending if pending else (None, None)
                r["vmaf"].append((scene, cq, float(m[1])))
                pending = None
            elif m := RE_CQ.search(line):
                r["cq"] = float(m[1])
            elif m := RE_VQA.search(line):
                r["vqa"].append((int(m[1]), int(m[2]), float(m[3])))
            elif m := RE_SLOPE.search(line):
                r["slope"] = float(m[1])
            elif m := RE_TRES.search(line):
                r["target_res"] = int(m[1])
    return r

def main():
    folders = sorted(p for p in ROOT_DIR.iterdir() if p.is_dir() and (p / "app.log").is_file())
    if not folders:
        raise SystemExit(f"No subfolders with app.log found in {ROOT_DIR}")
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        for folder in folders:
            r = parse_log(folder / "app.log")
            vpc = parse_vpc(folder / "VPC.txt")
            w.writerow(["# folder", folder.name])
            for k in VPC_KEYS:
                w.writerow([k, vpc[k]])
            w.writerow(["target_resolution", r["target_res"]])
            w.writerow(["average_slope", r["slope"]])
            w.writerow(["Calculated CQ", r["cq"]])
            w.writerow([])
            w.writerow(["scene", "cq", "vmaf_score"]); w.writerows(r["vmaf"])
            w.writerow([])
            w.writerow(["scene", "resolution", "vqa"]); w.writerows(sorted(r["vqa"]))
            w.writerow([]); w.writerow([])
    print(f"Parsed {len(folders)} folder(s) -> {OUTPUT_CSV}")

if __name__ == "__main__":
    main()