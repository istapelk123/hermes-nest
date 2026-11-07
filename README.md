# Hermes Headless for Home Assistant OS (Experimental)

Community HAOS app/add-on for an unprivileged, persistent Hermes Agent with cloud inference and an optional WhatsApp bridge. Not an official Nous Research or Home Assistant integration.

## Status and limits

This is a cleaned publication snapshot of an existing working installation, not a newly tested release. No image rebuild, fresh-install test or regression suite was run for this publication. Only packaging, attribution and targeted privacy/secret checks were performed. The source installation was previously exercised with real WhatsApp inbound -> cloud model -> outbound communication.

- amd64 only (Intel/AMD HAOS); no ARM/Raspberry Pi support in this image.
- Hermes 0.22.7, database schema 32; provider openai-codex and model gpt-6.1-sol are deliberately pinned in policy. They are not arbitrary configurable providers in this snapshot. Account access to this model is required for agent/live mode; this package does not grant access or include a subscription. Other providers require a separate reviewed change.
- Fixture mode is the default: synthetic checks only, no account, WhatsApp or inference.
- Agent mode uses an independent cloud login without messaging credentials.
- Live mode requires manual operator provisioning, an exclusive WhatsApp cutover and a root-owned activation gate. There is no browser setup wizard, automatic Windows migration or one-click WhatsApp onboarding in this public package.
- Status-only HA Ingress; no general-purpose web chat or setup terminal. Browser/voice are disabled. Home Assistant API access is off by default.
- No private or bundled skill collection is included. The empty seed skill manifest is intentional.

## Install

1. Upload this folder's CONTENTS to your own GitHub repository, retaining the hermes_lite_poc subfolder. See UPLOADEN.txt.
2. Add your repository URL in Home Assistant Settings -> Apps/Add-ons -> Store -> menu -> Repositories.
3. Install Hermes Headless (Experimental). The image is built locally; this may take time and needs internet and sufficient disk space. Node is downloaded only during the build and checked against its pinned SHA-256. No image is downloaded from your own GitHub Container Registry.
4. Keep mode: fixture for the first start. Enable Start on boot and Watchdog in the app UI if you choose to use it persistently. Inspect the read-only Ingress status.
5. Read hermes_lite_poc/DOCS.md before agent/live use. Do not select live until all safety gates and credentials are intentionally prepared.

Adding this repository beside an existing local installation creates a DIFFERENT Supervisor app identity and data directory. It is not an in-place upgrade. Do not run both with the same WhatsApp account, remove the old app, or copy authentication blindly.

## Repository layout

repository.yaml identifies the repository. hermes_lite_poc/ is the build context. All runtime data is outside source in the Supervisor-owned /data volume. The pinned filtered Hermes source archive is included to preserve the already-reviewed source hash; the larger Node binary archive is not included. Do not upload data or backups beside the code.

## Security and licensing

See SECURITY.md and NOTICE.md. Tool access lets an authenticated agent execute code within its container; this is not a sandbox against a hostile operator. Keep the add-on's protection settings and least-privilege defaults. Transport readiness is not proof of model inference or WhatsApp message delivery. This experimental publication is not a penetration test or full dependency-license/security audit.
