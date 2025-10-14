import os
import glob

def search_logs_for_expression(root_folder, expression="average slope is:"):
    """
    Search for a specific expression in all app.log files within a folder and its subfolders.
    
    Args:
        root_folder (str): The root directory to search in
        expression (str): The expression to search for
    
    Returns:
        dict: Dictionary with file paths as keys and list of matching lines as values
    """
    results = {}
    
    # Use glob to find all app.log files recursively
    pattern = os.path.join(root_folder, "**/VPC.txt")
    log_files = glob.glob(pattern, recursive=True)
    
    print(f"Found {len(log_files)} app.log files to search:")
    for log_file in log_files:
        print(f"  - {log_file}")
    
    # Search each file for the expression
    for log_file in log_files:
        try:
            with open(log_file, 'r', encoding='utf-8') as file:
                matching_lines = []
                for line_num, line in enumerate(file, 1):
                    if expression.lower() in line.lower():
                        matching_lines.append((line_num, line.strip()))
                
                if matching_lines:
                    results[log_file] = matching_lines
                    print(f"\n✓ Found matches in: {log_file}")
                    for line_num, line in matching_lines:
                        print(f"  Line {line_num}: {line}")
                else:
                    print(f"✗ No matches in: {log_file}")
                    
        except Exception as e:
            print(f"Error reading {log_file}: {e}")
    
    return results

# Example usage:
if __name__ == "__main__":
    # Replace with your actual folder path
    folder_path = r"D:\Files\Projects\AutoCompression\workspaceForFailed"  # Current directory - change this to your target folder
    expression = "VQA"
    
    print(f"Searching for '{expression}' in all app.log files...")
    print(f"Root folder: {os.path.abspath(folder_path)}")
    print("=" * 50)
    
    results = search_logs_for_expression(folder_path, expression)
    
    print("\n" + "=" * 50)
    print("SUMMARY:")
    if results:
        print(f"Found '{expression}' in {len(results)} files:")
        for file_path, matches in results.items():
            print(f"  {file_path}: {len(matches)} matches")
    else:
        print(f"No files containing '{expression}' were found.")
