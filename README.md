# Multi Account Messaging Lab

![Language: Python](https://img.shields.io/badge/Language-Python-3776AB?style=flat-square&logo=python) ![Sessions: Telethon](https://img.shields.io/badge/Sessions-Telethon-555555?style=flat-square) [![License: MIT](https://img.shields.io/badge/License-MIT-555555?style=flat-square)](LICENSE)

A local Telegram account laboratory with separate session slots, destination allowlists and SQLite/JSONL audit state.

The CLI supports account setup, authentication, listening and explicitly selected messaging actions. It also includes Telegram Desktop `tdata` import/export adapters. These are account-management capabilities, not a reason to share session material with the repository.

## Configure before connecting

```console
python -m venv .venv
python -m pip install -e .
stolas-tg --help
```

The package retains the internal `stolas-tg` command name. Start by reading the [allowlist example](config/allowlist.example.json), [.env.example](.env.example) and [configuration loader](src/stolas_tg/config.py). `scaffold-accounts` generates slots; `config-check` validates selected configuration. Neither an account slot nor a configuration file means the account is authenticated.

## Responsibilities inside the lab

| Module | Responsibility |
| --- | --- |
| [telegram_stack.py](src/stolas_tg/telegram_stack.py) | Telethon sessions and account actions. |
| [rate_limit.py](src/stolas_tg/rate_limit.py) | Per-account/per-peer asynchronous locks and minimum-interval waiting. |
| [storage.py](src/stolas_tg/storage.py) | Local state and audit persistence. |
| [tdata.py](src/stolas_tg/tdata.py) | Desktop/session conversion boundary. |

Authentication, sending, reactions, pinning and read-state changes can affect real accounts. Dry-run flags are command-specific; inspect the chosen command's help. Keep experiments scoped to accounts and destinations you control. No credentials, authenticated sessions or live account-state dataset are included.

This snapshot has no dedicated behavioral test suite. Local rate control is not a guarantee against Telegram restrictions, and storing interval state does not by itself establish correct timing across every process restart.

**Technology:** Python · asyncio · Telethon · SQLite · JSONL

Project-authored source: [MIT](LICENSE). Third-party components retain their own notices and terms.
