import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from utils.app_initializer import lifespan
from utils.logger import setup_logger, UVICORN_LOGGING_CONFIG

# 加载环境变量
load_dotenv()
logger = setup_logger('main')

# 创建FastAPI应用
app = FastAPI(lifespan=lifespan)

@app.post("/webhook")
async def webhook(request: Request):
    """处理Telegram webhook回调"""
    return await app.state.webhook_controller.handle_webhook(request, app.state.application)

@app.get("/")
async def index():
    """处理首页请求"""
    return await app.state.webhook_controller.handle_index()

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=9527, log_config=UVICORN_LOGGING_CONFIG)