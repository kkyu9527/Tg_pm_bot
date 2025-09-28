import logging
import datetime

# 自定义日志格式化器
class CustomFormatter(logging.Formatter):
    def formatTime(self, record, datefmt=None):
        ct = datetime.datetime.fromtimestamp(record.created)
        if datefmt:
            s = ct.strftime(datefmt)
        else:
            s = ct.strftime("%Y-%m-%d %H:%M:%S")
        return s

# 自定义过滤器，用于简写 logger 名称
class LoggerNameFilter(logging.Filter):
    def filter(self, record):
        # 简化常见的长 logger 名称
        name = record.name
        if name == "uvicorn.error":
            record.name = "uv_err"
        elif name == "uvicorn.access":
            record.name = "uv_access"
        elif name.startswith("uvicorn."):
            record.name = "uvicorn"
        return True

def setup_logger(name, level=logging.INFO):
    """设置并返回一个命名的日志记录器（只输出到控制台）"""
    logger = logging.getLogger(name)
    logger.setLevel(level)

    if not logger.handlers:
        console_handler = logging.StreamHandler()
        console_handler.addFilter(LoggerNameFilter())
        formatter = CustomFormatter(
            "%(asctime)s - %(lineno)-4d - %(name)-8.8s - %(levelname)-8s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    return logger

# Uvicorn 日志配置
UVICORN_LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default": {
            "()": "utils.logger.CustomFormatter",
            "fmt": "%(asctime)s - %(lineno)-4d - %(name)-8.8s - %(levelname)-8s - %(message)s",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        },
        "access": {
            "()": "utils.logger.CustomFormatter",
            "fmt": "%(asctime)s - %(lineno)-4d - %(name)-8.8s - %(levelname)-8s - %(message)s",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        },
    },
    "filters": {
        "logger_name_filter": {
            "()": "utils.logger.LoggerNameFilter",
        },
    },
    "handlers": {
        "default": {
            "formatter": "default",
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stderr",
            "filters": ["logger_name_filter"],
        },
        "access": {
            "formatter": "access",
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stdout",
            "filters": ["logger_name_filter"],
        },
    },
    "loggers": {
        "uvicorn": {"handlers": ["default"], "level": "INFO"},
        "uvicorn.error": {"handlers": ["default"], "level": "INFO", "propagate": False},
        "uvicorn.access": {"handlers": ["access"], "level": "INFO", "propagate": False},
    },
}