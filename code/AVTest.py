import subprocess
import re, os
import json
from multiprocessing import Pool, Manager
import time
import math
import numpy as np
import soundfile as sf

#Meassure video using FasterVQA, number of runs for averaging
def getVQA(video_path: str, num_of_runs: int = 4) -> int: #enter full path to video

    quality_score = []
    
    for i in range(num_of_runs):
        command = ["python", "./FastVQA-and-FasterVQA/vqa.py", "-v", video_path]
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
                print(f"Script exited with error code {process.returncode}")
                error_output = process.stderr.read()
                print("Error Output:", error_output)

        except Exception as e:
            print(f"An error occurred: {str(e)}")

        #Parse the output
        for line in output_lines:
            if "The quality score of the video" in line:
                match = re.search(r'\b0\.\d+', line)
                if match:
                    quality_score.append(float(match.group()))

    #get average
    average_quality = sum(quality_score) / len(quality_score)

    return average_quality

def getRes_parallel(workspace: str, orig_video_path : str, h_res_values: list, number_of_scenes:int, decode_table: dict,  video_profile: list, scene_length = 1, cq_value = 1, num_of_VQA_runs: int = 2, threads=6, keep_best_slopes=0.6,) -> int: #enter full path to video

    name = str(os.path.basename(orig_video_path)[:-4]) + "_res"
    video_folder = os.path.join(workspace, name)

    _prepareRes_test(video_folder, orig_video_path, h_res_values, number_of_scenes, scene_length, cq_value, video_profile)

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

    #determine regression slope for each scene
    regression_slope = list()
    for scene in sorted_dict.keys():
        res = sorted_dict[scene].keys()
        res_min = int(sorted(res)[1])
        res_max = int(sorted(res)[0])
        VQA_res_min = float(sorted_dict[scene][str(res_min)])
        VQA_res_max = float(sorted_dict[scene][str(res_max)])
        slope = (VQA_res_max-VQA_res_min)/(res_max-res_min)
        regression_slope.append(slope)

    if __name__ == '__main__':
        print(regression_slope)

    #remove worst scenes and make average
    regression_slope = sorted(regression_slope, reverse=True)
    to_keep = math.ceil(len(regression_slope)*keep_best_slopes)
    regression_slope = regression_slope[:to_keep]
    
    average_slope = 0
    for value in regression_slope:
        average_slope = average_slope + value
    average_slope = average_slope/len(regression_slope)

    print(f"average slope is: {average_slope}")

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

    print(f"Original resolution: {orig_res}, Target resolution: {target_res}")
    return target_res

def _run_VQA_process(video_path, shared_dict, lock):

    match = re.search(r'\d*(?=_cq\d.mp4)', video_path)
    if match:
        type = match.group()
    else: type = video_path

    name = os.path.basename(video_path)[:-4]

    command = ["python", "./FastVQA-and-FasterVQA/vqa.py", "-v", video_path]

    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, shell=True)
    
    type = str(process.pid)
    print(f"Calculating VQA on file {name}")

    output_lines = []
    try:
        for line in process.stdout:
            output_lines.append(line.strip())

        # Wait for the process to complete and get the exit code
        process.wait()
        
        # Check for errors
        if process.returncode != 0:
            print(f"Script exited with error code {process.returncode}")
            error_output = process.stderr.read()
            print("Error Output:", error_output)

    except Exception as e:
        print(f"An error occurred: {str(e)}")

    #Parse the output
    for line in output_lines:
        if "The quality score of the video" in line:
            match = re.search(r'\b0\.\d+', line)
            if match:
                VQA = float(match.group())

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

def _prepareRes_test(output_folder, file_path, h_res_values, number_of_scenes, scene_length, cq_value, video_profile):

    if not os.path.exists(output_folder):
            # Create the directory
            os.makedirs(output_folder)
            print(f'Directory "{output_folder}" created.')

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

                print(f"Creating test file {output_name}")

                    # Define the ffmpeg command as a list of arguments
                command_append = [
                    '-t', str(scene_length),                  # Duration
                    '-cq', str(cq_value),                     # Constant Quality mode
                    #'-vf', f'scale={str(h_resolution)}:-1',   # Scale video width and maintain aspect ratio                
                    '-an',                                    # Disable audio
                    '-y',                                      # overvrite
                    output_path                               # Output file
                ]

                command_prepend =[
                    "ffmpeg",             # Command to run FFmpeg
                    "-ss", str(timestep*timestamp),     # Seek to the calculated timestamp
                    "-i", file_path      # Input file path
                ]

                command = command_prepend + video_profile + command_append
                

                testsFFMPEG(command)

def testsFFMPEG(command) -> None:

    # Run the command and wait for it to complete
    process = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    #process = subprocess.run(command)

    # Check if the process completed successfully
    if process.returncode != 0:
        print(f"FFmpeg finished with errors. Exit code: {process.returncode}")
        print(process.stderr) 

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
        print(f"Error occurred while running ffprobe: {result.stderr}")
        return None

    # Parse the JSON output
    ffprobe_output = result.stdout
    
    if not ffprobe_output:
        print("No output received from ffprobe.")
        return None
    
    data = None
    try:
        data = json.loads(ffprobe_output)
    except json.JSONDecodeError:
        print("Error decoding JSON output.")
        return None
    
    # Extract duration from the JSON data
    if 'format' not in data or 'duration' not in data['format']:
        print("Duration information is missing in the JSON output.")
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
        print(f"An error occurred: {e}")
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
    #print(command)
    # Run the command and wait for it to complete
    process = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    # Check if the process completed successfully
    if process.returncode == 0:
        print(f"VMAF calculation completed successfully")
        # Load the VMAF results from the output file
        with open("VMAFlog.json", 'r') as file:
            for line in file:
                if '<metric name="vmaf"' in line:
                    match = re.findall(r"(?<=harmonic_mean=\").*\d", line)
                    if match: vmaf_score = float(match[0])
                    else: vmaf_score = 0
                
                    return vmaf_score
    else:
        print(f"FFmpeg finished with errors. Exit code: {process.returncode}")
        print(process.stderr)  # Display the error output

def getCQ(workspace: str, orig_video_path : str, h_res, cq_values: list, number_of_scenes:int, threashold_variable: float, video_profile: list, cq_reference = 1, scene_length = 60, threads=6, keep_best_scenes=0.6) -> float:
    
    if len(cq_values) != 4:
        print("cq values list different size")
        return
    
    cq_values.sort()
    
    name = str(os.path.basename(orig_video_path)[:-4]) + "_cq"
    video_folder = os.path.join(workspace, name)

    if not os.path.exists(video_folder):
            # Create the directory
            os.makedirs(video_folder)
            print(f'Directory "{video_folder}" created.')

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

            print(f"Creating reference file {output_name}")
         
            _createAndTestVMAF(output_path, orig_video_path, h_res, cq_reference, timestamp*timestep, scene_length, video_profile, None, threads)
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

                print(f"Getting VMAF result for: {output_name}")
            
                results[timestamp][cq_values[position]] = _createAndTestVMAF(output_path, orig_video_path, h_res, cq_values[position], timestamp*timestep, scene_length, video_profile, reference_files[timestamp-1], threads)

        #get optimized VMAF value
        output_name = f"1_{cq_values[1]}.mp4"
        output_path = os.path.join(video_folder, output_name)
        print(f"Getting VMAF result for: {output_name}")
        optimization_VMAF = _createAndTestVMAF(output_path, orig_video_path, h_res, cq_values[1], 1*timestep, scene_length, video_profile, reference_files[0], threads)

        for key in results.keys():
            results[key]
            results[key][cq_values[1]] = optimization_VMAF

    #region calculation
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
            discriminant = b**2 - 4*a*(c-threashold_variable)
            if discriminant >= 0:
                solution = (-b + np.sqrt(discriminant)) / (2 * a)
                calculated_CQs.append(solution)
            else:
                print("No solution was found")

        #remove worst scenes and make average
        calculated_CQs = sorted(calculated_CQs)
        if __name__ == '__main__':
            print(calculated_CQs)
        to_keep = math.ceil(len(calculated_CQs)*keep_best_scenes)
        calculated_CQs = calculated_CQs[:to_keep]

        print(calculated_CQs)

        target_cq = 0
        for value in calculated_CQs:
            target_cq = target_cq + value
        target_cq = target_cq/len(calculated_CQs)

        target_cq = round(target_cq * 2) / 2
        print(f"Video has calculated CQ of {target_cq}")
    #endregion
        return target_cq

def _createAndTestVMAF(output_path: str, orig_video_path : str, h_res, cq_value, start_time, scene_length, video_profile: list, reference_video = None, threads = 6):

    #add resolution filter to alreadz existing filters
    resolution_filter = f'scale={str(h_res)}:-1'
    try:
        index = video_profile.index("-vf")
        video_profile[index+1] = video_profile[index+1] + "," + resolution_filter
    except ValueError:
        video_profile.append("-vf")
        video_profile.append(resolution_filter)

    command_append = [
        '-t', str(scene_length),                  # Duration
        '-cq', str(cq_value),                     # Constant Quality mode
        #'-vf', f'scale={str(h_resolution)}:-1',   # Scale video width and maintain aspect ratio                
        '-an',                                    # Disable audio
        '-y',                                      # overvrite
        output_path                               # Output file
    ]

    command_prepend =[
        "ffmpeg",             # Command to run FFmpeg
        "-ss", str(start_time),     # Seek to the calculated timestamp
        "-i", orig_video_path      # Input file path
    ]

    command = command_prepend + video_profile + command_append


    testsFFMPEG(command)

    if reference_video is not None:
        return getVMAF(reference_video, output_path, threads)
    else:
        return None

def getNumOfChannels(orig_video_path: str, workspace: str, simmilarity_cutoff: float, duration: int)-> int:

    name = str(os.path.basename(orig_video_path)[:-4]) + "_channels"
    work_folder = os.path.join(workspace, name)



    if not os.path.exists(work_folder):
            # Create the directory
            os.makedirs(work_folder)
            print(f'Directory "{work_folder}" created.')

    act_duration = getDuration(orig_video_path)

    if act_duration is not None and act_duration >= duration:

        audio_file = _extractAudio(orig_video_path, work_folder, duration)

        y, sr = sf.read(audio_file) # Function to load the audio and extract the channels
        num_channels = y.shape[1] if len(y.shape) > 1 else 1  # Determine the number of channels

        if num_channels == 1:
            print("The audio file has only one channel (mono). No comparison needed.")
            return

        print(f"The audio file has {num_channels} channels. Comparing channels using MSE:")

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
                if __name__ == '__main__':
                    print(f"MSE between channel {i + 1} and channel {j + 1}: {mse}")

        if __name__ == '__main__':
            print(channel_list)

        output = list()
        for i in range(len(channel_list)):
            if channel_list[i] == True:
                output.append(i+1)

        if len(output) == 0:
            return 1
        
        print(f"There are at least {len(output)} uniqe channels:")
        print(output)
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
        subprocess.run(extract_command)
        print(f"Audio extracted to: {output_audio}")
        return output_audio

    
    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == '__main__':
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
