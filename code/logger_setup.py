import logging

def setup_logger(log_level=logging.INFO, log_file=None):
    """
    Configures the logger with separate logging levels for console and file.
    The console shows only the specified log level, while the file logs all levels.
    """
    logger = logging.getLogger("AppLogger")
    logger.setLevel(logging.DEBUG)  # Set to DEBUG to capture all levels internally
    
    # Remove existing handlers to avoid duplicates
    if logger.hasHandlers():
        logger.handlers.clear()
    
    formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')
    
    # Console handler: Prints messages at or above the specified level
    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)
    console_handler.setFormatter(formatter)
    console_handler.stream = open(1, "w", encoding="utf-8")  # Force UTF-8 encoding for console
    logger.addHandler(console_handler)
    
    # File handler: Logs all messages and overwrites the log file
    if log_file:
        file_handler = logging.FileHandler(log_file, mode="w", encoding="utf-8")  # UTF-8 encoding
        file_handler.setLevel(logging.DEBUG)  # Log everything to the file
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    
    return logger