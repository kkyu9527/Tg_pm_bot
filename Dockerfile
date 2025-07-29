FROM python:3.11-slim

# 安装编译 cryptography 所需依赖（含 Rust 工具链）
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      build-essential \
      libssl-dev \
      libffi-dev \
      python3-dev \
      cargo \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 升级 pip 并安装 requirements.txt 中所有依赖（包含 cryptography）
COPY requirements.txt ./
RUN pip install --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt

# 若你还想单独指定安装最新 cryptography，可以加在这里
# RUN pip install --no-cache-dir cryptography

COPY . .

CMD ["python", "main.py"]