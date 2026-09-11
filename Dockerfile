# syntax=docker/dockerfile:1

FROM python:3.12-slim

# impit ships manylinux/musllinux wheels (amd64+arm64), so no Rust toolchain is needed.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY src ./src

# No .git in the build context (see .dockerignore), so hatch-vcs can't read a
# version from it; supply the fallback it uses instead.
RUN SETUPTOOLS_SCM_PRETEND_VERSION=0.0.0.dev0 \
    uv pip install --system --no-cache .

RUN useradd --system --uid 1000 mcp
USER mcp

# 0.0.0.0 is only safe in a container: exposure is governed by `docker run -p`.
# To require auth, set FOURPDA_API_KEY at runtime.
EXPOSE 8000
ENTRYPOINT ["4pda-mcp"]
CMD ["--http", "--host", "0.0.0.0", "--port", "8000"]