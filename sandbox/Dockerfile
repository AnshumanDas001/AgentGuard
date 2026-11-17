# Throwaway sandbox for the agent. Run with --network none (see agentguard/agent/sandbox.py).
FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl procps \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir pytest==8.3.3 \
    && useradd --create-home --shell /bin/bash agent

COPY --chown=agent:agent seed/home/ /home/agent/

USER agent
WORKDIR /home/agent/project
CMD ["sleep", "infinity"]
