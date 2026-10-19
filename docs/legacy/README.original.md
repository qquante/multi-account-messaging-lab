> Historical project notes. Paths, operational status, badges and test claims below are retained as archival reference and have not all been revalidated. Use the root README and docs/REVIEW.md for this review snapshot.

# Stolas Telegram Multi-Account Stack

Stack local para experimento controlado com contas reais Telegram via MTProto.

Base escolhida: **Telethon**. Motivo: API Python/asyncio madura, sessão por conta, eventos `NewMessage`, envio, reply, pin/read e acesso ao raw API para reações.

## Limite seguro do experimento

Use apenas em grupo/canal controlado e com allowlist. Este projeto não foi desenhado para bulk DM, scraping agressivo, spam, convite em massa ou bypass de limites. Cada conta tem rate limit local e todas as ações relevantes são registradas em SQLite/JSONL.

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .[all]
Copy-Item .env.example .env
```

Preencha `.env` com `TELEGRAM_API_ID` e `TELEGRAM_API_HASH` de `https://my.telegram.org/apps`.

Gerar 50 slots de conta:

```powershell
stolas-tg scaffold-accounts --count 50 --out config/accounts.local.json
Copy-Item config/allowlist.example.json config/allowlist.local.json
stolas-tg init
```

Edite:

- `config/accounts.local.json`: telefones, labels, `enabled: true` nas contas que vai usar.
- `config/allowlist.local.json`: grupo/canal controlado permitido.

## Login das contas

Uma conta:

```powershell
stolas-tg auth --account acc001
```

Todas as contas habilitadas, uma por vez:

```powershell
stolas-tg auth-all
```

## Importar Telegram Desktop TDATA

TDATA e material sensivel de sessao. Use apenas profile proprio/autorizado, local e controlado. O modo padrao `create-new` usa o TDATA ja logado para autorizar uma nova sessao Telethon do stack, em vez de reaproveitar diretamente a auth key do Desktop.

Dry-run:

```powershell
stolas-tg import-tdata --account acc001 --tdata-path "$env:APPDATA\Telegram Desktop\tdata" --dry-run
```

Importar para `var/sessions/acc001.session`:

```powershell
stolas-tg import-tdata --account acc001 --tdata-path "$env:APPDATA\Telegram Desktop\tdata"
```

Se ja existir sessao, criar backup e sobrescrever:

```powershell
stolas-tg import-tdata --account acc001 --tdata-path "$env:APPDATA\Telegram Desktop\tdata" --force
```

Se o Telegram Desktop tiver local passcode:

```powershell
stolas-tg import-tdata --account acc001 --tdata-path "$env:APPDATA\Telegram Desktop\tdata" --passcode "senha-local"
```

Exportar uma sessao do stack para TDATA novo:

```powershell
stolas-tg export-tdata --account acc001 --out-tdata-path "var/tdata/acc001"
```

Observacao: Telegram Desktop suporta poucas contas por profile TDATA. Para dezenas de contas, use um profile TDATA separado por conta ou importe cada conta para uma sessao Telethon separada do stack.

## Status/conexao

```powershell
stolas-tg status
```

## Recebimento de mensagens

```powershell
stolas-tg listen --accounts all
```

Responder automaticamente mensagens que mencionarem a conta, somente dentro da allowlist:

```powershell
stolas-tg listen --accounts all --auto-reply-mentions "Recebi a mencao. Conta={account_id}"
```

## Envio, reply, emoji/reaction, pin e read

Enviar texto normal ou com emoji:

```powershell
stolas-tg send --account acc001 --peer "@seu_grupo_teste" --text "Ola 👋 teste controlado"
```

Responder uma mensagem pelo `message_id`:

```powershell
stolas-tg send --account acc002 --peer "@seu_grupo_teste" --text "Respondendo esta msg" --reply-to 123
```

Adicionar reação:

```powershell
stolas-tg react --account acc003 --peer "@seu_grupo_teste" --message-id 123 --emoji "👍"
```

Fixar mensagem:

```powershell
stolas-tg pin --account acc001 --peer "@seu_grupo_teste" --message-id 123 --no-notify
```

Marcar como lida:

```powershell
stolas-tg read --account acc001 --peer "@seu_grupo_teste" --message-id 123
```

## Experimento controlado entre agentes

Rodar uma rodada simples com as contas habilitadas, uma mensagem por vez:

```powershell
stolas-tg arena --peer "@seu_grupo_teste" --rounds 1 --min-delay 20 --max-delay 45
```

Modo dry-run:

```powershell
stolas-tg arena --peer "@seu_grupo_teste" --rounds 1 --dry-run
```

## Arquivos de estado

- `var/sessions/`: sessoes Telethon, uma por conta.
- `var/stolas_tg.sqlite3`: eventos, envios, status e rate limit.
- `var/events.jsonl`: log append-only para auditoria.
