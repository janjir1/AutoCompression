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
    """
    Configuration class for video processing operations.

    
    Manages video processing parameters including input/output paths, encoding settings,
    HDR metadata handling, and temporal/spatial cropping configurations.

    """
    crop: List[int] = [0, 0]
    channels: Union[int, bool] = False
    start: Union[int, bool] = False
    duration: Union[int, bool] = False
    subtitles: bool = False
    HDR_type: str = "uninit"

    def __init__(self, input_file_path: str, output_file_name: str, workspace: str):
        """
        Initialize video processing configuration.
        Args:
            input_file_path (str): Path to the input video file
            output_file_name (str): Name for the output file (without extension)
            workspace (str): Working directory for temporary and output files
        """
        logger.info(f"[VideoProcessingConfig.__init__] Initializing video processing config")
        logger.debug(f"[VideoProcessingConfig.__init__] Input file: {input_file_path}")
        logger.debug(f"[VideoProcessingConfig.__init__] Output name: {output_file_name}")
        logger.debug(f"[VideoProcessingConfig.__init__] Workspace: {workspace}")
        
        self.orig_file_path = input_file_path
        self.output_file_name = output_file_name
        self.workspace = workspace
        self.output_file_path = os.path.join(self.workspace, self.output_file_name) + ".mkv"   

        if not os.path.exists(workspace):
            os.makedirs(workspace)

        self.dovi_metadata_file = os.path.join(workspace, "dovi_metadata_test.bin")
        self.HDR10_metadata_file = os.path.join(workspace, "HDR10_metadata_test.json")

        logger.debug(f"[VideoProcessingConfig.__init__] DoVi metadata file: {self.dovi_metadata_file}")
        logger.debug(f"[VideoProcessingConfig.__init__] HDR10 metadata file: {self.HDR10_metadata_file}")

    def readProfiles(self, profile_path: str, test_settings_path: str, tools_path: str):
        """
        Load encoding profiles and test settings from YAML files.
        Args:

            profile_path (str): Path to the encoding profile YAML file
            test_settings_path (str): Path to the test settings YAML file
            tools_path (str): Path to external tools directory
        """
        logger.info(f"[VideoProcessingConfig.readProfiles] Loading profiles and settings")
        logger.debug(f"[VideoProcessingConfig.readProfiles] Profile path: {profile_path}")
        logger.debug(f"[VideoProcessingConfig.readProfiles] Test settings path: {test_settings_path}")
        logger.debug(f"[VideoProcessingConfig.readProfiles] Tools path: {tools_path}")

        self.profile, self.profile_settings = readProfile(profile_path)
        self.test_settings = readSettings(test_settings_path)
        self.tools_path = tools_path
        self.target_cq = self.getProfileValue(self.profile["test_settings"], "defalut_cq")
        self.output_cq = self.getProfileValue(self.profile["test_settings"], "defalut_cq")
    
    def analyzeOriginal(self):
        """
        Analyze the original video file to extract metadata such as resolution, framerate, and duration.
        """
        logger.info(f"[VideoProcessingConfig.analyzeOriginal] Analyzing original video file: {self.orig_file_path}")

        self.orig_h_res = getH_res(self.orig_file_path)
        self.orig_v_res = getV_res(self.orig_file_path)
        self.orig_framerate = get_framerate(self.orig_file_path)
        self.orig_duration = getDuration(self.orig_file_path)
        self.target_res = self.orig_h_res
        self.output_res = self.orig_h_res
        self.orig_container = None
        self.orig_codec = None

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

    def setWorkspace(self, workspace: str):
        if not os.path.exists(workspace):
            os.makedirs(workspace)
        self.workspace = workspace

    def setOutputFileName(self, name: str):
        self.output_file_name = name
        self.output_file_path = os.path.join(self.workspace, name + ".mkv")

    def setHDR_Type(self, hdr_type: str):
        if hdr_type == ("DoVi" or "HDR10" or "None"):
          self.HDR_type = hdr_type
        else: logger.error(f"[VideoProcessingConfig.setHDR_Type] Unknown HDR type: {hdr_type}")

    def getProfileValue(self, lst: list, word: str):
        
        """
        Get a value from a profile list based on a key word.
        Args:
            lst (list): Profile list containing key-value pairs
            word (str): Key to search for
        Returns:
            The value following the specified key
        """
        return lst[lst.index(word)+1]


def readProfile(yaml_profile):
    """
    Read and parse a YAML profile file for video encoding settings.
    Args:
        yaml_profile (str): Path to the YAML profile file
    Returns:
        tuple: (profile dictionary, profile_settings dictionary)
    """
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
    """   
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
    """
    with open(yaml_settings, 'r') as file:
        data = yaml.safe_load(file)
    return data

    return settings

def getDuration(input_path: str) -> float:
    """
    Retrieve the duration of a video file using FFprobe.
    Args:
        input_path (str): Path to the video file
    Returns:
        float: Duration of the video in seconds, or 0 if an error occurs
    """
    logger.debug(f"[getDuration] Getting duration for: {input_path}")

    # Run ffprobe to get video information in JSON format
    command = [
        'ffprobe',
        '-v', 'error',                         # Suppress non-error messages
        '-show_entries', 'format=duration',    # Extract duration
        '-of', 'json',                         # Output format as JSON
        input_path                             # Input file path
    ]
    
    logger.debug(f"[getDuration] FFprobe command: {' '.join(command)}")

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
    # ffprobe command to get the stream info in JSON format
    command = [
        "ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
        "stream=width", "-of", "json", video_path
    ]
    logger.debug(f"[getH_res] FFprobe command: {' '.join(command)}")
    # Run the command and capture the output
    try:
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, shell=False)

        # Check if FFprobe execution was successful
        if result.returncode != 0:
            logger.error(f"[getH_res] FFprobe error for {video_path}: {result.stderr.strip()}")
            return 0
        
        # Parse the JSON output
        ffprobe_output = json.loads(result.stdout)

        # Extract the width from the 'width' field in the stream
        width = int(ffprobe_output['streams'][0]['width'])
        if width is not None:
            return width
        else:
            logger.error(f"[getH_res] Failed to retrieve height from FFprobe output for {video_path}.")
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
        float: Framerate in fps, or False if detection failed
    """
    logger.debug(f"[get_framerate] Getting framerate for: {input_file}")

    def probe(entry: str) -> str:
        cmd = [
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            f"-show_entries", f"stream={entry}",
            "-of", "default=noprint_wrappers=1:nokey=1",
            input_file
        ]
        logger.debug(f"[get_framerate] FFmpeg command: {' '.join(cmd)}")
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
    logger.debug(f"[get_framerate] Probe r_frame_rate: {raw}")  # Logging probe output[2]
    framerate_local = ffprobe_framerate_to_float(raw)
    logger.debug(f"[get_framerate] Probe r_frame_rate: {framerate_local}")  # Logging probe output[2]
    if 10 <= float(framerate_local) <= 1000:
        return framerate_local

    # Fallback to variable-frame-rate
    raw = probe("avg_frame_rate")
    logger.debug(f"[get_framerate] Probe avg_frame_rate: {raw}")  # Fallback probe logging[2]
    framerate_local = ffprobe_framerate_to_float(raw)
    logger.debug(f"[get_framerate] Probe r_frame_rate: {framerate_local}")  # Logging probe output[2]
    if 10 <= float(framerate_local) <= 1000:
        return framerate_local
    
    logger.error(f"[get_framerate] Framerate detection failed")
    return False