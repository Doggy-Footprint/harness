FROM {{TOOLS}} AS tools
FROM {{PROJECT}}
USER root
COPY --from=tools /opt/evaluation-py /opt/evaluation-py
COPY --from=tools /opt/evaluation-node /opt/evaluation-node
RUN mkdir -p /opt/evaluation/agent \
 && printf 'export LANG=C.UTF-8\nexport PATH=/opt/evaluation-node/bin:$PATH\n' > /opt/evaluation/env.sh
