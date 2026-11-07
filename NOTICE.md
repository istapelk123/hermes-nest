# Attribution and license scope

The repository integration/runtime code is offered under the MIT license in LICENSE. This does not relicense third-party components.

- Hermes Agent: Nous Research, MIT. Pinned source commit b200f5bc60e31588ba2cb60e288029c4a54ba5fa, packaged as version 0.22.7/schema 32. The filtered source archive retains its original LICENSE; a verbatim copy is in LICENSES/hermes-agent-MIT.txt. Upstream: https://github.com/NousResearch/hermes-agent
- The repository layout originally drew on nuttaruj/hermes-homeassistant at ce4776d9704dc24af718678ed0df9e645b92c152. Its README at that revision declares MIT; no separate LICENSE was present in the reviewed reference snapshot. The original WebUI, nginx and shell entrypoint are not distributed here. Upstream: https://github.com/nuttaruj/hermes-homeassistant
- Node.js is fetched from nodejs.org at build time at the version/SHA-256 in build-lock.json. Its distribution contains its own LICENSE and third-party notices, retained under /opt/node in the image.
- Python, Debian, Python dependencies and npm dependencies retain their respective licenses. Their distributions are fetched at build time, not included as installed dependencies in this repository. Lockfiles are not a comprehensive license audit or SBOM.
- privacy_build.py applies fail-closed build-time privacy patches to the pinned Hermes source; build_image.py sets the packaged version. See those files for the exact changes.

No official endorsement by Nous Research, Home Assistant, OpenAI or WhatsApp/Meta is implied. Personal skills, accounts, credentials, logs, migration state and user data are not distributed.
