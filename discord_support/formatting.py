from __future__ import annotations

MAX_DISCORD_MESSAGE_LENGTH = 2000


def truncate_discord_label(text: str, *, max_length: int = 80) -> str:
    cleaned = " ".join(text.split()).strip()
    if len(cleaned) <= max_length:
        return cleaned
    return f"{cleaned[: max_length - 1].rstrip()}…"


def truncate_discord_value(text: str, *, max_length: int = 1000) -> str:
    cleaned = text.strip()
    if len(cleaned) <= max_length:
        return cleaned
    return f"{cleaned[: max_length - 1].rstrip()}…"


def format_steering_marker(text: str) -> str:
    steering_text = truncate_discord_value(" ".join(text.split()), max_length=1500)
    if not steering_text:
        return "🕹️ Steering applied."
    return f"🕹️ Steering applied:\n{format_discord_block_quote(steering_text)}"


def format_voice_steering_marker(text: str) -> str:
    steering_text = truncate_discord_value(" ".join(text.split()), max_length=1500)
    if not steering_text:
        return "Steering said."
    return f"Steering said:\n{format_discord_block_quote(steering_text)}"


def format_bytes(byte_count: int) -> str:
    units = ("B", "KiB", "MiB", "GiB")
    value = float(byte_count)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.1f} {unit}" if unit != "B" else f"{byte_count} {unit}"
        value /= 1024
    return f"{byte_count} B"


def format_discord_block_quote(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return "> *(empty transcript)*"
    return "\n".join(f"> {line}" if line else ">" for line in normalized.split("\n"))


def starts_inside_block_quote(text: str, offset: int) -> bool:
    if offset <= 0 or offset >= len(text) or text[offset] == "\n":
        return False

    line_start = text.rfind("\n", 0, offset) + 1
    return offset > line_start and text.startswith(">", line_start)


def chunk_text(text: str, *, max_length: int = MAX_DISCORD_MESSAGE_LENGTH) -> list[str]:
    if not text:
        return ["I did not receive response text from the model."]

    chunks: list[str] = []
    offset = 0
    while offset < len(text):
        prefix = "> " if starts_inside_block_quote(text, offset) else ""
        available_length = max_length - len(prefix)
        chunks.append(f"{prefix}{text[offset : offset + available_length]}")
        offset += available_length

    return chunks or ["I did not receive response text from the model."]
