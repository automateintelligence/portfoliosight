# The build service and the nightly job (spec 9.1). Build context: the repository root.
#
#   docker build -f deploy/Dockerfile -t portfoliosight:<sha> .

FROM python:3.12-slim AS build
WORKDIR /src
COPY pyproject.toml README.md ./
COPY portfoliosight ./portfoliosight
COPY qse ./qse
# The dependencies of `.[api]` go to /install. The package itself runs from /app, next to the
# repository's data files it reads by relative path, so its installed copy is dropped here;
# `qse` stays in /install (it runs from site-packages, with its lock file as package data).
RUN pip install --no-cache-dir --prefix=/install ".[api]" \
    && rm -rf /install/lib/python3.12/site-packages/portfoliosight

FROM python:3.12-slim
RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --no-create-home --home-dir /app --shell /usr/sbin/nologin app
COPY --from=build /install /usr/local
WORKDIR /app
COPY portfoliosight ./portfoliosight
COPY data ./data
# COPY keeps the modes of the build host, and a checkout made under a restrictive umask is closed
# to others: the modes are set here, so the `app` user can read the code whatever the host's are.
RUN chmod -R u=rwX,go=rX /app/portfoliosight /app/data \
    && mkdir -p /app/cache && chown app:app /app/cache
ENV PYTHONPATH=/app \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PS_CACHE_DIR=/app/cache
# The pulled QSE files and `arch` import in the image that runs, with its runtime environment.
RUN python -c "import qse.distributions.joint, arch"
USER app
EXPOSE 8000
CMD ["uvicorn", "portfoliosight.api.app:app", "--host", "0.0.0.0", "--port", "8000", "--limit-concurrency", "32"]
