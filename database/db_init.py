from utils.logger import setup_logger
import pymysql

# 设置日志记录器
logger = setup_logger('db_init')

class DatabaseInitializer:
    """数据库初始化类"""

    def __init__(self, db_connector):
        self.db_connector = db_connector

    def initialize_database(self):
        """初始化数据库和表"""
        self.db_connector.create_database()
        self.create_tables()
        self.update_table_structure()  # 检查并更新表结构

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
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """)

                # 创建话题表
                cursor.execute("""
                CREATE TABLE IF NOT EXISTS topics (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    topic_id BIGINT NOT NULL,
                    topic_name VARCHAR(255) NOT NULL,
                    group_id VARCHAR(255) DEFAULT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                    UNIQUE KEY unique_topic (topic_id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
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
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                    FOREIGN KEY (topic_id) REFERENCES topics(topic_id) ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """)

            connection.commit()
            logger.info("所有数据库表已成功创建")
            connection.close()

        except Exception as e:
            logger.error(f"创建表时出错: {e}")
            raise

    def update_table_structure(self):
        """检查并更新表结构，添加缺失的字段"""
        try:
            connection = self.db_connector.get_connection()
            with connection.cursor() as cursor:
                # 检查并更新所有表的结构
                self._update_users_table_structure(cursor)
                self._update_topics_table_structure(cursor)
                self._update_messages_table_structure(cursor)
                
                connection.commit()
                logger.info("数据库表结构检查和更新完成")

            connection.close()

        except Exception as e:
            logger.error(f"更新表结构时出错: {e}")
            # 不抛出异常，因为这不应该阻止程序启动

    def _update_users_table_structure(self, cursor):
        """检查并更新users表结构"""
        # 检查users表的必需字段
        required_fields = {
            'id': "BIGINT PRIMARY KEY",
            'first_name': "VARCHAR(255)",
            'last_name': "VARCHAR(255)",
            'username': "VARCHAR(255)",
            'created_at': "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
        }
        
        for field_name, field_definition in required_fields.items():
            if not self._field_exists(cursor, 'users', field_name):
                try:
                    if field_name == 'id':
                        cursor.execute(f"ALTER TABLE users ADD COLUMN {field_name} {field_definition}")
                    else:
                        cursor.execute(f"ALTER TABLE users ADD COLUMN {field_name} {field_definition}")
                    logger.info(f"已添加字段 {field_name} 到 users 表")
                except Exception as e:
                    logger.warning(f"添加字段 {field_name} 到 users 表时出错: {e}")

    def _update_topics_table_structure(self, cursor):
        """检查并更新topics表结构"""
        # 检查topics表的必需字段
        required_fields = {
            'id': "INT AUTO_INCREMENT PRIMARY KEY",
            'user_id': "BIGINT NOT NULL",
            'topic_id': "BIGINT NOT NULL",
            'topic_name': "VARCHAR(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL",
            'group_id': "VARCHAR(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL",  # 新增字段
            'created_at': "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
        }
        
        for field_name, field_definition in required_fields.items():
            if not self._field_exists(cursor, 'topics', field_name):
                try:
                    cursor.execute(f"ALTER TABLE topics ADD COLUMN {field_name} {field_definition}")
                    logger.info(f"已添加字段 {field_name} 到 topics 表")
                except Exception as e:
                    logger.warning(f"添加字段 {field_name} 到 topics 表时出错: {e}")

    def _update_messages_table_structure(self, cursor):
        """检查并更新messages表结构"""
        # 检查messages表的必需字段
        required_fields = {
            'id': "INT AUTO_INCREMENT PRIMARY KEY",
            'user_id': "BIGINT NOT NULL",
            'topic_id': "BIGINT NOT NULL",
            'user_message_id': "BIGINT NOT NULL",
            'group_message_id': "BIGINT",
            'direction': "ENUM('user_to_owner', 'owner_to_user') NOT NULL",
            'created_at': "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
        }
        
        for field_name, field_definition in required_fields.items():
            if not self._field_exists(cursor, 'messages', field_name):
                try:
                    cursor.execute(f"ALTER TABLE messages ADD COLUMN {field_name} {field_definition}")
                    logger.info(f"已添加字段 {field_name} 到 messages 表")
                except Exception as e:
                    logger.warning(f"添加字段 {field_name} 到 messages 表时出错: {e}")

    def _field_exists(self, cursor, table_name, field_name):
        """检查字段是否存在"""
        cursor.execute("""
            SELECT COLUMN_NAME 
            FROM INFORMATION_SCHEMA.COLUMNS 
            WHERE TABLE_SCHEMA = %s 
            AND TABLE_NAME = %s 
            AND COLUMN_NAME = %s
        """, (self.db_connector.db_name, table_name, field_name))
        
        return cursor.fetchone() is not None