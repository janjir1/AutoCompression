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

    logger = logging.getLogger("AppLogger")

    if not os.path.isfile(VPC.orig_file_path):
        logger.error("file not found")
        return False

    #region logger begginig
    logger.info("Starting AV conversion script.")
    logger.info(f"file path: {VPC.orig_file_path}")
    logger.info(f"workspace path: {VPC.workspace}")

    logger.debug('Profile values:')
    logger.debug(VPC.profile)
   
    orig_file_size_GB = os.stat(VPC.orig_file_path).st_size / (1024 * 1024 * 1024)
    logger.info(f"Original file is {orig_file_size_GB:.3f}GB")

    passed = runTests(VPC)
    if not passed:
        logger.info(f"Some tests Failed")
    else:
        logger.info(f"Tests finished succesfully")

    VPC.export_to_txt()
    
    if VPC.test_settings["Export_output"]["Enabled"]:
        result = compressor2.compress(VPC)
        if not result:
            logger.info(f"Conversion failed")
            return False
        
        output_file_size_GB = os.stat(VPC.output_file_path).st_size / (1024 * 1024 * 1024)
        logger.info(f"Output file is {output_file_size_GB:.3f}GB")
        logger.info(f"Output file is {(orig_file_size_GB/output_file_size_GB):.3f}x size of original")

    else:
        logger.info(f"Export output is disabled")

    logger.info(f"Program finished succesfully")
    return True

def init(file, file_name, profile_path, settings_path, workspaces, tools_path) -> tuple[VideoProcessingConfig, logging.Logger, logging.Logger]:
     
    workspace = os.path.join(workspaces, file_name)

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

    return VPC, logger, stream_logger
     

if __name__ == '__main__':

    profile_path = r"Profiles\h265_slow_nvenc.yaml"
    settings_path = r"Profiles\Test_settings.yaml"
    workspaces = r"D:\Files\Projects\AutoCompression\workspaceForFailed"
    tools_path = r"D:\Files\Projects\AutoCompression\tools"

    test_files = {
        r"E:\Filmy\hrané\Action\Kingsman.avi": "Kingsman",
        r"E:\Filmy\hrané\Drama\Oppenheimer.2023.1080p.BluRay.x264.AAC5.1-[YTS.MX].mp4": "Oppenheimer",
        r"E:\Filmy\animované\Toy-Story-3-cz.avi": "Toy-Story-3-cz"
        }

    for key in test_files.keys():
        VPC, logger, stream_logger = init(key, test_files[key], profile_path, settings_path, workspaces, tools_path)
        passed = compressAV(VPC)
        test_files[key] = str(passed)
    
    print(test_files)

    """TODO:
        Copy all metadata even static HDR10
        for non FS multiply by 3 for only 1s (set 3s as minimum)
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