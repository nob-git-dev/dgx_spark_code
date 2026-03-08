FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    jq \
    git \
    && rm -rf /var/lib/apt/lists/*

# Non-root user
RUN groupadd -g 1000 sandbox && useradd -u 1000 -g 1000 -m sandbox
USER sandbox
WORKDIR /workspace

CMD ["bash"]
