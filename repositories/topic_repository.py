"""
话题数据访问层
负责话题相关的数据库操作
"""

from typing import Dict, Optional, Any
from database.db_operations import TopicOperations
from utils.logger import setup_logger

logger = setup_logger('topic_repository')


class TopicRepository:
    """话题数据访问仓库"""
    
    def __init__(self):
        self.topic_ops = TopicOperations()
    
    def save_topic(self, user_id: int, topic_id: int, topic_name: str) -> bool:
        """保存话题信息"""
        return self.topic_ops.save_topic(user_id, topic_id, topic_name)
    
    def get_user_topic(self, user_id: int) -> Optional[Dict[str, Any]]:
        """获取用户的话题信息"""
        return self.topic_ops.get_user_topic(user_id)
    
    def get_topic_by_id(self, topic_id: int) -> Optional[Dict[str, Any]]:
        """根据话题ID获取话题信息"""
        return self.topic_ops.get_topic_by_id(topic_id)
    
    def delete_topic(self, topic_id: int) -> bool:
        """删除话题"""
        return self.topic_ops.delete_topic(topic_id)
    
    def topic_exists(self, topic_id: int) -> bool:
        """检查话题是否存在"""
        return self.get_topic_by_id(topic_id) is not None