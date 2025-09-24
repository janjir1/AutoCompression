import subprocess, os, json
import logging
import AVTest
from threading import Thread
import logger_setup

from fractions import Fraction
from VideoClass import VideoProcessingConfig
# Retrieve the logger once at the module level
logger = logging.getLogger("AppLogger")


def compress(VPC: VideoProcessingConfig) -> bool:
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
    - tool_path (str, optional): Path to the compression tool (HandBrakeCLI);
    
    Returns:
    - bool: True if compression succeeded and output file is valid; otherwise, False.
    """

    logger.info(f"Starting compression for file: {VPC.orig_file_path}")
    logger.debug(f"Compression parameters - Profile: {VPC.profile["function"]["function"]}, "
                f"Target resolution: {VPC.target_res}, CQ: {VPC.target_cq}, Crop: {VPC.crop}")
    
    if VPC.start is not False or VPC.duration is not False:
        VPC.setSourcePath(VPC.orig_file_path)
        VPC.setTargetPath(os.path.join(VPC.workspace, VPC.output_file_name + "_time_crop.mkv"))
        logger.debug(f"Performing temporal crop to: {VPC.target_path}")
        
        if not temporal_crop(VPC):
            logger.error("Temporal cropping failed, aborting compression")
            return False
        
        # Use the temporally cropped file as input for main compression
        VPC.setSourcePath(VPC.target_path)
    else:
        VPC.setSourcePath(VPC.orig_file_path)

    function_mapping = {
    "HandbrakeAV1": video_HandbrakeAV1,
    "ffmpeg"      : video_ffmpeg
    }

    # Validate that the requested compression function exists
    if VPC.profile["function"][1] not in function_mapping:
        logger.error(f"Compression function '{VPC.profile['function'][1]}' not found in function mapping")
        return False
    
    # Execute the appropriate compression function
    compression_func = function_mapping[VPC.profile["function"][1]]
    logger.info(f"Using compression function: {VPC.profile['function'][1]}")
    
    success = compression_func(VPC)
    

    if success:
        logger.info(f"Compression completed successfully for: {output_file_name}")
    else:
        logger.error(f"Compression failed for: {output_file_name}")
        
    return success

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

    logger.debug(f"Command execution finished succesfully")
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

    logger.debug(f"Validating output file: {file_path}")

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
    
def temporal_crop(VPC: VideoProcessingConfig) -> bool:

    """
    Performs temporal cropping (time-based cutting) of video files using FFmpeg.
    
    This function extracts a specific time segment from a video file without
    re-encoding, using stream copying for maximum speed and quality preservation.
    
    Parameters:
        file (str): Path to input video file
        output_file (str): Path for the cropped output file
        start (int): Start time in seconds for the crop
        duration (int): Duration in seconds of the cropped segment
        tool_path (str, optional): Path to FFmpeg executable
        
    Returns:
        bool: True if temporal cropping succeeded, False otherwise
        
    Note:
        Uses stream copying (-c:v copy -c:a copy) to avoid quality loss
        and significantly reduce processing time compared to re-encoding.
    """

    logger.debug(f"Starting temporal crop: {VPC.source_path} -> {VPC.target_path}")
    logger.debug(f"Crop parameters - Start: {VPC.start}s, Duration: {VPC.duration}s")
  
    command =[
    os.path.join(VPC.tools_path, "ffmpeg"),
    "-y",
    "-ss", str(VPC.start),
    "-i", VPC.source_path,
    "-t", str(VPC.duration),
    "-c:v", "copy",
    "-c:a", "copy",
    "-copy_unknown",
    VPC.target_path
    ]

    logger.debug(f"ffmpeg command for temporal crop: {command}")
        
    if execute(command):
        if check_output(VPC.target_path):
            return True
        else:
            return False
    else:
        return False

def video_HandbrakeAV1(VPC: VideoProcessingConfig) -> bool:

    """
    Encodes video using HandBrakeCLI with AV1 codec and specified quality settings.
    
    This function constructs and executes HandBrakeCLI commands for AV1 encoding
    with cropping, resolution scaling, and quality control parameters.
    
    Parameters:
        file (str): Input video file path
        profile (dict): Encoding profile containing video/audio settings
        output_file_name (str): Name for output file
        workspace (str): Directory for output file
        crop (list): Crop values [top, bottom] in pixels
        target_res (int): Target width resolution
        target_cq (float): Constant quality value (lower = higher quality)
        tool_path (str, optional): Path to HandBrakeCLI executable
        
    Returns:
        bool: True if encoding succeeded and output is valid, False otherwise
    """
    logger.info(f"Starting HandBrake AV1 encoding: {VPC.source_path} -> {output_file}")
    logger.debug(f"Encoding parameters - Resolution: {VPC.target_res}, CQ: {VPC.target_cq}, Crop: {VPC.crop}")

    # Base command with input/output settings and basic encoding options
    command = [
        os.path.join(VPC.workspace, "HandBrakeCLI.exe"),
        '-i', VPC.source_path,
        '-o', VPC.output_file_path,
        '-q', str(VPC.target_cq),
        '--crop', f'0:{str(VPC.crop[0])}:0:{str(VPC.crop[1])}',
        '--width', str(VPC.target_res),
        '--non-anamorphic',
        '-a', 'none',
        '-s', 'none'
        ]

    # Append video-specific profile settings
    command = command + VPC.profile["video"]

    logger.debug(f"HandbrakeAV1 command: {command}")

    if execute(command):
        if check_output(VPC.output_file_path):
            logger.info(f"HandBrake AV1 encoding completed successfully: {VPC.output_file_path}")
            return True
        else:
            return False
    else:
        return False
    
def video_ffmpeg(VPC: VideoProcessingConfig) -> bool:

    """
    Main FFmpeg-based video encoding function with HDR metadata handling.
    
    This function orchestrates the complete FFmpeg encoding workflow including
    HDR metadata detection, extraction, encoding, and re-injection for formats
    like Dolby Vision and HDR10+.
    
    Parameters:
        input_file (str): Path to input video file
        profile (dict): Encoding profile with video settings and HDR options
        name (str): Base name for output files
        workspace (str): Working directory for temporary and output files
        crop (list): Crop parameters [top, bottom]
        target_res (int): Target horizontal resolution
        target_cq (float): Constant quality value
        
    Returns:
        bool: True if encoding completed successfully, False otherwise
    """

    logger.info(f"Starting FFmpeg encoding workflow")

    def get_video_metadata_type(VPC: VideoProcessingConfig):

        """
        Detects and caches the HDR metadata type present in a video file.
        
        This function performs a sequential check for Dolby Vision (DoVi) and HDR10+ metadata
        by attempting to extract metadata using specialized tools. The detected metadata type
        is cached globally to avoid redundant detection operations.
        
        Parameters:
            input_file (str): Path to the input video file to analyze
            dovi_metadata_file (str): Output path for extracted Dolby Vision metadata
            HDR10_metadata_file (str): Output path for extracted HDR10+ metadata
            relative_tools_path (str, optional): Directory containing extraction tools
            
        Returns:
            bool: True if metadata type was successfully detected or already cached,
                False if no supported HDR metadata was found
                
        Side Effects:
            Sets global _dynamic_metadata_type to "DoVi", "HDR10", or False
            
        Note:
            This function uses a global cache to avoid repeated metadata detection.
            DoVi detection takes priority over HDR10+ detection.
        """
        if VPC.HDR_type == "uninit":
                
            logger.info(f"Starting HDR metadata type detection for: {VPC.source_path}")
            #logger.debug(f"Output paths - DoVi: {dovi_metadata_file}, HDR10+: {HDR10_metadata_file}")

            logger.debug("Metadata type not cached, performing detection")
            _dynamic_metadata_type = False

            logger.info("Attempting Dolby Vision metadata extraction")
            dovi_tool_path = os.path.join(VPC.tools_path, "dovi_tool.exe")
            dovi = [f"{dovi_tool_path}", "extract-rpu", "-i", f"{VPC.source_path}", "-o", f"{VPC.dovi_metadata_file}"]

            logger.debug(f"DoVi extraction command: {' '.join(dovi)}")

            if not execute(dovi):
                return False

            if check_output(VPC.dovi_metadata_file):
                logger.info("DoVI metadata file is valid")
                VPC.HDR_type = "DoVi"
                return True
            
            else:

                logger.info("Dolby Vision not detected, attempting HDR10+ metadata extraction")

                #HDR10+
                HDR10plus_tool_path = os.path.join(VPC.tools_path, "hdr10plus_tool.exe")
                HDR10plus = [f"{HDR10plus_tool_path}", "extract", f"{VPC.source_path}", "-o", f"{VPC.HDR10_metadata_file}"]

                logger.debug(f"Using HDR10+ tool path: {HDR10plus_tool_path}")
                logger.debug(f"HDR10+ extraction command: {' '.join(HDR10plus)}")

                if not execute(HDR10plus):
                    return False

                if check_output(VPC.HDR10_metadata_file):
                    logger.info("HDR10+ metadata file is valid")
                    VPC.HDR_type = "HDR10"
                    return True
                else: 
                    logger.info("HDR10+ metadata file is not valid")
                    VPC.HDR_type = "None"
                    return False
                    
        else: # Metadata type has been previously cached
            logger.debug(f"Using cached metadata type: {VPC.HDR_type}")
            return True

    def video_HDR_extract(input_file, dovi_metadata_file, HDR10_metadata_file, relative_tools_path = "tools"):
        """
        Extracts HDR metadata from video files based on the previously detected metadata type.
        
        This function performs the actual extraction of HDR metadata after the type has been
        determined by get_video_metadata_type(). It handles both Dolby Vision RPU extraction
        and HDR10+ dynamic metadata extraction using specialized tools.
        
        Parameters:
            input_file (str): Path to the input video file containing HDR metadata
            dovi_metadata_file (str): Output path for extracted Dolby Vision metadata
            HDR10_metadata_file (str): Output path for extracted HDR10+ metadata
            relative_tools_path (str, optional): Directory containing extraction tools
            
        Returns:
            str | bool: Path to the extracted metadata file if successful,
                    False if extraction failed or unsupported metadata type
                    
        Note:
            This function relies on the global _dynamic_metadata_type variable being
            set by a previous call to get_video_metadata_type().
        """

        #TODO spetial crop for dovi
        global _dynamic_metadata_type

        logger.info(f"Starting HDR metadata extraction for: {input_file}")
        logger.debug(f"Metadata type: {_dynamic_metadata_type}")
        logger.debug(f"Output paths - DoVi: {dovi_metadata_file}, HDR10+: {HDR10_metadata_file}")

        if _dynamic_metadata_type == "DoVi":

            logger.info("Extracting Dolby Vision RPU metadata")
            dovi_tool_path = os.path.join(relative_tools_path, "dovi_tool.exe")
            dovi = [f"{dovi_tool_path}", "extract-rpu", "-i", f"{input_file}", "-o", f"{dovi_metadata_file}"]

            logger.debug(f"Using DoVi tool path: {dovi_tool_path}")
            logger.debug(f"DoVi extraction command: {' '.join(dovi)}")

            if not execute(dovi):
                return False
            if not check_output(dovi_metadata_file):
                return False
            return True
        
        elif _dynamic_metadata_type == "HDR10":

            logger.info("Extracting HDR10+ dynamic metadata")

            HDR10plus_tool_path = os.path.join(relative_tools_path, "hdr10plus_tool.exe")
            HDR10plus = [f"{HDR10plus_tool_path}", "extract", f"{input_file}", "-o", f"{HDR10_metadata_file}"]

            logger.debug(f"Using HDR10+ tool path: {HDR10plus_tool_path}")
            logger.debug(f"HDR10+ extraction command: {' '.join(HDR10plus)}")

            if not execute(HDR10plus):
                return False
            if not check_output(HDR10_metadata_file):
                return False
            return True
        
        else: 
            logger.error(f"Unsupported or uninitialized metadata type: {_dynamic_metadata_type}")
            logger.error("Ensure get_video_metadata_type() was called successfully before extraction")
            return False
        
    def video_HDR_inject(input_file, metadata_file, output_file, relative_tools_path = "tools"):
        """
        Injects HDR metadata into encoded video files based on the detected metadata type.
        
        This function takes an encoded video file and re-injects the previously extracted
        HDR metadata (either Dolby Vision RPU or HDR10+ dynamic metadata) to create
        the final HDR-capable output file.
        
        Parameters:
            input_file (str): Path to the encoded video file (usually HEVC format)
            metadata_file (str): Path to the extracted metadata file to inject
            output_file (str): Path for the output file with injected metadata
            relative_tools_path (str, optional): Directory containing injection tools
            
        Returns:
            bool: True if metadata injection succeeded and output is valid,
                False if injection failed or unsupported metadata type
                
        Note:
            This function relies on the global _dynamic_metadata_type variable being
            set by a previous call to get_video_metadata_type().
        """
            
        global _dynamic_metadata_type

        logger.info(f"Starting HDR metadata injection for: {input_file}")
        logger.info(f"Injecting {metadata_file} metadata into {output_file}")
        logger.debug(f"Metadata type: {_dynamic_metadata_type}")
        logger.debug(f"Tools path: {relative_tools_path}")
        
        if _dynamic_metadata_type == "HDR10":
            logger.info("Injecting HDR10+ dynamic metadata")
            HDR10plus_tool_path = os.path.join(relative_tools_path, "hdr10plus_tool.exe")
            command = [HDR10plus_tool_path, "inject", "-i", input_file, "-j", metadata_file, "-o", output_file]
            logger.debug(f"Using HDR10+ tool path: {HDR10plus_tool_path}")
            logger.debug(f"HDR10+ injection command: {' '.join(command)}")

        elif _dynamic_metadata_type == "DoVi":
            logger.info("Injecting Dolby Vision RPU metadata")
            dovi_tool_path = os.path.join(relative_tools_path, "dovi_tool.exe")
            command = [dovi_tool_path, "inject-rpu", "-i", input_file, "--rpu-in", metadata_file, "-o", output_file]

            logger.debug(f"Using DoVi tool path: {dovi_tool_path}")
            logger.debug(f"DoVi injection command: {' '.join(command)}")
        else:
            logger.error(f"Unsupported metadata format: {_dynamic_metadata_type}")
            logger.error("Supported formats are 'HDR10' and 'DoVi' only")
            logger.error("Ensure get_video_metadata_type() was called successfully before injection")
            return False
        
        if not execute(command):
                return False
        if not check_output(output_file):
            return False
        return True
             
    def video_encode_ffmpeg(input_file: str, profile: dict, output_file: str, crop: list, target_res: int, target_cq: float, 
    tool_path: str = r"ffmpeg") -> bool:
        
        """
        Encodes video files using FFmpeg with cropping, scaling, and quality control.
        
        This function performs video encoding using FFmpeg with support for cropping,
        resolution scaling, and constant quality encoding. It handles video filter
        chain construction and integrates with profile-based encoding settings.
        
        Parameters:
            input_file (str): Path to the input video file
            profile (dict): Encoding profile containing video settings under "video" key
            output_file (str): Path for the encoded output file
            crop (list): Crop parameters [top, bottom] in pixels
            target_res (int): Target horizontal resolution (width) in pixels
            target_cq (float): Constant quality value (lower = higher quality)
            tool_path (str, optional): Path to FFmpeg executable
            
        Returns:
            bool: True if encoding succeeded and output is valid, False otherwise
            
        Note:
            The function strips audio (-an) and subtitle (-sn) streams, focusing on
            video-only encoding for HDR workflows.
            
        Raises:
            ValueError: If crop parameters result in invalid dimensions
            FileNotFoundError: If FFmpeg executable is not found
        """

        logger.info(f"Starting FFmpeg video encoding: {input_file} -> {output_file}")
        logger.debug(f"Encoding parameters - Target resolution: {target_res}, CQ: {target_cq}, Crop: {crop}")
        
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


        logger.debug(f"Complete FFmpeg command: {' '.join(command)}")
        logger.info("Starting FFmpeg encoding process")
        if execute(command):
            if check_output(output_file):
                return True
            else:
                return False
        else:
            return False
        
        #Enable HDR only for h265
    
    
                
    def hevc_to_mkv(input_file, output_file_name):
        logger.info(f"Converting .hevc to .mkv")
        mp4_name = output_file_name + ".mp4"
        final_name = output_file_name + ".mkv"
        command = [
            'ffmpeg', '-y',  # Overwrite output file
            '-fflags', '+genpts',  # Generate presentation timestamps
            '-r', str(framerate),    # Set framerate
            '-i', input_file,       # Input HEVC file
            '-c:v', 'copy', 
            '-movflags', 'frag_keyframe+empty_moov',
            mp4_name
        ]

        logger.debug(f"Complete FFmpeg command: {' '.join(command)}")
        if not execute(command):
            return False
        if not check_output(mp4_name):
                return False
        
        logger.info(f"1st step success")
        
        command = [
            'ffmpeg', '-y',
            '-i', mp4_name,
            '-c:v', 'copy',
            final_name
        ]

        logger.debug(f"Complete FFmpeg command: {' '.join(command)}")
        if not execute(command):
            return False
        if not check_output(final_name):
            return False
        
        logger.info(f"2nd step success")
        return True
                
    if profile["HDR_enable"][1]:

        logger.info("HDR processing enabled - starting metadata workflow")

        # Define paths for metadata files

        # Detect and cache HDR metadata type
        if not get_video_metadata_type(input_file, dovi_metadata_file, HDR10_metadata_file):
            logger.error("HDR metadata type detection failed")
            return False
        
        # Cache framerate information for later use
        if not get_framerate(input_file):
            logger.error("Framerate detection failed")
            return False

        # Set up working file paths for HDR workflow
        dovi_metadata_file = os.path.join(workspace, name + "dovi_metadata.bin")
        HDR10_metadata_file = os.path.join(workspace, name + "HDR10_metadata.json")

        # Extract HDR metadata from source file
        if not video_HDR_extract(input_file, dovi_metadata_file, HDR10_metadata_file):
            logger.error("HDR metadata extraction failed")
            return False
        
        # Encode video to HEVC format
        ffmpeg_encode_name = os.path.join(workspace, name + "_reencode.hevc")
        if not video_encode_ffmpeg(input_file, profile, ffmpeg_encode_name, crop, target_res, target_cq):
            logger.error("FFmpeg encoding failed")
            return False

        HDR_inject_name = os.path.join(workspace, name + "_HDR_inject.hevc")
        if _dynamic_metadata_type == "HDR10": metadata_name = HDR10_metadata_file
        elif _dynamic_metadata_type == "DoVi": metadata_name = dovi_metadata_file
        else: return False
        if not video_HDR_inject(ffmpeg_encode_name, metadata_name, HDR_inject_name):
            logger.error("HDR metadata injection failed")
            return False

        # Convert final HEVC to MKV container
        final_name = os.path.join(workspace, name)
        if not hevc_to_mkv(HDR_inject_name, final_name):
            logger.error("HEVC to MKV conversion failed")
            return False

    else:

        # Standard encoding without HDR processing
        logger.info("Standard encoding mode (no HDR processing)")
        final_name = os.path.join(workspace, name + ".mkv")
        if not video_encode_ffmpeg(input_file, profile, final_name, crop, target_res, target_cq):
            logger.error("Standard FFmpeg encoding failed")
            return False
    
    logger.info(f"FFmpeg encoding workflow completed successfully: {final_name}")
    return True


if __name__ == '__main__':
    #workspace = r"D:\Files\Projects\AutoCompression\Tests\workspaces\compressor2\ffmpeg"
    #input_file = r"D:\Files\Projects\AutoCompression\Tests\HDR10_plus.mkv"
    #profile_path = r"D:\Files\Projects\AutoCompression\Profiles\h265_slow_nvenc.yaml"

    workspace = r"D:\Files\Projects\AutoCompression\Tests\workspaces\HDR10_H265"
    input_file = r"D:\Files\Projects\AutoCompression\Tests\HDR10_plus.mkv"
    profile_path = r"D:\Files\Projects\AutoCompression\Profiles\h265_slow_nvenc.yaml"

    if not os.path.exists(workspace):
            # Create the directory
            os.makedirs(workspace)
            print(f'Directory "{workspace}" created.')

    log_path = os.path.join(workspace, "app.log")
    logger = logger_setup.primary_logger(log_level=logging.INFO, log_file=log_path)
    log_path = os.path.join(workspace, "stream.log")
    stream_logger = logger_setup.file_logger(log_path, log_level=logging.DEBUG)


    profile, profile_settings = readers.readProfile(profile_path)
    compress(input_file, profile, "H265_HDR10", workspace, [10, 10], 1920, 30, False, 2, 5, False)
