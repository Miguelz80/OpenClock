# 0010. WhatsApp adapter on the Cloud API, sharing the chat core with Telegram

- **Status:** Accepted
- **Date:** 2026-11-19

## Context

WhatsApp was the maintainer's first idea for the main channel. ADR 0003 put it after a Telegram pilot because of Meta's AI-provider policy, the 24-hour window with paid templates, and costs. The Telegram bot (ADR 0009) now exists, and its logic (allowlist, commands, reports, assistant, usage log) does not depend on Telegram.

## Decision

- Move that logic into `openclock.channels.core.ChatCore`. Telegram (`Bot`) and WhatsApp (`WhatsAppBot`) are now thin transports that implement `send` (and `typing` where it exists).
- Use only the **official Cloud API**: an HTTPS webhook (Starlette, run with uvicorn; both already installed with the MCP SDK) and `POST /{phone_number_id}/messages`.
- **Security:** check every webhook POST against `X-Hub-Signature-256` with the App secret before reading it. Use a constant-time comparison for the verify token. Secrets live only in environment variables, and the access token travels in a header, never in a URL or log. uvicorn access logs are off, because the verification query contains the verify token.
- **Messaging rules:** replies to an inbound message are free-form. The only message the bot sends first, the weekly report, is a pre-approved **Utility template** with five short parameters (no line breaks). The full report follows when the user replies. This avoids having to track 24-hour windows across processes.
- **UX:** single words work as commands (`semana`, `metas`, `relatório`), because WhatsApp has no slash-command menu.
- **Policy fit:** the assistant's instructions now tell it to stay on the user's training and decline unrelated requests, so it serves OpenClock users rather than acting as a general-purpose assistant.

## Consequences

- WhatsApp is ready to try with a Meta test number. **A public launch is still gated** on the checklist in docs/whatsapp.md: AI policy, pricing, template approval, business verification and consent.
- Every weekly push costs one template message per user. Measure it in the pilot alongside the AI cost.
- A webhook needs public HTTPS hosting, which Telegram's polling did not.
