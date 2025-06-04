import os
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackQueryHandler
from database.db_connector import DatabaseConnector
from database.db_init import DatabaseInitializer
from handlers.command_handlers import CommandHandlers
from handlers.message_handlers import MessageHandlers
from utils.logger import setup_logger
from fastapi import FastAPI, Request, Response
from contextlib import asynccontextmanager
import uvicorn

# 加载环境变量
load_dotenv()

# 设置主日志记录器
logger = setup_logger('main', 'logs/main.log')

application = None  # 全局变量

@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        logger.info("开始初始化 Telegram 私聊转发机器人")

        logger.info("初始化数据库连接")
        db_connector = DatabaseConnector()

        logger.info("初始化数据库表")
        db_initializer = DatabaseInitializer(db_connector)
        db_initializer.initialize_database()

        logger.info("数据库初始化成功")

        bot_token = os.getenv('BOT_TOKEN')
        if not bot_token:
            logger.error("未找到 BOT_TOKEN 环境变量")
            raise ValueError("BOT_TOKEN 环境变量未设置")

        webhook_url = os.getenv('WEBHOOK_URL')
        if not webhook_url:
            logger.error("未找到 WEBHOOK_URL 环境变量")
            raise ValueError("WEBHOOK_URL 环境变量未设置")

        global application
        application = Application.builder().token(bot_token).connect_timeout(60.0).pool_timeout(60.0).read_timeout(60.0).build()

        application.add_handler(CommandHandler("start", CommandHandlers.start_command))
        application.add_handler(CommandHandler("info", CommandHandlers.info_command))
        application.add_handler(MessageHandler(filters.ChatType.PRIVATE & ~filters.COMMAND, MessageHandlers.handle_user_message))
        application.add_handler(MessageHandler(filters.ChatType.GROUPS & filters.IS_TOPIC_MESSAGE, MessageHandlers.handle_owner_message))
        application.add_handler(CallbackQueryHandler(MessageHandlers.handle_button_callback))

        await application.initialize()
        await application.start()
        await application.bot.set_webhook(url=webhook_url)
        logger.info(f"成功设置Webhook: {webhook_url}")

        yield
    except Exception as e:
        logger.error(f"初始化过程中出错: {e}")
        raise
    finally:
        if application:
            await application.bot.delete_webhook()
            await application.stop()
            await application.shutdown()


app = FastAPI(lifespan=lifespan)

@app.post("/webhook")
async def webhook(request: Request):
    data = await request.json()
    logger.info(f"收到Webhook更新: {data}")
    update = Update.de_json(data=data, bot=application.bot)
    await application.update_queue.put(update)
    return Response(content="OK", status_code=200)

@app.get("/")
async def index():
    return {"status": "running"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=9527)