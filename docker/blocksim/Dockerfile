# Execution image for BlockSim (maher243/BlockSim).
#
# BlockSim writes its results to an Excel file through pandas.ExcelWriter.save(),
# which pandas 2 removed, so pandas stays on 1.5.3. xlsx_to_csv.py turns that
# Excel file into one CSV per sheet so metrics can be recalculated with the
# Python standard library alone.
#
# Build with `uv run abc-harness image build --simulator blocksim`.

# python:3.11-slim, pinned by digest.
FROM python@sha256:07d4824036af339fa1b6ef769cc99d9c10a141769538b52b3b597c84f7a7b535

RUN pip install --no-cache-dir pandas==1.5.3 numpy==1.26.4 xlsxwriter==3.2.0 openpyxl==3.1.5

ARG BLOCKSIM_COMMIT=603361dab49101cdd820dbfd86e19536d841cbae

ADD --checksum=sha256:4ba3fc113f048078493b662b6f9bdda46ada6bed451d663bbceba84045ab2d65 \
    https://github.com/maher243/BlockSim/archive/${BLOCKSIM_COMMIT}.tar.gz /tmp/blocksim.tar.gz

RUN mkdir -p /opt/blocksim/src \
 && tar -xzf /tmp/blocksim.tar.gz -C /opt/blocksim/src --strip-components=1 \
 && rm /tmp/blocksim.tar.gz \
 && find /opt/blocksim/src -name '*.pyc' -delete \
 && echo "${BLOCKSIM_COMMIT}" > /opt/blocksim/REVISION

COPY xlsx_to_csv.py /opt/abc/xlsx_to_csv.py

LABEL org.abc-harness.simulator="blocksim" \
      org.abc-harness.blocksim-commit="${BLOCKSIM_COMMIT}"

WORKDIR /work
