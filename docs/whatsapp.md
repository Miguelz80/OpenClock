# WhatsApp (Mode B)

`openclock-whatsapp` connects OpenClock to WhatsApp through the **official WhatsApp Business Platform (Cloud API)**. It uses the same chat logic as the [Telegram bot](telegram.md):

- **Commands as plain words** (`semana`, `comparar`, `metas`, `ajuda`, `novo`, `privacidade`, or the English equivalents) are answered from OpenClock's numbers, with no AI.
- **Free-form questions** are answered by Claude with the same MCP tools as Mode A.
- **Only numbers listed in the config are served**, each with its own data folder.

> **Before inviting anyone, go through the [launch checklist](#launch-checklist).** WhatsApp has rules and costs that Telegram doesn't. Never use unofficial WhatsApp libraries: they break WhatsApp's terms and the number can be banned.

## How WhatsApp differs from Telegram

| | Telegram | WhatsApp Cloud API |
|---|---|---|
| Receiving messages | Bot polls | Meta calls **your HTTPS webhook** |
| Replying to a user's message | Free-form | Free-form, within 24 h of their last message |
| Weekly report (bot speaks first) | Free-form, free | **Pre-approved template**, billed per message by Meta |
| AI assistants | Allowed | Allowed only as a service for your users; general-purpose AI assistants are barred (from 2026-01-15) |

So the weekly push is a short template, for example "Seu resumo semanal do OpenClock (16/11 a 22/11): 13,44 km em 2 treino(s)…". When the person replies, the 24-hour window opens and the full report and questions follow as normal messages.

## 1. Set up the Meta side

Follow Meta's *Cloud API — Get started* guide. You will end up with:

- a Meta developer app with the WhatsApp product, and a business phone number (Meta provides a test number);
- its **phone number ID** (non-secret, goes in the config);
- a **permanent access token** (a System User token), the app's **App secret**, and a **verify token**, which is any random string you choose.

## 2. Register the weekly template

Print the template text and example parameters:

```bash
openclock-whatsapp template --config samples/whatsapp.example.toml --as-of 2026-11-20T00:00-03:00
```

```text
Template name: openclock_weekly_report  ·  category: Utility

[pt_BR]
Seu resumo semanal do OpenClock ({{1}}): {{2}} em {{3}} treino(s), ritmo médio {{4}}. Em relação à semana anterior: {{5}}. Responda esta mensagem para ver o relatório completo ou fazer uma pergunta.

[en_US]
Your OpenClock weekly summary ({{1}}): {{2}} in {{3}} workout(s), average pace {{4}}. Compared with the previous week: {{5}}. Reply to this message for the full report or to ask a question.

Example parameters: ["16/11 a 22/11", "13,44 km", "2", "5:30/km", "+2,84 km (+26,8%)"]
```

In WhatsApp Manager, create a template with that name, category **Utility**, one body per language, and the example values. Wait for approval. Meta decides the final category; if it is classified as Marketing, the price per message changes.

## 3. Configure

```bash
python -m pip install -e ".[bot]"
export WHATSAPP_ACCESS_TOKEN="..."   # System User token
export WHATSAPP_APP_SECRET="..."     # Meta app > Settings > Basic
export WHATSAPP_VERIFY_TOKEN="..."   # the random string you chose
export ANTHROPIC_API_KEY="..."       # for free-form questions
```

Copy [`samples/whatsapp.example.toml`](../samples/whatsapp.example.toml) to `whatsapp.toml` (git-ignored). Set `phone_number_id` and `graph_version` (the Graph API version shown in your Meta app), and add one `[[user]]` per participant with their `wa_id`: country code and number, digits only. `OPENCLOCK_MODEL` and `OPENCLOCK_EFFORT` work as for [Telegram](telegram.md#3-configure-the-pilot).

## 4. Run the webhook

```bash
openclock-whatsapp serve --config whatsapp.toml --host 127.0.0.1 --port 8080
```

Meta needs a public **HTTPS** URL. Put the server behind a reverse proxy with TLS (or a tunnel while testing). Then, in the app's WhatsApp → Configuration:

- **Callback URL:** `https://your-domain/webhook`
- **Verify token:** the same `WHATSAPP_VERIFY_TOKEN`
- **Webhook fields:** subscribe to `messages`

The server answers Meta's verification request and checks every POST against `X-Hub-Signature-256` signed with your App secret. Unsigned or forged calls get `401` and are not read. It acknowledges each delivery at once, processes it in the background, and ignores repeated deliveries. `GET /health` returns `{"ok": true}` for monitoring.

## 5. Weekly report

```cron
0 8 * * 1  cd /srv/openclock && WHATSAPP_ACCESS_TOKEN=... openclock-whatsapp send-weekly --config whatsapp.toml
```

This sends last week's template to every user with `weekly_report = true`.

## Launch checklist

Confirm each item against Meta's current pages before inviting people. These are the open items from [ADR 0003](adr/0003-channel-strategy.md):

- [ ] **AI policy:** read the current WhatsApp Business Solution terms on AI providers and confirm that a training assistant for your own users is allowed. The assistant is instructed to stay on training topics and decline unrelated requests, but the policy decision is yours.
- [ ] **Pricing:** check the current per-message rate for Utility templates in your users' country, and whether replies inside the 24-hour window are billed (Meta announced changes for 2026).
- [ ] **Template approved**, in every language you use.
- [ ] **Business verification** and messaging limits for your number.
- [ ] **Consent:** each participant agreed to receive the weekly message and knows that questions go to the Claude API (`privacidade` explains it).

## Costs

- **Meta:** one Utility template per user per week, plus any rate Meta applies to service replies.
- **Claude:** per free-form question, as on Telegram. Track it with `openclock-whatsapp usage --price-input … --price-output …`. Commands and the weekly template use no AI.

## Privacy

Phone numbers are personal data. `whatsapp.toml` and the usage log are git-ignored, and logs use a hashed id. Meta processes the message content under its own terms, and free-form questions are also sent to the Claude API. Deleting a participant means removing their `[[user]]` entry and their data folder.

## Limitations

- Tested against a mock Graph API and the webhook in-process. **It has not been run against Meta's real API**; the first test number is that test.
- Text messages only; audio, images and locations get a short reply saying so.
- One process serves all participants. Conversations are in memory and cleared on restart.
