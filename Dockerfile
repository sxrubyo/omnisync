FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    OMNI_HOME=/opt/omni-core \
    OMNI_CONFIG_DIR=/opt/omni-core/config \
    OMNI_STATE_DIR=/opt/omni-core/data \
    OMNI_BACKUP_DIR=/opt/omni-core/backups \
    OMNI_LOG_DIR=/opt/omni-core/logs

WORKDIR /opt/omni-core

RUN apt-get update && apt-get install -y --no-install-recommends \
    bash \
    ca-certificates \
    curl \
    git \
    openssh-client \
    procps \
    rsync \
    && rm -rf /var/lib/apt/lists/*

COPY . /opt/omni-core

RUN chmod +x /opt/omni-core/bin/omni /opt/omni-core/install.sh

ENTRYPOINT ["/opt/omni-core/bin/omni"]
CMD ["watch", "--interval", "600"]
