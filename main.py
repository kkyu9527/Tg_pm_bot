import os
import asyncio
from dotenv import load_dotenv
from telegram import Bot, Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from database.db_connector import DatabaseConnector
from database.db_init import DatabaseInitializer
from handlers.command_handlers import CommandHandlers
from handlers.message_handlers import MessageHandlers
from utils.logger import setup_logger

# 加载环境变量
load_dotenv()

# 设置主日志记录器
logger = setup_logger('main', 'logs/main.log')

async def main():
    """主函数"""
    try:
        logger.info("开始初始化 Telegram 私聊转发机器人")
        
        # 初始化数据库
        logger.info("初始化数据库连接")
        db_connector = DatabaseConnector()
        
        logger.info("初始化数据库表")
        db_initializer = DatabaseInitializer(db_connector)
        db_initializer.initialize_database()
        
        logger.info("数据库初始化成功")
        
        # 获取机器人令牌
        bot_token = os.getenv('BOT_TOKEN')
        if not bot_token:
            logger.error("未找到 BOT_TOKEN 环境变量")
            raise ValueError("BOT_TOKEN 环境变量未设置")
        
        # 创建应用程序
        application = Application.builder().token(bot_token).build()
        
        # 添加命令处理程序
        application.add_handler(CommandHandler("start", CommandHandlers.start_command))
        application.add_handler(CommandHandler("info", CommandHandlers.info_command))
        
        # 添加消息处理程序
        application.add_handler(MessageHandler(filters.ChatType.PRIVATE & ~filters.COMMAND, MessageHandlers.handle_user_message))
        application.add_handler(MessageHandler(filters.ChatType.GROUPS & filters.IS_TOPIC_MESSAGE, MessageHandlers.handle_owner_message))
        
        # 启动机器人
        logger.info("启动机器人")
        await application.initialize()
        await application.start()
        await application.updater.start_polling()
        
        # 保持机器人运行
        try:
            await asyncio.Future()  # 无限期运行
        finally:
            # 停止机器人
            await application.updater.stop()
            await application.stop()
            await application.shutdown()
        
    except Exception as e:
        logger.error(f"初始化过程中出错: {e}")
        raise

if __name__ == "__main__":
    asyncio.run(main())