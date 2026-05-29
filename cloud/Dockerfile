FROM runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04

# Install rclone + wget + build deps for FFmpeg NVENC
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget git build-essential yasm nasm pkg-config \
    libx264-dev libfdk-aac-dev \
    && curl https://rclone.org/install.sh | bash \
    && rm -rf /var/lib/apt/lists/*

# Install nv-codec-headers (for NVENC support in FFmpeg)
RUN git clone --depth 1 https://git.videolan.org/git/ffmpeg/nv-codec-headers.git /tmp/nv-codec-headers \
    && cd /tmp/nv-codec-headers && make install \
    && rm -rf /tmp/nv-codec-headers

# Build FFmpeg with NVENC + libx264 + libfdk-aac
RUN git clone --depth 1 --branch release/7.1 https://git.ffmpeg.org/ffmpeg.git /tmp/ffmpeg \
    && cd /tmp/ffmpeg \
    && ./configure \
        --enable-cuda-nvcc --enable-nvenc --enable-nonfree \
        --enable-libx264 --enable-gpl \
        --enable-libfdk-aac \
        --extra-cflags=-I/usr/local/cuda/include \
        --extra-ldflags=-L/usr/local/cuda/lib64 \
    && make -j$(nproc) \
    && make install \
    && rm -rf /tmp/ffmpeg

# Install RunPod SDK
RUN pip install --no-cache-dir runpod

# Copy worker code
COPY handler.py /handler.py
COPY filter_graph_builder.py /filter_graph_builder.py

CMD ["python", "/handler.py"]
