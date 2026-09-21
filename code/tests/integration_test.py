import pytest
import subprocess
import json
import os
import logging
from compressor2 import compress, get_video_metadata_type
from VideoClass import VideoProcessingConfig
import AVTest


def ffprobe_info(filepath):
    cmd = ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", filepath]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return json.loads(result.stdout)


FAST_SETTINGS = os.path.join(os.path.dirname(__file__), "fast_test_settings.yaml")


# ---------------------------------------------------------------------------
# Pipeline case configuration.
#
# Add a new entry here to run the full pipeline against another source /
# profile combination -- no new test code required.
#
#   id                 : short label, shows up in test names as [id]
#   file_fixture       : name of a conftest.py fixture that returns a path
#                        to the source clip to use for this case
#   profile            : path to the encode profile yaml, relative to repo root
#   expected_hdr_type  : value VPC.HDR_type must equal after detection
#   valid_resolutions  : acceptable values for VPC.output_res after calibration
#   expected_duration  : expected output duration in seconds (tolerance applied)
#   duration_tolerance : +/- seconds allowed around expected_duration
# ---------------------------------------------------------------------------
PIPELINE_CASES = [
    {
        "id": "dovi_1080p",
        "file_fixture": "synthetic_dovi_clip",
        "profile": "Profiles/AV1_svt_archive_sw.yaml",
        "expected_hdr_type": "DoVi",
        "valid_resolutions": [854, 1280, 1920],
        "expected_duration": 10.0,
        "duration_tolerance": 2.0,
    },
]



@pytest.mark.parametrize(
    "case",
    PIPELINE_CASES,
    ids=[c["id"] for c in PIPELINE_CASES],
    scope="class", 
)
class TestPipeline:
    """Full pipeline: HDR detection -> calibration (VQA/VMAF) -> crop -> AV1 encode -> mkv.

    Parametrized by PIPELINE_CASES above. Each case gets its own isolated
    VideoProcessingConfig, built once in setup_case and shared across
    test_01/02/03 within that case.
    """

    @pytest.fixture(scope="class", autouse=True)
    def setup_case(self, request, case, tmp_path_factory):
        source_path = request.getfixturevalue(case["file_fixture"])
        workspace = str(tmp_path_factory.mktemp(f"case_{case['id']}"))

        vpc = VideoProcessingConfig(source_path, f"pipeline_case_{case['id']}", workspace)
        vpc.readProfiles(case["profile"], FAST_SETTINGS, None)
        vpc.analyzeOriginal()
        vpc.setSourcePath(vpc.orig_file_path)

        request.cls.vpc = vpc
        request.cls.case = case

    @pytest.fixture(autouse=True)
    def print_warnings_and_above(self, caplog):
        caplog.set_level(logging.WARNING)
        yield
        flagged = [r for r in caplog.records if r.levelno >= logging.WARNING]
        if flagged:
            print(f"\n--- {len(flagged)} warning(s)/error(s) logged during this test ---")
            for r in flagged:
                print(f"[{r.levelname}] {r.name}: {r.message}")

    def test_01_hdr_detection(self, case):
        vpc = self.vpc
        assert vpc.is_H265 == True, "Source must be detected as H.265 for HDR gating to activate"

        if vpc.profile["HDR_enable"][1] == True:
            get_video_metadata_type(vpc)
        else:
            vpc.HDR_type = "None"

        assert vpc.HDR_type == case["expected_hdr_type"], (
            f"Expected HDR_type={case['expected_hdr_type']!r}, got {vpc.HDR_type!r}"
        )

    def test_02_calibration(self, case):
        vpc = self.vpc
        passed = AVTest.runTests(vpc)
        assert passed == True, "Calibration stage (black bars / VQA / VMAF) failed"

        print(f"[{case['id']}] output_res={vpc.output_res}, output_cq={vpc.output_cq}")

        assert isinstance(vpc.crop, list) and len(vpc.crop) == 2
        assert vpc.output_res in case["valid_resolutions"], (
            f"Calibrated resolution {vpc.output_res} not in expected set {case['valid_resolutions']}"
        )
        assert isinstance(vpc.output_cq, (int, float)) and vpc.output_cq > 0

    def test_03_final_encode(self, case):
        vpc = self.vpc
        vpc.is_final_export = True
        result = compress(vpc)
        assert result == True, "Final AV1 encode failed"
        assert os.path.isfile(vpc.output_file_path)

        info = ffprobe_info(vpc.output_file_path)
        video_stream = next(s for s in info["streams"] if s["codec_type"] == "video")
        assert video_stream["codec_name"] == "av1"

        actual_duration = float(info["format"]["duration"])
        expected = case["expected_duration"]
        tolerance = case["duration_tolerance"]
        assert abs(actual_duration - expected) < tolerance, (
            f"Output duration {actual_duration}s outside {expected}s +/- {tolerance}s"
        )