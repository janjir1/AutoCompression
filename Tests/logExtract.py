import re, os
from datetime import datetime

def parse_log_file(file_path):
    data = {
        "movie_file_name": None,
        "original_resolution": None,
        "average_list": [],
        "cq_polynomial": [],
        "cq_polynomial_values": {},
        "all_cq_polynomials": []  # Added to store all CQ polynomial lines
    }
    
    # Define regex patterns
    patterns = {
        "movie_file_name": r"file path: (.+\.\w+)",  # Match any file extension
        "original_resolution": r"Original resolution: (\d+)",
        "average_list": r"average:\s*\[(.*?)\]",
        "cq_polynomial": r"CQ polynomial:\s*([^,]+),\s*([^,]+),\s*([^\n]+)",
    }
    
    with open(file_path, 'r') as f:
        for line in f:
            # Extract movie file name
            if data["movie_file_name"] is None:
                match = re.search(patterns["movie_file_name"], line)
                if match:
                    data["movie_file_name"] = match.group(1)
            
            # Extract original resolution
            if data["original_resolution"] is None:
                match = re.search(patterns["original_resolution"], line)
                if match:
                    data["original_resolution"] = int(match.group(1))
            
           
            # Extract CQ polynomial
            match = re.search(patterns["cq_polynomial"], line)
            if match:
                polynomial = [float(match.group(1)), float(match.group(2)), float(match.group(3))]
                if not data["cq_polynomial"]:  # Store the first CQ polynomial (for backward compatibility)
                    data["cq_polynomial"] = polynomial
                # Add all CQ polynomials to a 2D list
                data["all_cq_polynomials"].append(polynomial)
    
    return data

def parse_average_list(file_path):
    pattern = r"average:\s.*\[([^\]]*)"
    
    with open(file_path, 'r') as f:
        content = f.read()  # Read the entire file content
    
    match = re.search(pattern, content)
    if match:
        # Split by commas, strip whitespace, and convert to floats
        return [float(x.strip()) for x in match.group(1).split(",")]
    return []


def calculate_execution_time(file_path):

    # Regex to match the timestamp at the beginning of each log entry
    timestamp_pattern = r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}'
    
    # List to store parsed datetime objects
    timestamps = []
    
    with open(file_path, 'r') as file:
        for line in file:
            # Search for a timestamp in the current line
            match = re.match(timestamp_pattern, line)
            if match:
                # Convert the timestamp string to a datetime object
                timestamps.append(datetime.strptime(match.group(), '%Y-%m-%d %H:%M:%S,%f'))
    
    # Check if we found at least two timestamps
    if len(timestamps) < 2:
        return "Not enough log entries to calculate execution time."
    
    # Calculate execution time as the difference between the first and last timestamp
    total_execution_time = timestamps[-1] - timestamps[0]
    
    return str(total_execution_time)


f = open("log_output_AV1.txt", "w")
root_dir = r"D:\Files\Projects\AutoCompression\Tests\full_bilinear"

for root, dirs, files in os.walk(root_dir):
    if 'app.log' in files:

        log_file_path = os.path.join(root, 'app.log')
        print(log_file_path)

        # Parse the log file
        #log_file_path = r"Tests\Avengers Infinity War CZ dabing-5.1 1080pHD 2018\app.log"  # Update with the actual file path if necessary
        parsed_data = parse_log_file(log_file_path)

        # Print the results
        #print("Movie File Name:", os.path.basename(parsed_data["movie_file_name"]))
        file_line = [os.path.basename(parsed_data["movie_file_name"])]

        #print("Original Resolution:", parsed_data["original_resolution"])
        file_line.append(parsed_data["original_resolution"])

        #print("All CQ Polynomials:")
        file_line.append("CQ poly")
        for polynomial in parsed_data["all_cq_polynomials"]:
            #print(polynomial)
            file_line = file_line + polynomial

        file_line.append("res slope")
        average_list = parse_average_list(log_file_path)
        #print("Average List:", average_list)
        file_line = file_line + average_list

        exec_time = calculate_execution_time(log_file_path)
        
        file_line.append(str(exec_time))
        file_line.append("\n")
        single_line = ';'.join(map(str, file_line))

        f.writelines(single_line)

f.close()
