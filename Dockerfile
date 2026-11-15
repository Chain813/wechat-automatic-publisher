# AutoWeChat Docker Image
# 云端精简版：不含 Chrome/Stable Diffusion
# 配图采用通义万相 Qwen-Image-3.0，无密钥/限流时兜底本地 Pillow Linear Modern Light 矢量卡片

FROM python:3.11-slim

LABEL org.opencontainers.image.title="AutoWeChat"
LABEL org.opencontainers.image.description="微信公众号 AI 内容工厂 - 云端版"

# 系统依赖（Graphviz 用于架构图 + Noto CJK 中文字体用于卡片与图表）
RUN apt-get update && apt-get install -y --no-install-recommends \
    graphviz \
    fonts-noto-cjk \
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
