import pymysql
import os
from dotenv import load_dotenv
from utils.logger import setup_logger

# 加载环境变量
load_dotenv()

# 设置日志记录器
logger = setup_logger('database', 'logs/database.log')

class DatabaseConnector:
    """数据库连接器类"""
    
    def __init__(self):
        """初始化数据库连接参数"""
        self.host = os.getenv('DB_HOST')
        self.user = os.getenv('DB_USER')
        self.password = os.getenv('DB_PASSWORD')
        self.db_name = os.getenv('DB_NAME')
        self.connection = None
        
    def connect(self):
        """连接到数据库"""
        try:
            # 尝试连接到数据库
            self.connection = pymysql.connect(
                host=self.host,
                user=self.user,
                password=self.password,
                charset='utf8mb4'
            )
            logger.info("成功连接到MySQL服务器")
            return self.connection
        except Exception as e:
            logger.error(f"连接数据库时出错: {e}")
            raise
            
    def create_database(self):
        """创建数据库（如果不存在）"""
        try:
            connection = self.connect()
            with connection.cursor() as cursor:
                # 创建数据库（如果不存在）
                cursor.execute(f"CREATE DATABASE IF NOT EXISTS {self.db_name} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
                logger.info(f"数据库 '{self.db_name}' 已创建或已存在")
            connection.close()
        except Exception as e:
            logger.error(f"创建数据库时出错: {e}")
            raise
            
    def get_connection(self):
        """获取数据库连接"""
        try:
            # 连接到指定的数据库
            self.connection = pymysql.connect(
                host=self.host,
                user=self.user,
                password=self.password,
                database=self.db_name,
                charset='utf8mb4'
            )
            return self.connection
        except Exception as e:
            logger.error(f"获取数据库连接时出错: {e}")
            raise