"""
用户数据访问层
负责用户相关的数据库操作
"""

from typing import Dict, Optional, Any
from database.db_operations import UserOperations
from utils.logger import setup_logger

logger = setup_logger('user_repository')


class UserRepository:
    """用户数据访问仓库"""
    
    def __init__(self):
        self.user_ops = UserOperations()
    
    def save_user(self, user_id: int, first_name: str, last_name: Optional[str] = None, 
                  username: Optional[str] = None) -> bool:
        """保存用户信息"""
        return self.user_ops.save_user(user_id, first_name, last_name, username)
    
    def get_user_by_id(self, user_id: int) -> Optional[Dict[str, Any]]:
        """根据ID获取用户信息"""
        return self.user_ops.get_user(user_id)
    
    def user_exists(self, user_id: int) -> bool:
        """检查用户是否存在"""
        return self.get_user_by_id(user_id) is not None