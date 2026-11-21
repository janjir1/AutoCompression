from AVTest import runTests
import logging
import logger_setup
import os
import sys
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
        logger.info("Some tests Failed")
    else:
        logger.info("Tests finished succesfully")

    VPC.export_to_txt()

    if VPC.test_settings["Export_output"]["Enabled"]:
        VPC.is_final_export = True
        result = compressor2.compress(VPC)
        if not result:
            logger.info("Conversion failed")
            return False

        output_file_size_GB = os.stat(VPC.output_file_path).st_size / (1024 * 1024 * 1024)
        logger.info(f"Output file is {output_file_size_GB:.3f}GB")
        if orig_file_size_GB > 0 and output_file_size_GB > 0:
            pct = (output_file_size_GB / orig_file_size_GB) * 100
            ratio = orig_file_size_GB / output_file_size_GB
            logger.info(f"Output file is {pct:.1f}% of original ({ratio:.2f}x smaller)")

    else:
        logger.info("Export output is disabled")

    logger.info("Program finished succesfully")
    return True


def init(file, file_name, profile_path, settings_path, workspaces) -> tuple[VideoProcessingConfig, logging.Logger, logging.Logger]:

    if not os.path.isfile(file):
        raise FileNotFoundError(f"Input file not found: {file}")

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
    VPC.readProfiles(profile_path, settings_path)
    if not VPC.analyzeOriginal():
        raise RuntimeError(f"Failed to analyze input video (or unsupported format): {file}")

    VPC.setSourcePath(VPC.orig_file_path)

    if VPC.profile["HDR_enable"][1] == True:
        compressor2.get_video_metadata_type(VPC)
    else:
        VPC.HDR_type = "None"

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

    args = parser.parse_args()

    try:
        VPC, logger, stream_logger = init(args.input_file, args.movie_name, args.profile, args.settings, args.workspace)
    except (FileNotFoundError, RuntimeError) as e:
        print(f"Initialization failed: {e}", file=sys.stderr)
        sys.exit(1)

    passed = compressAV(VPC)

    print(passed)

    """TODO:

        audio
        subtitles

        Edit log messages
        Logger doesnt work in multithreading

        Include metadata for windows (length, resolution)
        Documentation - doxygen
        Dolby Vision Profile 5 conversion/reshaping

    """