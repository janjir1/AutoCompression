from encodings.punycode import T
import shutil
import subprocess, os, json
import logging

from sympy import false
import AVTest
from threading import Thread
import logger_setup
from fractions import Fraction
from VideoClass import VideoProcessingConfig

# Retrieve the logger once at the module level
logger = logging.getLogger("AppLogger")
stream_logger = logging.getLogger("FileLogger")


def compress(VPC: VideoProcessingConfig) -> bool:
    """
    Compress a video file using the specified profile and encoding function.

    This function orchestrates the complete video compression workflow, including
    temporal cropping (if needed) and the main compression process using the
    configured encoding function.

    Args:
        VPC (VideoProcessingConfig): Video processing configuration object containing
                                   all necessary parameters for compression

    Returns:
        bool: True if compression succeeded and output file is valid, False otherwise
    """
    logger.info(f"[compress] Starting compression workflow for file: {VPC.orig_file_path}")
    logger.debug(f"[compress] Compression parameters - Profile: {VPC.profile['function'][1]}, "
                f"Target resolution: {VPC.output_res}, CQ: {VPC.output_cq}, Crop: {VPC.crop}")

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
    "HandbrakeAV1": video_HandbrakeAV1,
    "ffmpeg"      : video_ffmpeg
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

def execute(command: list) -> bool:
    """
    Execute a command using subprocess with real-time logging of stdout and stderr.

    This function runs external commands (like FFmpeg, HandBrake, etc.) and captures
    their output streams in separate threads, logging everything to dedicated file loggers.

    Args:
        command (list): Command and arguments to execute as a list

    Returns:
        bool: True if process finished successfully (exit code 0), False otherwise
    """
    logger.debug(f"[execute] Starting command execution")
    logger.debug(f"[execute] Command: {' '.join(command)}")
    
    # Start the process with UTF-8 encoding
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=False  # Handle decoding manually
    )

    # Create a dedicated file logger for stream logging
    stream_logger = logging.getLogger("FileLogger")
    for _ in range(6):
        stream_logger.debug(f"----------------------------------------------------------------------------------------------")
    stream_logger.debug(f"[execute] Command: {command}")


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
                    file_log.debug(f"[{stream_type}] {decoded_line}")
                elif stream_type == "STDERR":
                    file_log.debug(f"[{stream_type}] {decoded_line}")
                    
                last_line = stripped_line
        
        logger.debug(f"[execute.log_stream] Finished {stream_type} logging thread")

    # Start threads for stdout and stderr
    logger.debug(f"[execute] Starting logging threads for stdout and stderr")
    stdout_thread = Thread(target=log_stream, args=(process.stdout, "STDOUT", stream_logger))
    stderr_thread = Thread(target=log_stream, args=(process.stderr, "STDERR", stream_logger))
    
    stdout_thread.start()
    stderr_thread.start()

    # Wait for completion
    logger.debug(f"[execute] Waiting for process completion")
    process.wait()
    stdout_thread.join()
    stderr_thread.join()

    # Check final status
    if process.returncode != 0:
        logger.error(f"[execute] Process failed with exit code: {process.returncode}")
        return False
    
    logger.debug(f"[execute] Command execution finished successfully")
    return True

def check_output(file_path: str, size_limit=2048) -> bool:
    """
    Validate that an output file exists and meets minimum size requirements.

    Args:
        file_path (str): Path to the output file to validate
        size_limit (int, optional): Minimum acceptable file size in bytes. Defaults to 2048 bytes

    Returns:
        bool: True if the file exists and meets the size requirement, False otherwise
    """
    logger.debug(f"[check_output] Validating output file: {file_path}")
    logger.debug(f"[check_output] Size limit: {size_limit} bytes")
    
    try:
        if os.path.isfile(file_path):  # Ensure the path points to a file
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


def temporal_crop(VPC: VideoProcessingConfig, NoFS_offset: int = 3) -> bool:

    """
    Perform temporal cropping (time-based cutting) of video files using FFmpeg.

    This function extracts a specific time segment from a video file without
    re-encoding, using stream copying for maximum speed and quality preservation.

    Args:
        VPC (VideoProcessingConfig): Video processing configuration containing
                                   source/target paths, start time, and duration

    Returns:
        bool: True if temporal cropping succeeded, False otherwise

    Note:
        Uses stream copying (-c:v copy -c:a copy) to avoid quality loss
        and significantly reduce processing time compared to re-encoding.
    """

    logger.debug(f"[temporal_crop] Starting temporal crop operation")
    logger.debug(f"[temporal_crop] Source: {VPC.source_path} -> Target: {VPC.target_path}")
    logger.debug(f"[temporal_crop] Crop parameters - Start: {VPC.start}s, Duration: {VPC.duration}s")

    if VPC.profile["FS_enable"][1] and VPC.FS_support:
        command = [
            "ffmpeg",
            "-y",  # Overwrite output files
            "-ss", str(VPC.start),  # Start time
            "-i", VPC.source_path,  # Input file
            "-t", str(VPC.duration),  # Duration
        ]
    else:
        command = [
            "ffmpeg",
            "-y",  # Overwrite output files
            "-fflags", "+genpts",                              # Generate missing PTS
            "-copyts",                                         # Preserve input timestamps
            "-avoid_negative_ts", "make_zero",                 # Shift any negative DTS to zero
            "-i", VPC.source_path,  # Input file
            "-ss", str(VPC.start),  # Start time
            "-t", str(VPC.duration + NoFS_offset),  # Duration
        ]

    command = command + [   
                            "-c:v", "copy",  # Copy video stream without re-encoding
                            "-an",  # Copy audio stream without re-encoding
                            "-copy_unknown",  # Copy unknown streams
                            VPC.target_path  # Output file
                        ]

    logger.debug(f"[temporal_crop] FFmpeg command: {' '.join(command)}")

    if execute(command):
        if check_output(VPC.target_path):
            return True
        else:
            logger.error(f"[temporal_crop] Output file validation failed")
            if NoFS_offset >= 9:
                return False
            logger.debug(f"[temporal_crop] Atemting to create longer file")
            return temporal_crop(VPC, NoFS_offset + 1)
            
    else:
        logger.error(f"[temporal_crop] FFmpeg execution failed")
        return False

def video_HandbrakeAV1(VPC: VideoProcessingConfig) -> bool:

    """
    Encode video using HandBrakeCLI with AV1 codec and specified quality settings.

    This function constructs and executes HandBrakeCLI commands for AV1 encoding
    with cropping, resolution scaling, and quality control parameters.

    Args:
        VPC (VideoProcessingConfig): Video processing configuration containing
                                   encoding parameters, paths, and profile settings

    Returns:
        bool: True if encoding succeeded and output is valid, False otherwise
    """
    logger.debug(f"[video_HandbrakeAV1] Starting HandBrake AV1 encoding")
    logger.debug(f"[video_HandbrakeAV1] Source: {VPC.source_path} -> Output: {VPC.output_file_path}")
    logger.debug(f"[video_HandbrakeAV1] Encoding parameters - Resolution: {VPC.output_res}, CQ: {VPC.output_cq}, Crop: {VPC.crop}")

    # Base command with input/output settings and basic encoding options
    command = [
        os.path.join(VPC.tools_path, "HandBrakeCLI.exe"),
        '-i', VPC.source_path,  # Input file
        '-o', VPC.output_file_path,  # Output file
        '-q', str(VPC.output_cq),  # Quality setting
        '--crop', f'0:{str(VPC.crop[0])}:0:{str(VPC.crop[1])}',  # Crop settings
        '--width', str(VPC.output_res),  # Target width
        '--non-anamorphic',  # Disable anamorphic encoding
        '-a', 'none',  # No audio encoding
        '-s', 'none'   # No subtitle encoding
    ]

    # Append video-specific profile settings
    command = command + VPC.profile["video"]

    logger.debug(f"[video_HandbrakeAV1] Complete HandBrake command: {' '.join(command)}")

    if execute(command):
        if check_output(VPC.output_file_path):
            logger.debug(f"HandBrake AV1 encoding completed successfully: {VPC.output_file_path}")
            return True
        else:
            logger.error(f"[video_HandbrakeAV1] Output file validation failed")
            return False
    else:
        logger.error(f"[video_HandbrakeAV1] HandBrake execution failed")
        return False
    
def video_ffmpeg(VPC: VideoProcessingConfig) -> bool:
    """
    Main FFmpeg-based video encoding function with HDR metadata handling.

    This function orchestrates the complete FFmpeg encoding workflow including
    HDR metadata detection, extraction, encoding, and re-injection for formats
    like Dolby Vision and HDR10+.

    Args:
        VPC (VideoProcessingConfig): Video processing configuration containing
                                   all encoding parameters and HDR settings

    Returns:
        bool: True if encoding completed successfully, False otherwise
    """
    logger.debug(f"[video_ffmpeg] Starting FFmpeg encoding workflow")
    logger.debug(f"[video_ffmpeg] HDR processing enabled: {VPC.profile['HDR_enable'][1]}")

    def get_video_metadata_type(VPC: VideoProcessingConfig):

        """
        Detect and cache the HDR metadata type present in a video file.

        This function performs a sequential check for Dolby Vision (DoVi) and HDR10+ metadata
        by attempting to extract metadata using specialized tools. The detected metadata type
        is cached to avoid redundant detection operations.

        Args:
            VPC (VideoProcessingConfig): Video processing configuration

        Returns:
            bool: True if metadata type was successfully detected or already cached,
                 False if no supported HDR metadata was found\
            
        Note:
            DoVi detection takes priority over HDR10+ detection.
        """
        if VPC.HDR_type == "uninit":
            logger.debug(f"[video_ffmpeg.get_video_metadata_type] Starting HDR metadata type detection for: {VPC.source_path}")
            logger.debug(f"[video_ffmpeg.get_video_metadata_type] Output paths - DoVi: {VPC.dovi_metadata_file}, HDR10+: {VPC.HDR10_metadata_file}")
            logger.debug("[video_ffmpeg.get_video_metadata_type] Metadata type not cached, performing detection")

            # Try Dolby Vision first
            logger.debug("[video_ffmpeg.get_video_metadata_type] Attempting Dolby Vision metadata extraction")
            dovi_tool_path = "dovi_tool"
            dovi = [f"{dovi_tool_path}", "extract-rpu", "-i", f"{VPC.source_path}", "-o", f"{VPC.dovi_metadata_file}"]
            logger.debug(f"[video_ffmpeg.get_video_metadata_type] DoVi extraction command: {' '.join(dovi)}")

            if not execute(dovi):
                logger.warning("[video_ffmpeg.get_video_metadata_type] DoVi tool execution failed")
                return True

            if check_output(VPC.dovi_metadata_file):
                logger.debug("[video_ffmpeg.get_video_metadata_type] DoVi metadata file is valid")
                VPC.HDR_type = "DoVi"
                return True
            
            else:
                # Try HDR10+ as fallback
                logger.debug("[video_ffmpeg.get_video_metadata_type] Dolby Vision not detected, attempting HDR10+ metadata extraction")
                HDR10plus_tool_path = "hdr10plus_tool"
                HDR10plus = [f"{HDR10plus_tool_path}", "extract", f"{VPC.source_path}", "-o", f"{VPC.HDR10_metadata_file}"]
                logger.debug(f"[video_ffmpeg.get_video_metadata_type] HDR10+ extraction command: {' '.join(HDR10plus)}")

                if not execute(HDR10plus):
                    logger.warning("[video_ffmpeg.get_video_metadata_type] HDR10+ tool execution failed")

                if check_output(VPC.HDR10_metadata_file):
                    logger.debug("HDR10+ metadata file is valid")
                    VPC.HDR_type = "HDR10"
                    return True
                else: 
                    logger.debug("HDR10+ metadata file is not valid")
                    VPC.HDR_type = "None"
                    return True
        else:  # Metadata type has been previously cached
            logger.debug(f"[video_ffmpeg.get_video_metadata_type] Using cached metadata type: {VPC.HDR_type}")
            return True

    def video_HDR_extract(VPC: VideoProcessingConfig):
        """
        Extract HDR metadata from video files based on the previously detected metadata type.

        This function performs the actual extraction of HDR metadata after the type has been
        determined by get_video_metadata_type(). It handles both Dolby Vision RPU extraction
        and HDR10+ dynamic metadata extraction using specialized tools.

        Args:
            VPC (VideoProcessingConfig): Video processing configuration

        Returns:
            bool: True if extraction succeeded, False if extraction failed or unsupported metadata type

        """

        #TODO spatial crop for dovi

        logger.debug(f"[video_ffmpeg.video_HDR_extract] Starting HDR metadata extraction for: {VPC.source_path}")
        logger.debug(f"[video_ffmpeg.video_HDR_extract] Metadata type: {VPC.HDR_type}")
        logger.debug(f"[video_ffmpeg.video_HDR_extract] Output paths - DoVi: {VPC.dovi_metadata_file}, HDR10+: {VPC.HDR10_metadata_file}")

        if VPC.HDR_type == "uninit":
            if not get_video_metadata_type(VPC):
                logger.error("[video_ffmpeg.video_HDR_extract] Unable to get video metadata type")
                return False

        if VPC.HDR_type == "DoVi":
            logger.debug("[video_ffmpeg.video_HDR_extract] Extracting Dolby Vision RPU metadata")
            dovi_tool_path = "dovi_tool"
            dovi = [f"{dovi_tool_path}", "extract-rpu", "-i", f"{VPC.source_path}", "-o", f"{VPC.dovi_metadata_file}"]
            logger.debug(f"[video_ffmpeg.video_HDR_extract] DoVi extraction command: {' '.join(dovi)}")

            if not execute(dovi):
                logger.error("[video_ffmpeg.video_HDR_extract] DoVi extraction failed")
                return False
            if not check_output(VPC.dovi_metadata_file):
                logger.error("[video_ffmpeg.video_HDR_extract] DoVi metadata file validation failed")
                return False
            return True
        
        elif VPC.HDR_type == "HDR10":
            logger.debug("[video_ffmpeg.video_HDR_extract] Extracting HDR10+ dynamic metadata")
            HDR10plus_tool_path = "hdr10plus_tool"
            HDR10plus = [f"{HDR10plus_tool_path}", "extract", f"{VPC.source_path}", "-o", f"{VPC.HDR10_metadata_file}"]
            logger.debug(f"[video_ffmpeg.video_HDR_extract] HDR10+ extraction command: {' '.join(HDR10plus)}")

            if not execute(HDR10plus):
                logger.error("[video_ffmpeg.video_HDR_extract] HDR10+ extraction failed")
                return False
            if not check_output(VPC.HDR10_metadata_file):
                logger.error("[video_ffmpeg.video_HDR_extract] HDR10+ metadata file validation failed")
                return False

            logger.debug("[video_ffmpeg.video_HDR_extract] HDR10+ metadata extraction completed successfully")
            return True
        
        elif VPC.HDR_type == "None":
            logger.debug("[video_ffmpeg.video_HDR_extract] File doesn't contain HDR metadata")
            return True
        else:
            logger.error(f"[video_ffmpeg.video_HDR_extract] Unsupported or uninitialized metadata type: {VPC.HDR_type}")
            logger.error("[video_ffmpeg.video_HDR_extract] Ensure get_video_metadata_type() was called successfully before extraction")
            return False
        
    def video_HDR_inject(VPC: VideoProcessingConfig):
        """
        Inject HDR metadata into encoded video files based on the detected metadata type.

        This function takes an encoded video file and re-injects the previously extracted
        HDR metadata (either Dolby Vision RPU or HDR10+ dynamic metadata) to create
        the final HDR-capable output file.

        Args:
            VPC (VideoProcessingConfig): Video processing configuration

        Returns:
            bool: True if metadata injection succeeded and output is valid,
                 False if injection failed or unsupported metadata type

        """
            

        logger.debug(f"[video_ffmpeg.video_HDR_inject] Starting HDR metadata injection")
        logger.debug(f"[video_ffmpeg.video_HDR_inject] Source: {VPC.source_path} -> Target: {VPC.target_path}")
        logger.debug(f"[video_ffmpeg.video_HDR_inject] Metadata type: {VPC.HDR_type}")
        
        if VPC.HDR_type == "HDR10":
            logger.debug("[video_ffmpeg.video_HDR_inject] Injecting HDR10+ dynamic metadata")
            HDR10plus_tool_path = "hdr10plus_tool"
            command = [HDR10plus_tool_path, "inject", "-i", VPC.source_path, "-j", VPC.HDR10_metadata_file, "-o", VPC.target_path]
            logger.debug(f"[video_ffmpeg.video_HDR_inject] HDR10+ injection command: {' '.join(command)}")

        elif VPC.HDR_type == "DoVi":
            logger.debug("[video_ffmpeg.video_HDR_inject] Injecting Dolby Vision RPU metadata")
            dovi_tool_path = "dovi_tool"
            command = [dovi_tool_path, "inject-rpu", "-i", VPC.source_path, "--rpu-in", VPC.dovi_metadata_file, "-o", VPC.target_path]
            logger.debug(f"[video_ffmpeg.video_HDR_inject] DoVi injection command: {' '.join(command)}")

        elif VPC.HDR_type == "None":
            logger.debug("[video_ffmpeg.video_HDR_inject] File is not HDR, skipping metadata injection")
            return True
        
        else:
            logger.error(f"[video_ffmpeg.video_HDR_inject] Unsupported metadata format: {VPC.HDR_type}")
            logger.error("[video_ffmpeg.video_HDR_inject] Supported formats are 'HDR10' and 'DoVi' only")
            logger.error("[video_ffmpeg.video_HDR_inject] Ensure get_video_metadata_type() was called successfully before injection")
            return False
        
        if not execute(command):
            logger.error("[video_ffmpeg.video_HDR_inject] Metadata injection command failed")
            return False

        if not check_output(VPC.target_path):
            logger.error("[video_ffmpeg.video_HDR_inject] Injected file validation failed")
            return False
        return True
             
    def video_encode_ffmpeg(VPC: VideoProcessingConfig) -> bool:
        
        """
        Encode video files using FFmpeg with cropping, scaling, and quality control.

        This function performs video encoding using FFmpeg with support for cropping,
        resolution scaling, and constant quality encoding. It handles video filter
        chain construction and integrates with profile-based encoding settings.

        Args:
            VPC (VideoProcessingConfig): Video processing configuration

        Returns:
            bool: True if encoding succeeded and output is valid, False otherwise
            
        Note:
            The function strips audio (-an) and subtitle (-sn) streams, focusing on
            video-only encoding for HDR workflows.
            
        Raises:
            ValueError: If crop parameters result in invalid dimensions
            FileNotFoundError: If FFmpeg executable is not found
        """
        logger.debug(f"[video_ffmpeg.video_encode_ffmpeg] Starting FFmpeg video encoding")
        logger.debug(f"[video_ffmpeg.video_encode_ffmpeg] Source: {VPC.source_path} -> Target: {VPC.target_path}")
        logger.debug(f"[video_ffmpeg.video_encode_ffmpeg] Encoding parameters - Target resolution: {VPC.output_res}, CQ: {VPC.output_cq}, Crop: {VPC.crop}")

        def vfCropComandGenerator(VPC: VideoProcessingConfig) -> str:
            target_v_res = VPC.orig_v_res - VPC.crop[0] - VPC.crop[1]
            command = f"crop={VPC.orig_h_res}:{target_v_res}:0:{VPC.crop[0]},scale={VPC.output_res}:-2:sws_flags=neighbor"
            logger.debug(f"[video_ffmpeg.video_encode_ffmpeg.vfCropComandGenerator] Generated filter: {command}")
            return command

        command = [
            "ffmpeg",  # Command to run FFmpeg
            "-i", VPC.source_path,  # Input file
            "-an",  # No audio
            "-sn",  # No subtitles
        ]

        # Include video profile and resolution filter
        resolution_filter = vfCropComandGenerator(VPC)
        video_profile_modified = VPC.profile["video"].copy()

        try:
            index = video_profile_modified.index("-vf")
            video_profile_modified[index+1] = video_profile_modified[index+1] + "," + resolution_filter
        except ValueError:
            video_profile_modified.append("-vf")
            video_profile_modified.append(resolution_filter)
        
        command = command + video_profile_modified

        command_append = [
            "-copy_unknown",  # Copy unknown streams
            "-map_metadata", "0",  # Copy metadata from input
            '-cq', str(VPC.output_cq),  # Constant Quality mode
            '-y',  # Overwrite output file
            VPC.target_path  # Output file
        ]

        command = command + command_append

        logger.debug(f"[video_ffmpeg.video_encode_ffmpeg] Complete FFmpeg command: {' '.join(command)}")
        logger.debug("[video_ffmpeg.video_encode_ffmpeg] Starting FFmpeg encoding process")

        if execute(command):
            if check_output(VPC.target_path):
                logger.debug("[video_ffmpeg.video_encode_ffmpeg] FFmpeg encoding completed successfully")
                return True
            else:
                logger.error("[video_ffmpeg.video_encode_ffmpeg] Output file validation failed")
                return False
        else:
            return False
        
        #Enable HDR only for h265
             
    def hevc_to_mkv(VPC: VideoProcessingConfig):
        """
        Convert HEVC elementary stream to MKV container format.

        This function performs a two-step conversion process to properly containerize
        HEVC streams with correct timestamps and formatting.

        Args:
            VPC (VideoProcessingConfig): Video processing configuration

        Returns:
            bool: True if conversion succeeded, False otherwise
        """
        logger.debug(f"[video_ffmpeg.hevc_to_mkv] Converting .hevc to .mkv")
        logger.debug(f"[video_ffmpeg.hevc_to_mkv] Source: {VPC.source_path} -> Target: {VPC.target_path}")
        
        mp4_name = VPC.target_path[:-4] + ".mp4"
        logger.debug(f"[video_ffmpeg.hevc_to_mkv] Intermediate MP4 file: {mp4_name}")

        # Step 1: Convert HEVC to MP4 with proper timestamps
        command = [
            'ffmpeg', '-y',  # Overwrite output file
            '-fflags', '+genpts',  # Generate presentation timestamps
            '-r', str(VPC.orig_framerate),  # Set framerate
            '-i', VPC.source_path,  # Input HEVC file
            '-c:v', 'copy',  # Copy video stream
            '-movflags', 'frag_keyframe+empty_moov',  # MP4 optimization flags
            mp4_name
        ]

        logger.debug(f"[video_ffmpeg.hevc_to_mkv] Step 1 FFmpeg command: {' '.join(command)}")

        if not execute(command):
            logger.error("[video_ffmpeg.hevc_to_mkv] Step 1 (HEVC to MP4) failed")
            return False
        if not check_output(mp4_name):
            logger.error("[video_ffmpeg.hevc_to_mkv] Step 1 output validation failed")
            return False

        logger.debug("[video_ffmpeg.hevc_to_mkv] Step 1 (HEVC to MP4) completed successfully")
        

        # Step 2: Convert MP4 to MKV
        command = [
            'ffmpeg', '-y',  # Overwrite output file
            '-i', mp4_name,  # Input MP4 file
            '-c:v', 'copy',  # Copy video stream
            VPC.target_path  # Output MKV file
        ]

        logger.debug(f"[video_ffmpeg.hevc_to_mkv] Step 2 FFmpeg command: {' '.join(command)}")

        if not execute(command):
            logger.error("[video_ffmpeg.hevc_to_mkv] Step 2 (MP4 to MKV) failed")
            return False
        if not check_output(VPC.target_path):
            logger.error("[video_ffmpeg.hevc_to_mkv] Step 2 output validation failed")
            return False

        logger.debug("[video_ffmpeg.hevc_to_mkv] Step 2 (MP4 to MKV) completed successfully")
        logger.debug("[video_ffmpeg.hevc_to_mkv] HEVC to MKV conversion completed successfully")
        delete_file(VPC, mp4_name)
        return True
                
    if VPC.profile["HDR_enable"][1]:
        logger.debug("[video_ffmpeg] HDR processing enabled - starting metadata workflow")

        out = video_HDR_extract(VPC)
        # Extract HDR metadata from source file
        if out and (VPC.HDR_type != "None"):
            
            # Encode video to HEVC format
            VPC.setTargetPath(os.path.join(VPC.workspace, VPC.output_file_name + "_reencode.hevc"))
            if not video_encode_ffmpeg(VPC):
                logger.error("[video_ffmpeg] FFmpeg encoding failed")
                return False
            delete_file(VPC, VPC.source_path)

            # Inject HDR metadata into encoded file
            VPC.setSourcePath(VPC.target_path)
            VPC.setTargetPath(os.path.join(VPC.workspace, VPC.output_file_name + "_HDR_inject.hevc"))
            if not video_HDR_inject(VPC):
                logger.error("[video_ffmpeg] HDR metadata injection failed")
                return False

            delete_file(VPC, VPC.source_path)
            VPC.setSourcePath(VPC.target_path)

            # Convert final HEVC to MKV container
            VPC.setTargetPath(VPC.output_file_path)
            if not hevc_to_mkv(VPC):
                logger.error("[video_ffmpeg] HEVC to MKV conversion failed")
                return False
            delete_file(VPC, VPC.source_path)
            
        else: 
            logger.error("[video_ffmpeg] HDR metadata extraction failed")
            VPC.DisableParentHDR()
            logger.debug("[video_ffmpeg] Standard encoding mode (no HDR processing)")
            VPC.setTargetPath(VPC.output_file_path)
            if not video_encode_ffmpeg(VPC):
                logger.error("[video_ffmpeg] Standard FFmpeg encoding failed")
                return False
            delete_file(VPC, VPC.source_path)

    else:

        # Standard encoding without HDR processing
        logger.debug("[video_ffmpeg] Standard encoding mode (no HDR processing)")
        VPC.setTargetPath(VPC.output_file_path)
        if not video_encode_ffmpeg(VPC):
            logger.error("[video_ffmpeg] Standard FFmpeg encoding failed")
            return False
        delete_file(VPC, VPC.source_path)

    logger.debug("[video_ffmpeg] FFmpeg encoding workflow completed successfully")
    return True

#TODO
#new ffmpeg + svt-av1-hdr function here
#basic commands:
#ffmpeg -i /input/DoVi.mkv -pix_fmt yuv420p10le -f rawvideo - | SvtAv1EncApp -i /workspace/input.yuv -w 3840 -h 2160 -b /workspace/video.ivf --dolby-vision-rpu /workspace/dovi_rpu.bin
#ffmpeg -i video.ivf -c:v copy -an video.mkv

def delete_file(VPC, file: str) -> None:
    if VPC.test_settings["Enable_delete"]["Enabled"]:
        logger.debug(f"[delete_file] Deleting: {file}")
        
        if os.path.isfile(file):
            os.remove(file)
            logger.debug(f"[delete_file] Deleted file: {file}")
        elif os.path.isdir(file):
            shutil.rmtree(file)
            logger.debug(f"[delete_file] Deleted directory: {file}")
        else:
            logger.warning(f"[delete_file] Path does not exist: {file}")

if __name__ == '__main__':

    workspace = r"D:\Files\Projects\AutoCompression\Tests\workspaces\DoVi_AV1"
    #input_file = r"D:\Files\Projects\AutoCompression\Tests\HDR10_plus.mkv"
    input_file = r"D:\Files\Projects\AutoCompression\Tests\DoVi.mkv"
    profile_path = r"D:\Files\Projects\AutoCompression\Profiles\h265_slow_nvenc.yaml"
    settings_path = r"D:\Files\Projects\AutoCompression\Profiles\Test_settings.yaml"
    tools_path  = r"D:\Files\Projects\AutoCompression\tools"

    if not os.path.exists(workspace):
        os.makedirs(workspace)

    log_path = os.path.join(workspace, "app.log")
    logger = logger_setup.primary_logger(log_level=logging.INFO, log_file=log_path)
    log_path = os.path.join(workspace, "stream.log")
    stream_logger = logger_setup.file_logger(log_path, log_level=logging.DEBUG)

    VPC = VideoProcessingConfig(input_file, "DoVi", workspace)
    VPC.readProfiles(profile_path, settings_path, tools_path)
    VPC.analyzeOriginal()

    VPC.setDuration(1)
    VPC.setStart(2)
    VPC.setCrop([10, 10])
    VPC.setOutputRes(720)
    VPC.setOutputCQ(50)

    compress(VPC)
