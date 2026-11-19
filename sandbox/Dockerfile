# Throwaway sandbox for the agent. Run with --network none (see agentguard/agent/sandbox.py).
FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl procps \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir pytest==8.3.3 \
    && useradd --create-home --shell /bin/bash agent \
    && mkdir -p /var/log/agentguard && touch /var/log/agentguard/net.log \
    && chmod 666 /var/log/agentguard/net.log

# Level 3 checks: curl, wget and pip calls are logged (see bin/netlog), then run as usual.
COPY bin/netlog /usr/local/sbin/netlog
RUN chmod 755 /usr/local/sbin/netlog \
    && for n in curl wget pip pip3; do ln -s netlog /usr/local/sbin/$n; done
ENV PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

COPY --chown=agent:agent seed/home/ /home/agent/

USER agent
WORKDIR /home/agent/project
CMD ["sleep", "infinity"]
