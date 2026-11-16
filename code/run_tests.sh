#!/bin/bash

# ==========================================
# Constants
# ==========================================
PROFILE_PATH="/app/Profiles/AV1_svt_archive_sw.yaml"
SETTINGS_FILE="/app/Profiles/Test_settings.yaml"
WORKSPACE="/workspace"
TIMEOUT_SECONDS=7200   # 2 hours per file - timed-out file is skipped, run continues

# ==========================================
# Test Definitions (Dictionary)
# Format: tests["TEST_NAME"]="INPUT_FILE"
# ==========================================
declare -A tests

#tests["BlackPanther_Deband"]="/input/Deband/lossless/Black Panther 2018 Full HD CZ dabing_deband_m2_t050.mkv"
#tests["DoktorStrange_Deband"]="/input/Deband/lossless/Doktor Strange (1920x1080)_deband_m2_t050.mkv"
#tests["DunePartTwo_Deband"]="/input/Deband/lossless/Dune.Part.Two_deband_m2_t050.mkv"
tests["meda"]="/films/hrané/Komedie/Méďa 1 HD.avi"
#tests["Oppenheimer_Deband"]="/input/Deband/lossless/Oppenheimer.2023.2160p_deband_m2_t050.mkv"
#tests["Rp1_Deband"]="/input/Deband/lossless/Rp1 4K-1_deband_m2_t050.mkv"

# ==========================================
# Execution Loop
# ==========================================
echo "Starting batch execution ($((${#tests[@]})) tests, ${TIMEOUT_SECONDS}s timeout each)..."
echo "----------------------------------------"

for test_name in "${!tests[@]}"; do
    input_file="${tests[$test_name]}"

    echo "Running Test: [$test_name]"
    echo "Input File:   $input_file"

    timeout "$TIMEOUT_SECONDS" python code/main.py \
        -i "$input_file" \
        -n "$test_name" \
        -p "$PROFILE_PATH" \
        -s "$SETTINGS_FILE" \
        -w "$WORKSPACE"
    exit_code=$?

    if [ $exit_code -eq 124 ]; then
        echo "TIMEOUT: [$test_name] exceeded ${TIMEOUT_SECONDS}s - skipping to next test."
    elif [ $exit_code -ne 0 ]; then
        echo "ERROR: [$test_name] exited with code $exit_code - continuing."
    else
        echo "OK: [$test_name] completed."
    fi

    echo "----------------------------------------"
done

echo "All tests processed."