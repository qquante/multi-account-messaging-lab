# Multi Account Messaging Lab

A controlled Telegram account-orchestration experiment with per-account sessions, allowlists and audit state.

## Features

- Account scaffolding separates identity and session configuration.
- Allowlists restrict destinations for controlled experiments.
- Local rate limits and audit records track account actions.

## Stack

Python · asyncio · Telethon · SQLite · JSONL

SQLite/JSONL record operational state; each account uses separate local session storage. Local account and allowlist files are excluded.

## Getting started

Python >=3.11. Install the declared Telethon dependencies, inspect the CLI, and use only example configuration until a controlled experiment is explicitly configured.

## How it works

```text
Account slots and allowlist → isolated sessions → rate-limited controlled action → audit records
```

## Current limitations

This operates real accounts when configured. No login or messaging experiment was performed. It is not a bulk-DM or spam tool; use controlled destinations and explicit local account setup.

## License

No open-source license has been granted. Redistribution terms remain to be defined.
