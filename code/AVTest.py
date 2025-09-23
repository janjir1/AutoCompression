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
def getRes_parallel(workspace: str, orig_video_path : str, decode_table: dict, profile: dict, crop: list, h_res_values: list, number_of_scenes:int = 15, scene_length: int = 1, cq_value: int = 1, num_of_VQA_runs: int = 2, keep_best_slopes:float =0.6, threads: int= 2) -> int: #enter full path to video
    """
    Determines the optimal resolution for video encoding based on VQA scores.

    Parameters:
    - workspace (str): Path to the workspace directory.
    - orig_video_path (str): Full path to the original video file.
    - decode_table (dict): Mapping of resolution values to quality thresholds.
    - profile (dict): Encoding profile parameters.
    - crop (list): Crop settings.
    - h_res_values (list): List of resolution values to test.
    - number_of_scenes (int): Number of scenes to extract (default: 15).
    - scene_length (int): Duration of each scene in seconds (default: 1).
    - cq_value (int): Constant quality value for encoding (default: 1).
    - num_of_VQA_runs (int): Number of VQA evaluations per video (default: 2).
    - keep_best_slopes (float): Fraction of best regression slopes to keep (default: 0.6).
    - threads (int): Number of parallel processes to use (default: 2).

    Returns:
    - int: The selected target resolution.
    """
    
    name = str(os.path.basename(orig_video_path)[:-4]) + "_res"
    video_folder = os.path.join(workspace, name)

    video_paths = _prepareRes_test(video_folder, orig_video_path, h_res_values, number_of_scenes, scene_length, cq_value, profile, crop)

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

        with Pool(processes=threads) as pool:
                pool.starmap(_run_VQA_process, [(video_path, shared_dict, lock) for video_path in video_paths])

        result_dict = dict(shared_dict)
    
    #make output dict more readable and average the VQA values for each res
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
    to_keep = math.ceil(len(regression_slope)*keep_best_slopes)
    regression_slope = regression_slope[:to_keep]
    
    average_slope = 0
    for value in regression_slope:
        average_slope = average_slope + value
    average_slope = average_slope/len(regression_slope)

    logger.debug(f"average slope is: {average_slope}")

    #Assign res to average slope
    target_res = 854
    for key in decode_table:
        if average_slope >= decode_table[key]:
            if key > target_res:
                target_res = key

    #do not allow upscaling
    orig_res = getH_res(orig_video_path)

    if target_res > orig_res:
        target_res = orig_res

    logger.info(f"Original resolution: {orig_res}, Target resolution: {target_res}")
    return target_res

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

def _prepareRes_test(
    output_folder: str,
    file_path: str,
    h_res_values: list,
    number_of_scenes: int,
    scene_length: int,
    cq_value: int,
    profile: dict,
    crop: list
) -> None:
    """
    Prepares test video files by extracting scenes at specific timestamps and encoding them at different resolutions.

    Parameters:
    - output_folder (str): Path to the directory where test files will be saved.
    - file_path (str): Full path to the original video file.
    - h_res_values (list): List of horizontal resolution values to test.
    - number_of_scenes (int): Number of scenes to extract from the video.
    - scene_length (int): Length of each extracted scene in seconds.
    - cq_value (int): Constant Quality (CQ) value for encoding.
    - profile (dict): Encoding profile settings.
    - crop (list): Crop parameters for encoding.

    Returns:
    - None
    """

    # Ensure the output directory exists
    if not os.path.exists(output_folder):
            # Create the directory
            os.makedirs(output_folder)
            logger.info(f'Directory "{output_folder}" created.')

    # Get the duration of the input video
    duration = getDuration(file_path)
    if duration is None:
        logger.error(f"Failed to retrieve video duration for {file_path}")
        return

    created_files = list()

    # Calculate timestamps for scene extraction
    timestep = int(duration/(number_of_scenes+1))

    for timestamp in range(number_of_scenes):
        timestamp = timestamp + 1

        for h_resolution in h_res_values:

            output_name = f"{timestamp}_{h_resolution}_cq{cq_value}"
            output_path = os.path.join(output_folder, output_name)

            created_files.append(output_path + ".mkv")

            # Perform encoding using the compressor module
            logger.debug(f"Creating test file {output_name}")
            _ = compressor2.compress(file_path, profile, output_name, output_folder, crop, h_resolution, cq_value, False, timestep*timestamp, scene_length)

    return created_files

#endregion

# region Basic Tests
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
            return None

        # Parse JSON output
        data = json.loads(result.stdout)
        
        # Extract and return duration
        duration = float(data.get('format', {}).get('duration', 0))
        if duration > 0:
            return duration
        else:
            logger.error(f"Invalid duration value received from FFprobe for {input_path}.")
            return None

    except json.JSONDecodeError:
        logger.error(f"Failed to parse JSON output from FFprobe for {input_path}.")
    except Exception as e:
        logger.error(f"Unexpected error while retrieving duration for {input_path}: {e}")

    return None

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
            return None
        
        # Parse the JSON output
        ffprobe_output = json.loads(result.stdout)

        # Extract the width from the 'width' field in the stream
        width = int(ffprobe_output['streams'][0]['width'])
        if width is not None:
            return width
        else:
            logger.error(f"Failed to retrieve height from FFprobe output for {video_path}.")
            return None
    
    except json.JSONDecodeError:
        logger.error(f"Failed to parse JSON output from FFprobe for {video_path}.")
    except Exception as e:
        logger.error(f"Unexpected error while retrieving resolution for {video_path}: {e}")

    return None
    
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
            return None
        
        # Parse the JSON output
        ffprobe_output = json.loads(result.stdout)

        # Extract the height from the 'height' field in the stream
        height = int(ffprobe_output['streams'][0]['height'])
        
        if height is not None:
            return height
        else:
            logger.error(f"Failed to retrieve height from FFprobe output for {video_path}.")
            return None
    
    except json.JSONDecodeError:
        logger.error(f"Failed to parse JSON output from FFprobe for {video_path}.")
    except Exception as e:
        logger.error(f"Unexpected error while retrieving resolution for {video_path}: {e}")
     
def getVMAF(reference_file: str, distorted_file: str, threads: int = 8) -> float:
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
        '-i', reference_file + ".mkv",        # Input reference file
        '-i', distorted_file + ".mkv",        # Input distorted file
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
def getCQ(workspace: str, orig_video_path: str, h_res: int, profile: list, crop: list,
          threshold_variable: float, cq_values: list = [15, 18, 27, 36], number_of_scenes: int = 3,
          cq_reference: int = 1, scene_length: int = 60, keep_best_scenes: float = 0.6, threads: int = 6) -> float:
    """
    Calculates an optimal CQ value for video encoding based on VMAF quality assessment.

    Parameters:
    - workspace (str): Path to the workspace directory.
    - orig_video_path (str): Path to the original video file.
    - h_res (int): Target horizontal resolution.
    - profile (list): Encoding profile settings.
    - crop (list): Crop settings.
    - threshold_variable (float): VMAF threshold for CQ optimization.
    - cq_values (list): List of CQ values to evaluate. Default is [15, 18, 27, 36].
    - number_of_scenes (int): Number of scenes to analyze. Default is 3.
    - cq_reference (int): Reference CQ value for VMAF comparison. Default is 1.
    - scene_length (int): Scene duration in seconds. Default is 60.
    - keep_best_scenes (float): Fraction of best scenes to keep for averaging. Default is 0.6.
    - threads (int): Number of threads for processing. Default is 6.
    
    Returns:
    - float: Optimized CQ value rounded to the nearest 0.5, or None if an error occurs.
    """  

    if len(cq_values) != 4:
        logger.error("cq values list different size")
        return None
    
    cq_values.sort()
    name = str(os.path.basename(orig_video_path)[:-4]) + "_cq"
    video_folder = os.path.join(workspace, name)

    if not os.path.exists(video_folder):
            # Create the directory
            os.makedirs(video_folder)
            logger.debug(f'Directory "{video_folder}" created.')

    duration = getDuration(orig_video_path)
    if duration is None:
        logger.error("Could not determine video duration.")
        return None

    results = dict()
    timestep = int(duration/(number_of_scenes+1))
    reference_files = list()

    #genereate reference videos
    for timestamp in range(number_of_scenes):
        timestamp = timestamp + 1

        output_name = f"{timestamp}_reference"
        output_path = os.path.join(video_folder, output_name)

        logger.debug(f"Creating reference file {output_name}")
        
        _createAndTestVMAF(output_path, orig_video_path, h_res, cq_reference, timestamp*timestep, scene_length, profile, crop, None, threads)
        reference_files.append(output_path)
    reference_files.sort() #this will break with 9 or more scenes

    results = dict()

    #get VMAF values
    position_list = [0, 2, 3]
    for position in position_list:
        for timestamp in range(number_of_scenes):
            timestamp = timestamp + 1

            if not isinstance(results.get(timestamp), dict):
                results[timestamp] = dict()

            output_name = f"{timestamp}_{cq_values[position]}"
            output_path = os.path.join(video_folder, output_name)

            logger.debug(f"Getting VMAF result for: {output_name}")
        
            results[timestamp][cq_values[position]] = _createAndTestVMAF(output_path, orig_video_path, h_res, cq_values[position], timestamp*timestep, scene_length, profile, crop, reference_files[timestamp-1], threads)

    # Compute optimized VMAF for CQ 18
    output_name = f"1_{cq_values[1]}"
    output_path = os.path.join(video_folder, output_name)
    logger.debug(f"Getting VMAF result for: {output_name}")
    optimization_VMAF = _createAndTestVMAF(output_path, orig_video_path, h_res, cq_values[1], 1*timestep, scene_length, profile, crop, reference_files[0], threads)

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

    to_keep = math.ceil(len(calculated_CQs)*keep_best_scenes)
    calculated_CQs = calculated_CQs[:to_keep]
    logger.debug(f"Filtered CQ values: {calculated_CQs}")

    if not calculated_CQs:
        logger.error("No valid CQ values calculated.")
        return None

    target_cq = sum(calculated_CQs) / len(calculated_CQs)
    target_cq = round(target_cq * 2) / 2  # Round to nearest 0.5
    
    logger.info(f"Calculated CQ: {target_cq}")
    return target_cq

#endregion

def _createAndTestVMAF(
    output_path: str, 
    orig_video_path: str, 
    h_res: int, 
    cq_value: int, 
    start_time: int, 
    scene_length: int, 
    profile: dict, 
    crop: list, 
    reference_video: str = None, 
    threads: int = 6
) -> float:
    """
    Compresses a video segment and calculates VMAF if a reference video is provided.

    Parameters:
    - output_path (str): Path to save the compressed video.
    - orig_video_path (str): Path to the original video.
    - h_res (int): Target horizontal resolution.
    - cq_value (int): Constant quality (CQ) value for compression.
    - start_time (int): Timestamp (in seconds) from where the scene starts.
    - scene_length (int): Length of the scene in seconds.
    - profile (dict): Encoding profile settings.
    - crop (list): Crop parameters for encoding.
    - reference_video (str, optional): Path to the reference video for VMAF calculation. Default is None.
    - threads (int, optional): Number of threads to use for VMAF computation. Default is 6.

    Returns:
    - float: VMAF score if reference video is provided, else None.
    """

    _ = compressor2.compress(orig_video_path, profile, os.path.basename(output_path), os.path.dirname(output_path), crop, h_res, cq_value, False, start_time, scene_length)
    if reference_video is not None:
        VMAF_value = getVMAF(reference_video, output_path, threads)
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
def detectBlackbars(orig_video_path: str, workspace: str, frames_to_detect: int = 10) -> list:
    """
    Detects black bars in a video by sampling frames and analyzing the central column of each frame
    for consecutive black pixels from the top and bottom.

    Parameters:
    - orig_video_path (str): Full path to the original video file.
    - workspace (str): Directory where extracted frames and output will be stored.
    - frames_to_detect (int, optional): Number of frames to sample for detection. Default is 10.

    Returns:
    - list: A list [black_top_result, black_bottom_result] where:
        - black_top_result (int): Minimum number of consecutive black pixels detected from the top edge.
        - black_bottom_result (int): Minimum number of consecutive black pixels detected from the bottom edge.
    """
    
    name = str(os.path.basename(orig_video_path)[:-4]) + "_blackDetection"
    work_folder = os.path.join(workspace, name)

    if not os.path.exists(work_folder):
            # Create the directory
            os.makedirs(work_folder)
            logger.debug(f'Directory "{work_folder}" created.')

    # Get the video duration (in seconds)
    movie_duration = getDuration(orig_video_path)
    timestep = int(movie_duration/(frames_to_detect+1))

    # Initialize lists to hold the black pixel counts for each sampled frame
    black_top = [0] * frames_to_detect
    black_bottom = [0] * frames_to_detect

    # Process each frame for black bar detection
    for timestamp in range(frames_to_detect):
        timestamp = timestamp + 1

        # Define output filename and path for the extracted frame
        picture_name = str(timestamp) + ".png"
        target_name = os.path.join(work_folder, picture_name)
        exportFrame(orig_video_path, target_name, timestamp*timestep)
        
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

    return [black_top_result, black_bottom_result]

def exportFrame(orig_video_path: str, target_name_path: str, time: int, png_quality: int = 2) -> None:
    """
    Extracts a single frame from a video at a specified time and saves it as an image.

    Parameters:
    - orig_video_path (str): Full path to the original video file.
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
        "ffmpeg",
        "-ss", str(time),
        "-i", orig_video_path,
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

def runTests(file: str, workspace: str, profile, profile_settings, settings):
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
    try:
        orig_res = getH_res(file)
        logger.info(f"Original resolution is {orig_res}")
    except Exception as e:
        logger.error("Not able to detect horiontal resolution")
        logger.debug("Failed due to reason:")
        logger.debug("".join(traceback.format_exception(type(e), e, e.__traceback__)))
        return False

    # Black bar detection (if enabled)
    if settings["Black_bar_detection"][0]:
        try:
            crop = detectBlackbars(file, workspace, *settings["Black_bar_detection"][1])
        except Exception as e:
            logger.warning("Black bar detection failed")
            logger.debug("Failed due to reason:")
            logger.debug("".join(traceback.format_exception(type(e), e, e.__traceback__)))
            crop = [0, 0]
    else:
            logger.info("Black bar detection disabled")
            crop = [0, 0]
    logger.info(f"Black bars set as {crop[0]}, {crop[1]}")

    # Resolution calculation (if enabled)
    if settings["Resolution_calculation"][0]:
        try:
            target_res = getRes_parallel(workspace, file, profile_settings["res_decode"], profile, crop, *settings["Resolution_calculation"][1])
        except Exception as e:
            logger.warning("Resolution detection failed")
            logger.debug("Failed due to reason:")
            logger.debug("".join(traceback.format_exception(type(e), e, e.__traceback__)))
            target_res = orig_res
    else:
        logger.info("Resolution detection disabled")  
        target_res = orig_res  
    logger.info(f"Target resolution is {target_res}p")  
        
    # CQ (Constant Quality) calculation (if enabled)
    if settings["CQ_calculation"][0]:
        try:
            target_cq = getCQ(workspace, file, target_res, profile, crop, profile_settings["cq_threashold"], *settings["CQ_calculation"][1])
        except Exception as e:
            logger.warning("CQ test failed")
            logger.debug("Failed due to reason:")
            logger.debug("".join(traceback.format_exception(type(e), e, e.__traceback__)))
            target_cq = profile_settings["defalut_cq"]       
    else:
        logger.info("CQ calculation disabled") 
        target_cq = profile_settings["defalut_cq"] 
    logger.info(f"Video has target CQ of {target_cq}")

    # Audio channel detection (if enabled)
    if settings["Channels_calculation"][0]:
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

    return orig_res, crop, target_res, target_cq, channels
#endregion


if __name__ == '__main__':
    """
    decode_table =  {854: -10, 1280: -1e-04, 1920: -6.9e-05, 3840: -4e-05}
    workaspace = r"D:\Files\Projects\AutoCompression\Tests\Martan"
    file = r"E:\Filmy\hrané\Drama\Marťan-2015-Cz-Dabing-HD.mkv"
    start = time.time()
    target_res = getRes_parallel(workaspace, file, [854, 3840], 15, decode_table, num_of_VQA_runs=3)
    taret_cq = getCQ(workaspace, file, target_res, [15, 18, 27, 36], 3, 0.6, scene_length=50, video_encoding_preset="p2", threads=8)
    audio_channels = getNumOfChannels(file, workaspace, 0.001, 3600)
    end = time.time()
    print(f"this took {end - start}s")
    print(f"res: {target_res}, cq: {taret_cq}")
    print(f"audio ch: {audio_channels}")
    """
    workaspace = r"D:\Files\Projects\AutoCompression\Tests\Martan"
    file = r"E:\Filmy\hrané\Fantasy\Na hraně zítřka SD.avi"
    start = time.time()
    crop = detectBlackbars(file, workaspace, 9)
    #print(vfCropComandGenerator(file, crop, 720))
    end = time.time()
    print(f"this took {end - start}s")