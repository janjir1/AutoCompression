from typing import List, Union
import os
import yaml
import subprocess
import json
import copy
import logging
from fractions import Fraction

logger = logging.getLogger("AppLogger")

DEFAULT_VUI = {
    "color_primaries": "unknown",
    "color_space": "unknown",
    "color_transfer": "unknown",
    "chroma_location": "unknown",
    "color_range": "tv",
}

DEFAULT_SIDEDTA = {
    "Cll_exists": False,
    "Mastering_display_exists": False,
    "dv_profile": None,
}


class VideoProcessingConfig:
    """
    Configuration class for video processing operations.

    Manages video processing parameters including input/output paths, encoding settings,
    HDR metadata handling, and temporal/spatial cropping configurations.
    """

    def __init__(self, input_file_path: str, output_file_name: str, workspace: str):
        """
        Initialize video processing configuration.
        Args:
            input_file_path (str): Path to the input video file
            output_file_name (str): Name for the output file (without extension)
            workspace (str): Working directory for temporary and output files
        """
        logger.info("[VideoProcessingConfig.__init__] Initializing video processing config")
        logger.debug(f"[VideoProcessingConfig.__init__] Input file: {input_file_path}")
        logger.debug(f"[VideoProcessingConfig.__init__] Output name: {output_file_name}")
        logger.debug(f"[VideoProcessingConfig.__init__] Workspace: {workspace}")

        self.orig_file_path = input_file_path
        self.output_file_name = output_file_name
        self.workspace = workspace
        self.output_file_path = os.path.join(self.workspace, self.output_file_name) + ".mkv"
        self.parent = None
        self.is_final_export = False

        self.crop: List[int] = [0, 0]
        self.channels: Union[int, bool] = False
        self.start: Union[int, bool] = False
        self.duration: Union[int, bool] = False
        self.subtitles: bool = False
        self.HDR_type: str = "uninit"
        self.dv_profile: Union[int, None] = None

        # Initialize VUI and SideDTA with safe defaults before analysis runs
        self.VUI = DEFAULT_VUI.copy()
        self.SideDTA = DEFAULT_SIDEDTA.copy()
        self.orig_framerate = False
        self.orig_framerate_fraction = None

        if not os.path.exists(workspace):
            os.makedirs(workspace)

        self.dovi_metadata_file = os.path.join(workspace, "dovi_metadata_test.bin")
        self.HDR10_metadata_file = os.path.join(workspace, "HDR10_metadata_test.json")

        logger.debug(f"[VideoProcessingConfig.__init__] DoVi metadata file: {self.dovi_metadata_file}")
        logger.debug(f"[VideoProcessingConfig.__init__] HDR10 metadata file: {self.HDR10_metadata_file}")

    def readProfiles(self, profile_path: str, test_settings_path: str):
        """
        Load encoding profiles and test settings from YAML files.
        Args:
            profile_path (str): Path to the encoding profile YAML file
            test_settings_path (str): Path to the test settings YAML file
        """
        logger.info("[VideoProcessingConfig.readProfiles] Loading profiles and settings")
        logger.debug(f"[VideoProcessingConfig.readProfiles] Profile path: {profile_path}")
        logger.debug(f"[VideoProcessingConfig.readProfiles] Test settings path: {test_settings_path}")

        self.profile, self.profile_settings = readProfile(profile_path)
        self.test_settings = readSettings(test_settings_path)
        self.target_cq = self.getProfileValue(self.profile["test_settings"], "defalut_cq")
        self.output_cq = self.getProfileValue(self.profile["test_settings"], "defalut_cq")

    def analyzeOriginal(self) -> bool:
        """
        Analyze the original video file to extract metadata such as resolution, framerate, and duration.
        Returns True if required stream metadata was extracted, False otherwise.
        """
        logger.info(f"[VideoProcessingConfig.analyzeOriginal] Analyzing original video file: {self.orig_file_path}")
        self.orig_h_res = getH_res(self.orig_file_path)
        self.orig_v_res = getV_res(self.orig_file_path)
        self.orig_framerate, self.orig_framerate_fraction = get_framerate(self.orig_file_path)
        self.orig_duration = getDuration(self.orig_file_path)
        self.FS_support = get_fast_seek_support(self.orig_file_path)
        self.is_H265 = is_h265(self.orig_file_path)
        if not self.is_H265:
            self.profile["HDR_enable"][1] = False
            logger.info("[VideoProcessingConfig.analyzeOriginal] File is not h265 disabling HDR")

        self.target_res = self.orig_h_res
        self.output_res = self.orig_h_res

        metadata = get_static_metadata(self.orig_file_path)
        if metadata is None:
            logger.warning(f"[analyzeOriginal] Failed to extract static metadata for {self.orig_file_path}; using defaults")
            self.VUI = DEFAULT_VUI.copy()
            self.SideDTA = DEFAULT_SIDEDTA.copy()
        else:
            vui_data, side_data = metadata
            self.VUI = {**DEFAULT_VUI, **(vui_data or {})}
            self.SideDTA = {**DEFAULT_SIDEDTA, **(side_data or {})}

        self.dv_profile = self.SideDTA.get("dv_profile")
        if self.dv_profile == 5:
            # TODO: Implement Dolby Vision Profile 5 conversion/reshaping
            logger.error(
                "[VideoProcessingConfig.analyzeOriginal] Dolby Vision Profile 5 detected "
                "(IPTPQc2 colorspace). Conversion is not implemented yet."
            )
            return False

        if self.orig_h_res <= 0 or self.orig_v_res <= 0 or self.orig_duration <= 0 or self.orig_framerate is False:
            logger.error(
                f"[VideoProcessingConfig.analyzeOriginal] Failed to probe required metadata: "
                f"res={self.orig_h_res}x{self.orig_v_res}, duration={self.orig_duration}, fps={self.orig_framerate}"
            )
            return False

        return True

    def create_copy(self):
        """Create a deepcopy that remembers its parent."""
        new_copy = copy.deepcopy(self)
        new_copy.parent = self  # Child remembers parent
        return new_copy

    def DisableParentHDR(self):
        parent = self.parent
        while True:
            if parent is None:
                logger.debug("Original parent")
                break
            parent.profile["HDR_enable"][1] = False
            parent = parent.parent

    def setTargetPath(self, name: str):
        self.target_path = name

    def setSourcePath(self, name: str):
        self.source_path = name

    def setOutputCQ(self, CQ: float):
        self.output_cq = CQ

    def setOutputRes(self, res: int):
        self.output_res = res

    def setCrop(self, crop: list):
        self.crop = crop
        self.target_crop = crop

    def setStart(self, start: int):
        self.start = start

    def setDuration(self, duration: int):
        self.duration = duration

    def setWorkspace(self, workspace: str):
        if not os.path.exists(workspace):
            os.makedirs(workspace)
        self.workspace = workspace
        self.output_file_path = os.path.join(self.workspace, self.output_file_name + ".mkv")
        self.dovi_metadata_file = os.path.join(self.workspace, "dovi_metadata_test.bin")
        self.HDR10_metadata_file = os.path.join(self.workspace, "HDR10_metadata_test.json")

    def setOutputFileName(self, name: str):
        self.output_file_name = name
        self.output_file_path = os.path.join(self.workspace, name + ".mkv")

    def setHDR_Type(self, hdr_type: str):
        if hdr_type in ("DoVi", "HDR10", "None"):
            self.HDR_type = hdr_type
        else:
            logger.error(f"[VideoProcessingConfig.setHDR_Type] Unknown HDR type: {hdr_type}")

    def getProfileValue(self, lst: list, word: str):
        """
        Get a value from a profile list based on a key word.
        Args:
            lst (list): Profile list containing key-value pairs
            word (str): Key to search for
        Returns:
            The value following the specified key
        """
        return lst[lst.index(word) + 1]

    def export_to_txt(self):
        """
        Export all attributes of this VideoProcessingConfig instance to a text file.

        Each line is either “attribute: value” for simple attrs, or
        dict entries for profile and settings if present.
        """
        lines = []
        # Dump all simple attributes
        for attr, val in vars(self).items():
            lines.append(f"{attr}: {val}")

        # Dump profile dict if exists
        if hasattr(self, "profile") and isinstance(self.profile, dict):
            lines.append("\n# profile settings")
            for k, v in self.profile.items():
                lines.append(f"profile[{k}]: {v}")

        # Dump settings dict if exists
        if hasattr(self, "test_settings") and isinstance(self.test_settings, dict):
            lines.append("\n# test_settings")
            for k, v in self.test_settings.items():
                lines.append(f"settings[{k}]: {v}")

        # Write out
        text_output_path = os.path.join(self.workspace, "VPC.txt")
        with open(text_output_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))


def readProfile(yaml_profile):
    """
    Read and parse a YAML profile file for video encoding settings.
    Args:
        yaml_profile (str): Path to the YAML profile file
    Returns:
        tuple: (profile dictionary, profile_settings dictionary)
    """
    with open(yaml_profile, "r", encoding="utf-8") as file:
        loaded_data = yaml.safe_load(file)

    profile = dict()
    for key, value in loaded_data.items():
        profile[key] = list()
        for subvalue in value.items():
            profile[key].append(str(subvalue[0]))

            if isinstance(subvalue[1], bool):
                profile[key].append(subvalue[1])
            else:
                profile[key].append(str(subvalue[1]))

    profile_settings = loaded_data["test_settings"]

    logger.debug(f"[readProfile] Successfully loaded profile with {len(profile)} sections")
    return profile, profile_settings


def readSettings(yaml_settings):
    """
    Read and parse a YAML settings file for test configurations.
    Args:
        yaml_settings (str): Path to the YAML settings file
    Returns:
        dict: Parsed settings dictionary with enable flags and parameters
    """
    with open(yaml_settings, "r", encoding="utf-8") as file:
        data = yaml.safe_load(file)
    return data


def getDuration(input_path: str) -> float:
    """
    Retrieve the duration of a video file using FFprobe.
    Args:
        input_path (str): Path to the video file
    Returns:
        float: Duration of the video in seconds, or 0 if an error occurs
    """
    logger.debug(f"[getDuration] Getting duration for: {input_path}")

    command = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "json",
        input_path,
    ]

    logger.debug(f"[getDuration] FFprobe command: {' '.join(command)}")

    try:
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, shell=False)

        if result.returncode != 0:
            logger.error(f"FFprobe error for {input_path}: {result.stderr.strip()}")
            return 0

        data = json.loads(result.stdout)
        duration = float(data.get("format", {}).get("duration", 0))
        if duration > 0:
            return duration
        else:
            logger.error(f"[getDuration] Invalid duration value received from FFprobe for {input_path}")
            return 0

    except json.JSONDecodeError:
        logger.error(f"[getDuration] Failed to parse JSON output from FFprobe for {input_path}")
    except Exception as e:
        logger.error(f"[getDuration] Unexpected error while retrieving duration for {input_path}: {e}")

    return 0


def getH_res(video_path: str) -> int:
    """
    Retrieves the horizontal resolution (width) of a video file using FFprobe.

    Parameters:
    - video_path (str): Path to the video file.

    Returns:
    - int: Width of the video in pixels, or 0 if an error occurs.
    """
    logger.debug(f"[getH_res] Getting horizontal resolution for: {video_path}")
    command = [
        "ffprobe", "-v", "error", "-select_streams", "V:0", "-show_entries",
        "stream=width", "-of", "json", video_path,
    ]
    logger.debug(f"[getH_res] FFprobe command: {' '.join(command)}")

    try:
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, shell=False)

        if result.returncode != 0:
            logger.error(f"[getH_res] FFprobe error for {video_path}: {result.stderr.strip()}")
            return 0

        ffprobe_output = json.loads(result.stdout)
        width = int(ffprobe_output["streams"][0]["width"])
        if width is not None:
            return width
        else:
            logger.error(f"[getH_res] Failed to retrieve width from FFprobe output for {video_path}.")
            return 0

    except json.JSONDecodeError:
        logger.error(f"[getH_res] Failed to parse JSON output from FFprobe for {video_path}.")
    except Exception as e:
        logger.error(f"[getH_res] Unexpected error while retrieving resolution for {video_path}: {e}")

    return 0


def getV_res(video_path: str) -> int:
    """
    Retrieves the vertical resolution (height) of a video file using FFprobe.

    Parameters:
    - video_path (str): Path to the video file.

    Returns:
    - int: Height of the video in pixels, or 0 if an error occurs.
    """
    logger.debug(f"[getV_res] Getting vertical resolution for: {video_path}")

    command = [
        "ffprobe", "-v", "error", "-select_streams", "V:0", "-show_entries",
        "stream=height", "-of", "json", video_path,
    ]

    try:
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, shell=False)

        if result.returncode != 0:
            logger.error(f"FFprobe error for {video_path}: {result.stderr.strip()}")
            return 0

        ffprobe_output = json.loads(result.stdout)
        height = int(ffprobe_output["streams"][0]["height"])

        if height is not None:
            return height
        else:
            logger.error(f"[getV_res] Failed to retrieve height from FFprobe output for {video_path}.")
            return 0

    except json.JSONDecodeError:
        logger.error(f"[getV_res] Failed to parse JSON output from FFprobe for {video_path}.")
    except Exception as e:
        logger.error(f"[getV_res] Unexpected error while retrieving resolution for {video_path}: {e}")
    return 0


def get_framerate(input_file):
    """
    Retrieve the video framerate using ffprobe, supporting both CFR and VFR.
    Args:
        input_file (str): Path to the input video file
    Returns:
        tuple: (float framerate in fps or False, exact fraction string e.g. '24000/1001' or None)
    """
    logger.debug(f"[get_framerate] Getting framerate for: {input_file}")

    def probe(entry: str) -> str:
        cmd = [
            "ffprobe", "-v", "error",
            "-select_streams", "V:0",
            "-show_entries", f"stream={entry}",
            "-of", "default=noprint_wrappers=1:nokey=1",
            input_file,
        ]
        logger.debug(f"[get_framerate] FFprobe command: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return result.stdout.strip()

    def parse_framerate(framerate_string: str):
        framerate_string = framerate_string.strip()
        if not framerate_string or framerate_string == "0/0":
            return None, None
        fraction = Fraction(framerate_string)
        fps_float = round(float(fraction), 3)
        exact_str = (
            f"{fraction.numerator}/{fraction.denominator}"
            if fraction.denominator != 1
            else str(fraction.numerator)
        )
        return fps_float, exact_str

    try:
        # Try constant-frame-rate first, then fallback to average-frame-rate
        # Upper limit 250 avoids Matroska's bogus 1000/1 timebase reporting as fps
        for entry in ("r_frame_rate", "avg_frame_rate"):
            raw = probe(entry)
            logger.debug(f"[get_framerate] Probe {entry}: {raw}")
            fps_float, exact_str = parse_framerate(raw)
            if fps_float is not None and 10 <= fps_float <= 250:
                logger.debug(f"[get_framerate] Parsed {entry}: {fps_float} ({exact_str})")
                return fps_float, exact_str
    except Exception as e:
        logger.error(f"[get_framerate] Error probing framerate for {input_file}: {e}")

    logger.error("[get_framerate] Framerate detection failed")
    return False, None


def get_fast_seek_support(file_path: str, scan_bytes: int = 1_048_576) -> bool:
    """
    Determine whether a media file supports fast seek.

    For MP4-family files, “moov” atom must precede “mdat” atom.
    For Matroska (MKV), either the EBML “Cues” element (0x1C53BB6B) precedes the first
    “Cluster” element (0x1F43B675), OR a “SeekHead” element (0x114D9B74) before the first
    Cluster indexes the Cues element.
    """
    ext = os.path.splitext(file_path)[1].lower()
    try:
        with open(file_path, "rb") as f:
            data = f.read(scan_bytes)
    except (OSError, IOError):
        return False

    if ext in (".mp4", ".m4v", ".mov", ".mp4v", ".ismv"):
        idx_index = data.find(b"moov")
        idx_data = data.find(b"mdat")
        if idx_index == -1 or idx_data == -1:
            return False
        return idx_index < idx_data

    elif ext == ".mkv":
        # EBML IDs for Matroska:
        #   SeekHead -> 0x114D9B74
        #   Cues     -> 0x1C53BB6B
        #   Cluster  -> 0x1F43B675
        seekhead_id = b"\x11\x4D\x9B\x74"
        cues_id = b"\x1C\x53\xBB\x6B"
        cluster_id = b"\x1F\x43\xB6\x75"

        idx_cluster = data.find(cluster_id)
        if idx_cluster == -1:
            return False

        # Direct Cues before first Cluster
        idx_cues = data.find(cues_id)
        if 0 <= idx_cues < idx_cluster:
            return True

        # Or SeekHead before first Cluster referencing the Cues EBML ID
        idx_seekhead = data.find(seekhead_id)
        if 0 <= idx_seekhead < idx_cluster and (cues_id in data[idx_seekhead:idx_cluster]):
            return True

        return False

    return False


def is_h265(file_path: str, ffprobe_path: str = "ffprobe") -> bool:
    """
    Check whether the given video file's primary video stream uses H.265/HEVC.
    """
    cmd = [
        ffprobe_path,
        "-v", "error",
        "-select_streams", "V:0",
        "-show_entries", "stream=codec_name",
        "-of", "json",
        file_path,
    ]

    try:
        proc = subprocess.run(cmd, check=True, capture_output=True, text=True)
        info = json.loads(proc.stdout)
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        return False

    streams = info.get("streams", [])
    if not streams:
        return False

    codec = streams[0].get("codec_name", "").lower()
    return codec == "hevc"


def get_static_metadata(input_file: str):
    """
    Extract static VUI and HDR10 side data metadata from both stream and first frame using FFprobe.
    Gracefully falls back to DEFAULT_VUI and DEFAULT_SIDEDTA on any missing or malformed fields.
    """
    def parse_val(val):
        if isinstance(val, str) and "/" in val:
            n, d = map(int, val.split("/"))
            return n / d if d != 0 else 0.0
        return float(val)

    def clean_vui_str(val, default="unknown") -> str:
        if val is None:
            return default
        s = str(val).strip()
        if not s or s.lower() in ("unknown", "unspecified", "none", "n/a"):
            return default
        return s

    cmd = [
        "ffprobe",
        "-v", "quiet",
        "-select_streams", "V:0",
        "-read_intervals", "%+#1",
        "-show_streams",
        "-show_frames",
        "-print_format", "json",
        input_file,
    ]

    VUI = DEFAULT_VUI.copy()
    SideDTA = DEFAULT_SIDEDTA.copy()

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        data = json.loads(result.stdout)

        streams = data.get("streams", [])
        if not streams:
            logger.warning(f"[get_static_metadata] No video stream found in {input_file}; using VUI defaults")
            return VUI, SideDTA

        json_data = streams[0]
        frames = data.get("frames", [])
        first_frame = frames[0] if frames else {}

        # Prefer stream VUI tags, falling back to first-frame tags if stream tags are missing/unknown
        for key, default in (
            ("color_primaries", "unknown"),
            ("color_space", "unknown"),
            ("color_transfer", "unknown"),
            ("chroma_location", "unknown"),
            ("color_range", "tv"),
        ):
            val = clean_vui_str(json_data.get(key), "unknown")
            if val == "unknown":
                val = clean_vui_str(first_frame.get(key), default)
            VUI[key] = val

        # Combine side_data_list from both stream container and first decoded frame
        side_data_list = list(json_data.get("side_data_list", [])) + list(first_frame.get("side_data_list", []))

        for side_data in side_data_list:
            if not isinstance(side_data, dict):
                continue

            sd_type = side_data.get("side_data_type", "")

            if "dv_profile" in side_data and SideDTA["dv_profile"] is None:
                try:
                    SideDTA["dv_profile"] = int(side_data["dv_profile"])
                except (ValueError, TypeError):
                    pass

            if sd_type == "Content light level metadata" or "Content light level metadata" in side_data.values():
                try:
                    max_content = int(side_data["max_content"])
                    max_average = int(side_data["max_average"])
                    if max_content > 0 or max_average > 0:
                        SideDTA["max_content"] = max_content
                        SideDTA["max_average"] = max_average
                        SideDTA["Cll_exists"] = True
                except (KeyError, ValueError, TypeError) as e:
                    logger.warning(f"[get_static_metadata] Incomplete Content Light Level metadata: {e}")

            if sd_type == "Mastering display metadata" or "Mastering display metadata" in side_data.values():
                try:
                    max_lum = parse_val(side_data["max_luminance"])
                    if max_lum > 0:
                        SideDTA["red_x"] = parse_val(side_data["red_x"])
                        SideDTA["red_y"] = parse_val(side_data["red_y"])
                        SideDTA["green_x"] = parse_val(side_data["green_x"])
                        SideDTA["green_y"] = parse_val(side_data["green_y"])
                        SideDTA["blue_x"] = parse_val(side_data["blue_x"])
                        SideDTA["blue_y"] = parse_val(side_data["blue_y"])
                        SideDTA["white_point_x"] = parse_val(side_data["white_point_x"])
                        SideDTA["white_point_y"] = parse_val(side_data["white_point_y"])
                        SideDTA["min_luminance"] = parse_val(side_data["min_luminance"])
                        SideDTA["max_luminance"] = max_lum
                        SideDTA["Mastering_display_exists"] = True
                except (KeyError, ValueError, TypeError) as e:
                    logger.warning(f"[get_static_metadata] Incomplete Mastering Display metadata: {e}")

        return VUI, SideDTA

    except subprocess.CalledProcessError as e:
        logger.warning(f"[get_static_metadata] FFprobe execution failed for {input_file}: {e}; using defaults")
        return VUI, SideDTA
    except json.JSONDecodeError as e:
        logger.warning(f"[get_static_metadata] Failed to decode FFprobe JSON for {input_file}: {e}; using defaults")
        return VUI, SideDTA
    except Exception as e:
        logger.warning(f"[get_static_metadata] Unexpected error extracting VUI for {input_file}: {e}; using defaults")
        return VUI, SideDTA


if __name__ == "__main__":
    None