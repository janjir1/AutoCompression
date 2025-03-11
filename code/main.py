import yaml
from AVTest import runTests
import logging
from logger_setup import setup_logger
import os, subprocess, traceback
import json
import compressor

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

    result = compressor.compress(file, profile, output_file, crop, target_res, target_cq, channels, subtitles= True)
    if not result:
        return False

    logger.info(f"Conversion finished succesfully")

    output_file_size_GB = os.stat(output_file).st_size / (1024 * 1024 * 1024)
    
    logger.info(f"Output file is {output_file_size_GB:.3f}GB")
    logger.info(f"Output file is {(orig_file_size_GB/output_file_size_GB):.3f}x size of original")

    return output_file_size_GB


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

    file = r"C:\Users\Janjiri\Videos\Dovi.mkv"
    profile_path = r"Profiles\AV1_archive_software.yaml"
    workspace = r"D:\Files\Projects\AutoCompression\workspace\DoVi_1080_5"

    if not os.path.exists(workspace):
            # Create the directory
            os.makedirs(workspace)
            print(f'Directory "{workspace}" created.')

    log_path = os.path.join(workspace, "app.log")
    logger = setup_logger(log_level=logging.INFO, log_file=log_path)
    profile, settings = readProfile(profile_path)
    print(profile)
    #passed = compressor.compress(file, profile, 'test.mkv', [20, 20], 720, 32, 2, 5, 5)


    passed = compressAV(file, workspace, profile_path, 3)

