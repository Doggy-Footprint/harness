ARG UV_IMAGE
ARG BASE
FROM ${UV_IMAGE} AS uv
FROM ${BASE}
ARG PYTHON
ARG SDK
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_PYTHON_INSTALL_DIR=/opt/selfcheck-py/python
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates && rm -rf /var/lib/apt/lists/* \
 && uv python install ${PYTHON} \
 && uv venv --python ${PYTHON} /opt/selfcheck-py/venv \
 && uv pip install --python /opt/selfcheck-py/venv/bin/python ${SDK}
