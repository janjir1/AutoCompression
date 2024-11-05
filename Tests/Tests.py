import AVTest
import os
import yaml
from datetime import datetime
import time

def resolutionTest(file_path, output_folder, h_resolution_values, number_of_scenes, scene_length = 1, cq_value = 1, VQAs_per_scene = 2):

    if not os.path.exists(output_folder):
        # Create the directory
        os.makedirs(output_folder)
        print(f'Directory "{output_folder}" created.')

    duration = AVTest.getDuration(file_path)

    results = dict()

    if duration is not None:
        timestep = int(duration/(number_of_scenes+1))
        for timestamp in range(number_of_scenes):
            timestamp = timestamp + 1

            for h_resolution in h_resolution_values:

                output_name = f"{timestamp}_{h_resolution}_cq{cq_value}.mp4"
                output_path = os.path.join(output_folder, output_name)

                results[output_name] = dict()

                print(f"Starting test file {output_name}")

                    # Define the ffmpeg command as a list of arguments
                command = [
                    'ffmpeg',
                    '-y',                                     # Force overwrite without confirmation
                    '-ss', str(timestamp*timestep),           # Start time specified by the user
                    '-i', file_path,                          # Input file
                    '-t', str(scene_length),                  # Duration
                    '-c:v', 'hevc_nvenc',                     # Use GPU with NVIDIA NVENC for H.265
                    '-preset', 'slow',                        # Preset for encoding speed/quality
                    '-cq', str(cq_value),                     # Constant Quality mode
                    '-vf', f'scale={str(h_resolution)}:-1',   # Scale video width and maintain aspect ratio                
                    '-an',                                    # Disable audio
                    output_path                               # Output file
                ]

                AVTest.testsFFMPEG(command)
                print("  -File created, getting Video Quality Assesment")
                results[output_name]["VQA"] = AVTest.getVQA(output_path, VQAs_per_scene)
                print(f"  -{output_name} has VQA score of {results[output_name]["VQA"]}")
                results[output_name]["size"] = round(os.path.getsize(output_path)/(1024 * 1024), 2)

        return results

    else: print("Couldnt get file length")


def cqTest(file_path, output_folder, cq_values, number_of_samples):

    if not os.path.exists(output_folder):
        # Create the directory
        os.makedirs(output_folder)
        print(f'Directory "{output_folder}" created.')
    else:
        print(f'Directory "{output_folder}" already exists.')

    duration = AVTest.getDuration(file_path)

    results = dict()

    if duration is not None:
        timestep = int(duration/(number_of_samples+1))
        for timestamp in range(number_of_samples):
            timestamp = timestamp + 1

            print(f"Generating {timestamp}. cq0 file")

            orig_name = f"{timestamp}_cq0.mp4"
            orig_path = os.path.join(output_folder, orig_name)
            results[orig_name] = dict()

            command = [
                    'ffmpeg',
                    '-y',                                     # Force overwrite without confirmation
                    '-ss', str(timestamp*timestep),           # Start time specified by the user
                    '-i', file_path,                          # Input file
                    '-t', "60",                               # Duration of 1 minute
                    '-c:v', 'hevc_nvenc',                     # Use GPU with NVIDIA NVENC for H.265
                    '-preset', 'slow',                        # Preset for encoding speed/quality
                    '-cq', '0',                     # Constant Quality mode with highest quality (0)           
                    '-an',                                    # Disable audio
                    orig_path                               # Output file
                ]

            AVTest.testsFFMPEG(command)
            print("  -File created, getting Video Quality Assesment")
            results[orig_name]["VQA"] = AVTest.getVQA(orig_path)
            print(f"  -{orig_name} has VQA score of {results[orig_name]["VQA"]}")
            results[orig_name]["VMAF"] = 1
            results[orig_name]["size"] = round(os.path.getsize(orig_path)/(1024 * 1024), 2)


            for cq_value in cq_values:

                output_name = f"{timestamp}_cq{cq_value}.mp4"
                output_path = os.path.join(output_folder, output_name)

                results[output_name] = dict()

                print(f"Starting test file {output_name}")

                    # Define the ffmpeg command as a list of arguments
                command = [
                    'ffmpeg',
                    '-y',                                     # Force overwrite without confirmation
                    '-ss', str(timestamp*timestep),           # Start time specified by the user
                    '-i', file_path,                          # Input file
                    '-t', "60",                               # Duration of 1 minute
                    '-c:v', 'hevc_nvenc',                     # Use GPU with NVIDIA NVENC for H.265
                    '-preset', 'slow',                        # Preset for encoding speed/quality
                    '-cq', str(cq_value),                     # Constant Quality mode with highest quality (0)           
                    '-an',                                    # Disable audio
                    output_path                               # Output file
                ]

                vmaf_output_file = os.path.join(output_folder, f"{timestamp}_VMAFlog.json")

                AVTest.testsFFMPEG(command)
                print("  -File created, getting Video Quality Assesment")
                results[output_name]["VQA"] = AVTest.getVQA(output_path)
                print(f"  -{output_name} has VQA score of {results[output_name]["VQA"]}")
                results[output_name]["VMAF"] = AVTest.getVMAF(orig_path, output_path, vmaf_output_file)
                print(f"  -{output_name} has VMAF score of {results[output_name]["VMAF"]}")
                results[output_name]["size"] = round(os.path.getsize(output_path)/(1024 * 1024), 2)

        return results

    else: print("Couldnt get file length")


files_path = r"D:\Files\Projects\AutoCompression\Tests\Optimization"
output_folder = r"D:\Files\Projects\AutoCompression\Tests\Optimization"

h_resolution_values = [854, 3840]
cq_values = [1, 15, 18, 27, 36]
number_of_scenes = 10

files = [f for f in os.listdir(files_path) if os.path.isfile(os.path.join(files_path, f))]

for file in files:

    file_path = os.path.join(files_path, file)

    folder_name = os.path.splitext(file)[0]  # Remove file extension for folder name
    output_folder = os.path.join(files_path, folder_name)

    # Create the directory if it does not exist
    if not os.path.exists(output_folder):
        os.makedirs(output_folder)
        print(f"Directory created: {output_folder}")
    else:
        print(f"Directory already exists: {output_folder}")

    try:
        yaml_path = os.path.join(output_folder, "resTest.yaml")
        start = time.time()
        results = resolutionTest(file_path, output_folder, h_resolution_values, number_of_scenes)
        end = time.time()
        print(f"resolution test with {number_of_scenes} scenes took {end - start}s")
        with open(yaml_path, 'w') as file:
            yaml.dump(results, file, default_flow_style=False)
    except Exception as e:
        print(f"An unexpected error occurred in file {file}")

    """
    try:
        yaml_path = os.path.join(output_folder, "cqTest.yaml")
        results = cqTest(file_path, output_folder, cq_values, number_of_scenes)
        with open(yaml_path, 'w') as file:
            yaml.dump(results, file, default_flow_style=False)
    except Exception as e:
        print(f"An unexpected error occurred in file {file}")
    """
    
# Get the current date and time
now = datetime.now()

# Print the current time in the format HH:MM:SS
print("Current time:", now.strftime("%H:%M:%S"))