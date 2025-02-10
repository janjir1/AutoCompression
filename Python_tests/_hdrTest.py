import subprocess, json, os
from tkinter import NO


def delete_small_file(file_path, size_limit=2048):
    """Delete the file if its size is less than the specified limit (default: 2 KB)."""
    try:
        if os.path.isfile(file_path):  # Ensure it's a file
            file_size = os.path.getsize(file_path)
            if file_size < size_limit:
                os.remove(file_path)
                print(f"Deleted: {file_path} (Size: {file_size} bytes)")
                return True
            else:
                print(f"File is larger than {size_limit} bytes: {file_path}")
                return False
        else:
            print(f"File not found: {file_path}")
            return True
    except PermissionError:
        print(f"Permission denied: {file_path}")
        return None
    except Exception as e:
        print(f"Error deleting file {file_path}: {e}")
        return None

def get_video_metadata(input_file, workspace, extract_dynamic = False, relative_tools_path = "HDR_tools", cleanup = True):
    # Ensure workspace exists
    os.makedirs(workspace, exist_ok=True)

    # First command to get general metadata
    cmd = ["ffprobe", "-v", "error", "-of", "json", "-show_streams", "-show_format", input_file]
    
    print("Running command:", " ".join(cmd))
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    
    # Handle potential empty metadata
    try:
        metadata = json.loads(result.stdout) if result.stdout.strip() else {}
    except json.JSONDecodeError:
        metadata = {}

    # Find video stream
    video_stream = next((stream for stream in metadata.get("streams", []) if stream.get("codec_type") == "video"), {})

    # Extract color info
    color_primaries = video_stream.get("color_primaries", None)
    color_trc = video_stream.get("color_transfer", None)
    colorspace = video_stream.get("color_space", None)

    output_metadata = list()
    if color_primaries is not None: output_metadata += ["color_primaries", color_primaries]
    if color_trc is not None: output_metadata += ["color_transfer", color_trc]
    if colorspace is not None: output_metadata += ["color_space", colorspace]

    # Extract dynamic metadata
    metadata_file = None

    if extract_dynamic:
        
        video_stram = os.path.join(workspace, "dynamic_extract.hevc")
        hevc_command = ["ffmpeg", "-i", input_file, "-map", "0:v:0", "-c", "copy", "-bsf:v", "hevc_mp4toannexb", "-f", "hevc",  video_stram, "-y"]
        print(hevc_command)
        result = subprocess.run(hevc_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        print("STDOUT:", result.stdout)
        print("STDERR:", result.stderr)

        #DOVI
        dovi_metadata_file = os.path.join(workspace, "dovi_metadata.bin")
        dovi_tool_path = os.path.join(relative_tools_path, "dovi_tool.exe")
        dovi = f"{dovi_tool_path} extract-rpu -i {video_stram} -o {dovi_metadata_file}"

        result = subprocess.run(dovi, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        print("STDOUT:", result.stdout)
        print("STDERR:", result.stderr)

        deleted = delete_small_file(dovi_metadata_file)

        if deleted is None:
            print("problem")
            return False
        elif deleted is True:

            #HDR10+
            HDR10_metadata_file = os.path.join(workspace, "HDR10_dynamic_metadata.json")
            HDR10plus_tool_path = os.path.join(relative_tools_path, "hdr10plus_tool.exe")
            HDR10plus = f"{HDR10plus_tool_path} extract {video_stram} -o {HDR10_metadata_file}"

            result = subprocess.run(HDR10plus, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            print("STDOUT:", result.stdout)
            print("STDERR:", result.stderr)

            deleted = delete_small_file(HDR10_metadata_file)

            if deleted is False:
                metadata_file = {"hdr10_plus": HDR10_metadata_file}

        elif deleted is False:
            metadata_file = {"dolby-vision": dovi_metadata_file}

    if cleanup is True:
        try:
            if os.path.isfile(video_stram):  # Ensure it's a file
                    os.remove(video_stram)
            else:
                print(f"File not found: {video_stram}")
        except PermissionError:
            print(f"Permission denied: {video_stram}")
        except Exception as e:
            print(f"Error deleting file {video_stram}: {e}")

    return output_metadata, metadata_file


# Example Usage
#input_video = r"D:\Files\Projects\AutoCompression\Tests\HDR10_plus.mkv" #HDR10+
input_video = r"D:\Files\Projects\AutoCompression\Tests\DoVi.mkv" #dovi


output_metadata, metadata_file = get_video_metadata(input_video, r"D:\Files\Projects\AutoCompression\Python_tests", True)
print(output_metadata)
print(metadata_file)
