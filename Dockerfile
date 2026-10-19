# Official Firedrake installation; only application dependencies are added.
FROM firedrakeproject/firedrake-vanilla-default:2026.10.0@sha256:b3f8026897fe982b345227e36085b89430f98b389fdd1152a4d24619aa598744

USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends gmsh=4.12.1+ds1-1.1build2 libegl1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt constraints.txt /opt/bridge/
RUN python3 -m pip install --no-cache-dir -c /opt/bridge/constraints.txt -r /opt/bridge/requirements.txt

# Keep the original unmodified optimizer and its complete source/license/notices.
RUN git clone --quiet https://github.com/LLNL/pyMMAopt.git /opt/pyMMAopt \
    && git -C /opt/pyMMAopt checkout --quiet --detach 934c0f304354fcb9430e2c326dedf557e3705eab \
    && python3 -m pip install --no-cache-dir --no-deps --no-build-isolation /opt/pyMMAopt \
    && python3 -m pip check

ENV MPLBACKEND=Agg \
    PYVISTA_OFF_SCREEN=true \
    VTK_DEFAULT_OPENGL_WINDOW=vtkEGLRenderWindow \
    LIBGL_ALWAYS_SOFTWARE=1

WORKDIR /workspace
CMD ["bash"]
