import logging

def setup_logger():
    logger = logging.getLogger("app_logger")
    logger.setLevel(logging.DEBUG)

    # File Handler
    file_handler = logging.FileHandler("app.log")
    file_handler.setLevel(logging.WARNING)

    # Console Handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG)

    # Formatter
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger

logger = setup_logger()