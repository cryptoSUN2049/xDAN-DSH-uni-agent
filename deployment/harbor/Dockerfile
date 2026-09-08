# External build context: see README.md. Build with --platform linux/amd64.
FROM python@sha256:2fe5997d249a808b8eeea52c58a1dbffbba28754dc11699ef5c029f2d818ce79

ENV PYTHONPATH=/opt/uni-agent \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DSH_RUNTIME_MODE=exe

COPY wheelhouse/ /opt/wheelhouse/
RUN cd /opt/wheelhouse \
    && sha256sum --strict -c SHA256SUMS \
    && python -m pip install --no-cache-dir --no-index --only-binary=:all: \
        --find-links=/opt/wheelhouse \
        deepseek-harness-sdk==0.1.3a2 \
        deepseek-harness-runtime-bin==0.1.3a2 \
        pydantic==2.12.5 \
    && python -m pip check

# Preserve parent-package imports without installing the training framework.
COPY uni_agent/__init__.py /opt/uni-agent/uni_agent/__init__.py
COPY uni_agent/version/version /opt/uni-agent/uni_agent/version/version
COPY uni_agent/agents/__init__.py /opt/uni-agent/uni_agent/agents/__init__.py
COPY uni_agent/agents/base.py /opt/uni-agent/uni_agent/agents/base.py
COPY uni_agent/agents/registry.py /opt/uni-agent/uni_agent/agents/registry.py
COPY uni_agent/agents/dsh/__init__.py /opt/uni-agent/uni_agent/agents/dsh/__init__.py
COPY uni_agent/agents/dsh/agent.py /opt/uni-agent/uni_agent/agents/dsh/agent.py
COPY uni_agent/agents/dsh/runner.py /opt/uni-agent/uni_agent/agents/dsh/runner.py
COPY checks/keyless_sdk_smoke.py /opt/checks/keyless_sdk_smoke.py

WORKDIR /app
CMD ["sh", "-c", "sleep infinity"]
