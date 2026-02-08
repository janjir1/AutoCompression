#!/bin/bash

# Configuration
INPUT_FILE="/input/input.mkv"
SETTINGS_FILE="/app/Profiles/Test_settings.yaml"
PROFILE_DIR="/app/Profiles/AV1_Test"
WORKSPACE="/workspace/AV1_tests"

echo "Starting SVT-AV1 Benchmark Suite..."
echo "========================================"

# Loop from 1 to 10
for i in {1..9}; do
    TEST_NAME="test${i}"
    PROFILE_PATH="${PROFILE_DIR}/${i}.yaml"
    
    echo "Running ${TEST_NAME} using ${PROFILE_PATH}..."
    
    # Get start time (seconds since epoch)
    START_TIME=$(date +%s)
    
    # Run the command
    python main.py -i "$INPUT_FILE" -n "$TEST_NAME" -p "$PROFILE_PATH" -s "$SETTINGS_FILE" -w "$WORKSPACE"
    
    # Get end time and calculate duration
    END_TIME=$(date +%s)
    DURATION=$((END_TIME - START_TIME))
    
    # Convert duration to MM:SS format
    MINUTES=$((DURATION / 60))
    SECONDS=$((DURATION % 60))
    
    # Print result
    echo "----------------------------------------"
    printf "FINISHED: %s took %02dm:%02ds\n" "$TEST_NAME" $MINUTES $SECONDS
    echo "========================================"
    echo ""
done

echo "All 10 tests completed successfully."
