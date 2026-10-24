ARG TOOLS
ARG BASE
FROM ${TOOLS} AS tools
FROM ${BASE}
USER root
COPY --from=tools /opt/selfcheck-py /opt/selfcheck-py
COPY python3 /opt/selfcheck/bin/python3
COPY env.sh /opt/selfcheck/env.sh
COPY testbed_tools.txt /opt/selfcheck/testbed_tools.txt
RUN chmod 755 /opt/selfcheck/bin/python3 \
 && apt-get update && apt-get install -y --no-install-recommends locales \
 && rm -rf /var/lib/apt/lists/* \
 && sed -i '/en_US.UTF-8/s/^# //' /etc/locale.gen && locale-gen en_US.UTF-8
# Constraints skip editable and URL lines because pip rejects them in a constraints file; the
# project itself is already installed and is not touched by installing the tools.
RUN set -e; PY=/opt/miniconda3/envs/testbed/bin/python; \
    $PY -m pip list --format=freeze > /opt/selfcheck/freeze-before.txt; \
    grep -vE '^(-e |#)| @ ' /opt/selfcheck/freeze-before.txt > /opt/selfcheck/constraints.txt; \
    $PY -m pip install --no-cache-dir -c /opt/selfcheck/constraints.txt -r /opt/selfcheck/testbed_tools.txt; \
    $PY -m pip list --format=freeze > /opt/selfcheck/freeze-after.txt; \
    rm /opt/selfcheck/constraints.txt /opt/selfcheck/testbed_tools.txt
RUN chown -R nonroot:nonroot /testbed \
 && git config --system --add safe.directory /testbed
