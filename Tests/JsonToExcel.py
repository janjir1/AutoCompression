import os
import csv
import yaml
import re

input_directory = r'D:\Files\Projects\AutoCompression\Tests\Known'  # Replace with your input directory
output_file = r'D:\Files\Projects\AutoCompression\Tests\cqTestKnown.csv'  # Replace with your output directory

file_list = []
part_list = []
keys_list = []
size_list = []
VQA_list = []
VMAF_list = []


"""Recursively find YAML files in the directory and convert them to JSON format."""
for root, _, files in os.walk(input_directory):
    for file in files:
        if file.endswith('cqTest.yaml'):
            yaml_file_path = os.path.join(root, file)
            

            with open(yaml_file_path, 'r', encoding='utf-8') as yaml_file:
                data = yaml.safe_load(yaml_file)

                #(?<=_)\d*
                #keys_list.append("h_res")
                keys_list.append("cq")
                part_list.append("part")

                h_res_list = list(data.keys())
                for h_res in h_res_list:
                    #match = re.search(r"(?<=_)\d*", h_res)
                    match = re.search(r"(?<=cq)\d*", h_res)
                    keys_list.append(match.group())

                    match = re.search(r"\d*", h_res)
                    part_list.append(match.group())

                file_list.append("name")
                #size_list.append("size")
                VQA_list.append("VQA")
                VMAF_list.append("VMAF")
                

                for key in list(data.keys()):
                    file_list.append(os.path.basename(root))
                    VQA_list.append(data[key]["VQA"])
                    VMAF_list.append(data[key]["VMAF"])
                   

                #print(keys_list)
                #print(size_list)
print(VMAF_list)

rows = [file_list, part_list, keys_list, VQA_list, VMAF_list]

with open(output_file, mode='w', newline='') as file:
    writer = csv.writer(file)
    writer.writerows(rows)



