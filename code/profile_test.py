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
workaspaces = r"D:\Files\Projects\AutoCompression\Tests"
files = [
        #r"E:\Filmy\hrané\Super-heroes\Marvel\Avengers Infinity War CZ dabing-5.1 1080pHD 2018..mkv",
        r"E:\Filmy\hrané\Super-heroes\Marvel\Black Panther 2018 Full HD CZ dabing.mkv",
        r"E:\Filmy\hrané\Super-heroes\Marvel\Thor 2 (Temny svet) (720x304).avi",
        r"E:\Filmy\hrané\Sci-fi\Star Wars\Star-Wars 6 Návrat Jediho SD.avi",
        r"E:\Filmy\hrané\Sci-fi\Star Wars\'Star Wars I - Hviezdne vojny - Epizóda I - Skrytá hrozba    1999  1080p  5.1 CZ 5.1 SK 5.1 ENG.mkv",
        r"E:\Filmy\hrané\Komedie\Alvin a Chipmunkove 2 SD.avi",
        r"E:\Filmy\hrané\Komedie\Free.Guy.CZ.mkv",
        r"E:\Filmy\hrané\Fantasy\Eragon HD.avi",
        r"E:\Filmy\hrané\Fantasy\Cruella.mkv",
        r"E:\Filmy\4K\Dune1.mkv",
        r"E:\Filmy\4K\Oppenheimer.2023.2160p.REMUX.IMAX.Dolby.Vision.And.HDR10.PLUS.ENG.ITA.LATINO.DTS-HD.Master.DDP5.1.DV.x265.MKV-BEN.THE.MEN\Oppenheimer.2023.2160p.REMUX.IMAX.Dolby.Vision.And.HDR10.PLUS.ENG.ITA.LATINO.DTS-HD.Master.DDP5.1.DV.x265.mkv",
        r"E:\Filmy\4K\interstellar.2014.2160p.uhd.bluray.x265-terminal.mkv",
        r"E:\Filmy\hrané\Action\300 Bitva u Thermopyl HD.mkv",
        r"E:\Filmy\hrané\Action\Nobody.2021.1080p.WEBRip.x264.AAC5.1-[YTS.MX].mp4",
        r"E:\Filmy\hrané\Fantasy\Na hraně zítřka SD.avi"
    ]

if __name__ == '__main__':

    for file in files:

        if not os.path.isfile(file):
            print(file)
            print("File not found")
            continue
        
        workaspace = os.path.join(workaspaces, os.path.basename(file)[:-4])

        if not os.path.exists(workaspace):
                # Create the directory
                os.makedirs(workaspace)
                print(f'Directory "{workaspace}" created.')

        log_path = os.path.join(workaspace, "app.log")
        logger = setup_logger(log_level=logging.INFO, log_file=log_path)

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
        target_res = AVTest.getRes_parallel(workaspace, file, [854, 3840], 20, decode_table, profile["video"], crop, num_of_VQA_runs=2)
        taret_cq = AVTest.getCQ(workaspace, file, target_res, [15, 18, 27, 36], 5, threashold_variable, profile["video"], crop, scene_length=50, threads=6)
        print(f"res: {target_res}, cq: {taret_cq}")
        #print(f"res: {target_res}")


