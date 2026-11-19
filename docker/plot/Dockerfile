# Plot image: runs the agent's figure scripts (the make_figure tool).
#
# One container per script, with no network, the task's results read-only at
# /data, and only /out writable. `abcplot` (copied below) loads the results and
# applies the house style, so a script never needs to type a number.
#
# Build with `uv run abc-harness image build`.

# python:3.12-slim-bookworm, pinned by digest.
FROM python@sha256:935c3c5b12357a7e10caa9c1e6ca5692344d97cf229832ef584be2cec9fc03df

RUN pip install --no-cache-dir "matplotlib==3.11.2" "numpy==2.5.4" \
 && python -c "import matplotlib; print('matplotlib', matplotlib.__version__)" > /opt/REVISION \
 && python -c "import numpy; print('numpy', numpy.__version__)" >> /opt/REVISION

COPY abcplot.py /opt/abcplot/abcplot.py

# Agg renders without a display; the font cache is built here so runs need no writable home.
ENV PYTHONPATH=/opt/abcplot \
    MPLBACKEND=Agg \
    MPLCONFIGDIR=/opt/mplconfig
RUN mkdir -p /opt/mplconfig && python -c "import matplotlib.pyplot as plt; plt.figure()" \
 && chmod -R a+rX /opt/mplconfig

LABEL org.abc-harness.tool="plot"

WORKDIR /out
