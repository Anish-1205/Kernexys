# syntax=docker/dockerfile:1.7
ARG PYTHON_IMAGE=python:3.13.7-slim-bookworm

FROM ${PYTHON_IMAGE} AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    VIRTUAL_ENV=/opt/venv
ENV PATH="${VIRTUAL_ENV}/bin:${PATH}"

WORKDIR /build
RUN python -m venv "${VIRTUAL_ENV}"

COPY requirements requirements
RUN pip install --requirement requirements/build.txt --requirement requirements/runtime.txt

COPY pyproject.toml README.md ./
COPY app app
RUN pip install --no-build-isolation --no-deps . && pip uninstall --yes pip setuptools


FROM ${PYTHON_IMAGE} AS runtime

ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN groupadd --gid 10001 kernexys \
    && useradd --uid 10001 --gid kernexys --no-create-home --home-dir /nonexistent kernexys

WORKDIR /srv/kernexys
COPY --from=builder /opt/venv /opt/venv
COPY --chown=10001:10001 alembic.ini ./
COPY --chown=10001:10001 migrations migrations

USER 10001:10001
EXPOSE 8000
STOPSIGNAL SIGTERM

HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=2).read()"]

CMD ["kernexys-api"]
