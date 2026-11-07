# Security and privacy

Experimental software, not a security certification. Keep protection mode and the shipped least-privilege defaults. Do not expose the internal status listener publicly. The agent runs unprivileged but has container tool/code execution capabilities; WhatsApp access must be narrowly allowed and pairing material remains secret.

Never commit .env, auth.json, WhatsApp/Baileys keysets or creds.json, SSH/private keys, vault files, sessions, memories, databases, raw logs, recovery keys or backups. .gitignore is a convenience, not a secret scanner, and does not remove already-committed files or history. Start with this clean folder and a new repository, not a copy of an operational workspace's .git directory.

This package was assembled from an explicit source allowlist. Personal seed skills and operational migration scripts/audits were excluded. A targeted scan includes the content of the bundled source archive, not only the visible files. No private runtime credentials were loaded for publishing. No account, live service, network permission or active installation was changed.

Before reporting a vulnerability, contact the repository owner privately through GitHub where possible; never open a public issue containing tokens, QR codes, private backups or account identifiers. If credentials were exposed, revoke/rotate them; removing the latest file is not enough to erase Git history.

No complete dependency audit, penetration test, vulnerability scan or deployment regression suite was performed for this publication. Review changes before adopting them, and do not assume the author's working installation proves your environment safe.
