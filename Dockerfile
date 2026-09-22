# CloudBase 云托管(容器模式)部署用镜像
# 云托管要求容器监听平台注入的 PORT，并绑定 0.0.0.0，否则健康检查探不到。
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 平台会注入 PORT；容器必须监听 0.0.0.0 才能被外部与就绪探针访问。
ENV PORT=8080
ENV HOST=0.0.0.0
EXPOSE 8080

CMD ["sh", "-c", "python webapp/server.py --host ${HOST} --port ${PORT}"]
