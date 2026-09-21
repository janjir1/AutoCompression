import subprocess
import json
import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

@pytest.fixture(scope="session")
def synthetic_dovi_clip(tmp_path_factory):
    """Generates a 10s H.265 elementary stream with a synthetic Profile 8.1 DoVi RPU injected."""

    tmp_path = tmp_path_factory.mktemp("synthetic_dovi")

    fps = 24
    duration = 10
    num_frames = fps * duration

    # 1. Generate raw H.265 elementary stream (not MKV -- inject-rpu needs the raw bitstream)
    raw_hevc = tmp_path / "raw.hevc"
    encode_command = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"testsrc2=size=1920x1080:rate={fps}:duration={duration}",
        "-pix_fmt", "yuv420p10le",
        "-c:v", "libx265",
        "-x265-params", "hdr10=1:repeat-headers=1",
        str(raw_hevc)
    ]
    subprocess.run(encode_command, check=True, capture_output=True)

    # 2. Build a minimal Profile 8.1 RPU generator config
    rpu_config = {
        "cm_version": "V40",
        "profile": "8.1",
        "length": num_frames,
        "level6": {
            "max_display_mastering_luminance": 1000,
            "min_display_mastering_luminance": 1,
            "max_content_light_level": 1000,
            "max_frame_average_light_level": 400
        }
    }
    config_path = tmp_path / "rpu_config.json"
    with open(config_path, "w") as f:
        json.dump(rpu_config, f)

    # 3. Generate the synthetic RPU binary
    rpu_bin = tmp_path / "synthetic_rpu.bin"
    subprocess.run(
        ["dovi_tool", "generate", "-j", str(config_path), "-o", str(rpu_bin)],
        check=True, capture_output=True
    )

    # 4. Inject the RPU into the raw H.265 stream
    injected_hevc = tmp_path / "injected.hevc"
    subprocess.run(
        ["dovi_tool", "inject-rpu", "-i", str(raw_hevc), "--rpu-in", str(rpu_bin), "-o", str(injected_hevc)],
        check=True, capture_output=True
    )

    # 5. Remux to MKV so it matches what your pipeline actually expects as input
    output_mkv = tmp_path / "synthetic_dovi_input.mkv"
    subprocess.run(
        ["mkvmerge", "-o", str(output_mkv), "--default-duration", f"0:{fps}fps", str(injected_hevc)],
        check=True, capture_output=True
    )

    return str(output_mkv)