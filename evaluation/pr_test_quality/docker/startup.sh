#!/bin/bash
set -eu
export DEBIAN_FRONTEND=noninteractive

meta() { curl -fsH 'Metadata-Flavor: Google' "http://metadata.google.internal/computeMetadata/v1/instance/attributes/$1"; }
PROJECT=$(meta eval-project)
SECRET=$(meta eval-secret)
RUN_USER=$(meta eval-user)
DISK=$(meta eval-disk)
DEV="/dev/disk/by-id/google-$DISK"

id "$RUN_USER" >/dev/null 2>&1 || useradd -m -s /bin/bash "$RUN_USER"

blkid "$DEV" >/dev/null 2>&1 || mkfs.ext4 -q -F "$DEV"
mkdir -p /data
mountpoint -q /data || mount -o discard,defaults "$DEV" /data
grep -q "$DEV" /etc/fstab || echo "$DEV /data ext4 discard,defaults,nofail 0 2" >> /etc/fstab
mkdir -p /data/evaluation /data/results /data/logs /data/src /data/secrets

if ! command -v docker >/dev/null 2>&1; then
  apt-get update -qq
  apt-get install -y -qq docker.io git curl ca-certificates
fi
usermod -aG docker "$RUN_USER"
# Project images for 160 repositories do not fit on the 50GB boot disk; keep docker on the data disk.
if ! grep -q '"data-root": "/data/docker"' /etc/docker/daemon.json 2>/dev/null; then
  mkdir -p /etc/docker /etc/systemd/system/docker.service.d
  printf '{"data-root": "/data/docker"}\n' > /etc/docker/daemon.json
  printf '[Unit]\nRequiresMountsFor=/data\n' > /etc/systemd/system/docker.service.d/data-disk.conf
  systemctl daemon-reload
  systemctl restart docker
fi
systemctl enable --now docker

if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin INSTALLER_NO_MODIFY_PATH=1 sh
fi
if [ ! -x /usr/local/bin/python3 ] || ! /usr/local/bin/python3 -c 'import sys; sys.exit(sys.version_info[:2] != (3, 12))'; then
  uv python install 3.12 --install-dir /opt/python
  ln -sf "$(ls /opt/python/*/bin/python3.12 | head -n 1)" /usr/local/bin/python3.12
  ln -sf /usr/local/bin/python3.12 /usr/local/bin/python3
fi

if ! command -v node >/dev/null 2>&1; then
  curl -fsSL https://deb.nodesource.com/setup_22.x | bash - >/dev/null 2>&1
  apt-get install -y -qq nodejs
fi
command -v claude >/dev/null 2>&1 || npm install -g @anthropic-ai/claude-code@2.1.309 >/dev/null 2>&1

install -d -m 700 -o "$RUN_USER" -g "$RUN_USER" /data/secrets
umask 077
if gcloud secrets versions access latest --secret="$SECRET" --project="$PROJECT" > /data/secrets/oauth_token 2>/dev/null; then
  chown "$RUN_USER:$RUN_USER" /data/secrets/oauth_token
  chmod 600 /data/secrets/oauth_token
else
  rm -f /data/secrets/oauth_token
fi
chown -R "$RUN_USER:$RUN_USER" /data/evaluation /data/results /data/logs /data/src
