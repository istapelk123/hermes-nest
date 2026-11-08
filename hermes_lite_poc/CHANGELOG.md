# Changelog

## 0.1.2

- Fix: boot no longer fails the link gate after a reboot; the runtime sets HERMES_DISABLE_LAZY_INSTALLS=1 because the pinned image already packages its dependencies.
- Fix: Home Assistant Core (172.30.32.1 on the hassio bridge) may read GET /status only, so HA status sensors work; all other endpoints stay restricted.
- Anthropic provider support baked into the image (anthropic 0.125.0, docstring-parser 0.18.0, hash-pinned), needed now that lazy installs are disabled.

## 0.1.1 - Experimental public snapshot

- Pinned Hermes 0.22.7/schema 32 amd64 headless runtime.
- Fixture/agent/live separation, explicit activation gate, private logging patches.
- Clean publication packaging: no user skills, credentials, migration state or Git history.
- Node distribution fetched and hash-verified at image build instead of shipping a large binary in Git.
- Publication changes have not been rebuilt or deployment-tested.
