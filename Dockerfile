# AutoWeChat Docker Image
# 云端精简版：不含 Chrome/Selenium/Ollama/Stable Diffusion
# 图片降级到免费图源 (Unsplash + Bing)
# 图片评分降级到 Gemini Vision (免费层)

FROM python:3.11-slim

LABEL org.opencontainers.image.title="AutoWeChat"
LABEL org.opencontainers.image.description="微信公众号 AI 内容工厂 - 云端版"

# 系统依赖（仅 Graphviz 用于 diagrams 架构图，可选）
RUN apt-get update && apt-get install -y --no-install-recommends \
    graphviz \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 先复制依赖清单，利用 Docker 层缓存
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制项目文件
COPY . .

# 云端模式环境变量
ENV CLOUD_MODE=1
ENV SD_ENABLED=False
ENV PYTHONUNBUFFERED=1

# Render 使用 $PORT 环境变量
EXPOSE 5000

CMD ["python", "webui.py"]
