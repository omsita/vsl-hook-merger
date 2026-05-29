FROM nvidia/cuda:12.4.1-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

# Install Python 3.11 + system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.11 python3.11-venv python3-pip \
    wget curl git ca-certificates \
    ffmpeg \
    && curl https://rclone.org/install.sh | bash \
    && ln -sf /usr/bin/python3.11 /usr/bin/python3 \
    && ln -sf /usr/bin/python3.11 /usr/bin/python \
    && rm -rf /var/lib/apt/lists/*

# Install RunPod SDK
RUN pip install --no-cache-dir --break-system-packages runpod

# Copy worker code
COPY handler.py /handler.py
COPY filter_graph_builder.py /filter_graph_builder.py

CMD ["python", "/handler.py"]
