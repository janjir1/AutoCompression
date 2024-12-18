import yaml
import AVTest
import subprocess

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


if __name__ == '__main__':
    yaml_file = r'D:\Files\Projects\AutoCompression\Profiles\h265_slow_nvenc.yaml'
    profile = readProfile(yaml_file)
    decode_table =  {854: -10, 1280: -1e-04, 1920: -6.9e-05, 3840: -4e-05}
    workaspace = r"D:\Files\Projects\AutoCompression\Tests\Martan"
    file = r"E:\Filmy\hrané\Drama\Marťan-2015-Cz-Dabing-HD.mkv"
    target_res = AVTest.getRes_parallel(workaspace, file, [854, 3840], 15, decode_table, profile["video"], num_of_VQA_runs=3)
    taret_cq = AVTest.getCQ(workaspace, file, target_res, [15, 18, 27, 36], 3, 0.6, profile["video"], scene_length=50, threads=6)
    #print(f"res: {target_res}, cq: {taret_cq}")
    print(f"cq: {taret_cq}")


