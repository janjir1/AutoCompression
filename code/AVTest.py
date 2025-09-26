import subprocess
import re, os, sys
import json
from multiprocessing import Pool, Manager
import time
import math
import numpy as np
import soundfile as sf
from PIL import Image
import logging
import compressor2
import traceback
from VideoClass import VideoProcessingConfig
import copy
import ast
from typing import Union

#TODO: add cleanup

# Retrieve the logger once at the module level
logger = logging.getLogger("AppLogger")

# region singlethread VQA
#Meassure video using FasterVQA, number of runs for averaging
def getVQA(video_path: str, num_of_runs: int = 4) -> float:
    """
    Computes the video quality assessment (VQA) score for a given video.

    Parameters:
    - video_path (str): Full path to the video file.
    - num_of_runs (int): Number of times to run the VQA assessment (default: 4).

    Returns:
    - float: Average quality score of the video.
    """

    quality_score = []
    
    for _ in range(num_of_runs):
        command = [sys.executable, "./FastVQA-and-FasterVQA/vqa.py", "-v", video_path]
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

        # Capture the output in real-time
        output_lines = []
        try:
            for line in process.stdout:
                output_lines.append(line.strip())

            # Wait for the process to complete and get the exit code
            process.wait()
            
            # Check for errors
            if process.returncode != 0:
                logger.error(f"Script exited with error code {process.returncode}")
                error_output = process.stderr.read()
                logger.error("Error Output:", error_output)

        except Exception as e:
            logger.error(f"An error occurred: {str(e)}")

        #Parse the output
        for line in output_lines:
            if "The quality score of the video" in line:
                match = re.search(r'\b0\.\d+', line)
                if match:
                    quality_score.append(float(match.group()))

    #get average
    average_quality = sum(quality_score) / len(quality_score)

    return average_quality

# region getRes_parallel
def getRes_parallel(VPC: VideoProcessingConfig) -> bool: #enter full path to video
    """
    Determines the optimal resolution for video encoding based on VQA scores.

    Args:
            VPC (VideoProcessingConfig): Video processing configuration

        Returns:
            bool: True if conversion succeeded, False otherwise
    """
    res_VPC = copy.deepcopy(VPC)
    name = VPC.output_file_name + "_res"

    res_VPC.setWorkspace(os.path.join(VPC.workspace, name))

    video_paths = _prepareRes_test(res_VPC)

    """
    video_paths = list()
    files = [f for f in os.listdir(video_folder) 
         if os.path.isfile(os.path.join(video_folder, f)) and f.lower().endswith('.mkv')]

    for file in files:
        for _ in range(num_of_VQA_runs):
            video_paths.append(os.path.join(video_folder, file))
    """
     # Manager for sharing dictionary and lock between processes
    with Manager() as manager:
        shared_dict = manager.dict()  # Shared dictionary to store outputs
        lock = manager.Lock()  # Manager's Lock to prevent overwriting

        with Pool(processes=VPC.test_settings["Resolution_calculation"]["Threads"]) as pool:
                pool.starmap(_run_VQA_process, [(video_path, shared_dict, lock) for video_path in video_paths])

        result_dict = dict(shared_dict)
    
    #make output dict more readable and average the VQA values for each res
    if len(result_dict) < 2:
        logger.error("result us empty")
        return False
    
    sorted_dict = dict()
    for key in result_dict.keys():
        matches = re.findall(r"\d*", key)
        sample = matches[0]
        res = matches[2]

        VQA_result = 0
        for value in result_dict[key]:
            VQA_result = VQA_result + value
        VQA_result = VQA_result/len(result_dict[key])

        if sample not in sorted_dict:
            sorted_dict[sample] = dict()
            sorted_dict[sample][res] = VQA_result
        else:
            sorted_dict[sample][res] = VQA_result
    logger.debug("Processed VQA data:")
    logger.debug(sorted_dict)
    #determine regression slope for each scene
    regression_slope = list()
    logger.debug("regression slope:")
    for scene in sorted_dict.keys():
        res = sorted_dict[scene].keys()
        res_min = int(sorted(res)[1])
        res_max = int(sorted(res)[0])
        VQA_res_min = float(sorted_dict[scene][str(res_min)])
        VQA_res_max = float(sorted_dict[scene][str(res_max)])
        slope = (VQA_res_max-VQA_res_min)/(res_max-res_min)
        regression_slope.append(slope)
        logger.debug(f"{scene}: {slope}")

    logger.debug("average:")
    logger.debug(regression_slope)

    #remove worst scenes and make average
    regression_slope = sorted(regression_slope, reverse=True)
    to_keep = math.ceil(len(regression_slope)*VPC.test_settings["Resolution_calculation"]["keep_best_slopes"])
    regression_slope = regression_slope[:to_keep]
    
    average_slope = 0
    for value in regression_slope:
        average_slope = average_slope + value
    average_slope = average_slope/len(regression_slope)

    logger.debug(f"average slope is: {average_slope}")

    #Assign res to average slope
    target_res = 854
    decode_table = ast.literal_eval(VPC.getProfileValue(VPC.profile["test_settings"], "res_decode"))

    for key in decode_table:
        if average_slope >= decode_table[key]:
            if key > target_res:
                target_res = key

    if target_res > VPC.orig_h_res:
        target_res = VPC.orig_h_res

    logger.info(f"Original resolution: {VPC.orig_h_res}, Target resolution: {target_res}")
    VPC.setOutputRes(target_res)
    return True

def _run_VQA_process(video_path: str, shared_dict: dict, lock) -> int:

    """
    Runs the VQA process on a given video file and stores the results in a shared dictionary.

    Parameters:
    - video_path (str): Full path to the video file.
    - shared_dict (dict): A multiprocessing manager dictionary to store results.
    - lock: A multiprocessing lock for thread-safe operations.

    Returns:
    - int: Return code of the subprocess execution (0 if successful, non-zero if an error occurs).
    """

    # Extract video ID from the filename
    match = re.search(r'\d*(?=_cq\d.mkv)', video_path)
    video_id = match.group() if match else video_path

    # Extract filename without extension
    name = os.path.basename(video_path)[:-4]

    # Construct the command for VQA execution
    command = [sys.executable, "./FastVQA-and-FasterVQA/vqa.py", "-v", video_path]
    logger.info(f"Starting VQA calculation on file {name} (Video ID: {video_id}) with PID {os.getpid()}")

    try:
        # Run the command with a timeout of 20 minutes (1200 seconds)
        result = subprocess.run(command, capture_output=True, text=True, shell=False, timeout=1200)
    except subprocess.TimeoutExpired:
        logger.error(f"Timeout expired for file {name} after 20 minutes.")
        return 1
    except Exception as e:
        logger.exception(f"An error occurred while running VQA on {name}: {e}")
        return 1

    # Handle subprocess errors
    if result.returncode != 0:
        logger.error(f"Script for {name} exited with error code {result.returncode}")
        logger.error(f"Error Output: {result.stderr}")
    else:
        logger.info(f"VQA process for {name} completed successfully.")

    # Parse the output to extract the VQA score
    VQA = None
    for line in result.stdout.splitlines():
        if "The quality score of the video" in line:
            score_match = re.search(r'\b0\.\d+', line)
            if score_match:
                try:
                    VQA = float(score_match.group())
                    logger.debug(f"Calculated VQA for {name}: {VQA}")
                except ValueError:
                    logger.error(f"Failed to convert VQA value to float for {name}")

    if VQA is None:
        logger.warning(f"No VQA score found for {name}")

    # Append the VQA result to the shared dictionary in a thread-safe manner
    with lock:
        if name in shared_dict:
            shared_dict[name].append(VQA)
        else:
            shared_dict[name] = [VQA]

    return result.returncode

def _prepareRes_test(VPC: VideoProcessingConfig)-> list:
    """
    Prepares test video files by extracting scenes at specific timestamps and encoding them at different resolutions.

        Args:
            VPC (VideoProcessingConfig): Video processing configuration

        Returns:
            list: list of created files
    """
    created_files = list()

    # Calculate timestamps for scene extraction
    res_settings = VPC.test_settings["Resolution_calculation"]
    timestep = int(VPC.orig_duration/(res_settings["num_of_tests"]+1))

    VPC.setDuration(res_settings["scene_length"])
    VPC.setOutputCQ(res_settings["cq_value"])

    for timestamp in range(res_settings["num_of_tests"]):
        timestamp = timestamp + 1

        for h_resolution in res_settings["testing_resolutions"]:

            test_VPC = copy.deepcopy(VPC)
            test_VPC.setOutputFileName(f"{timestamp}_{h_resolution}_cq{res_settings["cq_value"]}")
            test_VPC.setStart(timestamp * timestep)
            test_VPC.setOutputRes(h_resolution)

            created_files.append(test_VPC.output_file_path)

            # Perform encoding using the compressor module
            logger.debug(f"Creating test file {test_VPC.output_file_path}")
            _ = compressor2.compress(test_VPC)

    return created_files

#endregion

# region Basic Tests  
def getVMAF(reference_file: str, distorted_file: str, threads: int = 8) -> Union[float, None]:
    """
    Computes VMAF (Video Multi-Method Assessment Fusion) score between a reference video
    and a distorted video using FFmpeg.

    Parameters:
    - reference_file (str): Path to the reference (original) video file.
    - distorted_file (str): Path to the distorted (compressed) video file.
    - threads (int): Number of threads to use for VMAF computation. Default is 8.

    Returns:
    - float: VMAF score (higher is better), or None if an error occurs.
    """

     # Define the ffmpeg command to compute VMAF with multithreading
    output_file = r"VMAFlog.json"

    command = [
        'ffmpeg',
        '-i', reference_file,        # Input reference file
        '-i', distorted_file,        # Input distorted file
        '-lavfi', f'libvmaf=n_threads={threads}:log_path={output_file}',  # VMAF with multithreading and log output
        '-f', 'null', '-'            # No output file, just compute VMAF
    ]

    logger.debug(f"ffmpeg vmaf command: {command}")

    try:
        # Run the command
        process = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, shell=False)

        # Check if the process completed successfully
        if process.returncode != 0:
            logger.error(f"FFmpeg finished with errors. Exit code: {process.returncode}")
            logger.error(process.stderr.strip())  # Display error output
            return None
        
        # Load and parse the VMAF results from the output file
        if not os.path.exists(output_file):
            logger.error(f"VMAF log file '{output_file}' not found.")
            return None

        logger.debug(f"VMAF calculation completed successfully")

        # Load the VMAF results from the output file
        vmaf_score = None
        with open("VMAFlog.json", 'r') as file:
            for line in file:
                if '<metric name="vmaf"' in line:
                    match = re.findall(r"(?<=harmonic_mean=\").*\d", line)
                    if match: vmaf_score = float(match[0])

        if vmaf_score is not None:
            return vmaf_score
        else:
            logger.error("VMAF score not found in the output JSON.")

    except Exception as e:
        logger.error(f"Unexpected error while computing VMAF: {e}")
#endregion

# region getCQ
def getCQ(VPC: VideoProcessingConfig) -> bool:
    """
    Calculates an optimal CQ value for video encoding based on VMAF quality assessment.

    Args:
        VPC (VideoProcessingConfig): Video processing configuration

    Returns:
        bool: True if conversion succeeded, False otherwise
    """  
    cq_values = VPC.test_settings["CQ_calculation"]["cq_values"]
    if len(cq_values) != 4:
        logger.error("cq values list different size")
        return False
    
    cq_values.sort()
    cq_VPC = copy.deepcopy(VPC)
    name = VPC.output_file_name + "_cq"
    cq_VPC.setWorkspace(os.path.join(VPC.workspace, name))
    number_of_scenes = cq_VPC.test_settings["CQ_calculation"]["number_of_scenes"]

    results = dict()
    timestep = int(cq_VPC.orig_duration/(number_of_scenes+1))
    reference_files = list()

    #genereate reference videos
    for timestamp in range(number_of_scenes):
        timestamp = timestamp + 1

        cq_VPC.setOutputFileName(f"{timestamp}_reference")
        cq_VPC.setStart(timestamp * timestep)
        cq_VPC.setDuration(VPC.test_settings["CQ_calculation"]["scene_length"])
        cq_VPC.setOutputCQ(VPC.test_settings["CQ_calculation"]["cq_reference"])

        logger.debug(f"Creating reference file {cq_VPC.output_file_name}")
        
        _createAndTestVMAF(cq_VPC, reference_video=None)
        reference_files.append(cq_VPC.output_file_path)
    reference_files.sort() #this will break with 9 or more scenes

    results = dict()

    #get VMAF values
    position_list = [0, 2, 3]
    for position in position_list:
        for timestamp in range(number_of_scenes):
            timestamp = timestamp + 1

            if not isinstance(results.get(timestamp), dict):
                results[timestamp] = dict()

            cq_VPC.setOutputFileName(f"{timestamp}_{cq_values[position]}")
            cq_VPC.setStart(timestamp * timestep)
            cq_VPC.setOutputCQ(cq_values[position])

            logger.debug(f"Getting VMAF result for: {cq_VPC.output_file_name}")
        
            results[timestamp][cq_values[position]] = _createAndTestVMAF(cq_VPC, reference_files[timestamp-1])

    # Compute optimized VMAF for CQ 18
    cq_VPC.setOutputFileName(f"1_{cq_values[1]}")
    cq_VPC.setStart(1*timestep)
    cq_VPC.setOutputCQ(cq_values[1])
    logger.debug(f"Getting VMAF result for: {cq_VPC.output_file_name}")

    optimization_VMAF = _createAndTestVMAF(cq_VPC, reference_files[0])

    for key in results.keys():
        results[key][cq_values[1]] = optimization_VMAF

    #calculate VMAF difference to cq15
    subtracted_results = dict()
    for scene, vmaf_data in results.items():
        subtracted_results[scene] = {
            cq_values[0]: 0,
            cq_values[1]: vmaf_data[cq_values[0]] - vmaf_data[cq_values[1]],
            cq_values[2]: vmaf_data[cq_values[0]] - vmaf_data[cq_values[2]],
            cq_values[3]: vmaf_data[cq_values[0]] - vmaf_data[cq_values[3]],
        }

    # Calculate CQ values using quadratic regression
    calculated_CQs = list()
    for key in subtracted_results.keys():
        x = np.array(list(subtracted_results[key].keys()))  # The x-values
        y = np.array(list(subtracted_results[key].values()))  # The y-values
        a, b, c = np.polyfit(x, y, 2)
        logger.debug(f"CQ polynomial: {a}, {b}, {c}")

        threshold_variable = np.float64(VPC.getProfileValue(VPC.profile["test_settings"], "cq_threashold"))
        discriminant = b**2 - 4*a*(c-threshold_variable)
        logger.debug(f"CQ discriminant: {discriminant}")

        if discriminant >= 0:
            solution = (-b + np.sqrt(discriminant)) / (2 * a)
            calculated_CQs.append(solution)
        else:
            logger.error("No valid CQ solution found.")

    # Filter worst scenes and compute average CQ
    calculated_CQs = sorted(calculated_CQs)
    logger.debug(f"Calculated CQ values: {calculated_CQs}")

    to_keep = math.ceil(len(calculated_CQs)*VPC.test_settings["CQ_calculation"]["keep_best_scenes"])
    calculated_CQs = calculated_CQs[:to_keep]
    logger.debug(f"Filtered CQ values: {calculated_CQs}")

    if not calculated_CQs:
        logger.error("No valid CQ values calculated.")
        return False

    target_cq = sum(calculated_CQs) / len(calculated_CQs)
    target_cq = round(target_cq * 2) / 2  # Round to nearest 0.5
    
    logger.info(f"Calculated CQ: {target_cq}")
    VPC.setOutputCQ(target_cq)
    return True

#endregion

def _createAndTestVMAF(VPC: VideoProcessingConfig, reference_video: Union[str, None] = None) -> Union[float, None]:
    """
    Compresses a video segment and calculates VMAF if a reference video is provided.

    Args:
        VPC (VideoProcessingConfig): Video processing configuration
        reference_video (str, optional): Path to the reference video for VMAF calculation. Default is None.

    Returns:
    - float: VMAF score if reference video is provided, else None.
    """

    _ = compressor2.compress(VPC)
    if reference_video is not None:
        VMAF_value = getVMAF(reference_video, VPC.output_file_path, VPC.test_settings["CQ_calculation"]["threads"])
        logger.debug(f"VMAF Score: {VMAF_value}")
        return VMAF_value
    else:
        return None

#region Num of Channels
def getNumOfChannels(
    orig_video_path: str, 
    workspace: str, 
    similarity_cutoff: float = 0.001, 
    duration: int = 1200
) -> int:
    
    """
    Determines the number of unique audio channels in a video file.

    Parameters:
    - orig_video_path (str): Path to the original video file.
    - workspace (str): Directory where extracted audio and processing files will be stored.
    - similarity_cutoff (float, optional): MSE threshold to determine if channels are identical. Default is 0.001.
    - duration (int, optional): Maximum duration (in seconds) of audio to analyze. Default is 1200.

    Returns:
    - int: Number of unique channels (1, 2, 4, or 6).
    """

    name = str(os.path.basename(orig_video_path)[:-4]) + "_channels"
    work_folder = os.path.join(workspace, name)

    if not os.path.exists(work_folder):
            # Create the directory
            os.makedirs(work_folder)
            logger.debug(f'Directory "{work_folder}" created.')

    act_duration = getDuration(orig_video_path)

    if act_duration is not None and act_duration >= duration:

        audio_file = _extractAudio(orig_video_path, work_folder, duration)

        y, sr = sf.read(audio_file) # Function to load the audio and extract the channels
        num_channels = y.shape[1] if len(y.shape) > 1 else 1  # Determine the number of channels

        if num_channels == 1:
            logger.info("The audio file has only one channel (mono). No comparison needed.")
            return 1

        logger.debug(f"The audio file has {num_channels} channels. Comparing channels using MSE:")

        mse_list = list()
        channel_list = [True] * num_channels


        # Compare each pair of channels
        for i in range(num_channels):
            for j in range(i + 1, num_channels):
                #mse = calculate_mse(y[:, i], y[:, j])
                mse = np.mean((y[:, i] - y[:, j]) ** 2)
                if mse in mse_list or mse <= similarity_cutoff:
                    channel_list[j] = False
                if mse == 0:
                    channel_list[j] = False
                    channel_list[i] = False

                mse_list.append(mse)
                logger.debug(f"MSE between channel {i + 1} and channel {j + 1}: {mse}")

        logger.debug(channel_list)

        output = list()
        for i in range(len(channel_list)):
            if channel_list[i] == True:
                output.append(i+1)

        if len(output) == 0:
            return 2
        
        logger.info(f"There are at least {len(output)} uniqe channels:")
        logger.info(output)
        if len(output) == 3:
            return 4
        if len(output) >= 5:
            return 6
        return len(output)

def _extractAudio(orig_video_path: str, work_folder: str, duration: int) -> str:
    """
    Extracts audio from a video file and saves it as a WAV file.

    Parameters:
    - orig_video_path (str): Path to the original video file.
    - work_folder (str): Directory where extracted audio will be saved.
    - duration (int): Maximum duration (in seconds) of the extracted audio.

    Returns:
    - str: Path to the extracted audio file.
    """

    try:
            
        # Create output filename by replacing input extension with the audio file extension
        name = str(os.path.basename(orig_video_path)[:-4]) + ".wav"
        output_audio = os.path.join(work_folder, name)
        #output_audio = input_movie.rsplit('.', 1)[0] + f".{extension}"
        
        # Run FFmpeg command to extract the audio
        extract_command = [
            "ffmpeg", "-i", orig_video_path,  # Input video file
            "-vn",  # Disable video processing
            "-acodec", "pcm_s16le",  # Uncompressed WAV format (16-bit PCM)
            "-t", str(duration),  # Limit duration
            "-y",  # Overwrite output if it exists
            output_audio
        ]
        logger.debug(f"ffmpeg command: {extract_command}")
        process = subprocess.run(extract_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, shell=False)
        
        # Check for errors
        if process.returncode != 0:
            logger.error(f"An error occurred while extracting audio: {e}")
            return None
        
        return output_audio
    
    except Exception as e:
        logger.error(f"An error occurred: {e}")

#region Blackbars
def detectBlackbars(VPC: VideoProcessingConfig) -> bool:
    """
    Detects black bars in a video by sampling frames and analyzing the central column of each frame
    for consecutive black pixels from the top and bottom.

    Args:
        VPC (VideoProcessingConfig): Video processing configuration

    Returns:
        bool: True if conversion succeeded, False otherwise
    """
    blackbars_VPC = copy.deepcopy(VPC)
    name = VPC.output_file_name + "_blackDetection"
    blackbars_VPC.setWorkspace(os.path.join(VPC.workspace, name))

    frames_to_detect = VPC.test_settings["Black_bar_detection"]["frames_to_detect"]
    timestep = int(VPC.orig_duration/(frames_to_detect+1))

    # Initialize lists to hold the black pixel counts for each sampled frame
    black_top = [0] * frames_to_detect
    black_bottom = [0] * frames_to_detect

    # Process each frame for black bar detection
    for timestamp in range(frames_to_detect):
        timestamp = timestamp + 1

        # Define output filename and path for the extracted frame
        picture_name = str(timestamp) + ".png"
        target_name = os.path.join(blackbars_VPC.workspace, picture_name)
        exportFrame(blackbars_VPC, target_name, timestamp*timestep)
        
        # Open the image and load pixel data
        im = Image.open(target_name, 'r')
        pix = im.load()

        # Count consecutive black pixels from the top
        for i in range(0, im.size[1], 1):
            if all(channel < 10 for channel in pix[im.size[0] // 2, i]):
                black_top[timestamp-1] += 1
            else:
                break

        # Count consecutive black pixels from the bottom
        for i in range(im.size[1]-1, -1, -1):
            if all(channel < 10 for channel in pix[im.size[0] // 2, i]):
                black_bottom[timestamp-1] += 1
            else:
                break

    # Use the minimum value across all frames to get a robust estimate
    black_top_result = min(black_top)
    black_bottom_result = min(black_bottom)

    if black_bottom_result != 0 or black_top_result != 0:
        logger.info(f"Black bars detected: {black_top_result}pix from top, {black_bottom_result}pix from bottom")
    else:
        logger.info("No black bars detected")

    VPC.crop = [black_top_result, black_bottom_result]
    return True

def exportFrame(VPC: VideoProcessingConfig, target_name_path: str, time: int, png_quality: int = 2) -> None:
    """
    Extracts a single frame from a video at a specified time and saves it as an image.

    Parameters:
    - VideoProcessingConfig
    - target_name_path (str): Full path where the extracted image will be saved.
    - time (int): Timestamp (in seconds) at which to capture the frame.
    - png_quality (int, optional): Quality parameter for the output image (lower values indicate higher quality). Default is 2.

    Returns:
    - None
    """

    # Build the ffmpeg command to extract a single frame from the video.
    # -ss specifies the seek time,
    # -frames:v 1 tells ffmpeg to output only one frame,
    # -q:v sets the quality of the output image,
    # -update 1 overwrites the file if it exists,
    # -y forces overwriting without prompting.
    command = [
        os.path.join(VPC.tools_path, "ffmpeg.exe"),
        "-ss", str(time),
        "-i", VPC.orig_file_path,
        "-frames:v", "1",
        "-q:v", str(png_quality),
        "-update", "1",
        "-y", target_name_path
    ]

    logger.debug("Export frame ffmpeg command")
    logger.debug(command)


    process = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    #process = subprocess.run(command)

    # Check if the process completed successfully
    if process.returncode != 0:
        logger.error(f"FFmpeg finished with errors. Exit code: {process.returncode}")
        logger.error(process.stderr)

def runTests(VPC: VideoProcessingConfig):
    """
    Runs a series of tests on a video file to determine quality parameters such as resolution,
    black bar crop values, constant quality (CQ), and audio channel count.

    Definition params:
    - file (str): Path to the video file.
    - workspace (str): Directory for storing temporary and output files.
    - profile: Encoding profile for processing the video.
    - profile_settings (dict): Dictionary containing profile-specific settings (e.g., 'res_decode', 
      'cq_threashold', 'defalut_cq').
    - settings (dict): Dictionary with test settings. Each key corresponds to a test and maps to a list:
        * "Black_bar_detection": [enabled (bool), parameters (tuple)]
        * "Resolution_calculation": [enabled (bool), parameters (tuple)]
        * "CQ_calculation": [enabled (bool), parameters (tuple)]
        * "Channels_calculation": [enabled (bool), parameters (tuple)]

    Returns:
    - Tuple: (orig_res, crop, target_res, target_cq, channels) where:
         orig_res (int): Original horizontal resolution.
         crop (list): Detected crop values [top, bottom] from black bar detection.
         target_res (int): Calculated target resolution.
         target_cq (float): Calculated optimal CQ value.
         channels (int): Number of unique audio channels.
      If a critical error occurs (e.g., inability to detect the horizontal resolution), returns False.
    """

    # Get original horizontal resolution of the video

    # Black bar detection (if enabled)
    if VPC.test_settings["Black_bar_detection"]["Enabled"]:
        try:
            passed = detectBlackbars(VPC)
        except Exception as e:
            logger.warning("Black bar detection failed")
            logger.debug("Failed due to reason:")
            logger.debug("".join(traceback.format_exception(type(e), e, e.__traceback__)))
    else:
            logger.info("Black bar detection disabled")

    logger.info(f"Black bars set as {VPC.crop[0]}, {VPC.crop[1]}")

    # Resolution calculation (if enabled)
    if VPC.test_settings["Resolution_calculation"]["Enabled"]:
        try:
            passed = getRes_parallel(VPC)
        except Exception as e:
            logger.warning("Resolution detection failed")
            logger.debug("Failed due to reason:")
            logger.debug("".join(traceback.format_exception(type(e), e, e.__traceback__)))
    else:
        logger.info("Resolution detection disabled")  

    logger.info(f"Target resolution is {VPC.output_res}p")  
        
    # CQ (Constant Quality) calculation (if enabled)
    if VPC.test_settings["CQ_calculation"]["Enabled"]:
        try:
            passed = getCQ(VPC)
        except Exception as e:
            logger.warning("CQ test failed")
            logger.debug("Failed due to reason:")
            logger.debug("".join(traceback.format_exception(type(e), e, e.__traceback__)))   
    else:
        logger.info("CQ calculation disabled") 
    logger.info(f"Video has target CQ of {VPC.output_cq}")
    """
    # Audio channel detection (if enabled)
    if VPC.test_settings["Channels_calculation"]["Enabled"]:
        try:
            channels = getNumOfChannels(file, workspace, *settings["Channels_calculation"][1])
        except Exception as e:
            logger.warning("Unable to get number of audio chanels")
            logger.debug("Failed due to reason:")
            logger.debug("".join(traceback.format_exception(type(e), e, e.__traceback__)))
            channels = 2
    else:
        logger.info("Channels calculation disabled")
        channels = 2
    logger.info(f"Export will have {channels} channels")
    """

#endregion


if __name__ == '__main__':

    print("wrong file bro")