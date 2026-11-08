# Derived from nuttaruj/hermes-homeassistant ce4776d; headless replacement.
# No floating installer, third-party WebUI, npm install hook, production secret or state.
# Supervisor local builds override BUILD_FROM; keep the reviewed Debian base explicit.
FROM python:3.14.9-slim-bookworm@sha256:7dff173021016c8829ae58d5ce112ffc388073ebe67f351aeb6ba2909e35f847
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 LANG=C.UTF-8 LC_ALL=C.UTF-8 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 PATH=/opt/venv/bin:/opt/node/bin:/usr/local/bin:/usr/bin:/bin
COPY apt-sources.list /etc/apt/sources.list
RUN rm -f /etc/apt/sources.list.d/debian.sources \
    && apt-get -o Acquire::Check-Valid-Until=false update \
    && apt-get install -y --no-install-recommends ca-certificates bash curl jq git openssh-client xz-utils libatomic1 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /build
COPY build-lock.json requirements-linux.lock build_image.py privacy_build.py isolated.npmrc global.npmrc fetch_vendor.py ./
COPY vendor/ ./vendor/
RUN python fetch_vendor.py \
    && python build_image.py /build /opt/hermes \
    && mkdir -p /opt/node \
    && tar -xJf /build/vendor/node-linux-x64.tar.xz -C /opt/node --strip-components=1 \
    && python -m venv /opt/venv \
    && /opt/venv/bin/pip install --only-binary=:all: --require-hashes --no-deps -r /build/requirements-linux.lock \
    && PIP_NO_INDEX=1 /opt/venv/bin/pip install --no-build-isolation --no-deps -e /opt/hermes
ENV NPM_CONFIG_USERCONFIG=/build/isolated.npmrc NPM_CONFIG_GLOBALCONFIG=/build/global.npmrc
RUN cd /opt/hermes/scripts/whatsapp-bridge \
    && npm ci --omit=dev --ignore-scripts --no-audit --no-fund \
    && python -c "import sys; sys.path.insert(0,'/build'); from privacy_build import seal_bridge_dependencies; seal_bridge_dependencies('/opt/hermes')" \
    && node --check bridge.js \
    && node --input-type=module -e "import {makeWASocket} from '@whiskeysockets/baileys'; if(typeof makeWASocket !== 'function') process.exit(1)" \
    && /opt/venv/bin/python -c "from hermes_state_common import SCHEMA_VERSION; assert SCHEMA_VERSION == 32; import openai,cryptography,anthropic" \
    && rm -rf /root/.npm /root/.cache
WORKDIR /opt/poc
COPY poclib/ ./poclib/
COPY runtime/ ./runtime/
COPY seed/ ./seed/
COPY build-lock.json /opt/poc/build-lock.json
RUN mkdir -p /data /run/hermes \
    && chmod -R go-w /opt/hermes /opt/poc /opt/venv /opt/node
ENV PYTHONPATH=/opt/poc HERMES_HOME=/data/hermes-fixture HOME=/data/hermes-fixture \
    NPM_CONFIG_USERCONFIG=/dev/null NPM_CONFIG_GLOBALCONFIG=/etc/npmrc
EXPOSE 8787
VOLUME ["/data"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD ["/opt/venv/bin/python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8787/live',timeout=3).read()"]
LABEL io.hass.version="0.1.2" \
      io.hass.type="app" \
      io.hass.arch="amd64" \
      org.opencontainers.image.title="Hermes Lite PoC" \
      org.opencontainers.image.version="0.1.2" \
      org.opencontainers.image.revision="b200f5bc60e31588ba2cb60e288029c4a54ba5fa" \
      org.opencontainers.image.description="Headless Hermes0.22.7/schema32; fixture default; manual live cutover"
ENTRYPOINT ["/opt/venv/bin/python", "-m", "poclib.bootstrap"]
