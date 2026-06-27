from __future__ import annotations

import re


def _clean_tool_parameter(value: object, *, max_length: int = 120) -> str:
    if value is None:
        return ""

    text = str(value).replace("\r", " ").replace("\n", " ").strip()
    text = " ".join(text.split())
    if len(text) > max_length:
        return f"{text[: max_length - 1].rstrip()}…"
    return text


def _tool_key(tool_name: str) -> str:
    return (tool_name.strip() or "tool").rsplit(".", 1)[-1]


def _is_discord_send_file_tool(tool_name: str) -> bool:
    return _tool_key(tool_name) == "discord_send_file"


DISCORD_BOT_TOOL_KEYS = {
    # Current Pi/JARVIS tool surface: always-on tools, lazy-loaded tools, and
    # the multi-tool wrapper label used by provider events.
    "agent_phone",
    "bash",
    "browser_click",
    "browser_close",
    "browser_extract",
    "browser_key",
    "browser_open",
    "browser_screenshot",
    "browser_scroll",
    "browser_status",
    "browser_tabs",
    "browser_type",
    "browser_upload",
    "browser_wait",
    "code_search",
    "discord_cron",
    "discord_ping",
    "discord_send_file",
    "edit",
    "fetch_content",
    "find",
    "generate_image",
    "get_search_content",
    "github_cli",
    "google_workspace",
    "grep",
    "jarvis",
    "load_tools",
    "ls",
    "maps",
    "memory",
    "minecraft_jarvis",
    "parallel",
    "read",
    "session_search",
    "smart_plug",
    "ssh",
    "web_search",
    "write",
}

TOOL_EMOJIS = {
    "agent_phone": "📱",
    "bash": "🖥️",
    "browser_click": "👆",
    "browser_close": "❎",
    "browser_extract": "📰",
    "browser_key": "🔑",
    "browser_open": "🪟",
    "browser_screenshot": "🖼️",
    "browser_scroll": "📜",
    "browser_status": "🌐",
    "browser_tabs": "🗃️",
    "browser_type": "⌨️",
    "browser_upload": "📤",
    "browser_wait": "⏱️",
    "code_search": "💻",
    "discord_cron": "🗓️",
    "discord_ping": "📣",
    "discord_send_file": "📎",
    "edit": "✏️",
    "fetch_content": "📄",
    "find": "🗂️",
    "generate_image": "🎨",
    "get_search_content": "📥",
    "github_cli": "🐙",
    "google_workspace": "🏢",
    "grep": "🧶",
    "jarvis": "🤖",
    "load_tools": "🧰",
    "ls": "📁",
    "maps": "🗺️",
    "memory": "🧠",
    "minecraft_jarvis": "⛏️",
    "parallel": "🔀",
    "read": "📖",
    "session_search": "🧭",
    "smart_plug": "🔌",
    "ssh": "🔗",
    "web_search": "🔎",
    "write": "📝",
    "fallback": "🛠️",
}


_FALLBACK_TOOL_EMOJI_PALETTE = [
    "🧪",
    "🧬",
    "🔧",
    "⚙️",
    "🧲",
    "🛰️",
    "📡",
    "🔭",
    "🕯️",
    "🧯",
    "🚦",
    "🧷",
    "🪛",
    "🪚",
    "🧮",
    "🧿",
]
_DYNAMIC_TOOL_EMOJIS: dict[str, str] = {}
_KEYCAP_DIGIT_EMOJIS = {
    "0": "0️⃣",
    "1": "1️⃣",
    "2": "2️⃣",
    "3": "3️⃣",
    "4": "4️⃣",
    "5": "5️⃣",
    "6": "6️⃣",
    "7": "7️⃣",
    "8": "8️⃣",
    "9": "9️⃣",
}


def _keycap_number_emoji(number: int) -> str:
    return "".join(_KEYCAP_DIGIT_EMOJIS[digit] for digit in str(max(0, number)))


def _validate_tool_emojis() -> None:
    missing = sorted(DISCORD_BOT_TOOL_KEYS.difference(TOOL_EMOJIS))
    if missing:
        raise RuntimeError(f"Missing tool emoji mapping(s): {', '.join(missing)}")

    seen: dict[str, str] = {}
    duplicates: list[str] = []
    for tool_key, emoji in TOOL_EMOJIS.items():
        other_tool_key = seen.get(emoji)
        if other_tool_key:
            duplicates.append(f"{other_tool_key}/{tool_key} share {emoji}")
        else:
            seen[emoji] = tool_key
    if duplicates:
        raise RuntimeError(f"Duplicate tool emoji mapping(s): {', '.join(duplicates)}")


def _tool_emoji(tool_key: str) -> str:
    key = _tool_key(tool_key)
    emoji = TOOL_EMOJIS.get(key)
    if emoji:
        return emoji

    dynamic_emoji = _DYNAMIC_TOOL_EMOJIS.get(key)
    if dynamic_emoji:
        return dynamic_emoji

    used = set(TOOL_EMOJIS.values()).union(_DYNAMIC_TOOL_EMOJIS.values())
    for candidate in _FALLBACK_TOOL_EMOJI_PALETTE:
        if candidate not in used:
            _DYNAMIC_TOOL_EMOJIS[key] = candidate
            return candidate

    # If new tool surfaces exceed the named palette, keep the visible emoji unique
    # by appending keycap digits rather than reusing the bare fallback emoji.
    index = len(_DYNAMIC_TOOL_EMOJIS) + 1
    while True:
        candidate = f"{TOOL_EMOJIS['fallback']}{_keycap_number_emoji(index)}"
        if candidate not in used:
            _DYNAMIC_TOOL_EMOJIS[key] = candidate
            return candidate
        index += 1


_validate_tool_emojis()



TOOL_VOICE_START_NARRATIONS = {
    "agent_phone": "I’ll operate the phone, sir.",
    "bash": "I’ll run that in the terminal, sir.",
    "browser_click": "I’ll click in the browser, sir.",
    "browser_close": "I’ll close the browser item, sir.",
    "browser_extract": "I’ll extract the browser page content, sir.",
    "browser_key": "I’ll press that browser key, sir.",
    "browser_open": "I’ll open that in the browser, sir.",
    "browser_screenshot": "I’ll inspect the browser screen, sir.",
    "browser_scroll": "I’ll scroll the browser, sir.",
    "browser_status": "I’ll check browser status, sir.",
    "browser_tabs": "I’ll manage the browser tabs, sir.",
    "browser_type": "I’ll type in the browser, sir.",
    "browser_upload": "I’ll upload the file in the browser, sir.",
    "browser_wait": "I’ll wait on the browser, sir.",
    "code_search": "I’ll search the code references, sir.",
    "discord_cron": "I’ll adjust the scheduled jobs, sir.",
    "discord_ping": "I’ll send the Discord ping, sir.",
    "discord_send_file": "I’ll send the file to Discord, sir.",
    "edit": "I’ll make the edit, sir.",
    "fetch_content": "I’ll fetch the source content, sir.",
    "find": "I’ll find matching files, sir.",
    "generate_image": "I’ll generate the image, sir.",
    "get_search_content": "I’ll open the retrieved content, sir.",
    "github_cli": "I’ll use GitHub, sir.",
    "google_workspace": "I’ll work in Google Workspace, sir.",
    "grep": "I’ll search the files, sir.",
    "jarvis": "I’ll consult the JARVIS subsystem, sir.",
    "load_tools": "I’ll bring the required systems online, sir.",
    "ls": "I’ll list the directory, sir.",
    "maps": "I’ll check Maps, sir.",
    "memory": "I’ll check my memory, sir.",
    "minecraft_jarvis": "I’ll contact the Minecraft JARVIS bot, sir.",
    "parallel": "I’ll run those in parallel, sir.",
    "read": "I’ll inspect the file, sir.",
    "session_search": "I’ll search the previous sessions, sir.",
    "smart_plug": "I’ll adjust the smart plug, sir.",
    "ssh": "I’ll connect over SSH, sir.",
    "web_search": "I’ll search the web, sir.",
    "write": "I’ll write the file, sir.",
}

TOOL_VOICE_FAILURE_NARRATIONS = {
    "agent_phone": "The phone action failed, sir.",
    "bash": "The terminal command failed, sir.",
    "browser_click": "The browser click failed, sir.",
    "browser_close": "The browser close action failed, sir.",
    "browser_extract": "The browser extraction failed, sir.",
    "browser_key": "The browser keypress failed, sir.",
    "browser_open": "The browser open action failed, sir.",
    "browser_screenshot": "The browser screenshot failed, sir.",
    "browser_scroll": "The browser scroll failed, sir.",
    "browser_status": "The browser status check failed, sir.",
    "browser_tabs": "The browser tab action failed, sir.",
    "browser_type": "The browser typing failed, sir.",
    "browser_upload": "The browser upload failed, sir.",
    "browser_wait": "The browser wait failed, sir.",
    "code_search": "The code search failed, sir.",
    "discord_cron": "I couldn’t update the scheduled jobs, sir.",
    "discord_ping": "I couldn’t send the Discord ping, sir.",
    "discord_send_file": "I couldn’t send the file, sir.",
    "edit": "The edit failed, sir.",
    "fetch_content": "I couldn’t fetch that content, sir.",
    "find": "The file lookup failed, sir.",
    "generate_image": "The image generation failed, sir.",
    "get_search_content": "I couldn’t retrieve that content, sir.",
    "github_cli": "The GitHub action failed, sir.",
    "google_workspace": "The Google Workspace action failed, sir.",
    "grep": "The file search failed, sir.",
    "jarvis": "The JARVIS subsystem call failed, sir.",
    "load_tools": "I couldn’t load those systems, sir.",
    "ls": "The directory listing failed, sir.",
    "maps": "The Maps lookup failed, sir.",
    "memory": "The memory action failed, sir.",
    "minecraft_jarvis": "The Minecraft JARVIS call failed, sir.",
    "parallel": "The parallel tools failed, sir.",
    "read": "I couldn’t read the file, sir.",
    "session_search": "The session search failed, sir.",
    "smart_plug": "The smart plug action failed, sir.",
    "ssh": "The SSH command failed, sir.",
    "web_search": "The web search failed, sir.",
    "write": "I couldn’t write the file, sir.",
}


def _validate_tool_voice_narrations() -> None:
    missing_start = sorted(DISCORD_BOT_TOOL_KEYS.difference(TOOL_VOICE_START_NARRATIONS))
    missing_failure = sorted(DISCORD_BOT_TOOL_KEYS.difference(TOOL_VOICE_FAILURE_NARRATIONS))
    problems = []
    if missing_start:
        problems.append(f"missing start narration(s): {', '.join(missing_start)}")
    if missing_failure:
        problems.append(f"missing failure narration(s): {', '.join(missing_failure)}")
    if problems:
        raise RuntimeError("Invalid tool voice narration mapping: " + "; ".join(problems))


def _voice_tool_key(tool_name: object) -> str:
    raw_name = str(tool_name or "tool")
    key = _tool_key(raw_name)
    if raw_name in {"multi_tool_use.parallel", "parallel"} or key == "parallel":
        return "parallel"
    return key


def _tool_voice_narration(tool_name: object, *, failed: bool = False) -> str:
    key = _voice_tool_key(tool_name)
    narrations = TOOL_VOICE_FAILURE_NARRATIONS if failed else TOOL_VOICE_START_NARRATIONS
    narration = narrations.get(key)
    if narration:
        return narration
    spoken_name = re.sub(r"[_-]+", " ", key).strip() or "tool"
    if failed:
        return f"The {spoken_name} action failed, sir."
    return f"I’ll use {spoken_name}, sir."


_validate_tool_voice_narrations()


def _first_tool_arg(tool_args: dict[str, object], *keys: str, max_length: int = 120) -> str:
    for key in keys:
        value = _clean_tool_parameter(tool_args.get(key), max_length=max_length)
        if value:
            return value
    return ""


def _coordinate_label(tool_args: dict[str, object]) -> str:
    x = _first_tool_arg(tool_args, "x", "clientX", "screenX", max_length=24)
    y = _first_tool_arg(tool_args, "y", "clientY", "screenY", max_length=24)
    if x and y:
        return f"{x}, {y}"
    return ""


def _list_arg_label(value: object, *, max_length: int = 120) -> str:
    if isinstance(value, (list, tuple)):
        return _clean_tool_parameter(", ".join(str(item) for item in value if str(item).strip()), max_length=max_length)
    return _clean_tool_parameter(value, max_length=max_length)


def _tool_action_label(tool_name: str, args: object) -> str:
    tool_args = args if isinstance(args, dict) else {}
    name = tool_name.strip() or "tool"
    tool_key = _tool_key(name)

    if tool_key == "web_search":
        query = _clean_tool_parameter(tool_args.get("query") or tool_args.get("queries", ""))
        emoji = _tool_emoji("web_search")
        return f"{emoji} Searched the web for \"{query}\"" if query else f"{emoji} Searched the web"

    if tool_key == "code_search":
        query = _clean_tool_parameter(tool_args.get("query"))
        emoji = _tool_emoji("code_search")
        return f"{emoji} Searched code references for \"{query}\"" if query else f"{emoji} Searched code references"

    if tool_key == "fetch_content":
        url = _clean_tool_parameter(tool_args.get("url") or tool_args.get("urls", ""))
        emoji = _tool_emoji("fetch_content")
        return f"{emoji} Fetched source content from \"{url}\"" if url else f"{emoji} Fetched source content"

    if tool_key == "get_search_content":
        response_id = _clean_tool_parameter(tool_args.get("responseId"))
        emoji = _tool_emoji("get_search_content")
        return f"{emoji} Opened fetched result \"{response_id}\"" if response_id else f"{emoji} Opened fetched result"

    if tool_key == "youtube_api":
        action = _first_tool_arg(tool_args, "action", "resource", max_length=40)
        query = _first_tool_arg(tool_args, "query", "id", max_length=120)
        emoji = _tool_emoji("youtube_api")
        if action and query:
            return f"{emoji} Checked YouTube {action} for \"{query}\""
        return f"{emoji} Checked YouTube {action}" if action else f"{emoji} Checked YouTube"

    if tool_key == "discord_cron":
        action = _first_tool_arg(tool_args, "action", max_length=40)
        target = _first_tool_arg(tool_args, "name", "id", "channel", "query", max_length=100)
        emoji = _tool_emoji("discord_cron")
        if action and target:
            return f"{emoji} Updated scheduled job {action}: {target}"
        return f"{emoji} Updated scheduled jobs: {action}" if action else f"{emoji} Updated scheduled jobs"

    if tool_key == "discord_ping":
        message = _first_tool_arg(tool_args, "message", max_length=140)
        emoji = _tool_emoji("discord_ping")
        return f"{emoji} Sent Discord ping: \"{message}\"" if message else f"{emoji} Sent Discord ping"

    if tool_key == "session_search":
        query = _clean_tool_parameter(tool_args.get("query"))
        emoji = _tool_emoji("session_search")
        return f"{emoji} Searched prior sessions for \"{query}\"" if query else f"{emoji} Searched prior sessions"

    if tool_key == "memory":
        action = _clean_tool_parameter(tool_args.get("action"), max_length=40)
        query = _clean_tool_parameter(tool_args.get("query") or tool_args.get("text") or tool_args.get("id"), max_length=140)
        emoji = _tool_emoji("memory")
        if action == "search":
            return f"{emoji} Searched memory for \"{query}\"" if query else f"{emoji} Searched memory"
        if action == "remember":
            return f"{emoji} Saved memory: \"{query}\"" if query else f"{emoji} Saved memory"
        if action == "forget":
            return f"{emoji} Removed memory {query}" if query else f"{emoji} Removed memory"
        if action == "update":
            return f"{emoji} Updated memory {query}" if query else f"{emoji} Updated memory"
        if action == "list":
            return f"{emoji} Listed memory"
        if action == "status":
            return f"{emoji} Checked memory status"
        return f"{emoji} Managed memory: {action}" if action else f"{emoji} Managed memory"

    if tool_key == "memory_search":
        query = _clean_tool_parameter(tool_args.get("query"))
        emoji = _tool_emoji("memory_search")
        return f"{emoji} Searched memory for \"{query}\"" if query else f"{emoji} Searched memory"

    if tool_key == "memory_remember":
        detail = _first_tool_arg(tool_args, "key", "type", "text", max_length=140)
        emoji = _tool_emoji("memory_remember")
        return f"{emoji} Saved memory: {detail}" if detail else f"{emoji} Saved memory"

    if tool_key == "memory_forget":
        key = _clean_tool_parameter(tool_args.get("key") or tool_args.get("id"))
        emoji = _tool_emoji("memory_forget")
        return f"{emoji} Removed memory {key}" if key else f"{emoji} Removed memory"

    if tool_key == "memory_lessons":
        category = _clean_tool_parameter(tool_args.get("category"))
        emoji = _tool_emoji("memory_lessons")
        return f"{emoji} Reviewed saved lessons for {category}" if category else f"{emoji} Reviewed saved lessons"

    if tool_key == "memory_stats":
        return f"{_tool_emoji('memory_stats')} Checked memory statistics"

    if tool_key == "discord_send_file":
        path = _clean_tool_parameter(tool_args.get("path"))
        emoji = _tool_emoji("discord_send_file")
        return f"{emoji} Attached file \"{path}\"" if path else f"{emoji} Attached file to Discord"

    if tool_key == "bash":
        command = _clean_tool_parameter(tool_args.get("command"))
        emoji = _tool_emoji("bash")
        return f"{emoji} Executed terminal command: \"{command}\"" if command else f"{emoji} Executed terminal command"

    if tool_key == "read":
        path = _clean_tool_parameter(tool_args.get("path"))
        emoji = _tool_emoji("read")
        return f"{emoji} Inspected file \"{path}\"" if path else f"{emoji} Inspected file"

    if tool_key == "grep":
        pattern = _clean_tool_parameter(tool_args.get("pattern"))
        path = _clean_tool_parameter(tool_args.get("path"))
        emoji = _tool_emoji("grep")
        target = f" in {path}" if path else ""
        return f"{emoji} Searched files for \"{pattern}\"{target}" if pattern else f"{emoji} Searched files"

    if tool_key == "find":
        pattern = _clean_tool_parameter(tool_args.get("pattern"))
        path = _clean_tool_parameter(tool_args.get("path"))
        emoji = _tool_emoji("find")
        target = f" in {path}" if path else ""
        return f"{emoji} Found files matching \"{pattern}\"{target}" if pattern else f"{emoji} Found matching files"

    if tool_key == "ls":
        path = _clean_tool_parameter(tool_args.get("path"))
        emoji = _tool_emoji("ls")
        return f"{emoji} Listed directory \"{path}\"" if path else f"{emoji} Listed directory"

    if tool_key == "write":
        path = _clean_tool_parameter(tool_args.get("path"))
        emoji = _tool_emoji("write")
        return f"{emoji} Wrote file \"{path}\"" if path else f"{emoji} Wrote file"

    if tool_key == "edit":
        path = _clean_tool_parameter(tool_args.get("path"))
        emoji = _tool_emoji("edit")
        return f"{emoji} Patched file \"{path}\"" if path else f"{emoji} Patched file"

    if tool_key == "load_tools":
        groups = _list_arg_label(tool_args.get("groups"), max_length=120)
        emoji = _tool_emoji("load_tools")
        return f"{emoji} Loaded tool group{'s' if ',' in groups else ''}: {groups}" if groups else f"{emoji} Loaded optional tools"

    if tool_key == "jarvis":
        action = _first_tool_arg(tool_args, "action", "workflow", "prompt", max_length=120)
        emoji = _tool_emoji("jarvis")
        return f"{emoji} Queried JARVIS subsystem: {action}" if action else f"{emoji} Queried JARVIS subsystem"

    if tool_key == "smart_plug":
        action = _first_tool_arg(tool_args, "action", max_length=40)
        plug = _first_tool_arg(tool_args, "plug", "name", "alias", max_length=100)
        emoji = _tool_emoji("smart_plug")
        if action and plug:
            return f"{emoji} Updated smart plug {plug}: {action}"
        return f"{emoji} Updated smart plug: {action}" if action else f"{emoji} Updated smart plug"

    if tool_key == "google_workspace":
        action = _first_tool_arg(tool_args, "action", "resource", "query", max_length=120)
        emoji = _tool_emoji("google_workspace")
        return f"{emoji} Updated Google Workspace: {action}" if action else f"{emoji} Updated Google Workspace"

    if tool_key == "maps":
        query = _first_tool_arg(tool_args, "query", max_length=140)
        emoji = _tool_emoji("maps")
        return f"{emoji} Checked Maps for \"{query}\"" if query else f"{emoji} Checked Maps"

    if tool_key == "github_cli":
        args_label = _list_arg_label(tool_args.get("args"), max_length=140)
        emoji = _tool_emoji("github_cli")
        return f"{emoji} Ran GitHub CLI: gh {args_label}" if args_label else f"{emoji} Ran GitHub CLI"

    if tool_key == "agent_phone":
        args_label = _list_arg_label(tool_args.get("args"), max_length=140)
        emoji = _tool_emoji("agent_phone")
        return f"{emoji} Controlled phone: {args_label}" if args_label else f"{emoji} Controlled phone"

    if tool_key == "generate_image":
        prompt = _first_tool_arg(tool_args, "prompt", "description", max_length=140)
        emoji = _tool_emoji("generate_image")
        return f"{emoji} Generated image for \"{prompt}\"" if prompt else f"{emoji} Generated image"

    if tool_key.startswith("browser_"):
        emoji = _tool_emoji(tool_key)
        if tool_key == "browser_status":
            return f"{emoji} Checked browser status"
        if tool_key == "browser_open":
            url = _first_tool_arg(tool_args, "url", max_length=140)
            return f"{emoji} Opened browser page \"{url}\"" if url else f"{emoji} Opened browser"
        if tool_key == "browser_screenshot":
            return f"{emoji} Captured browser screenshot"
        if tool_key == "browser_click":
            target = _first_tool_arg(tool_args, "selector", "text", max_length=100)
            coordinates = _coordinate_label(tool_args)
            if target:
                return f"{emoji} Clicked browser target \"{target}\""
            return f"{emoji} Clicked browser at {coordinates}" if coordinates else f"{emoji} Clicked browser"
        if tool_key == "browser_type":
            target = _first_tool_arg(tool_args, "selector", max_length=100)
            return f"{emoji} Typed in browser field \"{target}\"" if target else f"{emoji} Typed in browser"
        if tool_key == "browser_upload":
            paths = _list_arg_label(tool_args.get("paths") or tool_args.get("path"), max_length=140)
            return f"{emoji} Uploaded browser file {paths}" if paths else f"{emoji} Uploaded browser file"
        if tool_key == "browser_key":
            key = _first_tool_arg(tool_args, "key", "shortcut", max_length=80)
            return f"{emoji} Pressed browser key {key}" if key else f"{emoji} Pressed browser key"
        if tool_key == "browser_scroll":
            detail = _first_tool_arg(tool_args, "direction", "deltaY", "amount", max_length=80)
            return f"{emoji} Scrolled browser {detail}" if detail else f"{emoji} Scrolled browser"
        if tool_key == "browser_wait":
            target = _first_tool_arg(tool_args, "text", "selector", "state", "seconds", max_length=100)
            return f"{emoji} Waited on browser for {target}" if target else f"{emoji} Waited on browser"
        if tool_key == "browser_extract":
            return f"{emoji} Extracted browser page content"
        if tool_key == "browser_tabs":
            action = _first_tool_arg(tool_args, "action", max_length=60)
            return f"{emoji} Managed browser tabs: {action}" if action else f"{emoji} Managed browser tabs"
        if tool_key == "browser_close":
            return f"{emoji} Closed browser item"

    if name in {"multi_tool_use.parallel", "parallel"} or tool_key == "parallel":
        return f"{_tool_emoji('parallel')} Executed multiple tools in parallel"

    readable_name = re.sub(r"[_-]+", " ", tool_key).strip() or name
    return f"{_tool_emoji(tool_key)} Completed {readable_name} action"


def _tool_failure_label(tool_name: str, args: object) -> str:
    tool_args = args if isinstance(args, dict) else {}
    name = tool_name.strip() or "tool"
    tool_key = _tool_key(name)
    emoji = _tool_emoji(tool_key)

    if tool_key == "bash":
        command = _clean_tool_parameter(tool_args.get("command"))
        return f"❌ {emoji} Terminal command failed: \"{command}\"" if command else f"❌ {emoji} Terminal command failed"
    if tool_key == "read":
        path = _clean_tool_parameter(tool_args.get("path"))
        return f"❌ {emoji} Could not inspect file \"{path}\"" if path else f"❌ {emoji} Could not inspect file"
    if tool_key == "write":
        path = _clean_tool_parameter(tool_args.get("path"))
        return f"❌ {emoji} Could not write file \"{path}\"" if path else f"❌ {emoji} Could not write file"
    if tool_key == "edit":
        path = _clean_tool_parameter(tool_args.get("path"))
        return f"❌ {emoji} Could not patch file \"{path}\"" if path else f"❌ {emoji} Could not patch file"
    if tool_key in {"web_search", "code_search", "session_search", "memory_search", "grep", "find"}:
        query = _clean_tool_parameter(tool_args.get("query") or tool_args.get("pattern"))
        readable = {
            "web_search": "web search",
            "code_search": "code reference search",
            "session_search": "prior session search",
            "memory_search": "memory search",
            "grep": "file search",
            "find": "file lookup",
        }[tool_key]
        return f"❌ {emoji} Failed {readable} for \"{query}\"" if query else f"❌ {emoji} Failed {readable}"
    if tool_key == "ls":
        path = _clean_tool_parameter(tool_args.get("path"))
        return f"❌ {emoji} Could not list directory \"{path}\"" if path else f"❌ {emoji} Could not list directory"
    if tool_key == "fetch_content":
        url = _clean_tool_parameter(tool_args.get("url") or tool_args.get("urls", ""))
        return f"❌ {emoji} Could not fetch source content from \"{url}\"" if url else f"❌ {emoji} Could not fetch source content"
    if tool_key == "get_search_content":
        response_id = _clean_tool_parameter(tool_args.get("responseId"))
        return f"❌ {emoji} Could not open fetched result \"{response_id}\"" if response_id else f"❌ {emoji} Could not open fetched result"
    if tool_key == "youtube_api":
        query = _first_tool_arg(tool_args, "query", "id", max_length=120)
        return f"❌ {emoji} YouTube lookup failed for \"{query}\"" if query else f"❌ {emoji} YouTube lookup failed"
    if tool_key == "discord_ping":
        message = _first_tool_arg(tool_args, "message", max_length=140)
        return f"❌ {emoji} Could not send Discord ping: \"{message}\"" if message else f"❌ {emoji} Could not send Discord ping"
    if tool_key == "discord_send_file":
        path = _clean_tool_parameter(tool_args.get("path"))
        return f"❌ {emoji} Could not attach file \"{path}\"" if path else f"❌ {emoji} Could not attach file"
    if tool_key == "load_tools":
        groups = _list_arg_label(tool_args.get("groups"), max_length=120)
        return f"❌ {emoji} Could not load tool group: {groups}" if groups else f"❌ {emoji} Could not load optional tools"
    if tool_key == "memory":
        action = _clean_tool_parameter(tool_args.get("action"), max_length=40)
        return f"❌ {emoji} Memory action failed: {action}" if action else f"❌ {emoji} Memory action failed"
    if tool_key == "smart_plug":
        action = _first_tool_arg(tool_args, "action", max_length=40)
        plug = _first_tool_arg(tool_args, "plug", "name", "alias", max_length=100)
        detail = f" {plug}: {action}" if action and plug else f": {action}" if action else ""
        return f"❌ {emoji} Smart plug action failed{detail}"
    if tool_key == "maps":
        query = _first_tool_arg(tool_args, "query", max_length=140)
        return f"❌ {emoji} Maps lookup failed for \"{query}\"" if query else f"❌ {emoji} Maps lookup failed"
    if tool_key == "github_cli":
        args_label = _list_arg_label(tool_args.get("args"), max_length=140)
        return f"❌ {emoji} GitHub CLI failed: gh {args_label}" if args_label else f"❌ {emoji} GitHub CLI failed"
    if tool_key == "agent_phone":
        args_label = _list_arg_label(tool_args.get("args"), max_length=140)
        return f"❌ {emoji} Phone action failed: {args_label}" if args_label else f"❌ {emoji} Phone action failed"
    if tool_key == "generate_image":
        prompt = _first_tool_arg(tool_args, "prompt", "description", max_length=140)
        return f"❌ {emoji} Image generation failed for \"{prompt}\"" if prompt else f"❌ {emoji} Image generation failed"
    if tool_key.startswith("browser_"):
        readable = re.sub(r"[_-]+", " ", tool_key).strip()
        return f"❌ {emoji} {readable.capitalize()} failed"
    if tool_key == "parallel" or name in {"multi_tool_use.parallel", "parallel"}:
        return f"❌ {_tool_emoji('parallel')} Parallel tool execution failed"

    readable_name = re.sub(r"[_-]+", " ", _voice_tool_key(name)).strip() or name
    return f"❌ {emoji} {readable_name.capitalize()} action failed"
