import logging

def setup_logger(name, level=logging.INFO):
    """设置并返回一个命名的日志记录器（只输出到控制台）"""
    logger = logging.getLogger(name)
    logger.setLevel(level)

    if not logger.handlers:
        console_handler = logging.StreamHandler()
        formatter = logging.Formatter(
            "%(asctime)s - %(lineno)-4d - %(name)-10s - %(levelname)-8s - %(message)s",
            datefmt="%H:%M:%S"
        )
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    return logger