import logging

def setup_logger(log_level=logging.INFO, log_file=None):
    """
    Configures the logger and returns the logger instance.
    """
    logger = logging.getLogger("AppLogger")
    logger.setLevel(log_level)
    
    # Check if the logger already has handlers to prevent duplicate messages
    if not logger.handlers:
        formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')
        
        # Console handler
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
        
        # File handler (optional)
        if log_file:
            file_handler = logging.FileHandler(log_file)
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
    
    return logger
