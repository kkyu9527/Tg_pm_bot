from database.db_connector import DatabaseConnector
from utils.logger import setup_logger
from typing import Dict, Optional, List, Any
import pymysql

# 设置日志记录器
logger = setup_logger('db_operations', 'logs/db_operations.log')

class UserOperations:
    """用户数据库操作类"""
    
    def __init__(self):
        """初始化数据库连接"""
        self.db_connector = DatabaseConnector()
    
    def save_user(self, user_id: int, first_name: str, last_name: Optional[str] = None, username: Optional[str] = None) -> bool:
        """保存用户信息到数据库"""
        try:
            connection = self.db_connector.get_connection()
            with connection.cursor() as cursor:
                # 检查用户是否已存在
                cursor.execute("SELECT id FROM users WHERE id = %s", (user_id,))
                if cursor.fetchone():
                    # 更新用户信息
                    cursor.execute(
                        "UPDATE users SET first_name = %s, last_name = %s, username = %s WHERE id = %s",
                        (first_name, last_name, username, user_id)
                    )
                else:
                    # 插入新用户
                    cursor.execute(
                        "INSERT INTO users (id, first_name, last_name, username) VALUES (%s, %s, %s, %s)",
                        (user_id, first_name, last_name, username)
                    )
                connection.commit()
                logger.info(f"用户 {user_id} 信息已保存")
                return True
        except Exception as e:
            logger.error(f"保存用户信息时出错: {e}")
            return False
        finally:
            if connection:
                connection.close()
    
    def get_user(self, user_id: int) -> Optional[Dict[str, Any]]:
        """获取用户信息"""
        try:
            connection = self.db_connector.get_connection()
            with connection.cursor(pymysql.cursors.DictCursor) as cursor:
                cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
                return cursor.fetchone()
        except Exception as e:
            logger.error(f"获取用户信息时出错: {e}")
            return None
        finally:
            if connection:
                connection.close()


class TopicOperations:
    """话题数据库操作类"""
    
    def __init__(self):
        """初始化数据库连接"""
        self.db_connector = DatabaseConnector()
    
    def save_topic(self, user_id: int, topic_id: int, topic_name: str) -> bool:
        """保存话题信息到数据库"""
        try:
            connection = self.db_connector.get_connection()
            with connection.cursor() as cursor:
                # 检查话题是否已存在
                cursor.execute("SELECT id FROM topics WHERE topic_id = %s", (topic_id,))
                if cursor.fetchone():
                    # 更新话题信息
                    cursor.execute(
                        "UPDATE topics SET user_id = %s, topic_name = %s WHERE topic_id = %s",
                        (user_id, topic_name, topic_id)
                    )
                else:
                    # 插入新话题
                    cursor.execute(
                        "INSERT INTO topics (user_id, topic_id, topic_name) VALUES (%s, %s, %s)",
                        (user_id, topic_id, topic_name)
                    )
                connection.commit()
                logger.info(f"话题 {topic_id} 信息已保存")
                return True
        except Exception as e:
            logger.error(f"保存话题信息时出错: {e}")
            return False
        finally:
            if connection:
                connection.close()
    
    def get_user_topic(self, user_id: int) -> Optional[Dict[str, Any]]:
        """获取用户的话题信息"""
        try:
            connection = self.db_connector.get_connection()
            with connection.cursor(pymysql.cursors.DictCursor) as cursor:
                cursor.execute("SELECT * FROM topics WHERE user_id = %s", (user_id,))
                return cursor.fetchone()
        except Exception as e:
            logger.error(f"获取用户话题信息时出错: {e}")
            return None
        finally:
            if connection:
                connection.close()
    
    def get_topic_by_id(self, topic_id: int) -> Optional[Dict[str, Any]]:
        """通过话题ID获取话题信息"""
        try:
            connection = self.db_connector.get_connection()
            with connection.cursor(pymysql.cursors.DictCursor) as cursor:
                cursor.execute("SELECT * FROM topics WHERE topic_id = %s", (topic_id,))
                return cursor.fetchone()
        except Exception as e:
            logger.error(f"获取话题信息时出错: {e}")
            return None
        finally:
            if connection:
                connection.close()


class MessageOperations:
    """消息数据库操作类"""
    
    def __init__(self):
        """初始化数据库连接"""
        self.db_connector = DatabaseConnector()
    
    def save_message(self, user_id: int, topic_id: int,
                    user_message_id: int, group_message_id: int, direction: str) -> bool:
        """保存消息记录到数据库"""
        try:
            connection = self.db_connector.get_connection()
            with connection.cursor() as cursor:
                cursor.execute(
                    """INSERT INTO messages 
                    (user_id, topic_id, user_message_id, group_message_id, direction) 
                    VALUES (%s, %s, %s, %s, %s)""",
                    (user_id, topic_id, user_message_id, group_message_id, direction)
                )
                connection.commit()
                logger.info(f"消息记录已保存: 用户 {user_id}, 话题 {topic_id}")
                return True
        except Exception as e:
            logger.error(f"保存消息记录时出错: {e}")
            return False
        finally:
            if connection:
                connection.close()
    
    def save_message_mapping(self, group_message_id: int, forwarded_message_id: int) -> bool:
        """保存消息映射关系"""
        try:
            connection = self.db_connector.get_connection()
            with connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO message_mapping (group_message_id, forwarded_message_id) VALUES (%s, %s)",
                    (group_message_id, forwarded_message_id)
                )
                connection.commit()
                logger.info(f"消息映射已保存: 群组消息 {group_message_id}, 转发消息 {forwarded_message_id}")
                return True
        except Exception as e:
            logger.error(f"保存消息映射时出错: {e}")
            return False
        finally:
            if connection:
                connection.close()