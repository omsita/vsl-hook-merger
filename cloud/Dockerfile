FROM nvidia/cuda:12.4.1-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

# Install Python 3 (Ubuntu 22.04 default = 3.10) + system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip python3-venv \
    wget curl ca-certificates unzip \
    ffmpeg \
    && curl https://rclone.org/install.sh | bash \
    && ln -sf /usr/bin/python3 /usr/bin/python \
    && rm -rf /var/lib/apt/lists/*

# Install RunPod SDK
RUN pip install --no-cache-dir runpod

# Copy worker code
COPY handler.py /handler.py
COPY filter_graph_builder.py /filter_graph_builder.py

CMD ["python", "/handler.py"]
