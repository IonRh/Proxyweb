# 使用官方 Python 3.9 镜像作为基础镜像（支持多架构，包括 ARM）
FROM python:3.9-slim

# 设置工作目录
WORKDIR /app

# 复制应用代码和 requirements.txt
COPY . .

# 设置非交互式安装，优化构建速度
ENV DEBIAN_FRONTEND=noninteractive

# 安装系统依赖，包括 Chromium 和 ChromeDriver
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    gnupg2 \
    unzip \
    ca-certificates \
    perl \
    chromium \
    chromium-driver \
    && rm -rf /var/lib/apt/lists/*

# 安装 Python 依赖
RUN pip install --no-cache-dir -r requirements.txt

# 暴露 FastAPI 应用的端口
EXPOSE 5000

# 使用 Uvicorn 运行 FastAPI 应用，优化 ARM 架构
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "5000", "--workers", "2", "--timeout-keep-alive", "60"]
