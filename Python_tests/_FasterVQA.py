import subprocess
import re
import os
import sys


folder_path = r"E:\Filmy\hrané\Action\Top Gun Maverick (2022) [1080p] [BluRay] [5.1] [YTS.MX]"
#Meassure eveerzthing in a folder.

for filename in os.listdir(folder_path):
    # Check if the file is an .mp4 file
    if filename.endswith('.mp4'):
        # Full path of the file
        video_path = os.path.join(folder_path, filename)
        print(sys.path)
        first_frame = ""
        quality_score = []
        #Meassure video using FasterVQA number of times for averaging
        for i in range(4):
            # Command to run the script with -v and the Windows path
            command = [sys.executable, "./FastVQA-and-FasterVQA/vqa.py", "-v", video_path]
            #subprocess.run([sys.executable, "./FastVQA-and-FasterVQA/vqa.py"])
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

            output_lines = []
            # Capture the output in real-time
            try:
                for line in process.stdout:
                    #print(line, end="")  # Print the output as it's generated
                    output_lines.append(line.strip())

                # Wait for the process to complete and get the exit code
                process.wait()
                
                # Check for errors
                if process.returncode != 0:
                    print(f"Script exited with error code {process.returncode}")
                    error_output = process.stderr.read()
                    print("Error Output:", error_output)

            except Exception as e:
                print(f"An error occurred: {str(e)}")

            #Parse the output
            for line in output_lines:
                if "Sampled frames are" in line:
                    match = re.search(r'\b\d+', line)
                    if match:
                        first_frame = int(match.group())
                        #print(f"{i+1} The first number is: {first_frame}")

                if "The quality score of the video" in line:
                    match = re.search(r'\b0\.\d+', line)
                    if match:
                        quality_score.append(float(match.group()))
                        #print(f"{i+1} The Quality score is: {match.group()}")

        #get average
        average_quality = sum(quality_score) / len(quality_score)

        print(f"{filename} has VQA of: {average_quality}")

