import logging
import datetime
from typing import Optional

# 日志格式常量
DEFAULT_LOG_FORMAT = "%(asctime)s - %(lineno)-4d - %(name)-8.8s - %(levelname)-8s - %(message)s"
DEFAULT_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

class CustomFormatter(logging.Formatter):
    """自定义日志格式化器
    
    重写formatTime方法以提供一致的时间格式
    """
    def formatTime(self, record, datefmt: Optional[str] = None) -> str:
        """格式化日志记录的时间
        
        Args:
            record: 日志记录对象
            datefmt: 日期格式字符串
            
        Returns:
            格式化后的时间字符串
        """
        ct = datetime.datetime.fromtimestamp(record.created)
        if datefmt:
            s = ct.strftime(datefmt)
        else:
            s = ct.strftime(DEFAULT_DATE_FORMAT)
        return s

class LoggerNameFilter(logging.Filter):
    """自定义日志过滤器
    
    用于简化和标准化日志记录器名称，特别是uvicorn相关的日志
    """
    def filter(self, record) -> bool:
        """过滤并修改日志记录
        
        Args:
            record: 日志记录对象
            
        Returns:
            始终返回True，表示记录应该被处理
        """
        # 简化常见的长logger名称
        name = record.name
        if name == "uvicorn.error":
            record.name = "uv_err"
        elif name == "uvicorn.access":
            record.name = "uv_access"
        elif name.startswith("uvicorn."):
            record.name = "uvicorn"
        return True

def setup_logger(name: str, level: int = logging.INFO) -> logging.Logger:
    """设置并返回一个命名的日志记录器
    
    创建一个带有控制台处理器的日志记录器，应用自定义格式和过滤器
    
    Args:
        name: 日志记录器名称
        level: 日志级别，默认为INFO
        
    Returns:
        配置好的日志记录器实例
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)

    # 只有在没有处理器时才添加新的处理器，避免重复
    if not logger.handlers:
        console_handler = logging.StreamHandler()
        console_handler.addFilter(LoggerNameFilter())
        formatter = CustomFormatter(
            DEFAULT_LOG_FORMAT,
            datefmt=DEFAULT_DATE_FORMAT
        )
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    return logger

# Uvicorn日志配置
UVICORN_LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default": {
            "()": "utils.logger.CustomFormatter",
            "fmt": DEFAULT_LOG_FORMAT,
            "datefmt": DEFAULT_DATE_FORMAT,
        },
        "access": {
            "()": "utils.logger.CustomFormatter",
            "fmt": DEFAULT_LOG_FORMAT,
            "datefmt": DEFAULT_DATE_FORMAT,
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