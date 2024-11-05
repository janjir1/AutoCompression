import subprocess
import os, re

def compare_videos_with_vmaf(reference_file, distorted_file, output_file='vmaf_output.json', threads=4):
    # Convert output file path to absolute path
    output_file_abs = os.path.abspath(output_file)
    
    # Define the ffmpeg command to compute VMAF with multithreading
    command = [
        'ffmpeg',
        '-i', reference_file,        # Input reference file
        '-i', distorted_file,        # Input distorted file
        '-lavfi', f'libvmaf=n_threads={threads}:log_path={output_file_abs}',  # VMAF with multithreading and log output
        '-f', 'null', '-'            # No output file, just compute VMAF
    ]
    
    # Run the command and wait for it to complete
    process = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)



    # Check if the process completed successfully
    if process.returncode == 0:
        print(f"VMAF calculation completed successfully. Results saved to {output_file_abs}.")
        # Load the VMAF results from the output file
        with open(output_file, 'r') as file:
            for line in file:
                if '<metric name="vmaf"' in line:
                    match = re.findall(r"(?<=harmonic_mean=\").*\d", line)
                    if match: vmaf_score = float(match[0])
                    else: vmaf_score = 0
                
                    print(vmaf_score)
    else:
        print(f"FFmpeg finished with errors. Exit code: {process.returncode}")
        print(process.stderr)  # Display the error output

# Example usage
reference_file = r'D:\Files\Projects\AutoCompression\Tests\auto\1_1920_cq0.mp4'  # Replace with your reference video file
distorted_file = r'D:\Files\Projects\AutoCompression\Tests\auto\1_1920_Cq30.mp4'  # Replace with your distorted video file
threads = 8  # Set the number of threads (cores) you want to use
compare_videos_with_vmaf(reference_file, distorted_file, threads=threads)