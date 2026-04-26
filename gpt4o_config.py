import re


def build_system_prompt(
    pinned_memories: list[str],
    seed_summary: str | None = None,
    recent_summaries: list[str] | None = None,
) -> str:
    parts: list[str] = []

    base_system = """
You are a helpful, natural, and attentive AI assistant running in a local chat interface.
Respond clearly and conversationally. Use the user's pinned memory and conversation summaries only as background context; do not invent details that are not present.
""".strip()
    parts.append(base_system)

    if seed_summary:
        parts.append(seed_summary.strip())

    if pinned_memories:
        parts.append(
            "GLOBAL PINNED MEMORY:\n"
            + "\n".join(f"- {m}" for m in pinned_memories if (m or "").strip())
        )

    if recent_summaries:
        blocks = []
        for idx, summary in enumerate(recent_summaries, start=1):
            text = (summary or "").strip()
            if text:
                blocks.append(f"Summary {idx}:\n{text}")
        if blocks:
            parts.append(
                "RECENT CONVERSATION BRIDGES. These are short summaries from previous conversations. "
                "Use them as background continuity, not as messages from the current conversation:\n\n"
                + "\n\n".join(blocks)
            )

    return "\n\n".join(parts).strip()


def postprocess_text(text: str) -> str:
    cleaned = text or ""
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned
