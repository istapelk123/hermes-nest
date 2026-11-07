# Changelog

## 0.1.1 - Experimental public snapshot

- Pinned Hermes 0.22.7/schema 32 amd64 headless runtime.
- Fixture/agent/live separation, explicit activation gate, private logging patches.
- Clean publication packaging: no user skills, credentials, migration state or Git history.
- Node distribution fetched and hash-verified at image build instead of shipping a large binary in Git.
- Publication changes have not been rebuilt or deployment-tested.
