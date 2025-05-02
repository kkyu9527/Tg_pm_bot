import logging
import os
from logging.handlers import RotatingFileHandler

def setup_logger(name, log_file, level=logging.INFO):
    """设置并返回一个命名的日志记录器"""
    
    # 确保日志目录存在
    os.makedirs(os.path.dirname(log_file), exist_ok=True)
    
    # 创建日志记录器
    logger = logging.getLogger(name)
    logger.setLevel(level)
    
    # 防止重复添加处理程序
    if not logger.handlers:
        # 创建文件处理程序
        file_handler = RotatingFileHandler(
            log_file, 
            maxBytes=10*1024*1024,  # 10MB
            backupCount=5,
            encoding='utf-8'
        )
        
        # 设置格式
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        file_handler.setFormatter(formatter)
        
        # 添加处理程序到日志记录器
        logger.addHandler(file_handler)
        
        # 添加控制台处理程序
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
    
    return logger