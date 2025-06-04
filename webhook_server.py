import os
import json
import asyncio
from dotenv import load_dotenv
from fastapi import FastAPI, Request, Response
from contextlib import asynccontextmanager
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackQueryHandler
from handlers.command_handlers import CommandHandlers
from handlers.message_handlers import MessageHandlers
from utils.logger import setup_logger

# 加载环境变量
load_dotenv()

# 设置日志记录器
logger = setup_logger('webhook', 'logs/webhook.log')

# 获取机器人令牌
bot_token = os.getenv('BOT_TOKEN')
if not bot_token:
    raise ValueError("BOT_TOKEN 环境变量未设置")

# 创建应用程序
application = Application.builder().token(bot_token).build()

# 添加命令处理程序
application.add_handler(CommandHandler("start", CommandHandlers.start_command))
application.add_handler(CommandHandler("info", CommandHandlers.info_command))

# 添加消息处理程序
application.add_handler(MessageHandler(filters.ChatType.PRIVATE & ~filters.COMMAND, MessageHandlers.handle_user_message))
application.add_handler(MessageHandler(filters.ChatType.GROUPS & filters.IS_TOPIC_MESSAGE, MessageHandlers.handle_owner_message))

# 添加按钮回调处理程序
application.add_handler(CallbackQueryHandler(MessageHandlers.handle_button_callback))

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时运行
    async with application:
        await application.start()
        yield
        # 关闭时运行
        await application.stop()

app = FastAPI(lifespan=lifespan)

@app.post("/webhook")
async def webhook(request: Request):
    # 获取更新数据
    data = await request.json()
    logger.info(f"收到Webhook更新: {data}")
    
    # 处理更新
    update = Update.de_json(data=data, bot=application.bot)
    await application.update_queue.put(update)
    
    return Response(content="OK", status_code=200)

@app.get("/")
async def index():
    return {"status": "running"}

# 运行服务器
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=9527)