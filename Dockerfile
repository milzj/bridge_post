# The digest pins the multi-platform official release (native arm64 and amd64).
FROM firedrakeproject/firedrake-vanilla-default:2026.10.0@sha256:b3f8026897fe982b345227e36085b89430f98b389fdd1152a4d24619aa598744

LABEL org.opencontainers.image.title="Bridge topology optimization"
LABEL org.opencontainers.image.description="Firedrake 2026.10.0, Gmsh, MMA, and offscreen reports"

USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        gmsh=4.12.1+ds1-1.1build2 \
        fonts-dejavu-core \
        libegl1 \
        libgl1 \
        libglu1-mesa \
        libopengl0 \
        libxrender1 \
        libxext6 \
        libsm6 \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt constraints.txt /opt/bridge/
RUN python3 -m pip install --no-cache-dir \
        --constraint /opt/bridge/constraints.txt \
        --requirement /opt/bridge/requirements.txt \
    && python3 -m pip check \
    && gmsh -version

ENV MPLBACKEND=Agg \
    PYVISTA_OFF_SCREEN=true \
    VTK_DEFAULT_OPENGL_WINDOW=vtkEGLRenderWindow \
    LIBGL_ALWAYS_SOFTWARE=1

WORKDIR /workspace
CMD ["bash"]
