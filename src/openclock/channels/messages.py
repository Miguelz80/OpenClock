"""Plain-text reports for chat channels, built from ``openclock.service`` results.

These reports are deterministic and do not call an AI model, so weekly summaries cost nothing
to produce. Only free-form questions go through ``openclock.assistant``.
"""

from __future__ import annotations

from datetime import date
from typing import Any

LANGUAGES = ("pt", "en")

TEXT: dict[str, dict[str, str]] = {
    "pt": {
        "week": "Semana {first} a {last}",
        "workouts": "{n} treino(s)",
        "total": "Total",
        "withheld": "Total combinado retido: possível treino duplicado entre dispositivos.",
        "vs_previous": "Vs. semana anterior: {distance} · ritmo {pace}",
        "faster": "{s} s/km mais rápido",
        "slower": "{s} s/km mais lento",
        "same": "igual",
        "unavailable": "indisponível",
        "goals": "Metas",
        "no_goals": "Nenhuma meta definida.",
        "remaining": "faltam {remaining} em {days} dia(s)",
        "notes": "Observações",
        "help": (
            "OpenClock: seus treinos do Garmin e do Apple Watch.\n"
            "/semana - resumo da semana\n"
            "/comparar - comparação com a semana anterior\n"
            "/metas - progresso das metas\n"
            "/novo - começar uma conversa nova\n"
            "/privacidade - quais dados são usados\n"
            'Ou pergunte em texto livre, por exemplo: "quanto corri esta semana?"'
        ),
        "privacy": (
            "Privacidade: este bot lê só os arquivos de treino que o operador configurou para "
            "você. Perguntas em texto livre são enviadas, com os números dos seus treinos, à "
            "API do Claude (Anthropic) para gerar a resposta. A conversa fica só na memória do "
            "bot e é apagada com /novo ou quando o bot reinicia. Para apagar seus arquivos, "
            "peça ao operador. Dúvidas sobre dor ou lesão: procure um profissional de saúde."
        ),
        "not_allowed": (
            "Este bot é um piloto privado do OpenClock. Peça ao operador para incluir este "
            "chat (id {chat_id}) na configuração."
        ),
        "new_conversation": "Conversa reiniciada.",
        "conversation_reset": "(A conversa anterior ficou longa e foi reiniciada.)",
        "error": "Não consegui responder agora. Tente de novo em instantes.",
        "status": {
            "met": "CUMPRIDA",
            "on_track": "NO RITMO",
            "behind": "ATRASADA",
            "in_progress": "EM ANDAMENTO",
            "not_met": "NÃO CUMPRIDA",
            "not_started": "NÃO INICIADA",
            "no_data": "SEM DADOS",
            "unavailable": "INDISPONÍVEL",
        },
        "decimal": ",",
        "units": {"km": "km", "min": "min", "workouts": "treino(s)", "s/km": "s/km"},
    },
    "en": {
        "week": "Week {first} to {last}",
        "workouts": "{n} workout(s)",
        "total": "Total",
        "withheld": "Combined total withheld: possible duplicate workout across devices.",
        "vs_previous": "Vs. previous week: {distance} · pace {pace}",
        "faster": "{s} s/km faster",
        "slower": "{s} s/km slower",
        "same": "same",
        "unavailable": "unavailable",
        "goals": "Goals",
        "no_goals": "No goals defined.",
        "remaining": "{remaining} to go in {days} day(s)",
        "notes": "Notes",
        "help": (
            "OpenClock: your Garmin and Apple Watch workouts.\n"
            "/week - this week's summary\n"
            "/compare - comparison with last week\n"
            "/goals - goal progress\n"
            "/new - start a new conversation\n"
            "/privacy - what data is used\n"
            'Or ask in plain text, for example: "how far did I run this week?"'
        ),
        "privacy": (
            "Privacy: this bot only reads the workout files the operator set up for you. "
            "Free-form questions are sent, together with your workout numbers, to the Claude API "
            "(Anthropic) to write the answer. The conversation is kept only in the bot's memory "
            "and is cleared with /new or when the bot restarts. To delete your files, ask the "
            "operator. Questions about pain or injury: see a health professional."
        ),
        "not_allowed": (
            "This bot is a private OpenClock pilot. Ask the operator to add this chat "
            "(id {chat_id}) to the configuration."
        ),
        "new_conversation": "Conversation restarted.",
        "conversation_reset": "(The previous conversation got long and was restarted.)",
        "error": "I couldn't answer right now. Please try again in a moment.",
        "status": {
            "met": "MET",
            "on_track": "ON TRACK",
            "behind": "BEHIND",
            "in_progress": "IN PROGRESS",
            "not_met": "NOT MET",
            "not_started": "NOT STARTED",
            "no_data": "NO DATA",
            "unavailable": "UNAVAILABLE",
        },
        "decimal": ".",
        "units": {"km": "km", "min": "min", "workouts": "workout(s)", "s/km": "s/km"},
    },
}

_SOURCE_NAMES = {"garmin": "Garmin", "apple_health": "Apple Health", "combined": "Total"}


def t(lang: str, key: str, **values: Any) -> str:
    return TEXT[lang][key].format(**values) if values else TEXT[lang][key]


def _num(lang: str, value: float, digits: int = 2) -> str:
    return f"{value:.{digits}f}".replace(".", TEXT[lang]["decimal"])


def _km(lang: str, value: Any) -> str:
    return f"{_num(lang, value)} km" if isinstance(value, int | float) else t(lang, "unavailable")


def _day(lang: str, iso: str) -> str:
    d = date.fromisoformat(iso)
    return d.strftime("%d/%m") if lang == "pt" else d.strftime("%b %d").replace(" 0", " ")


def _pace(text: str) -> str:
    return text.replace(" /km", "/km")


def _totals_line(lang: str, name: str, totals: dict[str, Any]) -> str:
    return (
        f"{name}: {t(lang, 'workouts', n=totals['workout_count'])} · "
        f"{_km(lang, totals['distance_km'])} · {totals['duration']} · {_pace(totals['avg_pace'])}"
    )


def week_report(
    lang: str,
    summary: dict[str, Any],
    comparison: dict[str, Any] | None = None,
    goals: dict[str, Any] | None = None,
) -> str:
    """Weekly summary text: per source, combined, change vs. last week and goals."""
    period = summary["period"]
    lines = [
        t(lang, "week", first=_day(lang, period["first_day"]), last=_day(lang, period["last_day"]))
        + f" ({period['timezone']})"
    ]
    for source, totals in summary["by_source"].items():
        lines.append(_totals_line(lang, _SOURCE_NAMES[source], totals))
    if summary["combined"]:
        lines.append(_totals_line(lang, t(lang, "total"), summary["combined"]))
    else:
        lines.append(t(lang, "withheld"))

    if comparison and comparison["changes"]["combined"]:
        c = comparison["changes"]["combined"]
        change = c["distance_km"]["change"]
        pct = c["distance_km"]["change_pct"]
        if isinstance(change, int | float):
            distance = f"{'+' if change >= 0 else '-'}{_num(lang, abs(change))} km"
            if isinstance(pct, int | float):
                distance += f" ({'+' if pct >= 0 else '-'}{_num(lang, abs(pct), 1)}%)"
        else:
            distance = t(lang, "unavailable")
        direction = c["avg_pace"]["direction"]
        if direction in ("faster", "slower"):
            pace = t(lang, direction, s=f"{abs(c['avg_pace']['change_s_per_km']):.0f}")
        elif direction == "same":
            pace = t(lang, "same")
        else:
            pace = t(lang, "unavailable")
        lines += ["", t(lang, "vs_previous", distance=distance, pace=pace)]

    if goals is not None:
        lines += ["", t(lang, "goals") + ":"]
        if not goals["goals"]:
            lines.append(t(lang, "no_goals"))
        for g in goals["goals"]:
            status = TEXT[lang]["status"][g["status"]]
            line = (
                f"- {g['description'] or g['id']}: {status} "
                f"({_display(lang, g['actual_display'])} / {_display(lang, g['target_display'])})"
            )
            if g["remaining"] and g["days_left"] and g["status"] in ("on_track", "behind"):
                value = g["remaining"]
                amount = str(value) if isinstance(value, int) else _num(lang, value)
                remaining = f"{amount} {TEXT[lang]['units'][g['unit']]}"
                line += "; " + t(lang, "remaining", remaining=remaining, days=g["days_left"])
            lines.append(line)

    notes = summary.get("notes", [])
    if notes:
        lines += ["", t(lang, "notes") + ":"] + [f"- {n}" for n in notes]
    return "\n".join(lines)


def _display(lang: str, text: str) -> str:
    """Localize the decimal separator in values such as ``"13.44 km"`` or ``"5:30 /km"``."""
    text = _pace(text)
    if lang == "pt" and "km" in text and ":" not in text:
        return text.replace(".", ",")
    return text
