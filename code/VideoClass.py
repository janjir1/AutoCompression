from typing import List, Union
import AVTest
import os
import compressor2
import yaml
import subprocess
import json
import logger_setup
import logging
from fractions import Fraction

logger = logging.getLogger("AppLogger")

class VideoProcessingConfig:
    crop: List[int] = [0, 0]
    channels: Union[int, bool] = False
    start: Union[int, bool] = False
    duration: Union[int, bool] = False
    subtitles: bool = False
    HDR_type: str = "uninit"

    def __init__(self, input_file_path: str, output_file_name: str, workspace: str):
        self.orig_file_path = input_file_path
        self.output_file_name = output_file_name
        self.workspace = workspace
        self.output_file_path = os.path.join(self.workspace, self.output_file_name) + ".mkv"
        if not os.path.exists(workspace):
            os.makedirs(workspace)
        self.dovi_metadata_file = os.path.join(workspace, "dovi_metadata_test.bin")
        self.HDR10_metadata_file = os.path.join(workspace, "HDR10_metadata_test.json")

    def readProfiles(self, profile_path: str, test_settings_path: str, tools_path: str):
        self.profile, self.profile_settings = readProfile(profile_path)
        self.test_settings = readSettings(test_settings_path)
        self.tools_path = tools_path
        self.target_cq = self.profile["defalut_cq"] 
        self.output_cq = self.profile["defalut_cq"] 
    
    def analyzeOriginal(self):
        self.orig_h_res = getH_res(self.orig_file_path)
        self.orig_v_res = getV_res(self.orig_file_path)
        self.orig_framerate = get_framerate(self.orig_file_path)
        self.orig_duration = getDuration(self.orig_file_path)
        self.target_res = self.orig_h_res
        self.output_res = self.orig_h_res
        self.orig_container = None
        self.orig_codec = None

    def setTargetCQ(self, CQ: float):
        self.target_cq = CQ

    def setTargetRes(self, res: int):
        self.target_res = res

    def setTargetPath(self, name: str):
        self.target_path = name

    def setSourcePath(self, name: str):
        self.source_path = name

    def setOutputCQ(self, CQ: float):
        self.output_cq = CQ

    def setOutputRes(self, res: int):
        self.output_res = res

    def setCrop(self, crop: list):
        self.target_crop = crop
    
    def setStart(self, start: int):
        self.start = start
    
    def setDuration(self, duration: int):
        self.duration = duration

    def setHDR_Type(self, hdr_type: str):
        if hdr_type == "DoVi" or "HDR10" or "None":
          self.HDR_type = hdr_type
        else: logger.error(f"Unknown hdr rype: {hdr_type}")

    def 

def readProfile(yaml_profile):
    with open(yaml_profile, 'r') as file:
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

    return profile, profile_settings

def readSettings(yaml_settings):

    with open(yaml_settings, 'r') as file:
        loaded_data = yaml.safe_load(file)

    
    dictionar = dict()
    for key, value in loaded_data.items():
        dictionar[key] = list()
        for subvalue in value.items():
            dictionar[key].append(subvalue[1])

    settings = dict()
    for key in dictionar.keys():

        enable = dictionar[key][0]
        if type(enable) is not bool:
            enable = False
        else: dictionar[key].pop(0)

        settings[key] = [enable, dictionar[key]]

    return settings

def getDuration(input_path: str) -> float:
    """
    Retrieves the duration of a video file using FFprobe.

    Parameters:
    - input_path (str): Path to the video file.

    Returns:
    - float: Duration of the video in seconds, or None if an error occurs.
    """

    # Run ffprobe to get video information in JSON format
    command = [
        'ffprobe',
        '-v', 'error',                         # Suppress non-error messages
        '-show_entries', 'format=duration',    # Extract duration
        '-of', 'json',                         # Output format as JSON
        input_path                             # Input file path
    ]
    
    try:
        # Execute the command and capture output
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, shell=False)
        
        # Check if FFprobe execution was successful
        if result.returncode != 0:
            logger.error(f"FFprobe error for {input_path}: {result.stderr.strip()}")
            return 0

        # Parse JSON output
        data = json.loads(result.stdout)
        
        # Extract and return duration
        duration = float(data.get('format', {}).get('duration', 0))
        if duration > 0:
            return duration
        else:
            logger.error(f"Invalid duration value received from FFprobe for {input_path}.")
            return 0

    except json.JSONDecodeError:
        logger.error(f"Failed to parse JSON output from FFprobe for {input_path}.")
    except Exception as e:
        logger.error(f"Unexpected error while retrieving duration for {input_path}: {e}")

    return 0

def getH_res(video_path: str) -> int:

    """
    Retrieves the horizontal resolution (width) of a video file using FFprobe.

    Parameters:
    - video_path (str): Path to the video file.

    Returns:
    - int: Width of the video in pixels, or None if an error occurs.
    """

    # ffprobe command to get the stream info in JSON format
    command = [
        "ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
        "stream=width", "-of", "json", video_path
    ]
    
    # Run the command and capture the output
    try:
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, shell=False)

        # Check if FFprobe execution was successful
        if result.returncode != 0:
            logger.error(f"FFprobe error for {video_path}: {result.stderr.strip()}")
            return 0
        
        # Parse the JSON output
        ffprobe_output = json.loads(result.stdout)

        # Extract the width from the 'width' field in the stream
        width = int(ffprobe_output['streams'][0]['width'])
        if width is not None:
            return width
        else:
            logger.error(f"Failed to retrieve height from FFprobe output for {video_path}.")
            return 0
    
    except json.JSONDecodeError:
        logger.error(f"Failed to parse JSON output from FFprobe for {video_path}.")
    except Exception as e:
        logger.error(f"Unexpected error while retrieving resolution for {video_path}: {e}")

    return 0
    
def getV_res(video_path: str) -> int:
    """
    Retrieves the vertical resolution (height) of a video file using FFprobe.

    Parameters:
    - video_path (str): Path to the video file.

    Returns:
    - int: Height of the video in pixels, or None if an error occurs.
    """

    # ffprobe command to get the stream info in JSON format
    command = [
        "ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
        "stream=height", "-of", "json", video_path
    ]

    # Run the command and capture the output
    try:
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, shell=False)

        # Check if FFprobe execution was successful
        if result.returncode != 0:
            logger.error(f"FFprobe error for {video_path}: {result.stderr.strip()}")
            return 0
        
        # Parse the JSON output
        ffprobe_output = json.loads(result.stdout)

        # Extract the height from the 'height' field in the stream
        height = int(ffprobe_output['streams'][0]['height'])
        
        if height is not None:
            return height
        else:
            logger.error(f"Failed to retrieve height from FFprobe output for {video_path}.")
            return 0
    
    except json.JSONDecodeError:
        logger.error(f"Failed to parse JSON output from FFprobe for {video_path}.")
    except Exception as e:
        logger.error(f"Unexpected error while retrieving resolution for {video_path}: {e}")
    return 0

def get_framerate(input_file):
    """
    Retrieves the video framerate using ffprobe, supporting both CFR and VFR.
    
    Returns:
        True if succefull
    
    Raises:
        ValueError: On ffprobe failure or invalid framerate.
    """

    logger.info(f"Getting framerate")
    def probe(entry: str) -> str:
        cmd = [
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            f"-show_entries", f"stream={entry}",
            "-of", "default=noprint_wrappers=1:nokey=1",
            input_file
        ]
        logger.debug(f"Complete FFmpeg command: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return result.stdout.strip()
    
    def ffprobe_framerate_to_float(framerate_string):
        # Remove any whitespace
        framerate_string = framerate_string.strip()
        
        # Use the fractions module to parse and convert to float
        fraction = Fraction(framerate_string)
        return round(float(fraction), 3)


    # Try constant-frame-rate
    raw = probe("r_frame_rate")
    logger.debug(f"Probe r_frame_rate: {raw}")  # Logging probe output[2]
    framerate_local = ffprobe_framerate_to_float(raw)
    logger.debug(f"Probe r_frame_rate: {framerate_local}")  # Logging probe output[2]
    if 10 <= float(framerate_local) <= 1000:
        framerate = framerate_local
        return True

    # Fallback to variable-frame-rate
    raw = probe("avg_frame_rate")
    logger.debug(f"Probe avg_frame_rate: {raw}")  # Fallback probe logging[2]
    framerate_local = ffprobe_framerate_to_float(raw)
    logger.debug(f"Probe r_frame_rate: {framerate_local}")  # Logging probe output[2]
    if 10 <= float(framerate_local) <= 1000:
        framerate = framerate_local
        return True
    
    logger.error(f"Framerate detection failed")
    return False