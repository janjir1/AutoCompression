from AVTest import runTests
import logging
import logger_setup
import os
import compressor2
import argparse
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

    VPC.setSourcePath(VPC.orig_file_path)

    compressor2.get_video_metadata_type(VPC)

    return VPC, logger, stream_logger

     

if __name__ == '__main__':


    parser = argparse.ArgumentParser(
        description='Run auto‐compression for a single movie file.'
    )
    parser.add_argument('--input_file',   '-i', required=True,
                        help='Path to the source video file.')
    parser.add_argument('--movie_name',   '-n', required=True,
                        help='Identifier or title for logging.')
    parser.add_argument('--profile',      '-p', required=True,
                        help='Path to the FFmpeg profile YAML.')
    parser.add_argument('--settings',     '-s', required=True,
                        help='Path to the settings YAML.')
    parser.add_argument('--workspace',    '-w', required=True,
                        help='Base workspace directory.')
    parser.add_argument('--tools',        '-t', required=False,
                        help='Does nothing, now')

    args = parser.parse_args()

    VPC, logger, stream_logger = init(args.input_file, args.movie_name, args.profile, args.settings, args.workspace, args.tools)
    passed = compressAV(VPC)

    print(passed)

    """TODO:

        audio
        subtitles

        Edit log messages
        Logger doesnt work in multithreading
        
        Include metadata for windows (length, resolution)
        delete VMAFlog.json after execution of vmaf
        fix output size calculation/comparison mesage
        Documentation - doxygen

    """