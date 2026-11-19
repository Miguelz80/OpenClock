# 0003. MCP first, Telegram pilot, WhatsApp later

- **Status:** Accepted
- **Date:** 2026-11-18

## Context

WhatsApp was the initial idea for the main interface: receive a summary and ask questions in the same chat. Research on 2026-11-18 found:

- **Official API only.** Unofficial WhatsApp libraries break WhatsApp's terms and risk the number being banned. The supported route is the WhatsApp Business Platform (Cloud API).
- **AI provider policy.** Since 2026-01-15, Meta's Business API terms bar general-purpose AI assistants whose primary function is the AI itself. Bots that support a specific service, notifications and updates remain allowed. A training-focused assistant likely fits the allowed case, but this must be confirmed against Meta's current text before building on it.
- **24-hour window.** Free-form replies are only possible within 24 hours of the user's last message. A scheduled weekly report sent by the business needs a pre-approved template, billed per message. Third-party sources quote about US$0.0068 per utility message in Brazil and mention billing changes from October 2026. Rates must be checked on Meta's official pricing page.
- **AI cost.** In any bot, the operator pays for each AI response.

## Decision

1. **Mode A first:** ship OpenClock as an MCP server that users connect to the AI app they already use. This has zero messaging and AI cost for the project and validates the core.
2. **Telegram for the messaging pilot:** the Bot API is free, has no template approval and no restriction on AI. It is used to test whether people come back for another summary.
3. **WhatsApp after validation:** implement it through the official Cloud API once the AI policy fit, template approval and per-message cost are confirmed.

The channel layer talks to the core only through the same functions the MCP tools use, so adding WhatsApp does not change importers or metrics.

## Consequences

- WhatsApp, the channel most familiar to Brazilian users, arrives later. The pilot may under-represent people who would only use WhatsApp.
- Two messaging adapters may have to be maintained. Keeping them thin limits that cost.
- Sources (secondary, to be confirmed against primary documents):
  [TechCrunch](https://techcrunch.com/2025/10/18/whatssapp-changes-its-terms-to-bar-general-purpose-chatbots-from-its-platform/),
  [respond.io](https://respond.io/blog/whatsapp-chatbot-policy-2026),
  [Meta pricing](https://developers.facebook.com/docs/whatsapp/pricing).
