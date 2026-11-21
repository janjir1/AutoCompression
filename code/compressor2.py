import shutil
import subprocess
import os
import json
import logging
import signal
import time
from threading import Thread
from fractions import Fraction

import AVTest
import logger_setup
from VideoClass import VideoProcessingConfig

# TODO:
# - Clean up leftover VapourSynth .lwi index files inside delete_file() (e.g. str(file) + ".lwi")
#   and remove stale .lwi cache files before reusing the same filename.
# - Fast-seek MKV Cues issue (in VideoClass.py / temporal_crop): MakeMKV and mkvmerge usually place
#   the Matroska Cues (0x1C53BB6B) at the end of the file and point to it via SeekHead (0x114D9B74)
#   at the beginning. Scanning only the first 1 MB for Cues before Cluster causes get_fast_seek_support()
#   to return False on valid MKVs, forcing slow output seeking (-ss after -i) in temporal_crop().
# - Implement Dolby Vision Profile 5 conversion/reshaping (currently rejected early).
# - NOTE / TODO: Pipeline assumes square pixels (SAR 1:1); anamorphic sources (e.g. DVDs) are not handled.

# Retrieve the logger once at the module level
logger = logging.getLogger("AppLogger")
stream_logger = logging.getLogger("FileLogger")

max_timeout = 604800


def compress(VPC: VideoProcessingConfig) -> bool:
    """
    Compress a video file using the specified profile and encoding function.

    This function orchestrates the complete video compression workflow, including
    temporal cropping (if needed) and the main compression process using the
    configured encoding function.
    """
    logger.info(f"[compress] Starting compression workflow for file: {VPC.orig_file_path}")
    logger.debug(
        f"[compress] Compression parameters - Profile: {VPC.profile['function'][1]}, "
        f"Target resolution: {VPC.output_res}, CQ: {VPC.output_cq}, Crop: {VPC.crop}"
    )

    if getattr(VPC, "dv_profile", None) == 5:
        # TODO: Implement Dolby Vision Profile 5 conversion/reshaping
        logger.error("[compress] Dolby Vision Profile 5 is not supported yet, aborting compression")
        return False

    # Handle temporal cropping if start time or duration is specified
    if VPC.start is not False or VPC.duration is not False:
        logger.debug(f"[compress] Temporal cropping required - Start: {VPC.start}s, Duration: {VPC.duration}s")
        VPC.setSourcePath(VPC.orig_file_path)
        VPC.setTargetPath(os.path.join(VPC.workspace, VPC.output_file_name + "_time_crop.mkv"))
        logger.debug(f"[compress] Performing temporal crop to: {VPC.target_path}")

        if not temporal_crop(VPC):
            logger.error("[compress] Temporal cropping failed, aborting compression")
            return False

        # Use the temporally cropped file as input for main compression
        VPC.setSourcePath(VPC.target_path)
    else:
        VPC.setSourcePath(VPC.orig_file_path)

    # Map compression function names to actual functions
    function_mapping = {
        "ffmpeg": video_ffmpeg_h265,
        "ffmpeg_AV1": video_ffmpeg_AV1,
    }

    # Validate that the requested compression function exists
    compression_function_name = VPC.profile["function"][1]
    if compression_function_name not in function_mapping:
        logger.error(f"[compress] Compression function '{compression_function_name}' not found in function mapping")
        logger.error(f"[compress] Available functions: {list(function_mapping.keys())}")
        return False

    # Execute the appropriate compression function
    compression_func = function_mapping[compression_function_name]
    logger.debug(f"[compress] Using compression function: {compression_function_name}")

    success = compression_func(VPC)

    if success:
        logger.info(f"[compress] Compression completed successfully for: {VPC.output_file_path}")
    else:
        logger.error(f"[compress] Compression failed for: {VPC.output_file_path}")

    return success


def execute(command: list, timeout: int = 3600) -> bool:
    """
    Execute a command using subprocess with real-time logging of stdout and stderr.
    """
    cmd_str = [str(c) for c in command]
    logger.debug("[execute] Starting command execution")
    logger.debug(f"[execute] Command: {' '.join(cmd_str)}")

    process = subprocess.Popen(
        cmd_str,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=False,
        start_new_session=True,
    )

    stream_logger = logging.getLogger("FileLogger")
    for _ in range(6):
        stream_logger.debug("-" * 94)
    stream_logger.debug(f"[execute] Command: {cmd_str}")

    def log_stream(stream, stream_type, file_log):
        last_line = None
        decoder = iter(lambda: stream.read(1), b"")
        line_buffer = bytearray()

        for byte in decoder:
            line_buffer += byte

            if byte in (b"\n", b"\r"):
                if not line_buffer:
                    continue

                try:
                    decoded_line = line_buffer.decode("utf-8").rstrip("\r\n")
                    stripped_line = decoded_line.strip()
                except UnicodeDecodeError:
                    decoded_line = line_buffer.decode("utf-8", errors="replace").rstrip("\r\n")
                    stripped_line = decoded_line.strip()
                    file_log.warning(f"Encoding issue detected in {stream_type} stream")

                line_buffer = bytearray()

                if not stripped_line or stripped_line == last_line:
                    continue

                file_log.debug(f"[{stream_type}] {decoded_line}")
                last_line = stripped_line

        logger.debug(f"[execute.log_stream] Finished {stream_type} logging thread")

    logger.debug("[execute] Starting logging threads for stdout and stderr")
    stdout_thread = Thread(target=log_stream, args=(process.stdout, "STDOUT", stream_logger))
    stderr_thread = Thread(target=log_stream, args=(process.stderr, "STDERR", stream_logger))

    stdout_thread.start()
    stderr_thread.start()

    logger.debug("[execute] Waiting for process completion")
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        logger.error(f"[execute] Process exceeded {timeout}s timeout, terminating")
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()
        stdout_thread.join(timeout=5)
        stderr_thread.join(timeout=5)
        return False

    stdout_thread.join()
    stderr_thread.join()

    if process.returncode != 0:
        logger.error(f"[execute] Process failed with exit code: {process.returncode}")
        return False

    logger.debug("[execute] Command execution finished successfully")
    return True


def execute_pipeline(commands: list, timeout: int = 3600) -> bool:
    """
    Run commands connected by pipes (cmd1 | cmd2 | ...) without a shell.
    Every command is a list. Each process's stderr is logged; the last
    process's stdout is logged. Returns True only if ALL processes exit 0.
    """
    for cmd in commands:
        logger.debug(f"[execute_pipeline] Command: {cmd}")

    stream_logger = logging.getLogger("FileLogger")
    for _ in range(6):
        stream_logger.debug("-" * 94)
    stream_logger.debug(f"[execute_pipeline] Commands: {commands}")

    procs = []
    threads = []
    pgid = None
    prev_stdout = None

    def log_stream(stream, stream_type, label):
        last_line = None
        buf = bytearray()
        for byte in iter(lambda: stream.read(1), b""):
            buf += byte
            if byte not in (b"\n", b"\r"):
                continue
            line = buf.decode("utf-8", errors="replace").rstrip("\r\n")
            buf = bytearray()
            stripped = line.strip()
            if not stripped or stripped == last_line:
                continue
            stream_logger.debug(f"[{stream_type}:{label}] {line}")
            last_line = stripped

    try:
        for i, cmd in enumerate(commands):
            cmd_str = [str(c) for c in cmd]
            is_last = i == len(commands) - 1
            p = subprocess.Popen(
                cmd_str,
                stdin=prev_stdout,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                process_group=(0 if i == 0 else pgid),
            )
            if i == 0:
                pgid = p.pid
            if prev_stdout is not None:
                prev_stdout.close()
            prev_stdout = p.stdout
            procs.append(p)

            threads.append(Thread(target=log_stream, args=(p.stderr, "STDERR", cmd_str[0])))
            if is_last:
                threads.append(Thread(target=log_stream, args=(p.stdout, "STDOUT", cmd_str[0])))

        for t in threads:
            t.start()

        deadline = time.monotonic() + timeout
        for p in procs:
            p.wait(timeout=max(0.0, deadline - time.monotonic()))

    except subprocess.TimeoutExpired:
        logger.error(f"[execute_pipeline] Exceeded {timeout}s timeout, killing process group")
        try:
            os.killpg(pgid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        for p in procs:
            p.wait()
        for t in threads:
            t.join(timeout=5)
        return False
    except Exception:
        if pgid is not None:
            try:
                os.killpg(pgid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        raise

    for t in threads:
        t.join()

    codes = [p.returncode for p in procs]
    logger.debug(f"[execute_pipeline] Exit codes: {list(zip([c[0] for c in commands], codes))}")
    if any(c != 0 for c in codes):
        logger.error(f"[execute_pipeline] Pipeline failed, exit codes: {codes}")
        return False
    return True


def check_output(file_path: str, size_limit: int = 2048) -> bool:
    """
    Validate that an output file exists and meets minimum size requirements.
    """
    logger.debug(f"[check_output] Validating output file: {file_path}")
    logger.debug(f"[check_output] Size limit: {size_limit} bytes")

    try:
        if os.path.isfile(file_path):
            file_size = os.path.getsize(file_path)

            if file_size < size_limit:
                logger.error(f"[check_output] File is too small ({file_size} bytes) -> Command likely failed")
                return False
            else:
                logger.debug(f"[check_output] File check passed: {file_path} (Size: {file_size} bytes)")
                return True
        else:
            logger.error(f"[check_output] File not found: {file_path}")
            return False
    except PermissionError:
        logger.warning(f"[check_output] Permission denied: Unable to access {file_path}")
        return False
    except Exception as e:
        logger.error(f"[check_output] Unexpected error checking file {file_path}: {e}")
        return False


def temporal_crop(VPC: VideoProcessingConfig, NoFS_offset: int = 6) -> bool:
    """
    Perform temporal cropping (time-based cutting) of video files using FFmpeg.
    """
    logger.debug("[temporal_crop] Starting temporal crop operation")
    logger.debug(f"[temporal_crop] Source: {VPC.source_path} -> Target: {VPC.target_path}")
    logger.debug(f"[temporal_crop] Crop parameters - Start: {VPC.start}s, Duration: {VPC.duration}s")

    if VPC.profile["FS_enable"][1] and VPC.FS_support:
        command = [
            "ffmpeg",
            "-y",
            "-ss", str(VPC.start),
            "-i", VPC.source_path,
            "-t", str(VPC.duration),
        ]
    else:
        command = [
            "ffmpeg",
            "-y",
            "-fflags", "+genpts",
            "-copyts",
            "-avoid_negative_ts", "make_zero",
            "-i", VPC.source_path,
            "-ss", str(VPC.start),
            "-t", str(VPC.duration + NoFS_offset),
        ]

    command += [
        "-map", "0:V:0",
        "-c:v", "copy",
        "-an",
        "-sn",
        "-dn",
        VPC.target_path,
    ]

    logger.debug(f"[temporal_crop] FFmpeg command: {' '.join(command)}")

    if execute(command):
        if check_output(VPC.target_path):
            return True
        else:
            logger.error("[temporal_crop] Output file validation failed")
            if NoFS_offset >= 9:
                return False
            logger.debug("[temporal_crop] Attempting to create longer file")
            return temporal_crop(VPC, NoFS_offset + 1)
    else:
        logger.error("[temporal_crop] FFmpeg execution failed")
        return False


# =====================================================================
# Shared HDR Extraction & Injection Helpers
# =====================================================================

def _hevc_annexb_pipe_cmd(source_path: str, frame_limit=None) -> list:
    """Build FFmpeg command that demuxes the main HEVC track to Annex-B on stdout."""
    cmd = [
        "ffmpeg", "-v", "error",
        "-i", str(source_path),
        "-map", "0:V:0",
        "-c:v", "copy",
        "-bsf:v", "hevc_mp4toannexb",
        "-f", "hevc",
    ]
    if frame_limit is not None:
        cmd += ["-frames:v", str(frame_limit)]
    cmd.append("-")
    return cmd


def get_video_metadata_type(VPC: VideoProcessingConfig) -> bool:
    """
    Detect and cache the dynamic HDR metadata type present in a video file ("DoVi", "HDR10", or "None").
    """
    if VPC.HDR_type != "uninit":
        logger.debug(f"[get_video_metadata_type] Using cached metadata type: {VPC.HDR_type}")
        return True

    if not getattr(VPC, "is_H265", False):
        logger.debug("[get_video_metadata_type] Non-HEVC source; skipping dynamic HDR detection")
        VPC.HDR_type = "None"
        return True

    logger.debug(f"[get_video_metadata_type] Starting HDR metadata type detection for: {VPC.source_path}")
    frame_limit = (
        VPC.test_settings["HDR_test_frame_limit"]["frame_limit"]
        if VPC.test_settings["HDR_test_frame_limit"]["Enabled"]
        else None
    )

    ffmpeg_pipe = _hevc_annexb_pipe_cmd(VPC.source_path, frame_limit=frame_limit)

    # Try Dolby Vision first
    dovi = ["dovi_tool", "-m", "2", "extract-rpu", "-", "-o", str(VPC.dovi_metadata_file)]
    logger.debug(f"[get_video_metadata_type] DoVi extraction pipeline: {' '.join(ffmpeg_pipe)} | {' '.join(dovi)}")
    if not execute_pipeline([ffmpeg_pipe, dovi]):
        logger.warning("[get_video_metadata_type] DoVi tool execution failed")

    if check_output(VPC.dovi_metadata_file, size_limit=100):
        logger.debug("[get_video_metadata_type] DoVi metadata file is valid")
        VPC.HDR_type = "DoVi"
        return True

    # Try HDR10+ as fallback
    logger.debug("[get_video_metadata_type] Dolby Vision not detected, attempting HDR10+ metadata extraction")
    hdr10plus = ["hdr10plus_tool", "extract", "-o", str(VPC.HDR10_metadata_file), "-"]
    logger.debug(f"[get_video_metadata_type] HDR10+ extraction pipeline: {' '.join(ffmpeg_pipe)} | {' '.join(hdr10plus)}")
    if not execute_pipeline([ffmpeg_pipe, hdr10plus]):
        logger.warning("[get_video_metadata_type] HDR10+ tool execution failed")

    if check_output(VPC.HDR10_metadata_file):
        logger.debug("[get_video_metadata_type] HDR10+ metadata file is valid")
        VPC.HDR_type = "HDR10"
        return True

    logger.debug("[get_video_metadata_type] No dynamic HDR metadata detected")
    VPC.HDR_type = "None"
    return True


def crop_dovi_rpu(VPC: VideoProcessingConfig) -> bool:
    """
    Update DoVi RPU Level 5 active-area metadata to match applied crop and/or resolution scaling.
    """
    crop_top = (int(VPC.crop[0]) // 2) * 2
    crop_bottom = (int(VPC.crop[1]) // 2) * 2
    is_cropped = crop_top > 0 or crop_bottom > 0
    is_scaled = VPC.output_res != VPC.orig_h_res

    if not is_cropped and not is_scaled:
        return True

    l5_export_path = os.path.join(VPC.workspace, "dovi_l5_export.json")
    edit_config_path = os.path.join(VPC.workspace, "dovi_edit.json")
    tmp_rpu_file = str(VPC.dovi_metadata_file) + ".tmp"

    export_cmd = [
        "dovi_tool", "export",
        "-i", str(VPC.dovi_metadata_file),
        "-d", f"level5={l5_export_path}",
    ]

    edit_config = None
    if execute(export_cmd) and os.path.isfile(l5_export_path):
        try:
            with open(l5_export_path, "r", encoding="utf-8") as f:
                l5_data = json.load(f)

            # Support both dovi_tool <2.3 (top-level presets/edits) and >=2.3 (nested under active_area)
            active_area = l5_data.get("active_area", l5_data) if isinstance(l5_data, dict) else {}
            presets = active_area.get("presets", [])

            if presets:
                cropped_v = VPC.orig_v_res - crop_top - crop_bottom
                if cropped_v <= 0:
                    cropped_v = VPC.orig_v_res
                    crop_top = 0
                    crop_bottom = 0

                scale_x = VPC.output_res / VPC.orig_h_res if is_scaled else 1.0
                if is_scaled:
                    scaled_v = max(2, round(cropped_v * scale_x / 2) * 2)
                    scale_y = scaled_v / cropped_v
                else:
                    scale_y = 1.0

                for preset in presets:
                    preset["left"] = round(max(0, preset.get("left", 0)) * scale_x)
                    preset["right"] = round(max(0, preset.get("right", 0)) * scale_x)
                    preset["top"] = round(max(0, preset.get("top", 0) - crop_top) * scale_y)
                    preset["bottom"] = round(max(0, preset.get("bottom", 0) - crop_bottom) * scale_y)

                edit_config = {"active_area": active_area}
        except Exception as e:
            logger.warning(f"[crop_dovi_rpu] Failed to parse exported L5 metadata: {e}")

    if edit_config is None:
        if is_cropped:
            edit_config = {"active_area": {"crop": True}}
        else:
            logger.debug("[crop_dovi_rpu] No L5 active-area presets found to scale; skipping RPU edit")
            return True

    with open(edit_config_path, "w", encoding="utf-8") as f:
        json.dump(edit_config, f)

    command = [
        "dovi_tool", "editor",
        "-i", str(VPC.dovi_metadata_file),
        "-j", edit_config_path,
        "-o", tmp_rpu_file,
    ]
    logger.debug(f"[crop_dovi_rpu] Command: {' '.join(command)}")
    if not execute(command) or not check_output(tmp_rpu_file, size_limit=100):
        logger.error("[crop_dovi_rpu] DoVi RPU crop/scale edit failed")
        return False

    os.replace(tmp_rpu_file, VPC.dovi_metadata_file)
    return True


def video_HDR_extract(VPC: VideoProcessingConfig) -> bool:
    """
    Extract dynamic HDR metadata (DoVi RPU with -m 2 or HDR10+ JSON) from the source video.
    """
    logger.debug(f"[video_HDR_extract] Starting HDR metadata extraction for: {VPC.source_path}")
    logger.debug(f"[video_HDR_extract] Metadata type: {VPC.HDR_type}")

    if VPC.HDR_type == "uninit":
        if not get_video_metadata_type(VPC):
            logger.error("[video_HDR_extract] Unable to get video metadata type")
            return False

    if VPC.HDR_type == "DoVi":
        logger.debug("[video_HDR_extract] Extracting Dolby Vision RPU metadata (-m 2)")
        ffmpeg_pipe = _hevc_annexb_pipe_cmd(VPC.source_path)
        dovi = [
            "dovi_tool", "-m", "2", "extract-rpu",
            "-",
            "-o", str(VPC.dovi_metadata_file),
        ]
        logger.debug(f"[video_HDR_extract] DoVi extraction pipeline: {' '.join(ffmpeg_pipe)} | {' '.join(dovi)}")

        if not execute_pipeline([ffmpeg_pipe, dovi], timeout=3600 * 4):
            logger.error("[video_HDR_extract] DoVi extraction failed")
            return False
        if not check_output(VPC.dovi_metadata_file, size_limit=100):
            logger.error("[video_HDR_extract] DoVi metadata file validation failed")
            return False
        if not crop_dovi_rpu(VPC):
            logger.error("[video_HDR_extract] DoVi RPU crop/scale adjustment failed")
            return False
        return True

    elif VPC.HDR_type == "HDR10":
        logger.debug("[video_HDR_extract] Extracting HDR10+ dynamic metadata")
        ffmpeg_pipe = _hevc_annexb_pipe_cmd(VPC.source_path)
        hdr10plus = [
            "hdr10plus_tool", "extract",
            "-o", str(VPC.HDR10_metadata_file),
            "-",
        ]
        logger.debug(f"[video_HDR_extract] HDR10+ extraction pipeline: {' '.join(ffmpeg_pipe)} | {' '.join(hdr10plus)}")

        if not execute_pipeline([ffmpeg_pipe, hdr10plus], timeout=3600 * 4):
            logger.error("[video_HDR_extract] HDR10+ extraction failed")
            return False
        if not check_output(VPC.HDR10_metadata_file):
            logger.error("[video_HDR_extract] HDR10+ metadata file validation failed")
            return False
        return True

    elif VPC.HDR_type == "None":
        logger.debug("[video_HDR_extract] File doesn't contain dynamic DoVi/HDR10+ metadata")
        return True
    else:
        logger.error(f"[video_HDR_extract] Unsupported or uninitialized metadata type: {VPC.HDR_type}")
        return False


def video_HDR_inject(VPC: VideoProcessingConfig) -> bool:
    """
    Inject extracted dynamic HDR metadata (DoVi RPU or HDR10+ JSON) into an encoded HEVC stream.
    """
    logger.debug(f"[video_HDR_inject] Source: {VPC.source_path} -> Target: {VPC.target_path} (Type: {VPC.HDR_type})")

    if VPC.HDR_type == "HDR10":
        command = [
            "hdr10plus_tool", "inject",
            "-i", str(VPC.source_path),
            "-j", str(VPC.HDR10_metadata_file),
            "-o", str(VPC.target_path),
        ]
    elif VPC.HDR_type == "DoVi":
        command = [
            "dovi_tool", "inject-rpu",
            "-i", str(VPC.source_path),
            "--rpu-in", str(VPC.dovi_metadata_file),
            "-o", str(VPC.target_path),
        ]
    elif VPC.HDR_type == "None":
        logger.debug("[video_HDR_inject] File has no dynamic HDR, skipping injection")
        return True
    else:
        logger.error(f"[video_HDR_inject] Unsupported metadata format: {VPC.HDR_type}")
        return False

    logger.debug(f"[video_HDR_inject] Command: {' '.join(command)}")
    if not execute(command) or not check_output(VPC.target_path):
        logger.error("[video_HDR_inject] Metadata injection failed")
        return False
    return True


# =====================================================================
# Consolidated Color, Static HDR & MKV Container Finalization
# =====================================================================

MKV_PRIMARIES = {
    "bt709": 1, "bt470m": 4, "bt470bg": 5, "smpte170m": 6, "bt601": 6,
    "smpte240m": 7, "smpte240": 7, "film": 8, "bt2020": 9,
    "smpte428": 10, "xyz": 10, "smpte431": 11, "smpte432": 12,
    "jedec-p22": 22, "ebu3213": 22,
}
MKV_TRANSFER = {
    "bt709": 1, "gamma22": 4, "bt470m": 4, "gamma28": 5, "bt470bg": 5,
    "smpte170m": 6, "bt601": 6, "smpte240m": 7, "smpte240": 7, "linear": 8,
    "log": 9, "log100": 9, "log_sqrt": 10, "log100-sqrt10": 10,
    "iec61966-2-4": 11, "iec61966": 11, "bt1361e": 12, "bt1361": 12,
    "iec61966-2-1": 13, "srgb": 13, "bt2020-10": 14, "bt2020-12": 15,
    "smpte2084": 16, "pq": 16, "smpte428": 17, "arib-std-b67": 18, "hlg": 18,
}
MKV_MATRIX = {
    "gbr": 0, "rgb": 0, "identity": 0, "bt709": 1, "fcc": 4, "bt470bg": 5,
    "smpte170m": 6, "bt601": 6, "smpte240m": 7, "smpte240": 7, "ycgco": 8,
    "bt2020nc": 9, "bt2020-ncl": 9, "bt2020c": 10, "bt2020-cl": 10,
    "smpte2085": 11, "chroma-derived-nc": 12, "chroma-ncl": 12,
    "chroma-derived-c": 13, "chroma-cl": 13, "ictcp": 14,
}


def mkvmerge_colour_args(VPC: VideoProcessingConfig) -> list:
    """
    Build Matroska colour, range, and static HDR10 metadata arguments for mkvmerge (track 0).
    Used across all pipelines (both HDR and SDR, whether deband is enabled or not).
    """
    args = []
    for option, key, table in (
        ("--colour-primaries", "color_primaries", MKV_PRIMARIES),
        ("--colour-transfer-characteristics", "color_transfer", MKV_TRANSFER),
        ("--colour-matrix-coefficients", "color_space", MKV_MATRIX),
    ):
        number = table.get(str(VPC.VUI.get(key, "")).strip().lower())
        if number is not None:
            args += [option, f"0:{number}"]

    color_range = str(VPC.VUI.get("color_range", "")).strip().lower()
    if color_range in ("tv", "limited", "mpeg"):
        args += ["--colour-range", "0:1"]
    elif color_range in ("pc", "full", "jpeg"):
        args += ["--colour-range", "0:2"]

    side = VPC.SideDTA
    if side.get("Mastering_display_exists"):
        args += [
            "--chromaticity-coordinates",
            f"0:{side['red_x']:.5f},{side['red_y']:.5f},{side['green_x']:.5f},{side['green_y']:.5f},"
            f"{side['blue_x']:.5f},{side['blue_y']:.5f}",
            "--white-colour-coordinates", f"0:{side['white_point_x']:.5f},{side['white_point_y']:.5f}",
            "--max-luminance", f"0:{side['max_luminance']:.4f}",
            "--min-luminance", f"0:{side['min_luminance']:.6f}",
        ]
    if side.get("Cll_exists"):
        args += [
            "--max-content-light", f"0:{int(side['max_content'])}",
            "--max-frame-light", f"0:{int(side['max_average'])}",
        ]
    return args


def finalize_mkv(VPC: VideoProcessingConfig, is_elementary: bool) -> bool:
    """
    Unified MKV finalizer shared by both FFmpeg (H.265) and SVT-AV1 pipelines.
    Runs mkvmerge directly to write exact timing, seek cues, colour, and static HDR10 tags.
    """
    colour_args = mkvmerge_colour_args(VPC)
    timeout = 6 * 3600 if VPC.is_final_export else 3600

    raw_fps = getattr(VPC, "orig_framerate_fraction", None)
    fps_arg = f"0:{raw_fps}p" if raw_fps else f"0:{VPC.orig_framerate}fps"

    if is_elementary:
        logger.debug(f"[finalize_mkv] Muxing elementary stream with mkvmerge: {VPC.source_path} -> {VPC.target_path}")
        mkv_cmd = [
            "mkvmerge",
            "-o", str(VPC.target_path),
            "--default-duration", fps_arg,
            "--cues", "0:iframes",
            "--clusters-in-meta-seek",
        ]
        if str(VPC.source_path).lower().endswith((".hevc", ".h265", ".265")):
            mkv_cmd += ["--fix-bitstream-timing-information", "0:1"]
        mkv_cmd += [*colour_args, str(VPC.source_path)]

        if not execute(mkv_cmd, timeout=timeout) or not check_output(VPC.target_path):
            logger.error("[finalize_mkv] mkvmerge elementary mux failed")
            return False
        return True
    else:
        if not colour_args:
            return True
        tmp_mkv = str(VPC.target_path) + ".colour.mkv"
        mkv_cmd = ["mkvmerge", "-o", tmp_mkv, *colour_args, str(VPC.target_path)]
        if not execute(mkv_cmd, timeout=timeout) or not check_output(tmp_mkv):
            logger.error("[finalize_mkv] mkvmerge colour remux failed")
            return False
        os.replace(tmp_mkv, VPC.target_path)
        return True


# =====================================================================
# Shared Filters & Deband Helpers
# =====================================================================

def _validated_crop(VPC: VideoProcessingConfig) -> tuple[int, int, int]:
    """Return validated even (crop_top, crop_bottom, target_v_res)."""
    crop_top = (int(VPC.crop[0]) // 2) * 2
    crop_bottom = (int(VPC.crop[1]) // 2) * 2
    target_v_res = VPC.orig_v_res - crop_top - crop_bottom

    if target_v_res <= 0:
        logger.error(
            f"[_validated_crop] Invalid crop: orig_v_res={VPC.orig_v_res}, "
            f"crop={VPC.crop} produces non-positive height ({target_v_res})"
        )
        VPC.crop = [0, 0]
        logger.warning("[_validated_crop] Falling back to uncropped resolution")
        return 0, 0, VPC.orig_v_res

    return crop_top, crop_bottom, target_v_res


def vfCropComandGenerator(VPC: VideoProcessingConfig) -> str:
    """
    Generate FFmpeg crop and Lanczos scale filter string with even-pixel alignment
    and +full_chroma_int for clean 10-bit 4:2:0 scaling.
    NOTE / TODO: Assumes square pixels (SAR 1:1); anamorphic sources are not handled.
    """
    crop_top, _, target_v_res = _validated_crop(VPC)

    command = (
        f"crop={VPC.orig_h_res}:{target_v_res}:0:{crop_top},"
        f"scale={VPC.output_res}:-2:flags=lanczos+accurate_rnd+full_chroma_int"
    )
    logger.debug(f"[vfCropComandGenerator] Generated filter: {command}")
    return command


def y4m_range_filter(VPC: VideoProcessingConfig) -> str:
    """Restore source color range metadata on frames arriving from a Y4M pipe."""
    color_range = str(VPC.VUI.get("color_range", "")).strip().lower()
    if color_range in ("pc", "full", "jpeg"):
        return "setparams=range=full"
    if color_range in ("tv", "limited", "mpeg"):
        return "setparams=range=limited"
    return ""


def deband_enabled(VPC: VideoProcessingConfig) -> bool:
    """Optional deband stage, switched on by the profile section 'Deband_enable'."""
    return bool(VPC.profile.get("Deband_enable", [None, False])[1])


def deband_source_stage(VPC: VideoProcessingConfig) -> tuple:
    """
    Returns (leading_commands, ffmpeg_input_args).
    When deband is enabled, crop and scale run in VapourSynth before debanding.
    """
    if not deband_enabled(VPC):
        return [], ["-i", str(VPC.source_path)]

    section = VPC.profile["Deband"]
    options = {}
    for key, value in zip(section[0::2], section[1::2]):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            pass
        options[str(key).lstrip("-")] = value

    script = str(options.pop("script", "deband.vpy"))
    if not os.path.isabs(script):
        script = os.path.join(os.path.dirname(os.path.abspath(__file__)), script)
    cache = os.path.join(VPC.workspace, os.path.basename(str(VPC.source_path)) + ".lwi")
    crop_top, crop_bottom, _ = _validated_crop(VPC)

    vspipe_cmd = [
        "vspipe", "-c", "y4m",
        "-a", f"source={VPC.source_path}",
        "-a", f"cache={cache}",
        "-a", f"options={json.dumps(options)}",
        "-a", f"crop_top={crop_top}",
        "-a", f"crop_bottom={crop_bottom}",
        "-a", f"target_w={VPC.output_res}",
        script, "-",
    ]
    logger.debug(f"[deband_source_stage] Deband enabled, options: {options}")
    return [vspipe_cmd], ["-f", "yuv4mpegpipe", "-i", "-"]


def ffmpeg_colour_args(VPC: VideoProcessingConfig) -> list:
    """FFmpeg colour & range tags taken from the original file."""
    args = []
    for option, key in (
        ("-color_primaries", "color_primaries"),
        ("-color_trc", "color_transfer"),
        ("-colorspace", "color_space"),
        ("-color_range", "color_range"),
        ("-chroma_sample_location", "chroma_location"),
    ):
        value = VPC.VUI.get(key)
        if value and value != "unknown":
            args += [option, value]
    return args


# =====================================================================
# Encoding Pipelines (FFmpeg H.265 & SVT-AV1)
# =====================================================================

def video_encode_ffmpeg(VPC: VideoProcessingConfig) -> bool:
    """
    Encode video files using FFmpeg (H.265) with cropping, scaling, 10-bit preservation, and CQ control.
    """
    logger.debug("[video_encode_ffmpeg] Starting FFmpeg video encoding")
    logger.debug(f"[video_encode_ffmpeg] Source: {VPC.source_path} -> Target: {VPC.target_path}")

    use_deband = deband_enabled(VPC)
    lead_commands, input_args = deband_source_stage(VPC)

    command = [
        "ffmpeg",
        *input_args,
        "-map", "0:V:0",
        "-an",
        "-sn",
        "-dn",
        "-pix_fmt", "yuv420p10le",
    ]

    vf_filter = y4m_range_filter(VPC) if use_deband else vfCropComandGenerator(VPC)
    video_profile_modified = VPC.profile["video"].copy()

    if vf_filter:
        try:
            index = video_profile_modified.index("-vf")
            if use_deband:
                video_profile_modified[index + 1] = vf_filter + "," + video_profile_modified[index + 1]
            else:
                video_profile_modified[index + 1] = video_profile_modified[index + 1] + "," + vf_filter
        except ValueError:
            video_profile_modified.append("-vf")
            video_profile_modified.append(vf_filter)

    cq_flag = VPC.profile_settings.get("cq_flag") or VPC.profile.get("cq_flag", [None, "-cq"])[1]

    command += video_profile_modified
    command += [
        *ffmpeg_colour_args(VPC),
        "-map_metadata", "0",
        str(cq_flag), str(VPC.output_cq),
        "-y",
        VPC.target_path,
    ]

    logger.debug(f"[video_encode_ffmpeg] Complete FFmpeg command: {' '.join(str(c) for c in command)}")
    timeout = max_timeout if VPC.is_final_export else 3600

    ok = (
        execute_pipeline(lead_commands + [command], timeout=timeout)
        if lead_commands
        else execute(command, timeout=timeout)
    )
    if not ok or not check_output(VPC.target_path):
        logger.error("[video_encode_ffmpeg] FFmpeg encoding or output validation failed")
        return False

    return True


def video_ffmpeg_h265(VPC: VideoProcessingConfig) -> bool:
    """
    Main FFmpeg-based H.265 encoding workflow.
    Uses dovi_tool/hdr10plus_tool when dynamic HDR is present, and always finalizes
    the output MKV with complete colour and static HDR metadata via finalize_mkv().
    """
    logger.debug("[video_ffmpeg_h265] Starting FFmpeg H.265 encoding workflow")
    use_dynamic_hdr = False

    if VPC.profile["HDR_enable"][1]:
        if video_HDR_extract(VPC) and VPC.HDR_type in ("DoVi", "HDR10"):
            use_dynamic_hdr = True
        else:
            logger.debug("[video_ffmpeg_h265] No dynamic DoVi/HDR10+ metadata; using direct MKV encode")
            VPC.DisableParentHDR()

    if use_dynamic_hdr:
        # Step 1: Encode to raw .hevc elementary stream
        VPC.setTargetPath(os.path.join(VPC.workspace, VPC.output_file_name + "_reencode.hevc"))
        if not video_encode_ffmpeg(VPC):
            return False
        delete_file(VPC, VPC.source_path)

        # Step 2: Inject DoVi RPU or HDR10+ JSON into .hevc stream
        VPC.setSourcePath(VPC.target_path)
        VPC.setTargetPath(os.path.join(VPC.workspace, VPC.output_file_name + "_HDR_inject.hevc"))
        if not video_HDR_inject(VPC):
            return False
        delete_file(VPC, VPC.source_path)

        # Step 3: Mux elementary .hevc into final .mkv with colour & static HDR tags
        VPC.setSourcePath(VPC.target_path)
        VPC.setTargetPath(VPC.output_file_path)
        if not finalize_mkv(VPC, is_elementary=True):
            return False
        delete_file(VPC, VPC.source_path)
    else:
        # Direct encode to .mkv (Static HDR10 or SDR), then ensure MKV colour/HDR tags are written
        VPC.setTargetPath(VPC.output_file_path)
        if not video_encode_ffmpeg(VPC):
            return False
        delete_file(VPC, VPC.source_path)

        if not finalize_mkv(VPC, is_elementary=False):
            return False

    logger.debug("[video_ffmpeg_h265] FFmpeg encoding workflow completed successfully")
    return True


def SvtAv1EncApp_encode(VPC: VideoProcessingConfig) -> bool:
    """
    Encode video files using SVT-AV1 encoder with cropping, scaling, and HDR metadata signaling.
    NOTE / TODO: Assumes square pixels (SAR 1:1); anamorphic sources (e.g. DVDs) are not handled.
    """
    def cicp_lookup(name: str, table: dict, field_label: str) -> int:
        if not name:
            return 2
        cleaned = str(name).strip().lower()
        if cleaned in ("unknown", "unspecified"):
            return 2
        result = table.get(cleaned)
        if result is None:
            logger.warning(f"[SvtAv1EncApp_encode] Unrecognized {field_label} '{name}', defaulting to 2")
            return 2
        return result

    def chroma_sample_position_name_to_num(name: str) -> int:
        if name is None:
            return 0
        mapping = {
            "unspecified": 0, "unknown": 0,
            "left": 1,
            "topleft": 2,
            "center": 0, "top": 0, "bottom": 0, "bottomleft": 0,
        }
        return mapping.get(name.strip().lower(), 0)

    def color_range_name_to_num(name: str) -> int:
        if name is None:
            return 0
        return 1 if name.strip().lower() in ("pc", "full", "jpeg") else 0

    logger.debug("[SvtAv1EncApp_encode] Starting SVT-AV1 video encoding")
    logger.debug(f"[SvtAv1EncApp_encode] Source: {VPC.source_path} -> Target: {VPC.target_path}")

    use_deband = deband_enabled(VPC)
    vf_filter = y4m_range_filter(VPC) if use_deband else vfCropComandGenerator(VPC)
    lead_commands, input_args = deband_source_stage(VPC)

    ffmpeg_cmd = [
        "ffmpeg", "-nostdin",
        *input_args,
        "-map", "0:V:0",
        "-pix_fmt", "yuv420p10le",
        "-f", "yuv4mpegpipe", "-strict", "-1",
        "-an", "-sn", "-dn",
    ]
    if vf_filter:
        ffmpeg_cmd += ["-vf", vf_filter]
    ffmpeg_cmd.append("-")

    svt_cmd = [
        "SvtAv1EncApp", "-i", "stdin",
        "--input-depth", "10",
        "--crf", str(VPC.output_cq),
        "--color-primaries", str(cicp_lookup(VPC.VUI.get("color_primaries"), MKV_PRIMARIES, "color_primaries")),
        "--transfer-characteristics", str(cicp_lookup(VPC.VUI.get("color_transfer"), MKV_TRANSFER, "color_transfer")),
        "--matrix-coefficients", str(cicp_lookup(VPC.VUI.get("color_space"), MKV_MATRIX, "color_space")),
        "--color-range", str(color_range_name_to_num(VPC.VUI.get("color_range"))),
        "--chroma-sample-position", str(chroma_sample_position_name_to_num(VPC.VUI.get("chroma_location"))),
        "-b", str(VPC.target_path),
    ]

    for item in VPC.profile["video"]:
        svt_cmd += str(item).split()

    if VPC.profile["HDR_enable"][1]:
        if VPC.HDR_type == "HDR10":
            svt_cmd += ["--hdr10plus-json", str(VPC.HDR10_metadata_file)]
        elif VPC.HDR_type == "DoVi":
            svt_cmd += ["--dolby-vision-rpu", str(VPC.dovi_metadata_file)]

    if VPC.SideDTA.get("Cll_exists"):
        svt_cmd += [
            "--content-light",
            f"{int(VPC.SideDTA['max_content'])},{int(VPC.SideDTA['max_average'])}",
        ]

    if VPC.SideDTA.get("Mastering_display_exists"):
        svt_cmd += [
            "--mastering-display",
            (
                f"G({VPC.SideDTA['green_x']:.5f},{VPC.SideDTA['green_y']:.5f})"
                f"B({VPC.SideDTA['blue_x']:.5f},{VPC.SideDTA['blue_y']:.5f})"
                f"R({VPC.SideDTA['red_x']:.5f},{VPC.SideDTA['red_y']:.5f})"
                f"WP({VPC.SideDTA['white_point_x']:.5f},{VPC.SideDTA['white_point_y']:.5f})"
                f"L({VPC.SideDTA['max_luminance']:.4f},{VPC.SideDTA['min_luminance']:.6f})"
            ),
        ]

    timeout = max_timeout if VPC.is_final_export else 3600
    if execute_pipeline(lead_commands + [ffmpeg_cmd, svt_cmd], timeout=timeout):
        if check_output(VPC.target_path):
            logger.debug("[SvtAv1EncApp_encode] SVT-AV1 encoding completed successfully")
            return True
        else:
            logger.error("[SvtAv1EncApp_encode] Output file validation failed")
            return False
    return False


def video_ffmpeg_AV1(VPC: VideoProcessingConfig) -> bool:
    """
    Main SVT-AV1 encoding workflow.
    Extracts dynamic HDR if enabled, encodes to .ivf, and finalizes to .mkv via finalize_mkv().
    """
    logger.debug("[video_ffmpeg_AV1] Starting SVT-AV1 encoding workflow")

    if VPC.profile["HDR_enable"][1]:
        if not video_HDR_extract(VPC):
            logger.error("[video_ffmpeg_AV1] HDR metadata extraction failed")
            return False

    # Step 1: Encode video to IVF elementary stream
    VPC.setTargetPath(os.path.join(VPC.workspace, VPC.output_file_name + "_reencode.ivf"))
    if not SvtAv1EncApp_encode(VPC):
        logger.error("[video_ffmpeg_AV1] SVT-AV1 encoding failed")
        return False
    delete_file(VPC, VPC.source_path)

    # Step 2: Mux IVF to final MKV container with complete colour & static HDR metadata
    VPC.setSourcePath(VPC.target_path)
    VPC.setTargetPath(VPC.output_file_path)
    if not finalize_mkv(VPC, is_elementary=True):
        logger.error("[video_ffmpeg_AV1] IVF to MKV conversion failed")
        return False
    delete_file(VPC, VPC.source_path)

    logger.debug("[video_ffmpeg_AV1] SVT-AV1 encoding workflow completed successfully")
    return True


def delete_file(VPC: VideoProcessingConfig, file: str) -> None:
    """
    Delete temporary files/directories when Enable_delete is enabled.
    Never deletes the original input video (VPC.orig_file_path).
    """
    # TODO: Also delete leftover VapourSynth index files: str(file) + ".lwi"
    if VPC.test_settings["Enable_delete"]["Enabled"]:
        if os.path.abspath(str(file)) == os.path.abspath(str(VPC.orig_file_path)):
            logger.debug(f"[delete_file] Protecting original source file from deletion: {file}")
            return

        logger.debug(f"[delete_file] Deleting: {file}")

        if os.path.isfile(file):
            os.remove(file)
            logger.debug(f"[delete_file] Deleted file: {file}")
        elif os.path.isdir(file):
            shutil.rmtree(file)
            logger.debug(f"[delete_file] Deleted directory: {file}")
        else:
            logger.warning(f"[delete_file] Path does not exist: {file}")


if __name__ == "__main__":
    None