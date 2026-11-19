# Security and privacy

OpenClock handles health and location data, so please report problems privately.

## Reporting

Use GitHub's [private vulnerability reporting](https://github.com/Miguelz80/OpenClock/security/advisories/new) instead of a public issue. Examples of what to report:

- a way to read another person's workouts (for example, getting around the Telegram bot's allowlist);
- secrets such as a bot token or API key ending up in logs, errors or files;
- a crafted export file that makes an importer misbehave;
- personal data committed to the repository.

Include steps to reproduce with **synthetic data only**.

## Supported versions

OpenClock is a pre-release prototype. Fixes go to the `main` branch only.

## Design rules that protect your data

- Real exports, GPS routes and credentials never belong in the repository; `.gitignore` blocks the usual file names.
- Mode A keeps your files on your computer.
- The Telegram bot serves only the chats listed in its config, keeps conversations in memory, and logs token counts without message text ([docs/telegram.md](docs/telegram.md#privacy)).
- Apple Health exports are parsed with `defusedxml`, which blocks XML entity attacks.
