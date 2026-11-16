# 1. Start from NVIDIA CUDA base image (includes CUDA toolkit and headers)
FROM nvidia/cuda:12.8.1-devel-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=Europe/Prague

# 2. Install Python 3.12 and get-pip
RUN apt-get update && \
    apt-get install -y software-properties-common curl && \
    add-apt-repository ppa:deadsnakes/ppa && \
    apt-get install -y python3.12 python3.12-venv python3.12-dev && \
    update-alternatives --install /usr/bin/python python /usr/bin/python3.12 1 && \
    update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.12 1 && \
    curl -sS https://bootstrap.pypa.io/get-pip.py | python3.12 && \
    rm -rf /var/lib/apt/lists/*

# 3. Install build dependencies for FFmpeg
RUN apt-get update && \
    apt-get install -y \
        autoconf automake build-essential cmake git libtool pkg-config \
        clang \
        rustc cargo \
        libssl-dev \
        libass-dev libfreetype6-dev libgnutls28-dev libmp3lame-dev \
        libopus-dev libtheora-dev libvorbis-dev libvpx-dev libx264-dev \
        libnuma-dev yasm nasm libjpeg-dev wget tar ca-certificates \
        ocl-icd-libopencl1 ocl-icd-opencl-dev opencl-headers clinfo \
        libgl1 libglib2.0-0 libsm6 libxext6 libxrender1 libgomp1 && \
    rm -rf /var/lib/apt/lists/*

# OpenCL ICD for the NVIDIA runtime
RUN mkdir -p /etc/OpenCL/vendors && \
    echo "libnvidia-opencl.so.1" > /etc/OpenCL/vendors/nvidia.icd

# 4. Install Rust toolchain and cargo-c
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
ENV PATH="/root/.cargo/bin:${PATH}"
RUN rustup toolchain install nightly && rustup default nightly
RUN cargo install cargo-c --locked

# 5. Download and install NVIDIA Video Codec SDK headers
WORKDIR /tmp/nv-codec
RUN git clone https://git.videolan.org/git/ffmpeg/nv-codec-headers.git && \
    cd nv-codec-headers && \
    make install && \
    ldconfig

# 6. Build libvmaf from source
WORKDIR /tmp/vmaf-build
RUN apt-get update && apt-get install -y meson ninja-build xxd && \
    git clone --depth 1 https://github.com/Netflix/vmaf.git && \
    cd vmaf/libvmaf && \
    meson setup build --buildtype=release --prefix=/usr/local \
      -Denable_cuda=true \
      -Dc_link_args='-lstdc++' && \
    ninja -C build && \
    ninja -C build install && \
    ldconfig && \
    rm -rf /var/lib/apt/lists/*

# 7. Build libx265 from source (multilib: 8/10/12-bit)
WORKDIR /tmp/x265-build
RUN git clone --depth 1 https://bitbucket.org/multicoreware/x265_git.git && \
    cd x265_git && \
    rm -rf .git && \
    cd build/linux && \
    mkdir -p 8bit 10bit 12bit && \
    cd 12bit && \
    cmake ../../../source \
          -DHIGH_BIT_DEPTH=ON -DMAIN12=ON \
          -DEXPORT_C_API=OFF -DENABLE_SHARED=OFF -DENABLE_CLI=OFF && \
    make -j"$(nproc)" && \
    cd ../10bit && \
    cmake ../../../source \
          -DHIGH_BIT_DEPTH=ON \
          -DEXPORT_C_API=OFF -DENABLE_SHARED=OFF -DENABLE_CLI=OFF && \
    make -j"$(nproc)" && \
    cd ../8bit && \
    ln -sf ../10bit/libx265.a libx265_main10.a && \
    ln -sf ../12bit/libx265.a libx265_main12.a && \
    cmake ../../../source \
          -DCMAKE_INSTALL_PREFIX=/usr/local \
          -DENABLE_SHARED=ON -DENABLE_CLI=OFF \
          -DEXTRA_LIB="x265_main10.a;x265_main12.a" \
          -DEXTRA_LINK_FLAGS=-L. \
          -DLINKED_10BIT=ON -DLINKED_12BIT=ON && \
    make -j"$(nproc)" && make install && \
    ldconfig

# 8. Build libdav1d from source
WORKDIR /tmp/dav1d-build
RUN git clone --depth 1 https://code.videolan.org/videolan/dav1d.git && \
    cd dav1d && \
    rm -rf .git && \
    meson setup build \
      --buildtype=release \
      --prefix=/usr/local && \
    ninja -C build -j"$(nproc)" && \
    ninja -C build install && \
    ldconfig

# 9. Build + install libdovi (from dovi_tool repo, dolby_vision subdir)
WORKDIR /tmp/dovi_tool
RUN git clone --depth 1 https://github.com/quietvoid/dovi_tool.git . && \
    cd ./dolby_vision && \
    cargo cinstall --release --prefix=/usr/local --libdir=/usr/local/lib && \
    ldconfig && \
    pkg-config --exists dovi && pkg-config --modversion dovi && \
    ls -la /usr/local/lib/libdovi* /usr/local/lib/pkgconfig/dovi.pc

# 10. Build + install libhdr10plus-rs (from hdr10plus_tool repo, hdr10plus subdir)
WORKDIR /tmp/hdr10plus_tool
RUN git clone --depth 1 https://github.com/quietvoid/hdr10plus_tool.git . && \
    cd ./hdr10plus && \
    cargo cinstall --release --prefix=/usr/local --libdir=/usr/local/lib && \
    ldconfig && \
    pkg-config --exists hdr10plus-rs && pkg-config --modversion hdr10plus-rs && \
    ls -la /usr/local/lib/libhdr10plus* /usr/local/lib/pkgconfig/hdr10plus-rs.pc

# 11. Build and install SVT-AV1-HDR (libsvtav1)
WORKDIR /tmp/svtav1hdr
RUN git clone --depth 1 https://github.com/juliobbv-p/svt-av1-hdr.git . && \
    ./Build/linux/build.sh release --enable-dovi --enable-hdr10plus && \
    install -d /usr/local/lib/pkgconfig && \
    install -m 0644 /tmp/svtav1hdr/Build/linux/Release/SvtAv1Enc.pc /usr/local/lib/pkgconfig/ && \
    ldconfig

RUN pkg-config --modversion SvtAv1Enc

RUN install -d /usr/local/bin && \
    install -m 0755 /tmp/svtav1hdr/Bin/Release/SvtAv1EncApp /usr/local/bin/ && \
    ldconfig

# 12. Build and install libfdk-aac
WORKDIR /tmp/fdk-aac
#apt-get update && apt-get install -y autoconf automake libtool pkg-config && \
RUN     git clone --depth 1 https://github.com/mstorsjo/fdk-aac.git . && \
    autoreconf -fiv && \
    ./configure --prefix=/usr/local && \
    make -j"$(nproc)" && \
    make install && \
    ldconfig

# 13. Build FFmpeg with NVENC support
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
    --enable-libdav1d \
#    --enable-libsvtav1 \
    --enable-libfdk_aac \
    --enable-opencl \
    --enable-filter=libvmaf_cuda \
    --disable-debug \
    --disable-doc && \
    make -j$(nproc) && make install && ldconfig

# 14. Verify FFmpeg installation (NVENC, x265 8/10/12-bit, VMAF)
RUN ffmpeg -version && ffprobe -version && \
    ffmpeg -encoders 2>/dev/null | grep nvenc && \
    ffmpeg -encoders 2>/dev/null | grep x265 && \
    ffmpeg -hide_banner -h encoder=libx265 | grep yuv420p10le && \
    ffmpeg -hide_banner -h encoder=libx265 | grep yuv420p12le && \
    ffmpeg -hide_banner -f lavfi -i testsrc2=size=320x240:rate=1 -frames:v 1 -c:v libx265 -pix_fmt yuv420p10le -profile:v main10 -f null - && \
    ffmpeg -filters 2>/dev/null | grep vmaf && \
    ffmpeg -filters 2>/dev/null | grep nlmeans_opencl && \
    ffmpeg -filters 2>/dev/null | grep libvmaf_cuda

# 15. Clean up build artifacts
WORKDIR /
RUN rm -rf /tmp/ffmpeg-build /tmp/x265-build /tmp/vmaf-build /tmp/nv-codec && \
    apt-get purge -y autoconf automake build-essential cmake git libtool meson ninja-build && \
    apt-get autoremove -y && \
    apt-get clean

# 16. Set environment variable for NVIDIA runtime
ENV NVIDIA_DRIVER_CAPABILITIES=compute,utility,video


# 17. Download and install dovi_tool
ARG DOVI_TOOL_VERSION=2.3.3
RUN wget -q https://github.com/quietvoid/dovi_tool/releases/download/${DOVI_TOOL_VERSION}/dovi_tool-${DOVI_TOOL_VERSION}-x86_64-unknown-linux-musl.tar.gz && \
    tar -xzf dovi_tool-${DOVI_TOOL_VERSION}-x86_64-unknown-linux-musl.tar.gz && \
    mv dovi_tool /usr/local/bin/ && \
    rm dovi_tool-${DOVI_TOOL_VERSION}-x86_64-unknown-linux-musl.tar.gz && \
    chmod +x /usr/local/bin/dovi_tool

# 18. Download and install hdr10plus_tool
ARG HDR10PLUS_TOOL_VERSION=1.7.2
RUN wget -q https://github.com/quietvoid/hdr10plus_tool/releases/download/${HDR10PLUS_TOOL_VERSION}/hdr10plus_tool-${HDR10PLUS_TOOL_VERSION}-x86_64-unknown-linux-musl.tar.gz && \
    tar -xzf hdr10plus_tool-${HDR10PLUS_TOOL_VERSION}-x86_64-unknown-linux-musl.tar.gz && \
    mv hdr10plus_tool /usr/local/bin/ && \
    rm hdr10plus_tool-${HDR10PLUS_TOOL_VERSION}-x86_64-unknown-linux-musl.tar.gz && \
    chmod +x /usr/local/bin/hdr10plus_tool

# 19. Download and install mkvmerge
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        mkvtoolnix && \
    rm -rf /var/lib/apt/lists/*

# 20. Install VapourSynth and plugins
RUN --mount=type=cache,target=/root/.cache/pip \
    python3.12 -m pip install vapoursynth vapoursynth-vszip vapoursynth-lsmas vapoursynth-ffms2 && \
    vapoursynth config && \
    python3.12 -c "import vapoursynth as vs; c = vs.core; print(c.vszip, c.lsmas, c.ffms2)"

# 21. Application setup
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