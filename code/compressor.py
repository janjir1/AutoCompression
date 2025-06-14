import subprocess, os, json
import logging
import AVTest
from threading import Thread
import logger_setup
# Retrieve the logger once at the module level
logger = logging.getLogger("AppLogger")


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
    "HandbrakeAV1": command_HandbrakeAV1
    }

    if profile["function"][1] in function_mapping:
        command = function_mapping[profile["function"][1]](file, profile, output_file, crop, target_res, target_cq, channels, start, duration, subtitles, tool_path)
    else:
        logger.error(f"{profile["function"][1]} was not found in function map")

    if execute(command):
        if check_output(output_file):
            return True
        else:
            return False
    else:
        return False

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

def command_HandbrakeAV1(
    file: str, profile: dict, output_file: str, crop: list, target_res: list, target_cq: float, 
    channels: int, start: int, duration: int, subtitles: bool, tool_path: str = r"tools\HandBrakeCLI.exe"
) -> list:
    """
    Generates a HandBrakeCLI command for encoding a video using AV1.

    Parameters:
    - file (str): Input video file path.
    - profile (dict): Encoding profile containing audio and video settings.
    - output_file (str): Path to save the encoded output.
    - crop (list): List containing top and bottom crop values [top, bottom].
    - target_res (int): Target width resolution.
    - target_cq (float): Target constant quality value for encoding.
    - channels (int or bool): Number of audio channels, or False to disable audio.
    - start (int or bool): Start time in seconds, or False to encode from the beginning.
    - duration (int or bool): Duration in seconds, or False to encode till the end.
    - subtitles (bool): If True, include all subtitles; otherwise, disable them.
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
        ]

    if start or duration:
        sub = [
            '--start-at',  f'duration:{str(start)}',
            '--stop-at',  f'duration:{str(duration)}',
        ]
        command = command + sub

    if channels:
        channels_list = {
            1: 'mono',
            2: 'dpl2',
            6: '5point1',
            7: '6point1',
            8: '7point1'
        }

        if channels < 6 and channels > 2: channels = 2
        elif channels > 8: channels = 8

        sub = [
            '--mixdown',  channels_list[channels]
        ]
        command = command + profile["audio"] + sub 
    else:
        sub = [
            '-a', 'none'
        ]
        command = command + sub

    if subtitles:
        sub = [
            '--all-subtitles', 
            '--srt-codeset',  'UTF-8'
        ]
        command = command + sub
    else:
        sub = [
            '-s', 'none'
        ]
        command = command + sub        


    command = command + profile["video"]

    logger.debug(f"ffmpeg command: {command}")

    return command

def command_ffmpeg(file, profile, output_file, crop, target_res, target_cq, channels, start, duration, subtitles, tool_path) -> list:

    def vfCropComandGenerator(file_path: str, crop: list, target_h_res: int) -> str:
        h_res_orig = AVTest.getH_res(file_path)
        v_res_orig = AVTest.getV_res(file_path)
        target_v_res = v_res_orig - crop[0] - crop[1]
        #-vf "crop=1920:970:0:60,scale=1280:-2"
        command = f"crop={h_res_orig}:{target_v_res}:0:{crop[0]},scale={target_h_res}:-2:sws_flags=neighbor"
        return command

    #command begin
    if start or duration:
        command =[
        tool_path,
        "-ss", int(start),
        "-i", file,
        "-t", int(duration)
    ]
    else:
        command =[
            tool_path,                                  # Command to run FFmpeg
            "-i", file                                  # Input file path
        ]

    #include video profile
    resolution_filter = vfCropComandGenerator(file, crop, target_res)
    video_profile_modified = profile["video"].copy()

    try:
        index = video_profile_modified.index("-vf")
        video_profile_modified[index+1] = video_profile_modified[index+1] + "," + resolution_filter
    except ValueError:
        video_profile_modified.append("-vf")
        video_profile_modified.append(resolution_filter)
    
    command = command + video_profile_modified

    #audio
    if channels:
        if "stereo" in profile and channels == 2:
            command = command + profile["stereo"]
        else:
            command = command + profile["audio"] 
    else:
        command = command + ["-an"]

    #subtitles
    if subtitles:
        command = command +["-c:s", "srt", "-sub_charenc", "UTF-8"]
    else:
        command = command + ["-sn"]
        
    command_append = [
        "-copy_unknown",
        "-map_metadata", "0",
        '-cq', str(target_cq),                     # Constant Quality mode                
        '-y',                                      # overvrite
        output_file                                # Output file
    ]

    command = command + command_append


    logger.debug(f"ffmpeg command: {command}")
    #process = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return command

#temporary fix probalbly forever
_dynamic_metadata_exists = None
def get_video_metadata(input_file, workspace, extract_dynamic = False, relative_tools_path = "tools", cleanup = True):
    #probably dont need static metadata extraction

    global _dynamic_metadata_exists
    #DOVI
    dovi_metadata_file = os.path.join(workspace, "dovi_metadata.bin")
    HDR10_metadata_file = os.path.join(workspace, "HDR10_dynamic_metadata.json")

    if _dynamic_metadata_exists is False:
        return False
    
    elif _dynamic_metadata_exists and os.path.isfile(dovi_metadata_file):
        logger.info(f"Using {dovi_metadata_file} as dynamic metadata")
        return {"dolby-vision": dovi_metadata_file}
    
    elif _dynamic_metadata_exists and os.path.isfile(HDR10_metadata_file):
        logger.info(f"Using {HDR10_metadata_file} as dynamic metadata")
        return {"hdr10_plus": HDR10_metadata_file}
    
    elif _dynamic_metadata_exists is None:
        dovi_tool_path = os.path.join(relative_tools_path, "dovi_tool.exe")
        dovi = [f"{dovi_tool_path}", "extract-rpu", "-i", f"{input_file}", "-o", f"{dovi_metadata_file}"]

        if not execute(dovi):
            return False

        if check_output(dovi_metadata_file):
            logger.info("DoVI metadata file is valid")
            metadata_file = {"dolby-vision": dovi_metadata_file}
            _dynamic_metadata_exists = True
        else:
            logger.info("DoVI metadata file is not valid")

            #HDR10+
            HDR10plus_tool_path = os.path.join(relative_tools_path, "hdr10plus_tool.exe")
            HDR10plus = [f"{HDR10plus_tool_path}", "extract", f"{input_file}", "-o", f"{HDR10_metadata_file}"]

            if not execute(HDR10plus):
                return False

            if check_output(HDR10_metadata_file):
                logger.info("HDR10+ metadata file is valid")
                metadata_file = {"hdr10_plus": HDR10_metadata_file}
                _dynamic_metadata_exists = True
            else: 
                logger.info("HDR10+ metadata file is not valid")
                return False
            
            return metadata_file 
    """
    if cleanup is True:
        try:
            if os.path.isfile(video_stram):  # Ensure it's a file
                    os.remove(video_stram)
            else:
                print(f"File not found: {video_stram}")
        except PermissionError:
            print(f"Permission denied: {video_stram}")
        except Exception as e:
            print(f"Error deleting file {video_stram}: {e}")
    """

    

def compress_ffmpeg(file: str, profile: dict, output_file: str, crop: list, target_res: list, target_cq: float, 
    channels: int, start: int, duration: int, subtitles: bool, tool_path:str = r"tools"):

    workspace = os.path.dirname(output_file)
    file_name = os.path.basename(output_file) #TODO remove the .mkv
    file_name = os.path.splitext(file_name)[0]

    #Enable HDR only for h265
    if profile["HDR_enable"][1]: #pass to this function
        #extract metadata (if wanted) 

        metadata_file = get_video_metadata(file, workspace)

        if metadata_file is None:
            logger.warning("HDR dynamic metadata extraction from source was not sucesefull or is not enabled")

            #output file is without change
            logger.info(f"Compressing {file} into {output_file}")
            command = command_ffmpeg(file, profile, output_file, crop, target_res, target_cq, channels, start, duration, subtitles, tool_path) #command_ffmpeg doesnt know output metadata yet
            if not execute(command):
                return False
            return check_output(output_file)
            
        else:
            logger.info(f"Dynamic data extraction was succesfull, {metadata_file}")
            logger.info(f"Compressing {file} into {output_file}")
            hevc_file = os.path.join(workspace, file_name + ".hevc")
            command = command_ffmpeg(file, profile, hevc_file, crop, target_res, target_cq, channels, start, duration, subtitles, tool_path) #command_ffmpeg doesnt know output metadata yet
            if not execute(command):
                return False
            if not check_output(output_file):
                return False

            #inject metadata
            output_file_inject = os.path.join(workspace, file_name + "HDR.hevc")
            logger.info(f"Injecting {metadata_file.keys()[0]} metadata into {output_file_inject}")
            
            if metadata_file.keys()[0] == "hdr10_plus":
                tool_path = os.path.join(os.path.dirname(tool_path), "hdr10_plus.exe")
                command = [tool_path, "inject", "-i", output_file, "-j", metadata_file["hdr10_plus"], "-o", output_file_inject]
            elif metadata_file.keys()[0] == "dolby-vision":
                dovi_tool_path = os.path.join(os.path.dirname(tool_path), "dovi_tool.exe")
                command = [dovi_tool_path, "inject-rpu", "-i", output_file, "--rpu-in", metadata_file["dolby-vision"], "-o", output_file_inject]
            else:
                logger.error("unexpected metadata format (should not be possible)")
                return False
            
            execute(command)
            check_output(output_file)
            #TODO: delete non_hdr file

            #TODO: audio
            # mux back into desired format
            command = ["ffmpeg", "-i", output_file_inject, "-i", audio.aac, "-c", "copy", output.mkv]
            execute(command)
            return check_output(output_file)

    else:
        command = command_ffmpeg(file, profile, output_file, crop, target_res, target_cq, channels, output_metadata) #command_ffmpeg doesnt know output metadata yet
        execute(command)
        return check_output(output_file)   