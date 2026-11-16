import json
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# ---------------------------------------------------------------------------
# Shared geometry: every synthetic source uses the same letterbox so crop
# assertions (VPC.crop == [140, 140]) stay identical across all cases.
# ---------------------------------------------------------------------------
FPS = 24
DURATION = 10
NUM_FRAMES = FPS * DURATION
FRAME_WIDTH = 1920
FRAME_HEIGHT = 1080
BAR_HEIGHT = 140
CONTENT_HEIGHT = FRAME_HEIGHT - (2 * BAR_HEIGHT)

# ---------------------------------------------------------------------------
# Colour / static HDR metadata baked into the sources. integration_test.py
# checks that the pipeline carries these values through to the output.
#   master-display units: chromaticity 0.00002, luminance 0.0001 cd/m2
#   -> G(0.265,0.690) B(0.150,0.060) R(0.680,0.320) WP(0.3127,0.3290) L(1000, 0.0001)
#   max-cll = MaxCLL 1000, MaxFALL 400
# ---------------------------------------------------------------------------
HDR10_X265 = (
    "hdr10=1:repeat-headers=1:"
    "colorprim=bt2020:transfer=smpte2084:colormatrix=bt2020nc:range=limited:"
    "master-display=G(13250,34500)B(7500,3000)R(34000,16000)WP(15635,16450)L(10000000,1):"
    "max-cll=1000,400"
)
SDR_X265 = "repeat-headers=1:colorprim=bt709:transfer=bt709:colormatrix=bt709:range=limited"
SDR_FULL_X265 = "repeat-headers=1:colorprim=bt709:transfer=bt709:colormatrix=bt709:range=full"
SDR_X264_FLAGS = ["-color_primaries", "bt709", "-color_trc", "bt709",
                  "-colorspace", "bt709", "-color_range", "tv"]


def _encode_letterboxed_raw(tmp_path, codec, extra_params=None, x265_params=None):
    """Generates a letterboxed raw elementary stream (.hevc or .264) using
    the shared letterbox geometry. Returns the path to the raw file.
    """
    ext = "hevc" if codec == "libx265" else "264"
    raw_path = tmp_path / f"raw.{ext}"

    command = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"testsrc2=size={FRAME_WIDTH}x{CONTENT_HEIGHT}:rate={FPS}:duration={DURATION}",
        "-vf", f"pad={FRAME_WIDTH}:{FRAME_HEIGHT}:0:{BAR_HEIGHT}:black",
        "-pix_fmt", "yuv420p10le" if codec == "libx265" else "yuv420p",
        "-c:v", codec,
    ]
    if x265_params:
        command += ["-x265-params", x265_params]
    if extra_params:
        command += extra_params
    command += [str(raw_path)]

    subprocess.run(command, check=True, capture_output=True)
    return raw_path


def _remux_to_mkv(tmp_path, source_path, output_name="synthetic_input.mkv"):
    output_mkv = tmp_path / output_name
    subprocess.run(
        ["mkvmerge", "-o", str(output_mkv), "--default-duration", f"0:{FPS}fps", str(source_path)],
        check=True, capture_output=True
    )
    return output_mkv


# ---------------------------------------------------------------------------
# HDR sources
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def synthetic_dovi_clip(tmp_path_factory):
    """10s H.265, letterboxed, static HDR10 + synthetic Profile 8.1 DoVi RPU.
    The RPU carries L5 active-area offsets matching the letterbox so the
    crop -> RPU active-area edit can be verified.
    """
    tmp_path = tmp_path_factory.mktemp("synthetic_dovi")

    raw_hevc = _encode_letterboxed_raw(tmp_path, "libx265", x265_params=HDR10_X265)

    rpu_config = {
        "cm_version": "V40",
        "profile": "8.1",
        "length": NUM_FRAMES,
        "level5": {
            "active_area_left_offset": 0,
            "active_area_right_offset": 0,
            "active_area_top_offset": BAR_HEIGHT,
            "active_area_bottom_offset": BAR_HEIGHT,
        },
        "level6": {
            "max_display_mastering_luminance": 1000,
            "min_display_mastering_luminance": 1,
            "max_content_light_level": 1000,
            "max_frame_average_light_level": 400,
        },
    }
    config_path = tmp_path / "rpu_config.json"
    with open(config_path, "w") as f:
        json.dump(rpu_config, f)

    rpu_bin = tmp_path / "synthetic_rpu.bin"
    subprocess.run(
        ["dovi_tool", "generate", "-j", str(config_path), "-o", str(rpu_bin)],
        check=True, capture_output=True
    )

    injected_hevc = tmp_path / "injected.hevc"
    subprocess.run(
        ["dovi_tool", "inject-rpu", "-i", str(raw_hevc), "--rpu-in", str(rpu_bin), "-o", str(injected_hevc)],
        check=True, capture_output=True
    )

    output_mkv = _remux_to_mkv(tmp_path, injected_hevc, "synthetic_dovi_input.mkv")
    return str(output_mkv)


@pytest.fixture(scope="session")
def synthetic_hdr10plus_clip(tmp_path_factory):
    """10s H.265, letterboxed, static HDR10 (mastering display + CLL/FALL)
    plus synthetic dynamic HDR10+ (ST 2094-40) metadata injected via
    hdr10plus_tool.
    """
    tmp_path = tmp_path_factory.mktemp("synthetic_hdr10plus")

    raw_hevc = _encode_letterboxed_raw(tmp_path, "libx265", x265_params=HDR10_X265)

    def make_frame_entry(sequence_index, scene_frame_index):
        return {
            "LuminanceParameters": {
                "AverageRGB": 400,
                "LuminanceDistributions": {
                    "DistributionIndex": [1, 5, 10, 25, 50, 75, 90, 95, 99],
                    "DistributionValues": [50, 100, 200, 400, 600, 800, 900, 950, 995]
                },
                "MaxScl": [1000, 1000, 1000]
            },
            "NumberOfWindows": 1,
            "TargetedSystemDisplayMaximumLuminance": 0,
            "SceneFrameIndex": scene_frame_index,
            "SceneId": 0,
            "SequenceFrameIndex": sequence_index,
        }

    hdr10plus_config = {
        "JSONInfo": {"HDR10plusProfile": "B", "Version": "1.0"},
        "ToolInfo": {"Tool": "hdr10plus_parser", "Version": "1.7.2"},
        "SceneInfo": [make_frame_entry(i, i) for i in range(NUM_FRAMES)],
        "SceneInfoSummary": {
            "SceneFirstFrameIndex": [0],
            "SceneFrameNumbers": [NUM_FRAMES]
        },
    }

    metadata_path = tmp_path / "hdr10plus_metadata.json"
    with open(metadata_path, "w") as f:
        json.dump(hdr10plus_config, f)

    injected_hevc = tmp_path / "injected.hevc"
    inject = subprocess.run(
        ["hdr10plus_tool", "inject", "-i", str(raw_hevc), "-j", str(metadata_path), "-o", str(injected_hevc)],
        capture_output=True, text=True
    )
    if inject.returncode != 0:
        pytest.skip(
            f"hdr10plus_tool injection failed, likely a JSON schema mismatch "
            f"for this hdr10plus_tool version: {inject.stderr}"
        )

    output_mkv = _remux_to_mkv(tmp_path, injected_hevc, "synthetic_hdr10plus_input.mkv")
    return str(output_mkv)


@pytest.fixture(scope="session")
def synthetic_hdr10_clip(tmp_path_factory):
    """10s H.265, letterboxed, STATIC HDR10 only (PQ/BT.2020 + mastering
    display + CLL/FALL). No DoVi, no HDR10+.
    The pipeline must detect HDR_type == "None" yet still carry the static
    metadata through to the output.
    """
    tmp_path = tmp_path_factory.mktemp("synthetic_hdr10")
    raw_hevc = _encode_letterboxed_raw(tmp_path, "libx265", x265_params=HDR10_X265)
    return str(_remux_to_mkv(tmp_path, raw_hevc, "synthetic_hdr10_input.mkv"))


# ---------------------------------------------------------------------------
# SDR sources
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def synthetic_sdr_h265_clip(tmp_path_factory):
    """10s H.265, letterboxed, plain SDR tagged BT.709 limited range."""
    tmp_path = tmp_path_factory.mktemp("synthetic_sdr_h265")
    raw_hevc = _encode_letterboxed_raw(tmp_path, "libx265", x265_params=SDR_X265)
    return str(_remux_to_mkv(tmp_path, raw_hevc, "synthetic_sdr_h265_input.mkv"))


@pytest.fixture(scope="session")
def synthetic_sdr_fullrange_clip(tmp_path_factory):
    """10s H.265, letterboxed, SDR tagged BT.709 FULL range. Used to check
    that the colour-range tag is not silently rewritten to limited."""
    tmp_path = tmp_path_factory.mktemp("synthetic_sdr_fullrange")
    raw_hevc = _encode_letterboxed_raw(tmp_path, "libx265", x265_params=SDR_FULL_X265)
    return str(_remux_to_mkv(tmp_path, raw_hevc, "synthetic_sdr_fullrange_input.mkv"))


@pytest.fixture(scope="session")
def synthetic_h264_clip(tmp_path_factory):
    """10s H.264, letterboxed, SDR BT.709, no HDR metadata at all. Exercises
    the `VPC.is_H265 == False` gate that forces `profile["HDR_enable"] = False`
    in VideoProcessingConfig.analyzeOriginal().
    """
    tmp_path = tmp_path_factory.mktemp("synthetic_h264")
    raw_h264 = _encode_letterboxed_raw(tmp_path, "libx264", extra_params=SDR_X264_FLAGS)
    return str(_remux_to_mkv(tmp_path, raw_h264, "synthetic_h264_input.mkv"))