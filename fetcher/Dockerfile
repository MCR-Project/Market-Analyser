# Playwright needs a real Chromium plus its system libraries (fonts,
# codecs, sandbox deps); the upstream playwright/python image ships both
# already matched to the pinned playwright version below, which is far less
# fragile than layering `playwright install --with-deps` onto python:slim
# ourselves and tracking apt packages by hand. fetcher/requirements.txt only
# floors playwright at >=1.45.0, so pip leaves this image's pre-installed
# version alone - bump this tag (and re-check the tags list at
# mcr.microsoft.com/v2/playwright/python/tags/list) if that floor ever rises
# past it.
FROM mcr.microsoft.com/playwright/python:v1.62.0-jammy

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Windows checkouts don't preserve the executable bit git tracks, so set it
# here rather than relying on the committed file mode.
RUN chmod +x entrypoint.sh

# docker-compose.yml mounts a host directory at /output so the JSON survives
# the container exiting; every provider script's own --output default writes
# next to the script instead, so entrypoint.sh redirects it there.
RUN mkdir -p /output
VOLUME /output

ENTRYPOINT ["./entrypoint.sh"]
