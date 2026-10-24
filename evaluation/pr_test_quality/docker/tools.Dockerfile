ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.6.5
FROM ${UV_IMAGE} AS uv
FROM node:22-bookworm AS tools
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_PYTHON_INSTALL_DIR=/opt/evaluation-py/python
RUN uv python install 3.12 \
 && uv venv --python 3.12 /opt/evaluation-py/venv \
 && uv pip install --python /opt/evaluation-py/venv/bin/python claude-agent-sdk==0.2.165
RUN npm install -g --prefix /opt/evaluation-node @anthropic-ai/claude-code@2.1.309 \
 && cp /usr/local/bin/node /opt/evaluation-node/bin/node
