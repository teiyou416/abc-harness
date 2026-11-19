# PDF parser image: MinerU on CPU, "basic" tier (ONNX small models, no VLM).
#
# The harness starts one container per PDF, with no network, so the models are
# downloaded here, at build time, and runs use only local files. The MinerU
# release is pinned; its dependencies are not, so the image ID (recorded in
# every task that parses a PDF) is what identifies the exact parser.
#
# Build with `uv run abc-harness image build`. Needs about 3.2 GB of disk.

# python:3.12-slim-bookworm, pinned by digest.
FROM python@sha256:935c3c5b12357a7e10caa9c1e6ca5692344d97cf229832ef584be2cec9fc03df

ARG MINERU_VERSION=4.2.3

RUN apt-get update \
 && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
 && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir "mineru==${MINERU_VERSION}"

ENV MINERU_HOME=/opt/mineru \
    MINERU_MODEL_SMALL_BACKEND=onnx \
    MINERU_MODEL_ONNX_DEVICE=cpu \
    HF_HUB_DISABLE_TELEMETRY=1

# The model snapshot's commit is written next to the MinerU version, so the
# image says which weights it holds.
RUN mineru-kit models download --tier basic --small-backend onnx --source huggingface \
 && mineru-kit models verify --tier basic --small-backend onnx \
 && models=$(ls /opt/mineru/models/MinerU-4_models_onnx/.cache/huggingface/trees | sed 's/\.json$//') \
 && echo "mineru ${MINERU_VERSION}; models MinerU-4_models_onnx@${models}" > /opt/mineru/REVISION

ENV MINERU_MODEL_SOURCE=local \
    HF_HUB_OFFLINE=1

LABEL org.abc-harness.tool="pdf-parser" \
      org.abc-harness.mineru-version="${MINERU_VERSION}"

WORKDIR /work
