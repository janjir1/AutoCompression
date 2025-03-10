import subprocess, os, json
import logging
import AVTest

# Retrieve the logger once at the module level
logger = logging.getLogger("AppLogger")

def vfCropComandGenerator(file_path: str, crop: list, target_h_res: int) -> str:
    h_res_orig = AVTest.getH_res(file_path)
    v_res_orig = AVTest.getV_res(file_path)
    target_v_res = v_res_orig - crop[0] - crop[1]
    #-vf "crop=1920:970:0:60,scale=1280:-2"
    #TODO not constant flag neighbour for res test, lacroz for everything else
    command = f"crop={h_res_orig}:{target_v_res}:0:{crop[0]},scale={target_h_res}:-2:sws_flags=neighbor"
    return command

def compress_HEVC(file, profile, output_file, crop, target_res, target_cq, channels) -> bool:
    resolution_filter = AVTest.vfCropComandGenerator(file, crop, target_res)
    video_profile_modified = profile["video"].copy()

    #TODO add max thread count and HDR

    try:
        index = video_profile_modified.index("-vf")
        video_profile_modified[index+1] = video_profile_modified[index+1] + "," + resolution_filter
    except ValueError:
        video_profile_modified.append("-vf")
        video_profile_modified.append(resolution_filter)

    command_append = [
        '-cq', str(target_cq),                     # Constant Quality mode                
        '-y',                                      # overvrite
        output_file                                # Output file
    ]

    command_prepend =[
        "ffmpeg",                                  # Command to run FFmpeg
        "-i", file                                 # Input file path
    ]

    if "stereo" in profile and channels == 2:
        command = command_prepend + video_profile_modified + profile["stereo"] + command_append
    else:
        command = command_prepend + video_profile_modified + profile["audio"] + command_append

    logger.debug(f"ffmpeg command: {command}")
    #process = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    process = subprocess.run(command)


    #region Post
    # Check if the process completed successfully
    if process.returncode != 0:
        logger.error(f"FFmpeg finished with errors. Exit code: {process.returncode}")
        logger.error(process.stderr)
        return False
    
    if not os.path.isfile(output_file):
        logger.error("output file not found")
        return False
    
    logger.info(f"Conversion finished succesfully")

#TODO add logger
def delete_small_file(file_path, size_limit=2048):
    """Delete the file if its size is less than the specified limit (default: 2 KB)."""
    try:
        if os.path.isfile(file_path):  # Ensure it's a file
            file_size = os.path.getsize(file_path)
            if file_size < size_limit:
                os.remove(file_path)
                print(f"Deleted: {file_path} (Size: {file_size} bytes)")
                return True
            else:
                print(f"File is larger than {size_limit} bytes: {file_path}")
                return False
        else:
            print(f"File not found: {file_path}")
            return True
    except PermissionError:
        print(f"Permission denied: {file_path}")
        return None
    except Exception as e:
        print(f"Error deleting file {file_path}: {e}")
        return None

def get_video_metadata(input_file, workspace, extract_dynamic = False, relative_tools_path = "tools", cleanup = True):
    # Ensure workspace exists
    os.makedirs(workspace, exist_ok=True)

    # First command to get general metadata
    cmd = ["ffprobe", "-v", "error", "-of", "json", "-show_streams", "-show_format", input_file]
    
    print("Running command:", " ".join(cmd))
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    
    # Handle potential empty metadata
    try:
        metadata = json.loads(result.stdout) if result.stdout.strip() else {}
    except json.JSONDecodeError:
        metadata = {}

    # Find video stream
    video_stream = next((stream for stream in metadata.get("streams", []) if stream.get("codec_type") == "video"), {})

    # Extract color info
    color_primaries = video_stream.get("color_primaries", None)
    color_trc = video_stream.get("color_transfer", None)
    colorspace = video_stream.get("color_space", None)

    output_metadata = list()
    if color_primaries is not None: output_metadata += ["color_primaries", color_primaries]
    if color_trc is not None: output_metadata += ["color_transfer", color_trc]
    if colorspace is not None: output_metadata += ["color_space", colorspace]

    # Extract dynamic metadata
    metadata_file = None

    if extract_dynamic:
        
        video_stram = os.path.join(workspace, "dynamic_extract.hevc")
        hevc_command = ["ffmpeg", "-i", input_file, "-map", "0:v:0", "-c", "copy", "-bsf:v", "hevc_mp4toannexb", "-f", "hevc",  video_stram, "-y"]
        print(hevc_command)
        result = subprocess.run(hevc_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        print("STDOUT:", result.stdout)
        print("STDERR:", result.stderr)

        #DOVI
        dovi_metadata_file = os.path.join(workspace, "dovi_metadata.bin")
        dovi_tool_path = os.path.join(relative_tools_path, "dovi_tool.exe")
        dovi = f"{dovi_tool_path} extract-rpu -i {video_stram} -o {dovi_metadata_file}"

        result = subprocess.run(dovi, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        print("STDOUT:", result.stdout)
        print("STDERR:", result.stderr)

        deleted = delete_small_file(dovi_metadata_file)

        if deleted is None:
            print("problem")
            return False
        elif deleted is True:

            #HDR10+
            HDR10_metadata_file = os.path.join(workspace, "HDR10_dynamic_metadata.json")
            HDR10plus_tool_path = os.path.join(relative_tools_path, "hdr10plus_tool.exe")
            HDR10plus = f"{HDR10plus_tool_path} extract {video_stram} -o {HDR10_metadata_file}"

            result = subprocess.run(HDR10plus, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            print("STDOUT:", result.stdout)
            print("STDERR:", result.stderr)

            deleted = delete_small_file(HDR10_metadata_file)

            if deleted is False:
                metadata_file = {"hdr10_plus": HDR10_metadata_file}

        elif deleted is False:
            metadata_file = {"dolby-vision": dovi_metadata_file}

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

    return output_metadata, metadata_file

def compress(file, profile, output_file, crop, target_res, target_cq, channels = False, start = False, duration = False, subtitles = False, tool_path = r"tools\HandBrakeCLI.exe") -> bool:
    function_mapping = {
    "HandbrakeAV1": compress_HandbrakeAV1
    }
    if profile["function"] in function_mapping:
        function_mapping[profile["function"]](file, profile, output_file, crop, target_res, target_cq, channels, start, duration, subtitles, tool_path)

def compress_HandbrakeAV1(file, profile, output_file, crop, target_res, target_cq, channels, start, duration, subtitles, tool_path) -> bool:

    command = [
        tool_path,
        '-i', file,
        '-o', output_file,
        '-q', str(target_cq),
        '--crop', f'0:{str(crop[0])}:0:{str(crop[1])}'
        '--width', str(target_res),
        '--auto-anamorphic',
        '--all-subtitles', 
        '--srt-codeset',  'UTF-8'
        ]

    if start or duration:
        sub = [
            '--start-at',  f'duration:{str(start)}',
            '--stop-at-at',  f'duration:{str(duration)}',
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
            '--start-at',  f'duration:{str(start)}',
            '--stop-at-at',  f'duration:{str(duration)}',
        ]
        command = command + sub
    else:
        #TODO: disable audio
        None


    command = command + profile["video"]

    logger.debug(f"ffmpeg command: {command}")
    #process = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    process = subprocess.run(command)


    #region Post
    # Check if the process completed successfully
    if process.returncode != 0:
        logger.error(f"FFmpeg finished with errors. Exit code: {process.returncode}")
        logger.error(process.stderr)
        return False
    
    if not os.path.isfile(output_file):
        logger.error("output file not found")
        return False
    
    logger.info(f"Conversion finished succesfully")