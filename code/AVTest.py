import subprocess
import re, os, sys
import json
from multiprocessing import Pool
import math
import numpy as np
import logging
import compressor2
import traceback
from VideoClass import VideoProcessingConfig
from typing import Union

#TODO: add cleanup

# Retrieve the logger once at the module level
logger = logging.getLogger("AppLogger")

# region singlethread VQA
#Meassure video using FasterVQA, number of runs for averaging
def getVQA(video_path: str, num_of_runs: int = 4) -> Union[float, None]:
    """
    Computes the video quality assessment (VQA) score for a given video.

    Parameters:
    - video_path (str): Full path to the video file.
    - num_of_runs (int): Number of times to run the VQA assessment (default: 4).

    Returns:
    - float: Average quality score of the video, or None if all runs failed.
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
                logger.error(f"Error Output: {error_output}")

        except Exception as e:
            logger.error(f"An error occurred: {str(e)}")

        #Parse the output
        for line in output_lines:
            if "The quality score of the video" in line:
                match = re.search(r'\b0\.\d+', line)
                if match:
                    quality_score.append(float(match.group()))

    if not quality_score:
        logger.error(f"No valid VQA scores obtained for {video_path}")
        return None

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
    res_VPC = VPC.create_copy()
    name = VPC.output_file_name + "_res"

    res_VPC.setWorkspace(os.path.join(VPC.workspace, name))

    video_paths, passed = _prepareRes_test(res_VPC)

    if not passed:
        return False

    vqa_runs = VPC.test_settings["Resolution_calculation"].get("VQA_per_test", 1)
    vqa_tasks = [path for path in video_paths for _ in range(vqa_runs)]

    with Pool(processes=VPC.test_settings["Resolution_calculation"]["Threads"]) as pool:
        raw_results = pool.map(_run_VQA_process, vqa_tasks)

    result_dict = {}
    for file_name, score in raw_results:
        if score is not None:
            result_dict.setdefault(file_name, []).append(score)

    #make output dict more readable and average the VQA values for each res
    logger.debug("VQA process finished sucefully")

    if len(result_dict) < 2:
        logger.error("result is empty")
        return False

    sorted_dict = dict()
    for key, values in result_dict.items():
        matches = re.findall(r"\d+", key)
        if len(matches) < 2 or not values:
            logger.warning(f"Skipping unexpected VQA result key: {key}")
            continue
        sample = matches[0]
        res = int(matches[1])

        VQA_result = sum(values) / len(values)
        sorted_dict.setdefault(sample, {})[res] = VQA_result

    logger.debug("Processed VQA data:")
    logger.debug(sorted_dict)

    #determine regression slope for each scene
    regression_slope = list()
    logger.debug("regression slope:")
    for scene, res_map in sorted_dict.items():
        res_sorted = sorted(res_map.keys())
        if len(res_sorted) < 2:
            logger.warning(f"Insufficient resolution data for scene {scene}, skipping")
            continue
        res_min = res_sorted[0]
        res_max = res_sorted[-1]
        VQA_res_min = float(res_map[res_min])
        VQA_res_max = float(res_map[res_max])
        slope = (VQA_res_max - VQA_res_min) / (res_max - res_min)
        regression_slope.append(slope)
        logger.debug(f"{scene}: {slope}")

    if not regression_slope:
        logger.error("No valid regression slopes calculated.")
        return False

    logger.debug("average:")
    logger.debug(regression_slope)

    #remove worst scenes and make average
    regression_slope = sorted(regression_slope, reverse=True)
    to_keep = math.ceil(len(regression_slope) * VPC.test_settings["Resolution_calculation"]["keep_best_slopes"])
    regression_slope = regression_slope[:to_keep]

    average_slope = sum(regression_slope) / len(regression_slope)

    logger.debug(f"average slope is: {average_slope}")

    #Assign res to average slope
    target_res = 854
    decode_table = VPC.profile_settings["res_decode"]

    for key, threshold in decode_table.items():
        res_val = int(key)
        if average_slope >= float(threshold):
            if res_val > target_res:
                target_res = res_val

    if target_res > VPC.orig_h_res:
        target_res = VPC.orig_h_res

    logger.info(f"Original resolution: {VPC.orig_h_res}, Target resolution: {target_res}")
    VPC.setOutputRes(target_res)
    compressor2.delete_file(VPC, res_VPC.workspace)
    return True

def _run_VQA_process(video_path: str) -> tuple[str, Union[float, None]]:
    """
    Runs the VQA process on a given video file and returns (file_name, vqa_score).

    Parameters:
    - video_path (str): Full path to the video file.

    Returns:
    - tuple[str, float | None]: Filename without extension and parsed VQA score (or None on error).
    """

    # Extract video ID from the filename
    match = re.search(r'\d+(?=_cq\d+\.mkv)', video_path)
    video_id = match.group() if match else video_path

    # Extract filename without extension
    name = os.path.splitext(os.path.basename(video_path))[0]

    # Construct the command for VQA execution
    command = [sys.executable, "/app/FastVQA-and-FasterVQA/vqa.py", "-v", video_path]
    logger.debug(f"Starting VQA calculation on file {name} (Video ID: {video_id}) with PID {os.getpid()}")

    try:
        # Run the command with a timeout of 20 minutes (1200 seconds)
        result = subprocess.run(command, capture_output=True, text=True, shell=False, timeout=1200)
    except subprocess.TimeoutExpired:
        logger.error(f"Timeout expired for file {name} after 20 minutes.")
        return name, None
    except Exception as e:
        logger.exception(f"An error occurred while running VQA on {name}: {e}")
        return name, None

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

    return name, VQA

def _prepareRes_test(VPC: VideoProcessingConfig) -> tuple:
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
    timestep = int(VPC.orig_duration / (res_settings["num_of_tests"] + 1))

    VPC.setDuration(res_settings["scene_length"])
    VPC.setOutputCQ(res_settings["cq_value"])

    passed = True

    for timestamp in range(res_settings["num_of_tests"]):
        timestamp = timestamp + 1

        for h_resolution in res_settings["testing_resolutions"]:

            test_VPC = VPC.create_copy()
            test_VPC.setOutputFileName(f"{timestamp}_{h_resolution}_cq{res_settings['cq_value']}")
            test_VPC.setStart(timestamp * timestep)
            test_VPC.setOutputRes(h_resolution)

            created_files.append(test_VPC.output_file_path)

            # Perform encoding using the compressor module
            logger.debug(f"Creating test file {test_VPC.output_file_path}")
            if not compressor2.compress(test_VPC):
                passed = False

    return created_files, passed

#endregion

# region Basic Tests
def getVMAF(reference_file: str, distorted_file: str, VPC, threads: int = 8) -> Union[float, None]:
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
    output_file = os.path.join(VPC.workspace, f"VMAFlog_{os.getpid()}.json")
    # TODO: Check if cuda is available before running vmaf-cuda
    # TODO: Investigate 10-bit libvmaf_cuda (format=yuv420p10le) so 10-bit HDR/debanded videos aren't truncated to 8-bit during VMAF

    cuda_init = ['-init_hw_device', 'cuda=cu:0', '-filter_hw_device', 'cu']
    vmaf_graph = (
        "[0:v:0]setpts=PTS-STARTPTS,format=yuv420p,hwupload_cuda[a];"
        "[1:v:0]setpts=PTS-STARTPTS,format=yuv420p,hwupload_cuda[b];"
        f"[a][b]libvmaf_cuda=log_path={output_file}:log_fmt=json"
    )

    if "AV1" in VPC.profile["function"][1].upper():
        command = [
            'ffmpeg', *cuda_init,
            '-hwaccel', 'none', '-i', distorted_file,   # input 0
            '-hwaccel', 'none', '-i', reference_file,   # input 1
            '-lavfi', vmaf_graph,
            '-f', 'null', '-'
        ]
    else:
        command = [
            'ffmpeg', *cuda_init,
            '-i', distorted_file,       # input 0
            '-i', reference_file,       # input 1
            '-lavfi', vmaf_graph,
            '-f', 'null', '-'
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

        logger.debug("VMAF calculation completed successfully")

        with open(output_file, 'r', encoding='utf-8') as file:
            vmaf_data = json.load(file)

        vmaf_metrics = vmaf_data.get("pooled_metrics", {}).get("vmaf", {})
        vmaf_score = vmaf_metrics.get("harmonic_mean", vmaf_metrics.get("mean"))

        if vmaf_score is not None:
            return float(vmaf_score)
        else:
            logger.error("VMAF score not found in the output JSON.")
            return None

    except Exception as e:
        logger.error(f"Unexpected error while computing VMAF: {e}")
        return None
    finally:
        if os.path.exists(output_file):
            try:
                os.remove(output_file)
            except OSError:
                pass
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
    cq_values = sorted(VPC.test_settings["CQ_calculation"]["cq_values"])
    if len(cq_values) != 4:
        logger.error("cq values list different size")
        return False

    cq_VPC = VPC.create_copy()
    name = VPC.output_file_name + "_cq"
    cq_VPC.setWorkspace(os.path.join(VPC.workspace, name))
    number_of_scenes = cq_VPC.test_settings["CQ_calculation"]["number_of_scenes"]

    timestep = int(cq_VPC.orig_duration / (number_of_scenes + 1))
    reference_files = list()

    #genereate reference videos
    for timestamp in range(number_of_scenes):
        timestamp = timestamp + 1

        cq_VPC.setOutputFileName(f"{timestamp}_reference")
        cq_VPC.setStart(timestamp * timestep)
        cq_VPC.setDuration(VPC.test_settings["CQ_calculation"]["scene_length"])
        cq_VPC.setOutputCQ(VPC.test_settings["CQ_calculation"]["cq_reference"])

        logger.debug(f"Creating reference file {cq_VPC.output_file_name}")

        _, passed = _createAndTestVMAF(cq_VPC, reference_video=None)
        if not passed:
            logger.error("Media creation failed")
            return False
        reference_files.append(cq_VPC.output_file_path)
    reference_files.sort(key=lambda f: int(os.path.basename(f).split("_")[0]))

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

            results[timestamp][cq_values[position]], passed = _createAndTestVMAF(cq_VPC, reference_files[timestamp - 1])
            if not passed:
                logger.error("Media creation failed")
                return False

    # Compute optimized VMAF for CQ[1] on scene 1 and reuse its VMAF delta across scenes
    cq_VPC.setOutputFileName(f"1_{cq_values[1]}")
    cq_VPC.setStart(1 * timestep)
    cq_VPC.setOutputCQ(cq_values[1])
    logger.debug(f"Getting VMAF result for: {cq_VPC.output_file_name}")

    optimization_VMAF, passed = _createAndTestVMAF(cq_VPC, reference_files[0])
    if not passed:
        logger.error("Media creation failed")
        return False

    scene1_cq0 = results.get(1, {}).get(cq_values[0])
    if scene1_cq0 is None or optimization_VMAF is None:
        logger.error("[getCQ] Missing scene 1 VMAF data for CQ[1] delta calculation")
        return False
    cq1_delta = scene1_cq0 - optimization_VMAF

    #calculate VMAF difference to cq_values[0]
    subtracted_results = dict()
    for scene, vmaf_data in results.items():
        if any(vmaf_data.get(cq) is None for cq in (cq_values[0], cq_values[2], cq_values[3])):
            logger.warning(f"[getCQ] Incomplete VMAF data for scene {scene}, skipping")
            continue
        subtracted_results[scene] = {
            cq_values[0]: 0,
            cq_values[1]: cq1_delta,
            cq_values[2]: vmaf_data[cq_values[0]] - vmaf_data[cq_values[2]],
            cq_values[3]: vmaf_data[cq_values[0]] - vmaf_data[cq_values[3]],
        }

    # Calculate CQ values using quadratic regression
    threshold_variable = np.float64(VPC.getProfileValue(VPC.profile["test_settings"], "cq_threashold"))
    calculated_CQs = list()
    for key in subtracted_results.keys():
        x = np.array(list(subtracted_results[key].keys()))  # The x-values
        y = np.array(list(subtracted_results[key].values()))  # The y-values
        a, b, c = np.polyfit(x, y, 2)
        logger.debug(f"CQ polynomial: {a}, {b}, {c}")

        if abs(a) < 1e-12:
            if abs(b) > 1e-12:
                calculated_CQs.append((threshold_variable - c) / b)
            else:
                logger.error("Degenerate CQ curve (a=0, b=0); no valid CQ solution found.")
            continue

        discriminant = b**2 - 4 * a * (c - threshold_variable)
        logger.debug(f"CQ discriminant: {discriminant}")

        if discriminant >= 0:
            sqrt_d = np.sqrt(discriminant)
            roots = [(-b + sqrt_d) / (2 * a), (-b - sqrt_d) / (2 * a)]
            in_range = [r for r in roots if cq_values[0] <= r <= cq_values[-1]]
            if in_range:
                calculated_CQs.append(in_range[0])
            else:
                pos_roots = [r for r in roots if r > 0]
                if pos_roots:
                    calculated_CQs.append(min(pos_roots, key=lambda r: abs(r - cq_values[1])))
                else:
                    logger.error("No positive CQ root found.")
        else:
            logger.error("No valid CQ solution found.")

    # Filter worst scenes and compute average CQ
    calculated_CQs = sorted(calculated_CQs)
    logger.debug(f"Calculated CQ values: {calculated_CQs}")

    to_keep = math.ceil(len(calculated_CQs) * VPC.test_settings["CQ_calculation"]["keep_best_scenes"])
    calculated_CQs = calculated_CQs[:to_keep]
    logger.debug(f"Filtered CQ values: {calculated_CQs}")

    if not calculated_CQs:
        logger.error("No valid CQ values calculated.")
        return False

    target_cq = sum(calculated_CQs) / len(calculated_CQs)
    target_cq = round(target_cq * 2) / 2  # Round to nearest 0.5

    logger.info(f"Calculated CQ: {target_cq}")
    VPC.setOutputCQ(target_cq)

    compressor2.delete_file(VPC, cq_VPC.workspace)
    return True

#endregion

def _createAndTestVMAF(VPC: VideoProcessingConfig, reference_video: Union[str, None] = None) -> tuple[Union[float, None], bool]:
    """
    Compresses a video segment and calculates VMAF if a reference video is provided.

    Args:
        VPC (VideoProcessingConfig): Video processing configuration
        reference_video (str, optional): Path to the reference video for VMAF calculation. Default is None.

    Returns:
    - float: VMAF score if reference video is provided, else None.
    """

    passed = compressor2.compress(VPC)
    if reference_video is not None:
        VMAF_value = getVMAF(reference_video, VPC.output_file_path, VPC, VPC.test_settings["CQ_calculation"]["threads"])
        logger.debug(f"VMAF Score: {VMAF_value}")
        return VMAF_value, passed
    else:
        return None, passed

#region Blackbars
def detectBlackbars(VPC: VideoProcessingConfig) -> bool:
    """
    Detects top and bottom black bars using FFmpeg's native cropdetect filter
    across sampled timestamps without writing temporary PNG files.
    """
    frames_to_detect = VPC.test_settings["Black_bar_detection"]["frames_to_detect"]
    timestep = VPC.orig_duration / (frames_to_detect + 1)

    black_top = []
    black_bottom = []
    crop_re = re.compile(r"crop=(\d+):(\d+):(\d+):(\d+)")

    for i in range(1, frames_to_detect + 1):
        seek_time = round(i * timestep, 3)
        command = [
            "ffmpeg",
            "-v", "info",
            "-ss", str(seek_time),
            "-i", VPC.orig_file_path,
            "-map", "0:V:0",
            "-frames:v", "3",
            "-vf", "cropdetect=limit=0.1:round=2:reset=0",
            "-f", "null",
            "-",
        ]

        process = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if process.returncode != 0:
            logger.error(f"FFmpeg cropdetect failed at {seek_time}s: {process.stderr.strip()}")
            continue

        matches = crop_re.findall(process.stderr)
        if matches:
            _, h, _, y = map(int, matches[-1])
            top = y
            bottom = max(0, VPC.orig_v_res - h - y)
            black_top.append(top)
            black_bottom.append(bottom)

    if not black_top or not black_bottom:
        logger.warning("cropdetect produced no results; defaulting crop to [0, 0]")
        VPC.crop = [0, 0]
        return False

    # Take the minimum crop across all sampled frames and enforce even-pixel alignment
    black_top_result = (min(black_top) // 2) * 2
    black_bottom_result = (min(black_bottom) // 2) * 2

    if black_bottom_result != 0 or black_top_result != 0:
        logger.info(f"Black bars detected: {black_top_result}pix from top, {black_bottom_result}pix from bottom")
    else:
        logger.info("No black bars detected")

    VPC.crop = [black_top_result, black_bottom_result]
    return True


def runTests(VPC: VideoProcessingConfig) -> bool:
    """
    Runs a series of tests on a video file to determine quality parameters such as resolution,
    black bar crop values, and constant quality (CQ).
    """

    passed = True
    test_passed = True

    # Black bar detection (if enabled)
    if VPC.test_settings["Black_bar_detection"]["Enabled"]:
        try:
            test_passed = detectBlackbars(VPC)
        except Exception as e:
            test_passed = False
            logger.warning("Black bar detection failed")
            logger.debug("Failed due to reason:")
            logger.debug("".join(traceback.format_exception(type(e), e, e.__traceback__)))
    else:
        logger.info("Black bar detection disabled")

    logger.info(f"Black bars set as {VPC.crop[0]}, {VPC.crop[1]}")

    if not test_passed:
        passed = False
        test_passed = True

    # Resolution calculation (if enabled)
    if VPC.test_settings["Resolution_calculation"]["Enabled"]:
        try:
            test_passed = getRes_parallel(VPC)
        except Exception as e:
            test_passed = False
            logger.warning("Resolution detection failed")
            logger.debug("Failed due to reason:")
            logger.debug("".join(traceback.format_exception(type(e), e, e.__traceback__)))
    else:
        logger.info("Resolution detection disabled")

    logger.info(f"Target resolution is {VPC.output_res}p")

    if not test_passed:
        passed = False
        test_passed = True

    # CQ (Constant Quality) calculation (if enabled)
    if VPC.test_settings["CQ_calculation"]["Enabled"]:
        try:
            test_passed = getCQ(VPC)
        except Exception as e:
            test_passed = False
            logger.warning("CQ test failed")
            logger.debug("Failed due to reason:")
            logger.debug("".join(traceback.format_exception(type(e), e, e.__traceback__)))
    else:
        logger.info("CQ calculation disabled")

    logger.info(f"Video has target CQ of {VPC.output_cq}")

    if not test_passed:
        passed = False
        test_passed = True

    return passed
#endregion


if __name__ == '__main__':

    print("wrong file bro")