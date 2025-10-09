FROM python:3.11-slim

WORKDIR /app

# 安装系统依赖 - 使用现代的方式安装Chrome
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    unzip \
    fonts-wqy-microhei \
    fonts-wqy-zenhei \
    xfonts-wqy \
    curl \
    && mkdir -p /etc/apt/keyrings \
    && wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub | gpg --dearmor -o /etc/apt/keyrings/google-chrome.gpg \
    && echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/google-chrome.gpg] http://dl.google.com/linux/chrome/deb/ stable main" >> /etc/apt/sources.list.d/google-chrome.list \
    && apt-get update \
    && apt-get install -y google-chrome-stable \
    && rm -rf /var/lib/apt/lists/*

# 复制项目文件
COPY . .

# 安装Python依赖
RUN pip install --no-cache-dir -r requirements.txt

# 暴露端口
EXPOSE 8000

# 启动命令
CMD ["python", "app.py"]
