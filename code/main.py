from gc import enable
from sympy import li
import yaml
from AVTest import runTests
import logging
import logger_setup
import os, subprocess, traceback
import json
import compressor2
import readers

def compressAV(file: str, workspace: str, profile_path: str, settings_path: str) -> bool:

    if not os.path.isfile(file):
        logger.error("file not found")
        return False

    if not os.path.exists(workspace):
            # Create the directory
            os.makedirs(workspace)
            print(f'Directory "{workspace}" created.')
    
    output_file = os.path.join(workspace, os.path.splitext(os.path.basename(file))[0])

    try:
        profile, profile_settings = readers.readProfile(profile_path)
    except Exception as e:
        logger.error("Not able to read profile file")
        logger.debug("Failed due to reason:")
        logger.debug("".join(traceback.format_exception(type(e), e, e.__traceback__)))
        return False
    
    try:
        settings = readers.readSettings(settings_path)
    except Exception as e:
        logger.error("Not able to read settings file")
        logger.debug("Failed due to reason:")
        logger.debug("".join(traceback.format_exception(type(e), e, e.__traceback__)))
        return False
    
    #region logger begginig
    logger.info("Starting AV conversion script.")
    logger.info(f"file path: {file}")
    logger.info(f"workspace path: {workspace}")
    logger.info(f"profile path: {profile_path}")
    logger.debug(f"resolution decode table:")
    logger.debug(profile_settings["res_decode"])
    logger.debug(f'quality threashold value: {profile_settings["cq_threashold"]}')
    #endregion section 

    logger.debug('Profile values:')
    logger.debug(profile)
   
    orig_file_size_GB = os.stat(file).st_size / (1024 * 1024 * 1024)
    logger.info(f"Original file is {orig_file_size_GB:.3f}GB")

    orig_res, crop, target_res, target_cq, channels = runTests(file, workspace, profile, profile_settings, settings)

    result = compressor2.compress(file, profile, output_file, workspace, crop, target_res, target_cq, False, False)
    if not result:
        return False

    logger.info(f"Conversion finished succesfully")

    output_file_size_GB = os.stat(output_file).st_size / (1024 * 1024 * 1024)
    
    logger.info(f"Output file is {output_file_size_GB:.3f}GB")
    logger.info(f"Output file is {(orig_file_size_GB/output_file_size_GB):.3f}x size of original")

    return output_file_size_GB

     

if __name__ == '__main__':

    file = r"E:\Filmy\hrané\Action\James Bond - Spectre.mkv"
    profile_path = r"Profiles\h265_slow_nvenc.yaml"
    settings_path = r"Profiles\Test_settings.yaml"
    workspace = r"D:\Files\Projects\AutoCompression\workspace\test1"

    if not os.path.exists(workspace):
            # Create the directory
            os.makedirs(workspace)
            print(f'Directory "{workspace}" created.')

    log_path = os.path.join(workspace, "app.log")
    logger = logger_setup.primary_logger(log_level=logging.INFO, log_file=log_path)
    log_path = os.path.join(workspace, "stream.log")
    stream_logger = logger_setup.file_logger(log_path, log_level=logging.DEBUG)

    #profile, profile_settings = readProfile(profile_path)
    #print(profile_settings)
    #passed = compressor.compress(file, profile, 'test.mkv', [20, 20], 720, 32, 2, 5, 5)

    #settings = readSettings(r"D:\Files\Projects\AutoCompression\Profiles\Test_settings.yaml")
    #print(settings)


    passed = compressAV(file, workspace, profile_path, settings_path)

    """TODO:
        .avi doesnt support fast seek
        do HDR workflow onlz with HEVC
        audio
        subtitles
        Edit log messages
        Logger doesnt work in multithreading
        Output calculated things and settings to a file
        Include metadata for windows (length, resolution)
        delete VMAFlog.json after execution of vmaf
        fix output size calculation/comparison mesage
        Documentation - doxygen
    """