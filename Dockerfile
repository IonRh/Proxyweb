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

# 检测架构并选择合适的浏览器
RUN ARCH=$(uname -m) && \
    if [ "$ARCH" = "x86_64" ]; then \
        # 为 amd64 安装 Google Chrome
        wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub | apt-key add - && \
        echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" > /etc/apt/sources.list.d/google-chrome.list && \
        apt-get update && apt-get install -y --no-install-recommends google-chrome-stable && \
        CHROMEDRIVER_URL="https://chromedriver.storage.googleapis.com"; \
        CHROMEDRIVER_VERSION=$(wget -qO- --timeout=10 $CHROMEDRIVER_URL/LATEST_RELEASE || echo "130.0.6723.58"); \
    else \
        # 为 ARM 架构安装 Chromium
        apt-get update && apt-get install -y --no-install-recommends chromium && \
        CHROMEDRIVER_URL="https://chromedriver.storage.googleapis.com"; \
        CHROMEDRIVER_VERSION=$(wget -qO- --timeout=10 $CHROMEDRIVER_URL/LATEST_RELEASE || echo "130.0.6723.58"); \
    fi && \
    # 安装 ChromeDriver
    wget -q $CHROMEDRIVER_URL/$CHROMEDRIVER_VERSION/chromedriver_linux64.zip && \
    unzip chromedriver_linux64.zip && \
    mv chromedriver /usr/local/bin/ && \
    chmod +x /usr/local/bin/chromedriver && \
    rm chromedriver_linux64.zip && \
    rm -rf /var/lib/apt/lists/*

# 安装 Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 暴露端口
EXPOSE 5000

# 使用 Gunicorn 运行 Flask 应用
CMD ["gunicorn", "--workers=4", "--bind=0.0.0.0:5000", "app:app"]
