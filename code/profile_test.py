import yaml
import AVTest
import logging
from logger_setup import setup_logger
import os

def readProfile(yaml_file):
    with open(yaml_file, 'r') as file:
        loaded_data = yaml.safe_load(file)

    profile = dict()
    for key, value in loaded_data.items():
        profile[key] = list()
        for subvalue in value.items():
            profile[key].append(str(subvalue[0]))
            profile[key].append(str(subvalue[1]))


    return profile


yaml_profile_file = r'D:\Files\Projects\AutoCompression\Profiles\h265_slow_nvenc.yaml'
decode_table =  {854: -10, 1280: -1e-04, 1920: -6.9e-05, 3840: -4e-05}
threashold_variable = 0.6
workaspace = r"D:\Files\Projects\AutoCompression\Tests\Zitra"
file = r"E:\Filmy\hrané\Fantasy\Na hraně zítřka SD.avi"

if __name__ == '__main__':

    if not os.path.exists(workaspace):
            # Create the directory
            os.makedirs(workaspace)
            print(f'Directory "{workaspace}" created.')

    log_path = os.path.join(workaspace, "app.log")
    logger = setup_logger(log_level=logging.DEBUG, log_file=log_path)

    #region logger begginig
    logger.info("Starting AV conversion script.")
    logger.info(f"file path: {file}")
    logger.info(f"workspace path: {workaspace}")
    logger.info(f"profile path: {yaml_profile_file}")
    logger.debug(f"resolution decode table:")
    logger.debug(decode_table)
    logger.debug(f'quality threashold value: {threashold_variable}')
    #endregion section 

    profile = readProfile(yaml_profile_file)
    logger.debug('Profile values:')
    logger.debug(profile)

    crop = AVTest.detectBlackbars(file, workaspace, 10)
    target_res = AVTest.getRes_parallel(workaspace, file, [854, 3840], 15, decode_table, profile["video"], crop, num_of_VQA_runs=2)
    taret_cq = AVTest.getCQ(workaspace, file, target_res, [15, 18, 27, 36], 3, threashold_variable, profile["video"], crop, scene_length=50, threads=6)
    print(f"res: {target_res}, cq: {taret_cq}")
    #print(f"res: {target_res}")


