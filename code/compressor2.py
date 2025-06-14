import subprocess, os, json
import logging
import AVTest
from threading import Thread
import logger_setup
# Retrieve the logger once at the module level
logger = logging.getLogger("AppLogger")

#temporary fix probalbly forever
_dynamic_metadata_type = "uninit"
framerate


def compress(file: str, profile, output_file: str, crop: list, target_res: int, target_cq: float, channels: int = False, start: int = False, duration: int = False, subtitles: bool = False, tool_path: str = r"tools\HandBrakeCLI.exe") -> bool:
    """
    Compresses a video file using a specified profile and tool.
    
    Parameters:
    - file (str): Path to the input video file.
    - profile: Dictionary or object containing compression settings, including a "function" key.
    - output_file (str): Path to save the compressed video.
    - crop (list): List of crop parameters.
    - target_res (int): Target horizontal resolution.
    - target_cq (float): Target constant quality (CQ) value.
    - channels (int, optional): Audio channels to be used; defaults to False if not provided.
    - start (int, optional): Start time for compression; defaults to False if not provided.
    - duration (int, optional): Duration for compression; defaults to False if not provided.
    - subtitles (bool, optional): Whether to include subtitles; defaults to False.
    - tool_path (str, optional): Path to the compression tool (HandBrakeCLI); defaults to "tools\HandBrakeCLI.exe".
    
    Returns:
    - bool: True if compression succeeded and output file is valid; otherwise, False.
    """

    function_mapping = {
    "HandbrakeAV1": video_HandbrakeAV1
    }

    if profile["function"][1] in function_mapping:
        passed = function_mapping[profile["function"][1]](file, profile, output_file, crop, target_res, target_cq, channels, start, duration, subtitles, tool_path)
    else:
        logger.error(f"{profile["function"][1]} was not found in function map")

    

def execute(command: list) -> bool:
    """
    Executes a command using subprocess, processing stdout and stderr streams in separate threads.
    For each stream, output is logged to a dedicated file logger (only within the log_stream function).
    
    Parameters:
    - command (list): Command and arguments to execute.
    
    Returns:
    - bool: True if process finished successfully (exit code 0), else False.
    """
        
    # Start the process with UTF-8 encoding
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=1,  # Line-buffered mode
        universal_newlines=False  # Handle decoding manually
    )

    # Create a dedicated file logger for stream logging.
    stream_logger = logging.getLogger("FileLogger")
    for _ in range(6):
        stream_logger.debug(f"----------------------------------------------------------------------------------------------")

    stream_logger.info(f"{command}")
    # Function to read a stream line-by-line and log it to a file.
    def log_stream(stream, stream_type, file_log):

        last_line = None
        decoder = iter(lambda: stream.read(1), b'')
        line_buffer = bytearray()
        
        for byte in decoder:
            line_buffer += byte
            
            # Detect line endings (both Unix and Windows)
            if byte in (b'\n', b'\r'):
                if not line_buffer:
                    continue
                
                try:
                    # Decode and clean the line
                    decoded_line = line_buffer.decode('utf-8').rstrip('\r\n')
                    stripped_line = decoded_line.strip()
                except UnicodeDecodeError:
                    decoded_line = line_buffer.decode('utf-8', errors='replace').rstrip('\r\n')
                    stripped_line = decoded_line.strip()
                    file_log.warning(f"Encoding issue detected in {stream_type} stream")

                # Reset buffer after processing line
                line_buffer = bytearray()

                # Skip empty lines
                if not stripped_line:
                    continue

                # Skip consecutive duplicates
                if stripped_line == last_line:
                    continue

                # Log and update last line
                if stream_type == "STDOUT":
                    print(decoded_line)
                    file_log.debug(f"[{stream_type}] {decoded_line}")
                elif stream_type == "STDERR":
                    file_log.debug(f"[{stream_type}] {decoded_line}")
                    
                last_line = stripped_line

   # Start threads for stdout and stderr.
    stdout_thread = Thread(target=log_stream, args=(process.stdout, "STDOUT", stream_logger))
    stderr_thread = Thread(target=log_stream, args=(process.stderr, "STDERR", stream_logger))
    
    stdout_thread.start()
    stderr_thread.start()

    # Wait for completion
    process.wait()
    stdout_thread.join()
    stderr_thread.join()

    # Check final status
    if process.returncode != 0:
        logger.error(f"Process failed with exit code: {process.returncode}")
        return False

    logger.info(f"Conversion finished succesfully")
    return True

def check_output(file_path: str, size_limit=2048) -> bool:
    """
    Checks if the output file exists and meets the minimum size requirement.

    Parameters:
    - file_path (str): Path to the output file.
    - size_limit (int, optional): Minimum acceptable file size in bytes. Defaults to 2048 bytes.

    Returns:
    - bool: True if the file exists and meets the size requirement, False otherwise.
    """
    try:
        if os.path.isfile(file_path):  # Ensure the path points to a file
            file_size = os.path.getsize(file_path)

            if file_size < size_limit:
                logger.error(f"File is too small ({file_size} bytes) -> Command likely failed.")
                return False
            else:
                logger.debug(f"File check passed: {file_path} (Size: {file_size} bytes)")
                return True
        else:
            logger.error(f"File not found: {file_path}")
            return False  # Changed return value from True to False since the file is missing.

    except PermissionError:
        logger.warning(f"Permission denied: Unable to access {file_path}")
        return False  # Returning False as permission issues may prevent valid output.
    
def temporal_crop(file: str, output_file: str, start: int, duration: int, tool_path: str = r"ffmpeg") -> bool:
        
    command =[
    tool_path,
    "-y",
    "-ss", int(start),
    "-i", file,
    "-t", int(duration),
    "-c:v", "copy",
    "-c:a", "copy",
    "-copy_unknown",
    output_file
    ]

    logger.debug(f"ffmpeg command for temporal crop: {command}")
        
    if execute(command):
        if check_output(output_file):
            return True
        else:
            return False
    else:
        return False

def video_HandbrakeAV1(
    file: str, profile: dict, output_file: str, crop: list, target_res: list, target_cq: float, 
    tool_path: str = r"tools\HandBrakeCLI.exe") -> bool:
    """
    Generates a HandBrakeCLI command for encoding a video using AV1.

    Parameters:
    - file (str): Input video file path.
    - profile (dict): Encoding profile containing audio and video settings.
    - output_file (str): Path to save the encoded output.
    - crop (list): List containing top and bottom crop values [top, bottom].
    - target_res (int): Target width resolution.
    - target_cq (float): Target constant quality value for encoding.
    - start (int or bool): Start time in seconds, or False to encode from the beginning.
    - duration (int or bool): Duration in seconds, or False to encode till the end.
    - tool_path (str): Path to the HandBrakeCLI executable.

    Returns:
    - list: The constructed HandBrakeCLI command as a list of arguments.
    """

    # Base command with input/output settings and basic encoding options
    command = [
        tool_path,
        '-i', file,
        '-o', output_file,
        '-q', str(target_cq),
        '--crop', f'0:{str(crop[0])}:0:{str(crop[1])}',
        '--width', str(target_res),
        '--non-anamorphic',
        '-a', 'none',
        '-s', 'none'
        ]

    command = command + profile["video"]

    logger.debug(f"HandbrakeAV1 command: {command}")

    if execute(command):
        if check_output(output_file):
            return True
        else:
            return False
    else:
        return False
    
def video_ffmpeg(
    file: str, profile: dict, output_file: str, crop: list, target_res: list, target_cq: float, 
    start: int, duration: int, tool_path: str = r"tools\HandBrakeCLI.exe") -> bool:

    def get_video_metadata_type(input_file, workspace, relative_tools_path = "tools"):

        global _dynamic_metadata_type

        if _dynamic_metadata_type is "uninit":

            _dynamic_metadata_type = False
            dovi_metadata_file = os.path.join(workspace, "dovi_metadata.bin")
            HDR10_metadata_file = os.path.join(workspace, "HDR10_dynamic_metadata.json")

            #DOVI
            dovi_tool_path = os.path.join(relative_tools_path, "dovi_tool.exe")
            dovi = [f"{dovi_tool_path}", "extract-rpu", "-i", f"{input_file}", "-o", f"{dovi_metadata_file}"]

            if not execute(dovi):
                return False

            if check_output(dovi_metadata_file):
                logger.info("DoVI metadata file is valid")
                _dynamic_metadata_type = "DoVi"
                return True
            else:
                logger.info("DoVI metadata file is not valid")

                #HDR10+
                HDR10plus_tool_path = os.path.join(relative_tools_path, "hdr10plus_tool.exe")
                HDR10plus = [f"{HDR10plus_tool_path}", "extract", f"{input_file}", "-o", f"{HDR10_metadata_file}"]

                if not execute(HDR10plus):
                    return False

                if check_output(HDR10_metadata_file):
                    logger.info("HDR10+ metadata file is valid")
                    _dynamic_metadata_type = "HDR10"
                    return True
                else: 
                    logger.info("HDR10+ metadata file is not valid")
                    return False
                    
        else: return True

    def video_HDR_extract(input_file, workspace, name, relative_tools_path = "tools"):
        #TODO spetial crop for dovi
        global _dynamic_metadata_type
        dovi_metadata_file = os.path.join(workspace, "dovi_metadata_" + name + ".bin")
        HDR10_metadata_file = os.path.join(workspace, "HDR10_dynamic_metadata_" + name + ".json")

        if _dynamic_metadata_type == "DoVi":

            dovi_tool_path = os.path.join(relative_tools_path, "dovi_tool.exe")
            dovi = [f"{dovi_tool_path}", "extract-rpu", "-i", f"{input_file}", "-o", f"{dovi_metadata_file}"]

            if not execute(dovi):
                return False
            if not check_output(dovi_metadata_file):
                return False
            return dovi_metadata_file
        
        elif _dynamic_metadata_type == "HDR10":

            HDR10plus_tool_path = os.path.join(relative_tools_path, "hdr10plus_tool.exe")
            HDR10plus = [f"{HDR10plus_tool_path}", "extract", f"{input_file}", "-o", f"{HDR10_metadata_file}"]

            if not execute(HDR10plus):
                return False
            if not check_output(HDR10_metadata_file):
                return False
            return dovi_metadata_file
        
        else: return False

    def video_HDR_inject(input_file, workspace, metadata_file, output_file, relative_tools_path = "tools"):

        global _dynamic_metadata_type
        logger.info(f"Injecting {metadata_file} metadata into {output_file}")
        
        if _dynamic_metadata_type == "HDR10":
            tool_path = os.path.join(os.path.dirname(tool_path), "hdr10_plus.exe")
            command = [tool_path, "inject", "-i", output_file, "-j", metadata_file, "-o", output_file]
        elif _dynamic_metadata_type == "DoVi":
            dovi_tool_path = os.path.join(os.path.dirname(tool_path), "dovi_tool.exe")
            command = [dovi_tool_path, "inject-rpu", "-i", output_file, "--rpu-in", metadata_file, "-o", output_file]
        else:
            logger.error("unexpected metadata format")
            return False
        
    def video_encode_ffmpeg(input_file: str, profile: dict, output_file: str, crop: list, target_res: list, target_cq: float, 
    tool_path: str = r"tools\HandBrakeCLI.exe") -> bool:
        
        def vfCropComandGenerator(file_path: str, crop: list, target_h_res: int) -> str:
            h_res_orig = AVTest.getH_res(file_path)
            v_res_orig = AVTest.getV_res(file_path)
            target_v_res = v_res_orig - crop[0] - crop[1]
            #-vf "crop=1920:970:0:60,scale=1280:-2"
            command = f"crop={h_res_orig}:{target_v_res}:0:{crop[0]},scale={target_h_res}:-2:sws_flags=neighbor"
            return command

        command =[
            tool_path,                                  # Command to run FFmpeg
            "-i", input_file,
            "-an",
            "-sn",
        ]

        #include video profile
        resolution_filter = vfCropComandGenerator(input_file, crop, target_res)
        video_profile_modified = profile["video"].copy()

        try:
            index = video_profile_modified.index("-vf")
            video_profile_modified[index+1] = video_profile_modified[index+1] + "," + resolution_filter
        except ValueError:
            video_profile_modified.append("-vf")
            video_profile_modified.append(resolution_filter)
        
        command = command + video_profile_modified

        command_append = [
            "-copy_unknown",
            "-map_metadata", "0",
            '-cq', str(target_cq),                     # Constant Quality mode                
            '-y',                                      # overvrite
            output_file                                # Output file
        ]

        command = command + command_append


        logger.debug(f"ffmpeg command: {command}")

        if execute(command):
            if check_output(output_file):
                return True
            else:
                return False
        else:
            return False
        
        #Enable HDR only for h265
    
    def get_framerate(input_file):
        #TODO run only once
        try:
            # First attempt: Get r_frame_rate (most reliable for CFR content)
            cmd = [
                'ffprobe', '-v', 'error', '-select_streams', 'v:0',
                '-show_entries', 'stream=r_frame_rate',
                '-of', 'default=noprint_wrappers=1:nokey=1',
                input_file
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            framerate = result.stdout.strip()
            
            # Validate framerate
            if framerate and framerate != "0/0" and "/" in framerate:
                # Convert to decimal to verify it's reasonable
                numerator, denominator = map(int, framerate.split('/'))
                fps_decimal = numerator / denominator
                if 10 <= fps_decimal <= 120:  # Reasonable framerate range
                    return framerate
            
            # Fallback: Try avg_frame_rate for VFR content
            cmd[4] = 'stream=avg_frame_rate'
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            framerate = result.stdout.strip()
            
            if framerate and framerate != "0/0" and "/" in framerate:
                numerator, denominator = map(int, framerate.split('/'))
                fps_decimal = numerator / denominator
                if 10 <= fps_decimal <= 120:
                    return framerate
            
            return False
            
        except subprocess.CalledProcessError as e:
            raise ValueError(f"ffprobe failed to analyze MKV file: {e}")
        except Exception as e:
            raise ValueError(f"Error extracting framerate: {e}")

    def hevc_to_mkv(input_file, workspace, output_file, framerate):
            
        command = [
            'ffmpeg', '-y',  # Overwrite output file
            '-fflags', '+genpts',  # Generate presentation timestamps
            '-r', framerate,    # Set framerate
            '-i', input_file,       # Input HEVC file
            '-c:v', 'copy',        # Copy video stream without re-encoding
            output_file
        ]
        
        if execute(command):
            if check_output(output_file):
                return True
            else:
                return False
        else:
            return False
                

    if profile["HDR_enable"][1]:

        #get_video_metadata_type
        #get_framerate
        #video_HDR_extract
        #video_encode_ffmpeg
        #video_HDR_inject
        #hevc_to_mkv

    else:
        
        #video_encode_ffmpeg
