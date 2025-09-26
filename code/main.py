from gc import enable
from sympy import li
import yaml
from AVTest import runTests
import logging
import logger_setup
import os, subprocess, traceback
import json
import compressor2
from VideoClass import VideoProcessingConfig


def compressAV(VPC: VideoProcessingConfig) -> bool:

    if not os.path.isfile(file):
        logger.error("file not found")
        return False

    #region logger begginig
    logger.info("Starting AV conversion script.")
    logger.info(f"file path: {VPC.orig_file_path}")
    logger.info(f"workspace path: {VPC.workspace}")

    logger.debug('Profile values:')
    logger.debug(VPC.profile)
   
    orig_file_size_GB = os.stat(file).st_size / (1024 * 1024 * 1024)
    logger.info(f"Original file is {orig_file_size_GB:.3f}GB")

    _ = runTests(VPC)

    result = compressor2.compress(VPC)
    if not result:
        return False

    logger.info(f"Conversion finished succesfully")

    output_file_size_GB = os.stat(VPC.output_file_path).st_size / (1024 * 1024 * 1024)
    
    logger.info(f"Output file is {output_file_size_GB:.3f}GB")
    logger.info(f"Output file is {(orig_file_size_GB/output_file_size_GB):.3f}x size of original")

    return True

     

if __name__ == '__main__':

    file = r"E:\Filmy\hrané\Action\Lucy FHD.mkv"
    file_name = "Lucy"
    profile_path = r"Profiles\h265_slow_nvenc.yaml"
    settings_path = r"Profiles\Test_settings.yaml"
    workspace = r"D:\Files\Projects\AutoCompression\workspace\Lucy"
    tools_path = r"D:\Files\Projects\AutoCompression\tools"

    if not os.path.exists(workspace):
            # Create the directory
            os.makedirs(workspace)
            print(f'Directory "{workspace}" created.')

    log_path = os.path.join(workspace, "app.log")
    logger = logger_setup.primary_logger(log_level=logging.INFO, log_file=log_path)
    log_path = os.path.join(workspace, "stream.log")
    stream_logger = logger_setup.file_logger(log_path, log_level=logging.DEBUG)

    VPC = VideoProcessingConfig(file, file_name, workspace)
    VPC.readProfiles(profile_path, settings_path, tools_path)
    VPC.analyzeOriginal()


    passed = compressAV(VPC)

    """TODO:
        .avi doesnt support fast seek (videos in _res have random length)
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