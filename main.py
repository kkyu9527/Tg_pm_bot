import os
import asyncio
import time
from dotenv import load_dotenv
from telegram import Bot, Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from database.db_connector import DatabaseConnector
from database.db_init import DatabaseInitializer
from handlers.command_handlers import CommandHandlers
from handlers.message_handlers import MessageHandlers
from utils.logger import setup_logger
import httpx

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
        
        # 获取Webhook URL
        webhook_url = os.getenv('WEBHOOK_URL')
        if not webhook_url:
            logger.error("未找到 WEBHOOK_URL 环境变量")
            raise ValueError("WEBHOOK_URL 环境变量未设置")
        
        # 创建应用程序，设置连接超时和重试
        application = Application.builder().token(bot_token).connect_timeout(60.0).pool_timeout(60.0).read_timeout(60.0).build()
        
        # 添加命令处理程序
        application.add_handler(CommandHandler("start", CommandHandlers.start_command))
        application.add_handler(CommandHandler("info", CommandHandlers.info_command))
        
        # 添加消息处理程序
        application.add_handler(MessageHandler(filters.ChatType.PRIVATE & ~filters.COMMAND, MessageHandlers.handle_user_message))
        application.add_handler(MessageHandler(filters.ChatType.GROUPS & filters.IS_TOPIC_MESSAGE, MessageHandlers.handle_owner_message))
        
        # 添加按钮回调处理程序
        application.add_handler(CallbackQueryHandler(MessageHandlers.handle_button_callback))
        
        # 启动机器人，使用Webhook而不是轮询
        logger.info("启动机器人")
        max_retries = 10
        retry_count = 0
        
        while retry_count < max_retries:
            try:
                await application.initialize()
                await application.start()
                
                # 设置Webhook
                await application.bot.set_webhook(url=webhook_url)
                logger.info(f"成功设置Webhook: {webhook_url}")
                
                # 保持程序运行
                logger.info("机器人启动成功")
                await asyncio.Future()  # 无限等待，保持程序运行
                break
            except httpx.ConnectTimeout:
                retry_count += 1
                wait_time = retry_count * 10
                logger.warning(f"连接超时，第 {retry_count} 次重试，等待 {wait_time} 秒...")
                await asyncio.sleep(wait_time)
            except httpx.ConnectError:
                retry_count += 1
                wait_time = retry_count * 10
                logger.warning(f"连接错误，第 {retry_count} 次重试，等待 {wait_time} 秒...")
                await asyncio.sleep(wait_time)
            except Exception as e:
                logger.error(f"启动机器人时出错: {e}")
                raise
        
        if retry_count >= max_retries:
            logger.error(f"连接超时，已重试 {max_retries} 次，请检查网络连接")
            print("网络连接失败，请检查您的网络设置或代理配置")
            return
        
    except Exception as e:
        logger.error(f"初始化过程中出错: {e}")
        raise
    finally:
        # 停止机器人
        if 'application' in locals():
            await application.bot.delete_webhook()
            await application.stop()
            await application.shutdown()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("程序被用户中断")
    except Exception as e:
        print(f"程序出错: {e}")