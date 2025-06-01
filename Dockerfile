# 使用官方 Python 3.9 镜像作为基础镜像
FROM python:3.9-slim

# 设置工作目录
WORKDIR /app

# 复制应用代码
COPY . .

# 安装系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    gnupg2 \
    unzip \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# 安装 Chromium 和依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium \
    chromium-driver \
    && rm -rf /var/lib/apt/lists/*

# 安装 Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 暴露端口
EXPOSE 5000

# 使用 Gunicorn 运行 Flask 应用，优化 ARM
CMD ["gunicorn", "--workers=2", "--timeout=60", "--graceful-timeout=30", "--bind=0.0.0.0:5000", "app:app"]
