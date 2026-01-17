# 1. Start from NVIDIA CUDA base image (includes CUDA toolkit and headers)
FROM nvidia/cuda:12.3.1-devel-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=Europe/Prague

# 3. Install Python 3.12 and get-pip
RUN apt-get update && \
    apt-get install -y software-properties-common curl && \
    add-apt-repository ppa:deadsnakes/ppa && \
    apt-get update && \
    apt-get install -y python3.12 python3.12-venv python3.12-dev && \
    update-alternatives --install /usr/bin/python python /usr/bin/python3.12 1 && \
    update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.12 1 && \
    curl -sS https://bootstrap.pypa.io/get-pip.py | python3.12 && \
    rm -rf /var/lib/apt/lists/*

# 3. Install build dependencies for FFmpeg
RUN apt-get update && \
    apt-get install -y \
        autoconf automake build-essential cmake git libtool pkg-config \
        libass-dev libfreetype6-dev libgnutls28-dev libmp3lame-dev \
        libopus-dev libtheora-dev libvorbis-dev libvpx-dev libx264-dev \
        libnuma-dev yasm nasm libjpeg-dev wget tar ca-certificates \
        libgl1 libglib2.0-0 libsm6 libxext6 libxrender1 libgomp1 && \
    rm -rf /var/lib/apt/lists/*

# 4. Download and install NVIDIA Video Codec SDK headers
WORKDIR /tmp/nv-codec
RUN git clone https://git.videolan.org/git/ffmpeg/nv-codec-headers.git && \
    cd nv-codec-headers && \
    make install && \
    ldconfig

# 5. Build libvmaf from source
WORKDIR /tmp/vmaf-build
RUN apt-get update && apt-get install -y meson ninja-build xxd && \
    git clone --depth 1 https://github.com/Netflix/vmaf.git && \
    cd vmaf/libvmaf && \
    meson setup build --buildtype=release --prefix=/usr/local \
      -Dc_link_args='-lstdc++' && \
    ninja -C build && \
    ninja -C build install && \
    ldconfig && \
    rm -rf /var/lib/apt/lists/*

# 6. Build libx265 from source
WORKDIR /tmp/x265-build
RUN git clone --depth 1 https://bitbucket.org/multicoreware/x265_git.git && \
    cd x265_git && \
    rm -rf .git && \
    cd build/linux && \
    cmake -DCMAKE_INSTALL_PREFIX=/usr/local \
          -DENABLE_SHARED=ON \
          -DENABLE_CLI=OFF \
          ../../source && \
    make -j$(nproc) && make install && \
    ldconfig

# 7. Build FFmpeg with NVENC support
WORKDIR /tmp/ffmpeg-build
RUN git clone --depth 1 https://git.ffmpeg.org/ffmpeg.git ffmpeg
WORKDIR /tmp/ffmpeg-build/ffmpeg

RUN export PKG_CONFIG_PATH="/usr/local/lib/pkgconfig:$PKG_CONFIG_PATH" && \
    export LD_LIBRARY_PATH="/usr/local/lib:$LD_LIBRARY_PATH" && \
    ldconfig && \
    ./configure \
    --prefix=/usr/local \
    --extra-cflags="-I/usr/local/include -I/usr/local/cuda/include" \
    --extra-ldflags="-L/usr/local/lib -L/usr/local/cuda/lib64" \
    --extra-libs="-lpthread -lm -ldl" \
    --enable-gpl \
    --enable-nonfree \
    --enable-cuda-nvcc \
    --enable-cuda \
    --enable-cuvid \
    --enable-nvenc \
    --enable-libnpp \
    --enable-libx264 \
    --enable-libx265 \
    --enable-libmp3lame \
    --enable-libopus \
    --enable-libvpx \
    --enable-libass \
    --enable-libfreetype \
    --enable-libtheora \
    --enable-libvorbis \
    --enable-libvmaf \
    --disable-debug \
    --disable-doc && \
    make -j$(nproc) && make install && ldconfig

# 8. Verify FFmpeg installation with NVENC
RUN ffmpeg -version && ffprobe -version && \
    ffmpeg -encoders 2>/dev/null | grep nvenc && \
    ffmpeg -encoders 2>/dev/null | grep x265 && \
    ffmpeg -filters 2>/dev/null | grep vmaf

# 9. Clean up build artifacts
WORKDIR /
RUN rm -rf /tmp/ffmpeg-build /tmp/x265-build /tmp/vmaf-build /tmp/nv-codec && \
    apt-get purge -y autoconf automake build-essential cmake git libtool meson ninja-build && \
    apt-get autoremove -y && \
    apt-get clean

# 10. Set environment variable for NVIDIA runtime
ENV NVIDIA_DRIVER_CAPABILITIES=compute,utility,video

ARG DOVI_TOOL_VERSION=2.3.1
RUN wget -q https://github.com/quietvoid/dovi_tool/releases/download/${DOVI_TOOL_VERSION}/dovi_tool-${DOVI_TOOL_VERSION}-x86_64-unknown-linux-musl.tar.gz && \
    tar -xzf dovi_tool-${DOVI_TOOL_VERSION}-x86_64-unknown-linux-musl.tar.gz && \
    mv dovi_tool /usr/local/bin/ && \
    rm dovi_tool-${DOVI_TOOL_VERSION}-x86_64-unknown-linux-musl.tar.gz && \
    chmod +x /usr/local/bin/dovi_tool

# Download and install hdr10plus_tool
ARG HDR10PLUS_TOOL_VERSION=1.7.1
RUN wget -q https://github.com/quietvoid/hdr10plus_tool/releases/download/${HDR10PLUS_TOOL_VERSION}/hdr10plus_tool-${HDR10PLUS_TOOL_VERSION}-x86_64-unknown-linux-musl.tar.gz && \
    tar -xzf hdr10plus_tool-${HDR10PLUS_TOOL_VERSION}-x86_64-unknown-linux-musl.tar.gz && \
    mv hdr10plus_tool /usr/local/bin/ && \
    rm hdr10plus_tool-${HDR10PLUS_TOOL_VERSION}-x86_64-unknown-linux-musl.tar.gz && \
    chmod +x /usr/local/bin/hdr10plus_tool

# 11. Application setup
WORKDIR /app
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    python3.12 -m pip install --upgrade pip && \
    python3.12 -m pip install -r requirements.txt

COPY FastVQA-and-FasterVQA ./FastVQA-and-FasterVQA
COPY Profiles ./Profiles
COPY code ./code

EXPOSE 8000
#ENTRYPOINT ["ls /app"]

RUN chmod +x ./code/entrypoint.sh

ENTRYPOINT ["./code/entrypoint.sh"]
CMD ["--help"]