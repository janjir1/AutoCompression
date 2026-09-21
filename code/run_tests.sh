#!/bin/bash

# ==========================================
# Constants
# ==========================================
PROFILE_PATH="/app/Profiles/AV1_svt_archive_sw.yaml"
SETTINGS_FILE="/app/Profiles/Test_settings.yaml"
WORKSPACE="/workspace/"

# ==========================================
# Test Definitions (Dictionary)
# Format: tests["TEST_NAME"]="INPUT_FILE"
# ==========================================
declare -A tests

# Add your tests here
#tests["Dune1"]="/films/4K/Dune1.mkv"
tests["Dune2_new"]="/films/4K/Dune.Part.Two.mkv"
#tests["SpidermanNWH"]="/films/4K/Spider-Man.No.Way.Home.2022.2160p.UHD.BluRay.TrueHD.7.1.Atmos.HDR.x265-EVO.mkv"
#tests["Oppenheimer"]="/films/4K/Oppenheimer.2023.2160p.mkv"
#tests["Bitva"]="/films/hrané/Action/300 Bitva u Thermopyl HD.mkv"
#tests["Bond"]="/films/hrané/Action/James-Bond - Casino Royale SD.avi"
#tests["Kingsman"]="/films/hrané/Action/Kingsman Tajná služba FHD.avi"
#tests["Nobody"]="/films/hrané/Action/Nobody.2021.1080p.WEBRip.x264.AAC5.1-[YTS.MX].mp4"
#tests["Opp1080p"]="/films/hrané/Drama/Oppenheimer.2023.1080p.BluRay.x264.AAC5.1-[YTS.MX].mp4"
#tests["Apollo_new"]="/films/hrané/Drama/Oppenheimer.2023.1080p.BluRay.x264.AAC5.1-[YTS.MX].mp4"
#tests["LOTR"]="/films/hrané/Fantasy/LOTR/pan-prstenu-spolecenstvo-prstenu-prodlouzena-verze-czen-dab-cz-titulky.mkv"
#tests["Pirati3"]="/films/hrané/Fantasy/Piráti z karibiku/Pirati z Karibiku 3 Na konci sveta SD.avi"
#tests["Pirati1"]="/films/hrané/Fantasy/Piráti z karibiku/Piráti z Karibiku 1 Prokletí Černé perly FHD.mkv"
#tests["Alvin"]="/films/hrané/Komedie/Piráti z karibiku/Alvin a Chipmunkove 2 SD.avi"
#tests["IronMan"]="/films/hrané/Super-heroes/Marvel/Iron Man 2 (Iron Man 2) - Jon Favreau (2010) - 10bit HEVC (H.265) BDRip By HEaVenriC.mkv"
#tests["Deadpool"]="/films/hrané/Super-heroes/Marvel/Deadpool 2 DABING FHD.mkv"
#tests["Loki1"]="/films/Seriály/Loki/Loki_1.mkv"
#tests["Loki2"]="/films/Seriály/Loki/Loki_2.mkv"
#tests["Loki3"]="/films/Seriály/Loki/Loki_3.mkv"


# tests["04_Skipped_Test"]="./inputs/old_test.mp4"  # You can comment out tests easily

# ==========================================
# Execution Loop
# ==========================================
echo "Starting batch execution..."
echo "----------------------------------------"

# Iterate over the dictionary keys (Test Names)
for test_name in "${!tests[@]}"; do
    input_file="${tests[$test_name]}"
    
    echo "Running Test: [$test_name]"
    echo "Input File:   $input_file"
    
    python main.py \
        -i "$input_file" \
        -n "$test_name" \
        -p "$PROFILE_PATH" \
        -s "$SETTINGS_FILE" \
        -w "$WORKSPACE"

    echo "----------------------------------------"
done

echo "All tests processed."