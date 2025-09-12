# ===== Builder 阶段 =====
FROM python:3.11-slim AS builder

# 安装编译 cryptography 等依赖所需工具
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      build-essential \
      libssl-dev \
      libffi-dev \
      python3-dev \
      cargo \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 升级 pip 并安装依赖到 /app/deps 目录
COPY requirements.txt .
RUN pip install --upgrade pip \
 && pip install --no-cache-dir --prefix=/app/deps -r requirements.txt

# ===== Final 阶段 =====
FROM python:3.11-slim AS final

WORKDIR /app

# 把 builder 阶段安装好的依赖复制进来
COPY --from=builder /app/deps /usr/local

# 复制代码
COPY . .

# 默认启动命令
CMD ["python", "main.py"]