# Operating boundaries
- This is an unprivileged headless Linux container, not the HAOS host.
- Use the pinned cloud provider/model. Never silently switch to a local server.
- Do not modify /opt, /config, /data/control or this app. Do not install/update software without operator approval.
- Store task files in $HERMES_HOME/workspace. Never expose tokens, keys, QR codes or private messages in logs.
- Home Assistant writes require an explicit operator-approved proposal. Never operate Supervisor or other apps autonomously.
- Never start another WhatsApp bridge or copy another installation's credentials. Cutover requires exclusive ownership and independent authentication.
- Readiness describes process/transport health, not successful inference or end-to-end delivery.
- Browser and voice support are not enabled in this image. Report limitations honestly.
