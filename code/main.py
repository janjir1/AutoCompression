import yaml
import AVTest
import logging
from logger_setup import setup_logger
import os, subprocess, traceback
import json

def runTests(file: str, workspace: str, profile, settings, threads: int): 
    try:
        orig_res = AVTest.getH_res(file)
        logger.info(f"Original resolution is {orig_res}")
    except Exception as e:
        logger.error("Not able to detect horiontal resolution")
        logger.debug("Failed due to reason:")
        logger.debug("".join(traceback.format_exception(type(e), e, e.__traceback__)))
        return False

    try:
        crop = AVTest.detectBlackbars(file, workspace, 10)
    except Exception as e:
        logger.warning("Black bar detection failed")
        logger.debug("Failed due to reason:")
        logger.debug("".join(traceback.format_exception(type(e), e, e.__traceback__)))
        crop = [0, 0]
        logger.info(f"Black bars set as {crop[0]}, {crop[1]}")

    try:
        target_res = AVTest.getRes_parallel(workspace, file, [854, 3840], 15, settings["res_decode"], profile["video"], crop, num_of_VQA_runs=3, threads=threads)
    except Exception as e:
        logger.warning("Resolution detection failed")
        logger.debug("Failed due to reason:")
        logger.debug("".join(traceback.format_exception(type(e), e, e.__traceback__)))
        logger.info("Keeping original resolution")
        target_res = orig_res
        

    try:
        target_cq = AVTest.getCQ(workspace, file, target_res, [15, 18, 27, 36], 3, settings["cq_threashold"], profile["video"], crop, scene_length=50, threads=threads)
    except Exception as e:
        logger.warning("CQ test failed")
        logger.debug("Failed due to reason:")
        logger.debug("".join(traceback.format_exception(type(e), e, e.__traceback__)))
        target_cq = settings["defalut_cq"]
        logger.info(f"Video has calculated CQ of {target_cq}")

    try:
        channels = AVTest.getNumOfChannels(file, workspace, 0.001, 1200)
    except Exception as e:
        logger.warning("Unable to get number of audio chanels")
        logger.debug("Failed due to reason:")
        logger.debug("".join(traceback.format_exception(type(e), e, e.__traceback__)))
        channels = 2
        logger.info(f"Export will have {channels} channels")

    return orig_res, crop, target_res, target_cq, channels


def compressAV(file: str, workspace: str, profile_path: str, threads: int) -> bool:

    if not os.path.isfile(file):
        logger.error("file not found")
        return False

    if not os.path.exists(workspace):
            # Create the directory
            os.makedirs(workspace)
            print(f'Directory "{workspace}" created.')
    
    output_file = os.path.join(workspace, os.path.splitext(os.path.basename(file))[0] + ".mkv")

    try:
        profile, settings = readProfile(profile_path)
    except Exception as e:
        logger.error("Not able to read profile")
        logger.debug("Failed due to reason:")
        logger.debug("".join(traceback.format_exception(type(e), e, e.__traceback__)))
        return False
    
    #region logger begginig
    logger.info("Starting AV conversion script.")
    logger.info(f"file path: {file}")
    logger.info(f"workspace path: {workspace}")
    logger.info(f"profile path: {profile_path}")
    logger.debug(f"resolution decode table:")
    logger.debug(settings["res_decode"])
    logger.debug(f'quality threashold value: {settings["cq_threashold"]}')
    #endregion section 

    logger.debug('Profile values:')
    logger.debug(profile)
   
    orig_file_size_GB = os.stat(file).st_size / (1024 * 1024 * 1024)
    logger.info(f"Original file is {orig_file_size_GB:.3f}GB")

    orig_res, crop, target_res, target_cq, channels = runTests(file, workspace, profile, settings, threads)
    #TODO dynamic metadata and dolby vision


    #region FFMPEG
    #add resolution filter to alreadz existing filters
    resolution_filter = AVTest.vfCropComandGenerator(file, crop, target_res)
    video_profile_modified = profile["video"].copy()

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

    output_file_size_GB = os.stat(output_file).st_size / (1024 * 1024 * 1024)
    if output_file_size_GB < 0.0000039101:
        logger.error("Output is less then 1 cluster (4kB)")
        return False
    
    logger.info(f"Output file is {output_file_size_GB:.3f}GB")
    logger.info(f"Output file is {(orig_file_size_GB/output_file_size_GB):.3f}x size of original")
    return True


def readProfile(yaml_file):
    with open(yaml_file, 'r') as file:
        loaded_data = yaml.safe_load(file)

    profile = dict()
    for key, value in loaded_data.items():
        profile[key] = list()
        for subvalue in value.items():
            profile[key].append(str(subvalue[0]))
            profile[key].append(str(subvalue[1]))

    settings = loaded_data["test_settings"]

    return profile, settings

if __name__ == '__main__':
    file = r"E:\Filmy\hrané\Komedie\Alvin a Chipmunkove 2 SD.avi"
    profile_path = r"Profiles\h265_slow_nvenc.yaml"
    workspace = r"D:\Files\Projects\AutoCompression\workspace\Alvin"
    if not os.path.exists(workspace):
            # Create the directory
            os.makedirs(workspace)
            print(f'Directory "{workspace}" created.')

    log_path = os.path.join(workspace, "app.log")
    logger = setup_logger(log_level=logging.INFO, log_file=log_path)
    passed = compressAV(file, workspace, profile_path, 4)
    print(passed)
