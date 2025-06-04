from database.db_connector import DatabaseConnector
from utils.logger import setup_logger

# 设置日志记录器
logger = setup_logger('db_init', 'logs/db_init.log')

class DatabaseInitializer:
    """数据库初始化类"""

    def __init__(self, db_connector):
        self.db_connector = db_connector

    def initialize_database(self):
        """初始化数据库和表"""
        self.db_connector.create_database()
        self.create_tables()

    def create_tables(self):
        """创建所需的表"""
        try:
            connection = self.db_connector.get_connection()
            with connection.cursor() as cursor:
                # 创建用户表
                cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id BIGINT PRIMARY KEY,
                    first_name VARCHAR(255),
                    last_name VARCHAR(255),
                    username VARCHAR(255),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """)

                # 创建话题表
                cursor.execute("""
                CREATE TABLE IF NOT EXISTS topics (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    topic_id BIGINT NOT NULL,
                    topic_name VARCHAR(255) NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id),
                    UNIQUE KEY unique_topic (topic_id)
                )
                """)

                # 创建消息表
                cursor.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    topic_id BIGINT NOT NULL,
                    user_message_id BIGINT NOT NULL,
                    group_message_id BIGINT,
                    direction ENUM('user_to_owner', 'owner_to_user') NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id),
                    FOREIGN KEY (topic_id) REFERENCES topics(topic_id)
                )
                """)

            connection.commit()
            logger.info("所有数据库表已成功创建")
            connection.close()

        except Exception as e:
            logger.error(f"创建表时出错: {e}")
            raise