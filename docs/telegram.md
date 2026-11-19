# Telegram bot (Mode B)

`openclock-telegram` runs a Telegram bot for the messaging pilot. People get a weekly report and can ask questions about their training in the same chat.

- **Commands** (`/semana`, `/comparar`, `/metas`, or `/week`, `/compare`, `/goals`) are answered straight from OpenClock's numbers. They **do not call an AI model** and cost nothing.
- **Free-form questions** ("quanto corri nesta semana?") go to the Claude API, with the same MCP tools that Mode A exposes. The operator pays for these. See [Costs](#costs).
- **Only chats listed in the pilot config are served**, and each chat reads only its own data folder.

If you would rather use OpenClock in your own AI app, you don't need this bot: see [Mode A in docs/mcp.md](mcp.md#mode-a-install-in-your-own-ai-app).

## 1. Install

```bash
python -m pip install -e ".[bot]"
```

## 2. Create the bot

1. In Telegram, talk to [@BotFather](https://t.me/BotFather), send `/newbot` and follow the steps. It gives you a **bot token**.
2. Optional: send `/setcommands` to BotFather with:

   ```text
   semana - resumo da semana
   comparar - comparação com a semana anterior
   metas - progresso das metas
   novo - começar uma conversa nova
   privacidade - quais dados são usados
   ```

## 3. Configure the pilot

Secrets go in environment variables, never in files:

```bash
export TELEGRAM_BOT_TOKEN="123456:ABC..."     # from BotFather
export ANTHROPIC_API_KEY="sk-ant-..."         # for free-form questions
```

Copy [`samples/telegram.example.toml`](../samples/telegram.example.toml) to `telegram.toml`. That file is git-ignored. Add one `[[user]]` per pilot participant:

```toml
[[user]]
name = "ana"                    # label for you only
chat_id = 123456789             # see below
data_dir = "/srv/openclock/ana" # this person's .fit / export.xml files and goals.toml
timezone = "America/Sao_Paulo"
language = "pt"                 # pt | en
weekly_report = true
```

To find a `chat_id`, start the bot and have the person send it any message. A chat that is not in the config gets a reply with its id and no data.

Optional settings for free-form questions:

| Variable | Default | Meaning |
|---|---|---|
| `OPENCLOCK_MODEL` | `claude-opus-5-5` | Claude model. Cheaper models such as `claude-sonnet-5-5` or `claude-haiku-5-5` cost less per answer; compare quality on your own questions before switching. |
| `OPENCLOCK_EFFORT` | `medium` | `low`, `medium`, `high`, … Lower effort is cheaper and faster. |

## 4. Run

```bash
openclock-telegram run --config telegram.toml
```

The bot uses long polling, so it needs no public URL or webhook. It re-reads each data folder on every request, so new exports dropped into a folder are picked up without a restart.

Check a report locally, without Telegram or any key:

```bash
openclock-telegram preview --config samples/telegram.example.toml --as-of 2026-11-20T00:00-03:00
```

```text
Semana 16/11 a 22/11 (America/Sao_Paulo)
Garmin: 1 treino(s) · 8,42 km · 0:45:10 · 5:22/km
Apple Health: 1 treino(s) · 5,02 km · 0:28:45 · 5:44/km
Total: 2 treino(s) · 13,44 km · 1:13:55 · 5:30/km

Vs. semana anterior: +2,84 km (+26,8%) · ritmo 8 s/km mais rápido

Metas:
- Run 20 km per week: NO RITMO (13,44 km / 20,00 km); faltam 6,56 km em 3 dia(s)
- Run 3 times per week: NO RITMO (2 / 3); faltam 1 treino(s) em 3 dia(s)
- Average 5:35 /km or faster: CUMPRIDA (5:30/km / 5:35/km)
- One 10 km run per month: EM ANDAMENTO (8,42 km / 10,00 km)
```

## 5. Weekly report

`send-weekly` sends last week's report to every user with `weekly_report = true`. Schedule it with cron, for example on Mondays at 08:00:

```cron
0 8 * * 1  cd /srv/openclock && TELEGRAM_BOT_TOKEN=... openclock-telegram send-weekly --config telegram.toml
```

Telegram has no message templates or 24-hour window, so a scheduled report costs nothing. (On WhatsApp the same report would need an approved template, billed per message. See [ADR 0003](adr/0003-channel-strategy.md).)

## Costs

Only free-form questions call the Claude API. Each answer is usually 2 or more model calls: one that asks for a tool, then one that writes the reply. The bot appends **token counts only** (no message text, and a pseudonymous chat label) to `openclock-usage.jsonl`. Summarize them with the current prices from Anthropic's pricing page, in USD per million tokens:

```bash
openclock-telegram usage --usage-log openclock-usage.jsonl --price-input 4 --price-output 20
```

The bot keeps costs down in these ways:

- Reports are answered without AI.
- Prompt caching is on, so the tools, instructions and earlier turns are billed at cache-read rates on later calls.
- Conversations restart after 20 questions instead of growing without limit.

Measure the real cost per active user during the pilot before deciding how to fund a free public version.

## Privacy

- `/privacidade` tells participants what is used: their workout files, plus, for free-form questions, the numbers sent to the Claude API.
- Conversations live only in memory. `/novo` clears them, and so does a restart.
- The usage log holds token counts and a hashed chat id, never text.
- `telegram.toml` and the usage log are git-ignored. Keep participants' data folders outside the repository.
- Deleting a participant's data means deleting their data folder and removing their `[[user]]` entry.

## Limitations

- Tested with a mock Telegram server and a scripted Claude client. **It has not yet been run against the real Telegram and Claude APIs**; the first pilot run is that test.
- Goals are edited by the operator in each `goals.toml`, not from the chat.
- One process serves all pilot users. This suits a small pilot, not a public launch.
