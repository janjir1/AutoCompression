import subprocess, os

# Define the input and output file paths
#input_file = r'E:\Filmy\4K\Dune1.mkv'
input_file = r'E:\Filmy\hrané\Super-heroes\Marvel\Spider-Man.No.Way.Home.2022.mkv'
output_file = 'output.mkv'

cq_encoding_cmd = [
    'ffmpeg', '-i', input_file, 
    '-c:v', 'hevc_nvenc', #video encoding library
    #'-psy-rd', '1.0:1', Nvenc doesnt support it
    '-preset', 'slow',
    "-tune", "uhq", #maybe helpfull, maybe not
    '-g', '120', #group of pictures - the more the better
    '-bf', '4', # number of b frames
    '-refs', '4',  #number of reference frames
    '-cq', '30', #constant quality
    '-spatial-aq', '1', #enable spatial aq
    '-temporal-aq', '1', #enable temporal aq
    '-aq-strength', '8', #sets trength of aq filters
    #'-weighted_pred', '1', #better for slow movies, bad compression
    '-pix_fmt', 'p010le', #enable 10 bit
    '-s', '1920x1080', # set resolution
    "-y", "-t", "180", # time
    "-b:v", "0", # remove maximum bitrate limit
    #"-max_muxing_queue_size", "8192",
    "-rc-lookahead", "50", #looks for scene change
    "-fps_mode", "vfr", #enables variable frame times
    '-vf', 'hqdn3d',
    '-threads', '12',


    "-c:a", "libfdk_aac",
    "-profile:a", "aac_he_v2",
    "-vbr", "3",
    "-ac", "2",
    output_file
]

# Execute constant quality encoding with slow preset
subprocess.run(cq_encoding_cmd)
