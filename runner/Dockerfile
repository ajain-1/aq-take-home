# Image for the Kubernetes Job pods: the terminal-bench harness plus a docker CLI
# that drives the host daemon (mounted socket) to run the task container.
FROM docker:28-cli AS docker-cli

FROM python:3.12-slim

COPY --from=docker-cli /usr/local/bin/docker /usr/local/bin/docker
COPY --from=docker-cli /usr/local/libexec/docker/cli-plugins/docker-compose /usr/local/libexec/docker/cli-plugins/docker-compose

WORKDIR /opt/aq

COPY terminal_bench/pyproject.toml ./pyproject.toml
RUN python -c "import tomllib; print('\n'.join(tomllib.load(open('pyproject.toml', 'rb'))['project']['dependencies']))" > requirements.txt \
    && pip install --no-cache-dir -r requirements.txt pyyaml python-dotenv

COPY terminal_bench ./terminal_bench
COPY runner/trial_entrypoint.py ./trial_entrypoint.py

ENV PYTHONPATH=/opt/aq \
    PYTHONUNBUFFERED=1

ENTRYPOINT ["python", "/opt/aq/trial_entrypoint.py"]
