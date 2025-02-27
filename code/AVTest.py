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

#TODO: add cleanup

# Retrieve the logger once at the module level
logger = logging.getLogger("AppLogger")

# region singlethread VQA
#Meassure video using FasterVQA, number of runs for averaging
def getVQA(video_path: str, num_of_runs: int = 4) -> int: #enter full path to video

    quality_score = []
    
    for i in range(num_of_runs):
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
def getRes_parallel(workspace: str, orig_video_path : str, h_res_values: list, number_of_scenes:int, decode_table: dict,  video_profile: list, crop: list, scene_length = 1, cq_value = 1, num_of_VQA_runs: int = 2, threads=6, keep_best_slopes=0.6,) -> int: #enter full path to video

    name = str(os.path.basename(orig_video_path)[:-4]) + "_res"
    video_folder = os.path.join(workspace, name)

    _prepareRes_test(video_folder, orig_video_path, h_res_values, number_of_scenes, scene_length, cq_value, video_profile, crop)

    video_paths = list()
    files = [f for f in os.listdir(video_folder) if os.path.isfile(os.path.join(video_folder, f))]
    for file in files:
        for _ in range(num_of_VQA_runs):
            video_paths.append(os.path.join(video_folder, file))

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

def _run_VQA_process(video_path, shared_dict, lock):

    match = re.search(r'\d*(?=_cq\d.mp4)', video_path)
    if match:
        type = match.group()
    else: type = video_path

    name = os.path.basename(video_path)[:-4]

    command = [sys.executable, "./FastVQA-and-FasterVQA/vqa.py", "-v", video_path]

    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, shell=True)
    
    type = str(process.pid)
    logger.info(f"Calculating VQA on file {name}")

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
            logger.error("Error Output:")
            logger.error(error_output)

    except Exception as e:
        logger.error(f"An error occurred: {str(e)}")

    #Parse the output
    for line in output_lines:
        if "The quality score of the video" in line:
            match = re.search(r'\b0\.\d+', line)
            if match:
                VQA = float(match.group())
                logger.debug("Calculated VQA: {VQA}")

    # Append this process's output to the shared list
    with lock:
        if name in shared_dict:
            local_list = shared_dict[name]  # Get the local copy
        else:
            local_list = []
        # Update the local copy
        local_list.append(VQA)
        # Write back the updated dictionary
        shared_dict[name] = local_list


    return process.returncode

def vfCropComandGenerator(file_path: str, crop: list, target_h_res: int) -> str:
    h_res_orig = getH_res(file_path)
    v_res_orig = getV_res(file_path)
    target_v_res = v_res_orig - crop[0] - crop[1]
    #-vf "crop=1920:970:0:60,scale=1280:-2"
    #TODO not constant flag neighbour for res test, lacroz for everything else
    command = f"crop={h_res_orig}:{target_v_res}:0:{crop[0]},scale={target_h_res}:-2:sws_flags=neighbor"
    return command

def _prepareRes_test(output_folder, file_path, h_res_values, number_of_scenes, scene_length, cq_value, video_profile, crop):

    if not os.path.exists(output_folder):
            # Create the directory
            os.makedirs(output_folder)
            logger.info(f'Directory "{output_folder}" created.')

    duration = getDuration(file_path)

    results = dict()

    if duration is not None:
        timestep = int(duration/(number_of_scenes+1))
        for timestamp in range(number_of_scenes):
            timestamp = timestamp + 1

            for h_resolution in h_res_values:

                output_name = f"{timestamp}_{h_resolution}_cq{cq_value}.mp4"
                output_path = os.path.join(output_folder, output_name)

                results[output_name] = dict()

                logger.debug(f"Creating test file {output_name}")

                #add resolution crop filter to alreadz existing filters
                resolution_filter = vfCropComandGenerator(file_path, crop, h_resolution)
                video_profile_modified = video_profile.copy()
                try:
                    index = video_profile_modified.index("-vf")
                    video_profile_modified[index+1] = video_profile_modified[index+1] + "," + resolution_filter
                except ValueError:
                    video_profile_modified.append("-vf")
                    video_profile_modified.append(resolution_filter)
                    #TODO cq for h265 and crf for av1
                    #TODO -hwaccel for different hw configs
                    # Define the ffmpeg command as a list of arguments
                command_append = [
                    '-t', str(scene_length),                  # Duration
                    '-crf', str(cq_value),                     # Constant Quality mode
                    #'-vf', f'scale={str(h_resolution)}:-1',   # Scale video width and maintain aspect ratio                
                    '-an',                                    # Disable audio
                    '-y',                                      # overvrite
                    "-sn",                                      # disable subtitles
                    output_path                               # Output file
                ]

                command_prepend =[
                    "ffmpeg",             # Command to run FFmpeg
                    "-ss", str(timestep*timestamp),     # Seek to the calculated timestamp
                    "-hwaccel",  "cuda",
                    "-i", file_path      # Input file path
                ]

                command = command_prepend + video_profile_modified + command_append
                

                testsFFMPEG(command)
# region tests FFMPEG
def testsFFMPEG(command) -> None:

    logger.debug(f"ffmpeg command: {command}")
    # Run the command and wait for it to complete
    process = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    #process = subprocess.run(command)

    # Check if the process completed successfully
    if process.returncode != 0:
        logger.error(f"FFmpeg finished with errors. Exit code: {process.returncode}")
        logger.error(process.stderr) 

def getDuration(input_path:str) -> int:

    # Run ffprobe to get video information in JSON format
    command = [
        'ffprobe',
        '-v', 'error',                         # Suppress non-error messages
        '-show_entries', 'format=duration',    # Extract duration
        '-of', 'json',                         # Output format as JSON
        input_path                             # Input file path
    ]
    
    # Execute the command
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    
    # Check if the command was successful
    if result.returncode != 0:
        logger.error(f"Error occurred while running ffprobe: {result.stderr}")
        return None

    # Parse the JSON output
    ffprobe_output = result.stdout
    
    if not ffprobe_output:
        logger.error("No output received from ffprobe.")
        return None
    
    data = None
    try:
        data = json.loads(ffprobe_output)
    except json.JSONDecodeError:
        logger.error("Error decoding JSON output.")
        return None
    
    # Extract duration from the JSON data
    if 'format' not in data or 'duration' not in data['format']:
        logger.error("Duration information is missing in the JSON output.")
        return None
    
    duration = data['format']['duration']
    
    return float(duration)

def getH_res(video_path: str) -> int:
    # ffprobe command to get the stream info in JSON format
    command = [
        "ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
        "stream=width", "-of", "json", video_path
    ]
    
    # Run the command and capture the output
    try:
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        # Parse the JSON output
        ffprobe_output = json.loads(result.stdout)
        # Extract the width from the 'width' field in the stream
        width = int(ffprobe_output['streams'][0]['width'])
        return width
    except Exception as e:
        logger.error(f"An error occurred: {e}")
        return None
    
def getV_res(video_path: str) -> int:
    # ffprobe command to get the stream info in JSON format
    command = [
        "ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
        "stream=height", "-of", "json", video_path
    ]

    # Run the command and capture the output
    try:
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        # Parse the JSON output
        ffprobe_output = json.loads(result.stdout)
        # Extract the height from the 'height' field in the stream
        height = int(ffprobe_output['streams'][0]['height'])
        return height
    except Exception as e:
        logger.error(f"An error occurred: {e}")
        return None
    
def getVMAF(reference_file, distorted_file, threads=8) -> float:
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
    # Run the command and wait for it to complete
    process = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    # Check if the process completed successfully
    if process.returncode == 0:
        logger.debug(f"VMAF calculation completed successfully")
        # Load the VMAF results from the output file
        with open("VMAFlog.json", 'r') as file:
            for line in file:
                if '<metric name="vmaf"' in line:
                    match = re.findall(r"(?<=harmonic_mean=\").*\d", line)
                    if match: vmaf_score = float(match[0])
                    else: vmaf_score = 0
                
                    return vmaf_score
    else:
        logger.error(f"FFmpeg finished with errors. Exit code: {process.returncode}")
        logger.error(process.stderr)  # Display the error output

# region getCQ
def getCQ(workspace: str, orig_video_path : str, h_res, cq_values: list, number_of_scenes:int, threashold_variable: float, video_profile: list, crop: list, cq_reference = 1, scene_length = 60, threads=6, keep_best_scenes=0.6) -> float:
    
    if len(cq_values) != 4:
        logger.error("cq values list different size")
        return
    
    cq_values.sort()
    
    name = str(os.path.basename(orig_video_path)[:-4]) + "_cq"
    video_folder = os.path.join(workspace, name)

    if not os.path.exists(video_folder):
            # Create the directory
            os.makedirs(video_folder)
            logger.debug(f'Directory "{video_folder}" created.')

    duration = getDuration(orig_video_path)

    results = dict()

    if duration is not None:
        timestep = int(duration/(number_of_scenes+1))

        reference_files = list()

        #genereate reference
        for timestamp in range(number_of_scenes):
            timestamp = timestamp + 1

            output_name = f"{timestamp}_reference.mp4"
            output_path = os.path.join(video_folder, output_name)

            logger.debug(f"Creating reference file {output_name}")
         
            _createAndTestVMAF(output_path, orig_video_path, h_res, cq_reference, timestamp*timestep, scene_length, video_profile, crop, None, threads)
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

                output_name = f"{timestamp}_{cq_values[position]}.mp4"
                output_path = os.path.join(video_folder, output_name)

                logger.debug(f"Getting VMAF result for: {output_name}")
            
                results[timestamp][cq_values[position]] = _createAndTestVMAF(output_path, orig_video_path, h_res, cq_values[position], timestamp*timestep, scene_length, video_profile, crop, reference_files[timestamp-1], threads)

        #get optimized VMAF value
        output_name = f"1_{cq_values[1]}.mp4"
        output_path = os.path.join(video_folder, output_name)
        logger.debug(f"Getting VMAF result for: {output_name}")
        optimization_VMAF = _createAndTestVMAF(output_path, orig_video_path, h_res, cq_values[1], 1*timestep, scene_length, video_profile, crop, reference_files[0], threads)

        for key in results.keys():
            results[key]
            results[key][cq_values[1]] = optimization_VMAF

        #calculate VMAF difference to cq15
        subtracted_results = dict()
        for scene in results.keys():
            subtracted_results[scene] = dict()
            subtracted_results[scene][cq_values[0]]=0
            subtracted_results[scene][cq_values[1]]=results[scene][cq_values[0]]-results[scene][cq_values[1]]
            subtracted_results[scene][cq_values[2]]=results[scene][cq_values[0]]-results[scene][cq_values[2]]
            subtracted_results[scene][cq_values[3]]=results[scene][cq_values[0]]-results[scene][cq_values[3]]

        calculated_CQs = list()
        for key in subtracted_results.keys():
            x = np.array(list(subtracted_results[key].keys()))  # The x-values
            y = np.array(list(subtracted_results[key].values()))  # The y-values
            a, b, c = np.polyfit(x, y, 2)
            logger.debug(f"CQ polynomial: {a}, {b}, {c}")
            discriminant = b**2 - 4*a*(c-threashold_variable)
            logger.debug(f"CQ discriminant: {discriminant}")
            if discriminant >= 0:
                solution = (-b + np.sqrt(discriminant)) / (2 * a)
                calculated_CQs.append(solution)
            else:
                logger.error("No solution was found")

        #remove worst scenes and make average
        calculated_CQs = sorted(calculated_CQs)
        logger.debug("calculated CQs:")
        logger.debug(calculated_CQs)
        to_keep = math.ceil(len(calculated_CQs)*keep_best_scenes)
        calculated_CQs = calculated_CQs[:to_keep]
        logger.debug("Filtered CQs")
        logger.debug(calculated_CQs)

        target_cq = 0
        for value in calculated_CQs:
            target_cq = target_cq + value
        target_cq = target_cq/len(calculated_CQs)

        target_cq = round(target_cq * 2) / 2
        logger.info(f"Video has calculated CQ of {target_cq}")
    #endregion
        return target_cq

def _createAndTestVMAF(output_path: str, orig_video_path : str, h_res, cq_value, start_time, scene_length, video_profile: list, crop: list, reference_video = None, threads = 6):

    #add resolution filter to alreadz existing filters
    resolution_filter = vfCropComandGenerator(orig_video_path, crop, h_res)
    video_profile_modified = video_profile.copy()
    try:
        index = video_profile_modified.index("-vf")
        video_profile_modified[index+1] = video_profile_modified[index+1] + "," + resolution_filter
    except ValueError:
        video_profile_modified.append("-vf")
        video_profile_modified.append(resolution_filter)

    command_append = [
        '-t', str(scene_length),                  # Duration
        '-crf', str(cq_value),                     # Constant Quality mode
        #'-vf', f'scale={str(h_resolution)}:-1',   # Scale video width and maintain aspect ratio                
        '-an',                                    # Disable audio
        '-y',                                      # overvrite
        "-sn",                                     # disable subtitles
        output_path                               # Output file
    ]

    command_prepend =[
        "ffmpeg",             # Command to run FFmpeg
        "-ss", str(start_time),     # Seek to the calculated timestamp
        "-hwaccel",  "cuda",
        "-i", orig_video_path      # Input file path
    ]

    command = command_prepend + video_profile_modified + command_append


    testsFFMPEG(command)

    if reference_video is not None:
        VMAF_value = getVMAF(reference_video, output_path, threads)
        logger.debug(VMAF_value)
        return VMAF_value
    else:
        return None

#region Num of Channels
def getNumOfChannels(orig_video_path: str, workspace: str, simmilarity_cutoff: float, duration: int)-> int:

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
            return

        logger.debug(f"The audio file has {num_channels} channels. Comparing channels using MSE:")

        mse_list = list()
        channel_list = [True] * num_channels


        # Compare each pair of channels
        for i in range(num_channels):
            for j in range(i + 1, num_channels):
                #mse = calculate_mse(y[:, i], y[:, j])
                mse = np.mean((y[:, i] - y[:, j]) ** 2)
                if mse in mse_list or mse <= simmilarity_cutoff:
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
            return 1
        
        logger.info(f"There are at least {len(output)} uniqe channels:")
        logger.info(output)
        if len(output) == 3:
            return 4
        if len(output) >= 5:
            return 6
        return len(output)

def _extractAudio(orig_video_path: str, work_folder: str, duration: int) -> None: 

    try:
            
        # Create output filename by replacing input extension with the audio file extension
        name = str(os.path.basename(orig_video_path)[:-4]) + ".wav"
        output_audio = os.path.join(work_folder, name)
        #output_audio = input_movie.rsplit('.', 1)[0] + f".{extension}"
        
        # Run FFmpeg command to extract the audio
        extract_command = ["ffmpeg", "-i", orig_video_path, "-vn", "-acodec", "pcm_s16le", "-t", str(duration), output_audio, "-y"]
        logger.debug(f"ffmpeg command: {extract_command}")
        process = subprocess.run(extract_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        return output_audio
    
    except Exception as e:
        logger.error(f"An error occurred: {e}")



#region Blackbars
def detectBlackbars(orig_video_path: str, workspace: str, frames_to_detect: int) -> list:
    
    name = str(os.path.basename(orig_video_path)[:-4]) + "_blackDetection"
    work_folder = os.path.join(workspace, name)

    if not os.path.exists(work_folder):
            # Create the directory
            os.makedirs(work_folder)
            logger.debug(f'Directory "{work_folder}" created.')

    movie_duration = getDuration(orig_video_path)
    timestep = int(movie_duration/(frames_to_detect+1))

    black_top = [0] * frames_to_detect
    black_bottom = [0] * frames_to_detect

    for timestamp in range(frames_to_detect):
        timestamp = timestamp + 1

        picture_name = str(timestamp) + ".png"
        target_name = os.path.join(work_folder, picture_name)
        exportFrame(orig_video_path, target_name, timestamp*timestep)
        

        im = Image.open(target_name, 'r')
        pix = im.load()

        for i in range(0, im.size[1], 1):
            if all(channel < 10 for channel in pix[im.size[0] // 2, i]):
                black_top[timestamp-1] += 1
            else:
                break

        for i in range(im.size[1]-1, -1, -1):
            if all(channel < 10 for channel in pix[im.size[0] // 2, i]):
                black_bottom[timestamp-1] += 1
            else:
                break

    black_top_result = min(black_top)
    black_bottom_result = min(black_bottom)
    if black_bottom_result != 0 or black_top_result != 0:
        logger.info(f"Black bars detected: {black_top_result}pix from top, {black_bottom_result}pix from bottom")
    else:
        logger.info("No black bars detected")

    return [black_top_result, black_bottom_result]

def exportFrame(orig_video_path: str, target_name_path: str, time: int, png_quality: int = 2) -> None:

    #print(time)
    command = [
    'ffmpeg', '-ss', f"{time}", '-i', orig_video_path,
    '-frames:v', '1', '-q:v', str(png_quality), '-update', '1', '-y', target_name_path
    ]

    logger.debug("Export frame ffmpeg command")
    logger.debug(command)


    process = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    #process = subprocess.run(command)

    # Check if the process completed successfully
    if process.returncode != 0:
        logger.error(f"FFmpeg finished with errors. Exit code: {process.returncode}")
        logger.error(process.stderr)



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
    print(vfCropComandGenerator(file, crop, 720))
    end = time.time()
    print(f"this took {end - start}s")