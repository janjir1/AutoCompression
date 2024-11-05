import subprocess

# User-defined parameters
start_time = "150"  # Start time in hh:mm:ss format
horizontal_pixels = 1280  # Desired horizontal pixel resolution (e.g., 1280 for 1280x720 resolution)

# Define the ffmpeg command as a list of arguments
command = [
    'ffmpeg',
    '-ss', start_time,             # Start time specified by the user
    '-i', 'input.mkv',             # Input file
    '-t', '00:01:00',              # Duration of 1 minute
    '-c:v', 'hevc_nvenc',          # Use GPU with NVIDIA NVENC for H.265
    '-preset', 'slow',             # Preset for encoding speed/quality
    '-cq', '0',                    # Constant Quality mode with highest quality (0)
    '-vf', f'scale={horizontal_pixels}:-1',  # Scale video width and maintain aspect ratio
    '-an',                         # Disable audio
    'output.mp4'                   # Output file
]

# Run the command and wait for it to complete
process = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

# Check if the process completed successfully
if process.returncode == 0:
    print("FFmpeg processing finished successfully!")
else:
    print(f"FFmpeg finished with errors. Exit code: {process.returncode}")
    print(process.stderr)  # Optional: Display the error output
