"""
消息数据访问层
负责消息相关的数据库操作
"""

from database.db_operations import MessageOperations
from utils.logger import setup_logger

logger = setup_logger('message_repository')


class MessageRepository:
    """消息数据访问仓库"""
    
    def __init__(self):
        self.message_ops = MessageOperations()
    
    def save_message(self, user_id: int, topic_id: int, user_message_id: int, 
                    group_message_id: int, direction: str) -> bool:
        """保存消息记录"""
        return self.message_ops.save_message(
            user_id, topic_id, user_message_id, group_message_id, direction
        )