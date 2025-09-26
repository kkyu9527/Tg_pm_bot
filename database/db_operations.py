from database.db_connector import DatabaseConnector
from utils.logger import setup_logger
from utils.display_helpers import get_user_display_name_from_object
from typing import Dict, Optional, Any
from contextlib import contextmanager
import pymysql.cursors

# 设置日志记录器
logger = setup_logger('db_operations')

@contextmanager
def get_db_connection(db_connector):
    """数据库连接上下文管理器"""
    connection = None
    try:
        connection = db_connector.get_connection()
        yield connection
    finally:
        if connection:
            connection.close()

class UserOperations:
    """用户数据库操作类"""

    def __init__(self):
        """初始化数据库连接"""
        self.db_connector = DatabaseConnector()

    def save_user(self, user_id: int, first_name: str, last_name: Optional[str] = None, username: Optional[str] = None) -> bool:
        """保存用户信息到数据库"""
        try:
            with get_db_connection(self.db_connector) as connection:
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
                    # 使用工具函数生成显示名称
                    class MockUser:
                        def __init__(self, first_name, last_name, username, user_id):
                            self.first_name = first_name
                            self.last_name = last_name
                            self.username = username
                            self.id = user_id
                    
                    mock_user = MockUser(first_name, last_name, username, user_id)
                    user_display = get_user_display_name_from_object(mock_user)
                    logger.info(f"用户 {user_display} 信息已保存")
                    return True
        except Exception as e:
            logger.error(f"保存用户信息时出错: {e}")
            return False

    def get_user(self, user_id: int) -> Optional[Dict[str, Any]]:
        """获取用户信息"""
        try:
            with get_db_connection(self.db_connector) as connection:
                with connection.cursor(pymysql.cursors.DictCursor) as cursor:
                    cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
                    return cursor.fetchone()
        except Exception as e:
            logger.error(f"获取用户信息时出错: {e}")
            return None


class TopicOperations:
    """话题数据库操作类"""

    def __init__(self):
        """初始化数据库连接"""
        self.db_connector = DatabaseConnector()

    def save_topic(self, user_id: int, topic_id: int, topic_name: str) -> bool:
        """保存话题信息到数据库"""
        connection = None
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
                logger.info(f"话题 {topic_name} [话题ID:{topic_id}] 信息已保存")
                return True
        except Exception as e:
            logger.error(f"保存话题信息时出错: {e}")
            return False
        finally:
            if connection:
                connection.close()

    def get_user_topic(self, user_id: int) -> Optional[Dict[str, Any]]:
        """获取用户的话题信息"""
        connection = None
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
        connection = None
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

    def delete_topic(self, topic_id: int) -> bool:
        connection = None
        try:
            connection = self.db_connector.get_connection()
            with connection.cursor() as cursor:
                # 获取该话题的用户ID
                cursor.execute("SELECT user_id FROM topics WHERE topic_id = %s", (topic_id,))
                result = cursor.fetchone()
                if not result:
                    logger.warning(f"未找到 topic_id 为 {topic_id} 的话题，跳过删除")
                    return False
                user_id = result[0]

                # 删除与该话题相关的记录
                cursor.execute("DELETE FROM messages WHERE topic_id = %s", (topic_id,))
                cursor.execute("DELETE FROM topics WHERE topic_id = %s", (topic_id,))
                cursor.execute("DELETE FROM users WHERE id = %s", (user_id,))
                connection.commit()
                logger.info(f"话题 {topic_id} 及其相关消息与用户数据已从数据库中删除")
                return True
        except Exception as e:
            logger.error(f"删除话题时出错: {e}")
            return False
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
        connection = None
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
                # 使用工具函数生成用户显示名称
                from utils.display_helpers import get_user_display_name_from_db
                user_display = get_user_display_name_from_db(user_id, UserOperations())
                logger.info(f"消息记录已保存: 用户 {user_display}, 话题ID {topic_id}")
                return True
        except Exception as e:
            logger.error(f"保存消息记录时出错: {e}")
            return False
        finally:
            if connection:
                connection.close()