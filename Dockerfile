FROM python:3.11-slim

# 设置工作目录
WORKDIR /app

# 安装系统依赖 - 包括Chromium和中文字体
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    unzip \
    fonts-wqy-microhei \
    fonts-wqy-zenhei \
    xfonts-wqy \
    curl \
    && wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub | apt-key add - \
    && echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" >> /etc/apt/sources.list.d/google-chrome.list \
    && apt-get update \
    && apt-get install -y google-chrome-stable \
    && rm -rf /var/lib/apt/lists/*

# 复制requirements文件并安装Python依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 安装Playwright Python包
RUN pip install playwright

# 复制应用代码
COPY . .

# 设置环境变量
ENV PORT=8000
ENV PYTHONPATH=/app

# 暴露端口
EXPOSE $PORT

# 健康检查
HEALTHCHECK --interval=30s --timeout=30s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:$PORT/health || exit 1

# 启动命令
CMD exec uvicorn app:app --host 0.0.0.0 --port $PORT --workers 1