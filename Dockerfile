# syntax=docker/dockerfile:1
#
# Build:  docker build -t logbook .
# Run:    docker run --rm -v ~/Logbook:/data logbook show today
#
# Stage 1 builds the wheel and its environment with uv; stage 2 is the same slim base with only
# that environment copied in. (Distroless python3 ships Debian's interpreter, not 3.12, so the venv
# built here would not run there; python:3.12-slim is the smallest base that matches the builder.)

FROM python:3.12-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.12.14 /uv /bin/uv
ENV UV_PROJECT_ENVIRONMENT=/opt/logbook \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never
WORKDIR /src
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY logbook/ logbook/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable

FROM python:3.12-slim
COPY --from=builder /opt/logbook /opt/logbook
ENV PATH=/opt/logbook/bin:$PATH \
    LOGBOOK_HOME=/data
VOLUME /data
WORKDIR /data
ENTRYPOINT ["logbook"]
CMD ["--help"]
