import subprocess
import json

def get_video_duration(file_path):
    # Run ffprobe to get video information in JSON format
    command = [
        'ffprobe',
        '-v', 'error',               # Suppress non-error messages
        '-show_entries', 'format=duration',  # Extract duration
        '-of', 'json',               # Output format as JSON
        file_path                    # Input file path
    ]
    
    # Execute the command
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    
    # Check if the command was successful
    if result.returncode != 0:
        print(f"Error occurred while running ffprobe: {result.stderr}")
        return None

    # Parse the JSON output
    ffprobe_output = result.stdout
    
    if not ffprobe_output:
        print("No output received from ffprobe.")
        return None
    
    data = None
    try:
        data = json.loads(ffprobe_output)
    except json.JSONDecodeError:
        print("Error decoding JSON output.")
        return None
    
    # Extract duration from the JSON data
    if 'format' not in data or 'duration' not in data['format']:
        print("Duration information is missing in the JSON output.")
        return None
    
    duration = data['format']['duration']
    
    return float(duration)

# Example usage
file_path = 'input.mkv'  # Replace with your video file path
duration = get_video_duration(file_path)

if duration is not None:
    print(f"Video duration: {duration:.2f} seconds")
else:
    print("Could not determine video duration.")
