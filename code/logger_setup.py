import logging, sys

def primary_logger(log_level=logging.INFO, log_file=None):
    """
    Configures the logger with separate logging levels for console and file.
    The console shows only messages at or above log_level, while the file logs all levels.
    """
    logger = logging.getLogger("AppLogger")
    logger.setLevel(logging.DEBUG)  # Capture all levels internally

    # Remove existing handlers to avoid duplicate logging
    if logger.hasHandlers():
        logger.handlers.clear()

    formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')

    # Console handler: Use sys.stdout so encoding issues are handled correctly
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # File handler: Logs all messages (DEBUG and above) to the file, if provided
    if log_file:
        file_handler = logging.FileHandler(log_file, mode="w", encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger

def file_logger(log_file: str, log_level=logging.DEBUG):
    """
    Configures a logger that logs exclusively to a file.
    
    Parameters:
    - log_file (str): Path to the log file.
    - log_level (int): Logging level (default DEBUG to capture all messages).
    
    Returns:
    - logger (logging.Logger): A logger that writes exclusively to the specified file.
    """
    logger = logging.getLogger("FileLogger")
    logger.setLevel(log_level)
    
    # Remove existing handlers to avoid duplicate logging
    if logger.hasHandlers():
        logger.handlers.clear()
    
    formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')
    
    file_handler = logging.FileHandler(log_file, mode="w", encoding="utf-8")
    file_handler.setLevel(log_level)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    
    return logger