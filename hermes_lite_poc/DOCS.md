# Configuration and operator notes

## Safe default

mode: fixture creates a separate synthetic home at /data/hermes-fixture. A green fixture process does not authenticate an account, connect WhatsApp, or prove real model delivery. Provider/model options are constrained by poclib/policy.py, not interchangeable selectors.

## Agent mode

Switching to agent uses /data/hermes and starts the local Hermes gateway without messaging. Account authentication must be performed independently by an authorized operator using the packaged Hermes CLI as UID/GID 10001 and HOME/HERMES_HOME=/data/hermes. The bootstrap only forwards a fixed safe environment; setting a cloud token in an unrelated SSH app will not authenticate this app. Do not copy another running installation's OAuth refresh-token chain. This package does not configure HAOS host SSH or change other apps.

Agent-only policy rejects messaging .env files and WhatsApp credential files. Do not attempt WhatsApp pairing while relying on agent mode as a live gateway. Standard Hermes model/authentication setup is separate from live activation, and may require an interactive authorization/callback workflow.

## Live mode: manual, advanced provisioning

This snapshot retains the existing fail-closed safety gates. It is not a complete generic live onboarding wizard. An operator must stage an independent authenticated home, valid WhatsApp settings and session material with UID/GID 10001 ownership, and ensure the runtime home provenance matches live mode. Existing agent-mode runtime metadata cannot simply be relabeled without a reviewed transition; archive prior state and use an explicitly prepared independent home. Do not delete persistent data to bypass a guard.

The live activation record must be the exact JSON below, as a regular root-owned file at /data/control/activation.json (0644); the root-owned control directory must not be group/world-writable. The unprivileged agent must not be able to grant itself activation.

    {"version":1,"operator_approved":true,"source_gateway_stopped":true,"oauth_policy":"reauthorized","whatsapp_policy":"exclusive-cutover"}

This is a declaration of checks already performed, NOT an instruction to fabricate their result. Before activation: prove any source gateway AND its separately running/orphaned bridge stopped; preserve a recoverable private backup; never run two copies for the same WhatsApp session. Use the bundled CLI's own help for the pinned authentication/pairing workflow. Never weaken the gate, use --force, expose credentials in configuration examples, or reuse private host migration scripts from another installation.

## Readiness and recovery

/live checks supervisor liveness. /ready and /status check mode-dependent process/transport readiness; health_scope explains its scope. delivery_proven remains false because health probes do not generate model turns or send messages. Perform a real inbound -> model -> outbound test before claiming live delivery. The worker can recover its own crashed/hung process group with bounded backoff; authentication/network/ownership errors are not repaired by deleting credentials. Watchdog and Start on boot are Supervisor settings to check explicitly.

## Backups

The manifest requests cold backups and excludes live activation and temporary state. Backups still contain confidential account/user data. Encrypt and store them privately; never commit them. A restore requires operator review and exclusive ownership before live activation. Keep this app separate from other Supervisor apps and the HAOS host.

## Technical limits

Only amd64, the pinned provider/model and database schema are supported by this build. No automatic updates at startup, no runtime installer, no exposed host network or Docker socket, and no homeassistant_api/hassio_api permissions by default. The source is immutable to the agent; persistent state is data. Python/npm/base image build dependencies require upstream availability. No new installation/build test was performed for this publication.
