import functools
import json
import os
import re
import shutil
import subprocess
from fractions import Fraction

import pytest

from compressor2 import compress, get_video_metadata_type
from VideoClass import VideoProcessingConfig
import AVTest

FAST_SETTINGS = os.path.join(os.path.dirname(__file__), "fast_test_settings.yaml")

AV1_PROFILE = "Profiles/AV1_svt_archive_sw.yaml"
HEVC_PROFILE = "Profiles/h265_slow_nvenc.yaml"

# ---------------------------------------------------------------------------
# Expected behaviour (taken from compressor2.py):
#   * HDR_type naming: "DoVi" = Dolby Vision RPU found; "HDR10" = HDR10+ dynamic
#     metadata found (static-only HDR10 is detected as "None").
#   * Output is always a single-video-stream MKV (-an -sn, mkvmerge remux).
#   * AV1 path: SVT-AV1, always yuv420p10le, DoVi via --dolby-vision-rpu (AV1
#     DoVi profile 10), HDR10+ via --hdr10plus-json, static HDR from SideDTA.
#   * HEVC path: ffmpeg + hdr10plus_tool/dovi_tool re-injection (DoVi stays 8.x).
#   * Crop = crop=W:(H-top-bottom):0:top, scale=output_res:-2 -> output_res is the
#     output WIDTH, height is even.
#   * DoVi RPU active area is edited to match the crop (crop_dovi_rpu).
#
# Case fields
#   id               : class name suffix
#   file_fixture     : conftest.py fixture returning the source clip path
#   profile          : encode profile yaml, relative to repo root
#   expected_hdr_type: VPC.HDR_type after detection
#   valid_resolutions: acceptable VPC.output_res after calibration (widths)
#   expected_crop    : [top, bottom]
#   expected_duration/duration_tolerance : seconds
#   is_H265          : VPC.is_H265 for the source
#   expected_codec   : ffprobe codec_name of the output
#   output_hdr       : sdr | hdr10 | hdr10plus | dovi  (what the OUTPUT must contain)
#   dovi_profiles    : accepted dv_profile values if a DOVI configuration record exists
#   min_bit_depth    : 10 if the output must be >= 10-bit, else None
#   min_psnr         : per-plane PSNR floor vs. the cropped/scaled source (tune!)
#   known_issues     : {test_method_name: reason} -> applied as non-strict xfail
# ---------------------------------------------------------------------------
SOURCES = [
    dict(src="h265", label="dovi", file_fixture="synthetic_dovi_clip",
         expected_hdr_type="DoVi", is_H265=True, output_hdr="dovi"),
    dict(src="h265", label="hdr10plus", file_fixture="synthetic_hdr10plus_clip",
         expected_hdr_type="HDR10", is_H265=True, output_hdr="hdr10plus"),
    dict(src="h265", label="hdr10", file_fixture="synthetic_hdr10_clip",
         expected_hdr_type="None", is_H265=True, output_hdr="hdr10"),
    dict(src="h265", label="sdr", file_fixture="synthetic_sdr_h265_clip",
         expected_hdr_type="None", is_H265=True, output_hdr="sdr"),
    dict(src="h265", label="sdr_fullrange", file_fixture="synthetic_sdr_fullrange_clip",
         expected_hdr_type="None", is_H265=True, output_hdr="sdr"),
    dict(src="h264", label="sdr", file_fixture="synthetic_h264_clip",
         expected_hdr_type="None", is_H265=False, output_hdr="sdr"),
]

TARGETS = [
    dict(dst="av1", profile=AV1_PROFILE, expected_codec="av1", dovi_profiles=[10], always_10bit=True),
    dict(dst="h265", profile=HEVC_PROFILE, expected_codec="hevc", dovi_profiles=[8], always_10bit=False),
]

AV1_FULLRANGE_ISSUE = ("compressor2.SvtAv1EncApp_encode passes a hard-coded '--color-range 0' "
                       "(limited), so a full-range source gets re-tagged as limited")


def _build_cases():
    cases = []
    for s in SOURCES:
        for t in TARGETS:
            case = dict(
                id=f"{s['src']}_to_{t['dst']}_{s['label']}",
                file_fixture=s["file_fixture"],
                profile=t["profile"],
                expected_hdr_type=s["expected_hdr_type"],
                valid_resolutions=[854, 1280, 1920],
                expected_crop=[140, 140],
                expected_duration=10.0,
                duration_tolerance=0.25,
                is_H265=s["is_H265"],
                expected_codec=t["expected_codec"],
                output_hdr=s["output_hdr"],
                dovi_profiles=t["dovi_profiles"],
                min_bit_depth=10 if (t["always_10bit"] or s["output_hdr"] != "sdr") else None,
                min_psnr={"y": 30.0, "u": 35.0, "v": 35.0},
                crop_tolerance=2,
                known_issues={},
            )
            if s["label"] == "sdr_fullrange" and t["dst"] == "av1":
                case["known_issues"]["test_07_color_tags_preserved"] = AV1_FULLRANGE_ISSUE
            cases.append(case)
    return cases


PIPELINE_CASES = _build_cases()

# ---------------------------------------------------------------------------
# ffprobe / ffmpeg helpers
# ---------------------------------------------------------------------------
MASTERING = "Mastering display metadata"
CLL = "Content light level metadata"
HDR10PLUS = "HDR Dynamic Metadata SMPTE2094-40 (HDR10+)"
DOVI_CONF = "DOVI configuration record"
DOVI_RPU = "Dolby Vision RPU Data"
DOVI_META = "Dolby Vision Metadata"

MASTERING_KEYS = ("red_x", "red_y", "green_x", "green_y", "blue_x", "blue_y",
                  "white_point_x", "white_point_y", "min_luminance", "max_luminance")
CLL_KEYS = ("max_content", "max_average")
COLOR_KEYS = ("color_primaries", "color_transfer", "color_space", "color_range")

# Values baked into the HDR sources by conftest.HDR10_X265
SOURCE_MAXCLL = (1000, 400)


def ffprobe_json(path, *args):
    cmd = ["ffprobe", "-v", "error", "-print_format", "json", *args, str(path)]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def ffprobe_info(filepath):
    return ffprobe_json(filepath, "-show_format", "-show_streams")


def video_stream(info):
    return next(s for s in info["streams"] if s["codec_type"] == "video")


@functools.lru_cache(maxsize=None)
def frames_side_data(path):
    """Per-frame side data of the first video stream (decodes the file)."""
    data = ffprobe_json(path, "-select_streams", "v:0", "-show_frames",
                        "-show_entries", "frame=side_data_list")
    return data.get("frames", [])


@functools.lru_cache(maxsize=None)
def count_frames(path):
    data = ffprobe_json(path, "-select_streams", "v:0", "-count_frames",
                        "-show_entries", "stream=nb_read_frames")
    return int(data["streams"][0]["nb_read_frames"])


def side_types(obj):
    return {sd["side_data_type"] for sd in obj.get("side_data_list", [])}


def _num(value):
    return float(Fraction(str(value)))


def color_tags(stream):
    return {k: stream.get(k, "unspecified") for k in COLOR_KEYS}


def static_hdr(path):
    """Mastering display + CLL values, from stream-level or first-frame side data."""
    vs = video_stream(ffprobe_info(path))
    frames = frames_side_data(str(path))
    blocks = list(vs.get("side_data_list", []))
    if frames:
        blocks += frames[0].get("side_data_list", [])
    out = {}
    for sd in blocks:
        kind = sd["side_data_type"]
        if kind == MASTERING:
            out.update({k: _num(sd[k]) for k in MASTERING_KEYS if k in sd})
        elif kind == CLL:
            out.update({k: _num(sd[k]) for k in CLL_KEYS if k in sd})
    return out


def assert_hdr_kind(path, kind, dovi_profiles=None):
    """kind: sdr | hdr10 | hdr10plus | dovi"""
    path = str(path)
    info = ffprobe_info(path)
    vs = video_stream(info)
    frames = frames_side_data(path)
    n = len(frames)
    present = side_types(vs) | (side_types(frames[0]) if frames else set())
    tags = color_tags(vs)

    if kind == "sdr":
        assert tags["color_transfer"] not in ("smpte2084", "arib-std-b67"), f"SDR file tagged HDR: {tags}"
        leaked = present & {MASTERING, CLL, HDR10PLUS, DOVI_CONF, DOVI_RPU, DOVI_META}
        assert not leaked, f"HDR metadata present in SDR file: {leaked}"
        return

    assert tags["color_transfer"] == "smpte2084", f"Not PQ: {tags}"
    assert tags["color_primaries"] == "bt2020", f"Not BT.2020: {tags}"
    assert tags["color_space"] == "bt2020nc", f"Wrong matrix: {tags}"
    assert "10" in vs["pix_fmt"] or "12" in vs["pix_fmt"], f"HDR needs >=10-bit, got {vs['pix_fmt']}"
    assert MASTERING in present, "Mastering display metadata missing"
    assert CLL in present, "MaxCLL/MaxFALL missing"

    if kind == "hdr10plus":
        n_dyn = sum(HDR10PLUS in side_types(f) for f in frames)
        assert n > 0 and n_dyn == n, f"HDR10+ dynamic metadata on only {n_dyn}/{n} frames"

    if kind == "dovi":
        conf = next((sd for sd in vs.get("side_data_list", [])
                     if sd["side_data_type"] == DOVI_CONF), None)
        n_rpu = sum(bool(side_types(f) & {DOVI_RPU, DOVI_META}) for f in frames)
        assert conf is not None or n_rpu > 0, "No Dolby Vision configuration record or RPU found"
        if conf is not None and dovi_profiles:
            assert conf.get("dv_profile") in dovi_profiles, f"Unexpected DoVi profile: {conf}"
        if vs["codec_name"] == "hevc":
            assert n_rpu == n, f"DoVi RPU on only {n_rpu}/{n} frames"


def psnr_planes(src, out, crop, width, height):
    """PSNR per plane of `out` against `src` cropped (letterbox removed) and scaled to out size."""
    top, bottom = crop
    graph = (f"[0:v:0]crop=iw:ih-{top + bottom}:0:{top},scale={width}:{height}:flags=bicubic,"
             f"format=yuv420p10le[a];"
             f"[1:v:0]scale={width}:{height}:flags=bicubic,format=yuv420p10le[b];[a][b]psnr")
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(src), "-i", str(out),
                        "-filter_complex", graph, "-f", "null", "-"],
                       capture_output=True, text=True)
    m = re.search(r"PSNR y:(\S+) u:(\S+) v:(\S+)", r.stderr)
    assert m, f"PSNR not reported:\n{r.stderr[-600:]}"
    y, u, v = (float(x) for x in m.groups())
    return {"y": y, "u": u, "v": v}


def find_values(obj, key):
    """Recursively collect every value stored under `key` in nested JSON."""
    found = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == key:
                found.append(v)
            found += find_values(v, key)
    elif isinstance(obj, list):
        for item in obj:
            found += find_values(item, key)
    return found


def run_tool(*cmd):
    return subprocess.run(list(cmd), capture_output=True, text=True)


# ---------------------------------------------------------------------------
# Shared pipeline test implementation
# ---------------------------------------------------------------------------
class _PipelineTestBase:
    """Shared implementation for all per-case pipeline test classes.

    A dedicated subclass is generated per PIPELINE_CASES entry (see
    _make_pipeline_test_class / the loop at the bottom of this file), each
    with its own fixed `case` class attribute, so each case shows up as its
    own top-level class node with test_00..test_11 nested underneath.

    Tests run in definition order and share state (vpc, output path) via
    class attributes. Tests after test_03 skip if the final encode produced
    no output.
    """

    case = None
    out_path = None

    @pytest.fixture(scope="class", autouse=True)
    def setup_case(self, request, tmp_path_factory):
        case = self.case
        source_path = request.getfixturevalue(case["file_fixture"])
        workspace = str(tmp_path_factory.mktemp(f"case_{case['id']}"))

        vpc = VideoProcessingConfig(source_path, f"pipeline_case_{case['id']}", workspace)
        vpc.readProfiles(case["profile"], FAST_SETTINGS)
        assert "HDR_enable" in vpc.profile, (
            f"Profile {case['profile']!r} for case {case['id']!r} is missing 'HDR_enable' - "
            f"wrong profile file specified?"
        )

        vpc.analyzeOriginal()
        vpc.setSourcePath(vpc.orig_file_path)

        request.cls.vpc = vpc
        request.cls.source_fixture = source_path
        request.cls.out_path = None

    @pytest.fixture(autouse=True)
    def _known_issues(self, request):
        reason = self.case.get("known_issues", {}).get(request.node.originalname)
        if reason:
            request.applymarker(pytest.mark.xfail(reason=reason, strict=False))

    def _out(self):
        out = type(self).out_path
        if not out or not os.path.isfile(out):
            pytest.skip("final encode produced no output file")
        return out

    # -- source sanity ------------------------------------------------------
    def test_00_source_matches_fixture_claims(self):
        """Guards against vacuous tests: the synthetic source must really
        contain the HDR/colour data the case says it does."""
        case = self.case
        assert_hdr_kind(self.source_fixture, case["output_hdr"])
        if case["output_hdr"] != "sdr":
            sh = static_hdr(self.source_fixture)
            assert (sh.get("max_content"), sh.get("max_average")) == SOURCE_MAXCLL, sh
        if case["output_hdr"] == "dovi" and shutil.which("dovi_tool"):
            tmp = os.path.join(self.vpc.workspace, "src_rpu_check.bin")
            r1 = run_tool("dovi_tool", "extract-rpu", "-i", self.source_fixture, "-o", tmp)
            assert r1.returncode == 0, r1.stderr
            dump = os.path.join(self.vpc.workspace, "src_rpu_check.json")
            r2 = run_tool("dovi_tool", "export", "-i", tmp, "-d", f"all={dump}")
            assert r2.returncode == 0, r2.stderr
            with open(dump) as f:
                tops = find_values(json.load(f), "active_area_top_offset")
            if tops:
                assert set(tops) == {140}, f"Source RPU should carry letterbox offsets, got {set(tops)}"

    # -- detection ----------------------------------------------------------
    def test_01_hdr_detection(self):
        case = self.case
        vpc = self.vpc
        assert vpc.is_H265 == case["is_H265"], (
            f"Expected is_H265={case['is_H265']!r} for source, got {vpc.is_H265!r}"
        )
        if not case["is_H265"]:
            assert vpc.profile["HDR_enable"][1] is False, "H.264 source must force HDR_enable off"

        if vpc.profile["HDR_enable"][1] == True:
            get_video_metadata_type(vpc)
        else:
            vpc.HDR_type = "None"  # test-side stand-in for the disabled-HDR path

        assert vpc.HDR_type == case["expected_hdr_type"], (
            f"Expected HDR_type={case['expected_hdr_type']!r}, got {vpc.HDR_type!r}"
        )

    # -- calibration --------------------------------------------------------
    def test_02_calibration(self):
        case = self.case
        vpc = self.vpc
        passed = AVTest.runTests(vpc)
        assert passed == True, "Calibration stage (black bars / VQA / VMAF) failed"

        print(f"[{case['id']}] output_res={vpc.output_res}, output_cq={vpc.output_cq}, crop={vpc.crop}")
        assert isinstance(vpc.crop, list) and len(vpc.crop) == 2

        tol = case["crop_tolerance"]
        for edge, (got, want) in enumerate(zip(vpc.crop, case["expected_crop"])):
            assert abs(got - want) <= tol, (
                f"Crop edge {edge}: expected {want} +/- {tol} for letterboxed source, "
                f"got {got} (full crop {vpc.crop})"
            )

        assert vpc.output_res in case["valid_resolutions"], (
            f"Calibrated resolution {vpc.output_res} not in expected set {case['valid_resolutions']}"
        )
        assert isinstance(vpc.output_cq, (int, float)) and vpc.output_cq > 0

    # -- final encode -------------------------------------------------------
    def test_03_final_encode(self):
        case = self.case
        vpc = self.vpc
        vpc.is_final_export = True
        result = compress(vpc)
        assert result == True, "Final encode failed"
        assert os.path.isfile(vpc.output_file_path)
        type(self).out_path = vpc.output_file_path

        info = ffprobe_info(vpc.output_file_path)
        vs = video_stream(info)
        assert vs["codec_name"] == case["expected_codec"], (
            f"Expected output codec {case['expected_codec']!r}, got {vs['codec_name']!r}"
        )
        actual = float(info["format"]["duration"])
        assert abs(actual - case["expected_duration"]) < case["duration_tolerance"], (
            f"Output duration {actual}s outside {case['expected_duration']}s +/- {case['duration_tolerance']}s"
        )

    def test_04_source_not_deleted(self):
        """compressor2.delete_file() is called on VPC.source_path; with
        Enable_delete on and no temporal crop that is the original file.
        The session-scoped fixture must survive (other cases reuse it)."""
        self._out()
        assert os.path.isfile(self.source_fixture), "Pipeline deleted the original source file"

    # -- HDR / colour -------------------------------------------------------
    def test_05_hdr_present_in_output(self):
        assert_hdr_kind(self._out(), self.case["output_hdr"], dovi_profiles=self.case["dovi_profiles"])

    def test_06_static_hdr_values_preserved(self):
        if self.case["output_hdr"] == "sdr":
            pytest.skip("SDR case")
        src = static_hdr(self.source_fixture)
        out = static_hdr(self._out())
        assert out, "No static HDR metadata found in output"
        for k in ("red_x", "red_y", "green_x", "green_y", "blue_x", "blue_y",
                  "white_point_x", "white_point_y"):
            assert abs(out[k] - src[k]) < 1e-3, f"{k}: source {src[k]} -> output {out[k]}"
        assert abs(out["max_luminance"] - src["max_luminance"]) <= 0.01 * src["max_luminance"], \
            f"max_luminance: {src['max_luminance']} -> {out['max_luminance']}"
        assert abs(out["min_luminance"] - src["min_luminance"]) <= 2e-4, \
            f"min_luminance: {src['min_luminance']} -> {out['min_luminance']}"
        assert out["max_content"] == src["max_content"], f"MaxCLL {src['max_content']} -> {out['max_content']}"
        assert out["max_average"] == src["max_average"], f"MaxFALL {src['max_average']} -> {out['max_average']}"

    def test_07_color_tags_preserved(self):
        src = video_stream(ffprobe_info(self.source_fixture))
        out = video_stream(ffprobe_info(self._out()))
        assert color_tags(out) == color_tags(src), f"{color_tags(src)} -> {color_tags(out)}"
        if src.get("chroma_location", "unspecified") != "unspecified":
            assert out.get("chroma_location") == src["chroma_location"], \
                f"chroma_location {src['chroma_location']} -> {out.get('chroma_location')}"
        if self.case["min_bit_depth"]:
            assert str(self.case["min_bit_depth"]) in out["pix_fmt"], f"pix_fmt {out['pix_fmt']}"

    # -- geometry / streams / fidelity --------------------------------------
    def test_08_geometry_streams_frames(self):
        out_path = self._out()
        info = ffprobe_info(out_path)
        assert [s["codec_type"] for s in info["streams"]] == ["video"], \
            f"Expected exactly one video stream (-an -sn), got {[s['codec_type'] for s in info['streams']]}"
        vs = video_stream(info)
        w, h = vs["width"], vs["height"]
        assert w == self.vpc.output_res, f"width {w} != output_res {self.vpc.output_res}"
        tol = self.case.get("crop_tolerance", 2)
        expected_h = 2 * round((w * (1080 - 280) / 1920) / 2)
        # Account for crop tolerance on both top and bottom bars plus even-pixel rounding
        h_tol = 2 * tol + 2
        assert h % 2 == 0 and abs(h - expected_h) <= h_tol, \
            f"height {h}, expected ~{expected_h} ± {h_tol} (bars removed)"
        assert count_frames(out_path) == count_frames(self.source_fixture), "Frame count changed"
        assert vs.get("r_frame_rate") == "24/1", f"Frame rate changed: {vs.get('r_frame_rate')}"

    def test_09_pixel_fidelity(self):
        out_path = self._out()
        vs = video_stream(ffprobe_info(out_path))
        psnr = psnr_planes(self.source_fixture, out_path, self.vpc.crop, vs["width"], vs["height"])
        floor = self.case["min_psnr"]
        print(f"[{self.case['id']}] PSNR {psnr}")
        assert psnr["y"] > floor["y"], f"luma PSNR {psnr['y']:.1f} dB"
        assert psnr["u"] > floor["u"] and psnr["v"] > floor["v"], \
            f"chroma PSNR u={psnr['u']:.1f} v={psnr['v']:.1f} dB (colour shift?)"

    # -- tool-level metadata integrity (HEVC output only) -------------------
    def test_10_dovi_rpu_integrity(self, tmp_path):
        case = self.case
        if case["output_hdr"] != "dovi" or case["expected_codec"] != "hevc":
            pytest.skip("DoVi + HEVC output only (dovi_tool cannot read AV1)")
        if not shutil.which("dovi_tool"):
            pytest.skip("dovi_tool not installed")
        hevc_path = str(tmp_path / "out.hevc")
        rpu = str(tmp_path / "out_rpu.bin")
        dump = str(tmp_path / "out_rpu.json")
        r = run_tool(
            "ffmpeg", "-y", "-v", "error",
            "-i", self._out(),
            "-map", "0:V:0", "-c:v", "copy",
            "-bsf:v", "hevc_mp4toannexb",
            "-f", "hevc", hevc_path,
        )
        assert r.returncode == 0, r.stderr
        r = run_tool("dovi_tool", "extract-rpu", "-i", hevc_path, "-o", rpu)
        assert r.returncode == 0, r.stderr
        r = run_tool("dovi_tool", "export", "-i", rpu, "-d", f"all={dump}")
        assert r.returncode == 0, r.stderr
        with open(dump) as f:
            data = json.load(f)
        frame_count = count_frames(self._out())
        assert len(data) == frame_count, f"{len(data)} RPUs for {frame_count} frames"
        for key in ("active_area_top_offset", "active_area_bottom_offset",
                    "active_area_left_offset", "active_area_right_offset"):
            values = find_values(data, key)
            assert all(v == 0 for v in values), \
                f"RPU {key} not reset after crop (crop_dovi_rpu): {set(values)}"

    def test_11_hdr10plus_integrity(self, tmp_path):
        case = self.case
        if case["output_hdr"] != "hdr10plus" or case["expected_codec"] != "hevc":
            pytest.skip("HDR10+ + HEVC output only (hdr10plus_tool cannot read AV1)")
        if not shutil.which("hdr10plus_tool"):
            pytest.skip("hdr10plus_tool not installed")
        hevc_path = str(tmp_path / "out.hevc")
        dump = str(tmp_path / "out_hdr10plus.json")
        r = run_tool(
            "ffmpeg", "-y", "-v", "error",
            "-i", self._out(),
            "-map", "0:V:0", "-c:v", "copy",
            "-bsf:v", "hevc_mp4toannexb",
            "-f", "hevc", hevc_path,
        )
        assert r.returncode == 0, r.stderr
        r = run_tool("hdr10plus_tool", "extract", hevc_path, "-o", dump)
        assert r.returncode == 0, r.stderr
        with open(dump) as f:
            scenes = json.load(f)["SceneInfo"]
        frame_count = count_frames(self._out())
        assert len(scenes) == frame_count, \
            f"{len(scenes)} HDR10+ entries for {frame_count} frames"


def _make_pipeline_test_class(case):
    return type(
        f"TestPipeline_{case['id']}",
        (_PipelineTestBase,),
        {
            "case": case,
            "__doc__": f"Pipeline case: {case['id']}",
        },
    )


# Generate one test class per PIPELINE_CASES entry and register it at module
# scope so pytest's collector picks it up like any other TestXxx class.
for _case in PIPELINE_CASES:
    globals()[f"TestPipeline_{_case['id']}"] = _make_pipeline_test_class(_case)
del _case