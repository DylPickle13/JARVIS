from __future__ import annotations

import asyncio
import threading
import time

import discord

import config
from discord_support.formatting import (
    chunk_text as _chunk_text,
    format_steering_marker as _format_steering_marker,
)
from discord_support.tool_labels import (
    _is_discord_send_file_tool,
    _tool_action_label,
    _tool_failure_label,
)

config.load_project_env(config.DOTENV_PATH)
LOGGER = config.get_logger("jarvis.discord_bot")
DISCORD_TOOL_HEARTBEAT_SECONDS = config.get_int_env(
    "DISCORD_TOOL_HEARTBEAT_SECONDS",
    45,
    minimum=10,
)
SLASH_CANCEL_COMMAND = "/jarvis cancel"


class _StreamingResponse:
    def __init__(
        self,
        *,
        loop: asyncio.AbstractEventLoop,
        channel: discord.abc.Messageable,
        update_interval_seconds: float,
    ) -> None:
        self._loop = loop
        self._channel = channel
        self._update_interval_seconds = update_interval_seconds
        self._buffer = ""
        self._lock = threading.Lock()
        self._pending_task: asyncio.Task[None] | None = None
        self._last_edit_at = 0.0
        self._closed = False
        self._update_lock = asyncio.Lock()
        self._live_messages: list[discord.Message] = []
        self._sent_chunks: list[str] = []
        self._current_tool_name = ""
        self._current_tool_args = ""
        self._shown_tool_call_ids: set[str] = set()
        self._tool_args_by_call_id: dict[str, object] = {}
        self._tool_label_spans_by_call_id: dict[str, tuple[int, int]] = {}
        self._active_tool_call_id = ""
        self._active_tool_label = ""
        self._active_tool_started_at = 0.0
        self._heartbeat_task: asyncio.Task[None] | None = None
        self._in_thinking = False
        self._thinking_has_content = False
        self._thinking_line_needs_prefix = True
        self._needs_text_separator = False
        self._pause_updates = False
        self._file_tool_call_ids: set[str] = set()
        self._file_tool_labels: dict[str, str] = {}
        self._file_split_tasks: dict[str, asyncio.Task[None]] = {}
        self._pending_steering_markers: list[str] = []
        self._seen_turn_start = False
        self._has_output = False

    @property
    def has_output(self) -> bool:
        return self._has_output

    def append(self, delta: str) -> None:
        if not delta:
            return
        with self._lock:
            if self._closed:
                return
            self._buffer += delta
        self._has_output = True
        self._schedule_update()

    def current_text(self) -> str:
        with self._lock:
            return self._buffer

    def queue_marker(self, marker: str) -> str | None:
        marker = (marker or "").strip()
        if not marker:
            return None
        with self._lock:
            if self._closed:
                return None
            self._pending_steering_markers.append(marker)
        return marker

    def queue_steering_marker(self, text: str) -> str | None:
        return self.queue_marker(_format_steering_marker(text))

    def discard_steering_marker(self, marker: str | None) -> None:
        if not marker:
            return
        with self._lock:
            try:
                self._pending_steering_markers.remove(marker)
            except ValueError:
                pass

    async def finalize(self, text: str) -> None:
        with self._lock:
            if self._closed:
                return
            self._buffer = text
        await self._update_message()

    async def wait_pending(self) -> None:
        """Wait for any pending update tasks to complete."""
        if self._pending_task and not self._pending_task.done():
            await self._pending_task

    async def close(self) -> None:
        self._closed = True
        self._stop_tool_heartbeat()
        pending_task = self._pending_task
        if pending_task is not None and not pending_task.done():
            pending_task.cancel()
            await asyncio.gather(pending_task, return_exceptions=True)
        heartbeat_task = self._heartbeat_task
        if heartbeat_task is not None and not heartbeat_task.done():
            await asyncio.gather(heartbeat_task, return_exceptions=True)
        self._pending_task = None
        self._heartbeat_task = None

    def on_rpc_event(self, event: dict) -> None:
        """Process a Pi RPC event and stream it to Discord."""
        event_type = event.get("type", "")

        if event_type == "turn_start":
            self._handle_turn_start()
        elif event_type == "message_update":
            self._handle_message_update(event)
        elif event_type == "tool_execution_start":
            self._handle_tool_start(event)
        elif event_type == "tool_execution_update":
            self._handle_tool_update(event)
        elif event_type == "tool_execution_end":
            self._handle_tool_end(event)
        elif event_type == "compaction_start":
            self.append("Compacting context...\n")
        elif event_type == "compaction_end":
            self.append("Context compacted.\n")

    def _handle_turn_start(self) -> None:
        with self._lock:
            if not self._seen_turn_start:
                self._seen_turn_start = True
                return
            marker = self._pending_steering_markers.pop(0) if self._pending_steering_markers else ""
        if marker:
            self._request_steering_boundary(marker)

    def _request_steering_boundary(self, marker: str) -> None:
        if self._loop.is_closed():
            return

        with self._lock:
            if self._closed:
                return
            content_before_marker = self._buffer
            self._buffer = ""
            self._pause_updates = True
            self._has_output = True
            self._needs_text_separator = False
            self._thinking_has_content = False
            self._thinking_line_needs_prefix = True
            self._in_thinking = False

        def _schedule() -> None:
            if self._closed:
                return
            asyncio.create_task(self._split_for_steering_marker(marker, content_before_marker))

        self._loop.call_soon_threadsafe(_schedule)

    async def _split_for_steering_marker(self, marker: str, content_before_marker: str) -> None:
        if self._closed:
            return

        pending_task = self._pending_task
        if pending_task is not None and not pending_task.done():
            pending_task.cancel()
            await asyncio.gather(pending_task, return_exceptions=True)
        self._pending_task = None

        if content_before_marker:
            async with self._update_lock:
                await _sync_live_messages(
                    self._channel,
                    self._live_messages,
                    self._sent_chunks,
                    _chunk_text(content_before_marker),
                )
            self._last_edit_at = time.monotonic()

        await self._channel.send(marker)

        self._live_messages = []
        self._sent_chunks = []
        self._tool_label_spans_by_call_id.clear()
        self._needs_text_separator = False
        self._thinking_has_content = False
        self._thinking_line_needs_prefix = True
        self._in_thinking = False
        self._pause_updates = False
        self._schedule_update()

    def _format_thinking_delta(self, delta: str) -> str:
        """Format thinking text as a Discord block quote without dangling quote markers."""
        formatted_parts: list[str] = []
        normalized_delta = delta.replace("\r\n", "\n").replace("\r", "\n")

        for char in normalized_delta:
            if char == "\n":
                if self._thinking_has_content:
                    formatted_parts.append("\n")
                    self._thinking_line_needs_prefix = True
                continue

            if self._thinking_line_needs_prefix:
                formatted_parts.append("> ")
                self._thinking_line_needs_prefix = False

            self._thinking_has_content = True
            formatted_parts.append(char)

        return "".join(formatted_parts)

    def _handle_message_update(self, event: dict) -> None:
        """Handle text/thinking deltas from message_update events."""
        msg_event = event.get("assistantMessageEvent", {})
        event_type = msg_event.get("type", "")
        
        if event_type == "thinking_start":
            with self._lock:
                if self._buffer and not self._buffer.endswith(("\n", "\r")):
                    self._buffer += "\n"
            self._in_thinking = True
            self._thinking_has_content = False
            self._thinking_line_needs_prefix = True
        elif event_type == "thinking_delta":
            delta = msg_event.get("delta", "")
            if delta and self._in_thinking:
                formatted_delta = self._format_thinking_delta(delta)
                if formatted_delta:
                    self.append(formatted_delta)
        elif event_type == "thinking_end":
            self._in_thinking = False
            self._thinking_line_needs_prefix = True
            with self._lock:
                if self._thinking_has_content:
                    self._buffer = self._buffer.rstrip("\r\n")
                    self._needs_text_separator = bool(self._buffer)
            self._schedule_update()
        elif event_type == "text_start":
            pass
        elif event_type == "text_delta":
            delta = msg_event.get("delta", "")
            if delta:
                if self._needs_text_separator:
                    delta = "\n" + delta.lstrip("\r\n")
                    self._needs_text_separator = False
                self.append(delta)
        elif event_type == "text_end":
            pass
        elif event_type == "toolcall_start":
            self._current_tool_name = msg_event.get("toolCall", {}).get("name", "unknown")
        elif event_type == "toolcall_delta":
            pass
        elif event_type == "toolcall_end":
            pass

    def _handle_tool_start(self, event: dict) -> None:
        """Handle tool execution start."""
        tool_name = event.get("toolName", "unknown")
        tool_call_id = str(event.get("toolCallId", ""))
        self._current_tool_name = tool_name

        if tool_call_id and tool_call_id in self._shown_tool_call_ids:
            return
        if tool_call_id:
            self._shown_tool_call_ids.add(tool_call_id)

        args = event.get("args", {})
        if tool_call_id:
            self._tool_args_by_call_id[tool_call_id] = args

        label = _tool_action_label(str(tool_name), args)
        if _is_discord_send_file_tool(str(tool_name)):
            self._request_file_stream_split(tool_call_id, label)
            return

        self._append_tool_label(tool_call_id, label)
        self._start_tool_heartbeat(tool_call_id, label)

    def _handle_tool_update(self, event: dict) -> None:
        """Handle tool execution progress without dumping raw tool output."""
        pass

    def _append_tool_label(self, tool_call_id: str, label: str) -> None:
        line = f"\n{label}\n"
        with self._lock:
            if self._closed:
                return
            start = len(self._buffer) + 1
            self._buffer += line
            if tool_call_id:
                self._tool_label_spans_by_call_id[tool_call_id] = (start, start + len(label))
        self._has_output = True
        self._schedule_update()

    def _shift_tool_label_spans(self, from_index: int, delta: int, *, skip_tool_call_id: str = "") -> None:
        if delta == 0:
            return
        for call_id, (start, end) in list(self._tool_label_spans_by_call_id.items()):
            if skip_tool_call_id and call_id == skip_tool_call_id:
                continue
            if start >= from_index:
                self._tool_label_spans_by_call_id[call_id] = (start + delta, end + delta)

    def _prefix_failed_tool_label(self, tool_call_id: str, label: str, failed_label: str | None = None) -> bool:
        failed_label = failed_label or (label if label.startswith("❌ ") else f"❌ {label}")
        with self._lock:
            if self._closed:
                return False

            buffer = self._buffer
            start = -1
            end = -1
            span = self._tool_label_spans_by_call_id.get(tool_call_id) if tool_call_id else None
            if span is not None:
                span_start, span_end = span
                if 0 <= span_start <= span_end <= len(buffer) and buffer[span_start:span_end] == label:
                    start, end = span_start, span_end

            if start < 0:
                needle = f"\n{label}\n"
                idx = buffer.rfind(needle)
                if idx < 0:
                    return False
                start = idx + 1
                end = start + len(label)

            self._buffer = buffer[:start] + failed_label + buffer[end:]
            delta = len(failed_label) - (end - start)
            if tool_call_id:
                self._tool_label_spans_by_call_id[tool_call_id] = (start, start + len(failed_label))
            self._shift_tool_label_spans(end, delta, skip_tool_call_id=tool_call_id)

        self._has_output = True
        self._schedule_update()
        return True

    def _handle_tool_end(self, event: dict) -> None:
        """Handle tool execution completion."""
        tool_name = str(event.get("toolName", ""))
        is_error = event.get("isError", False)

        tool_call_id = str(event.get("toolCallId", ""))
        args = event.get("args", self._tool_args_by_call_id.get(tool_call_id, {}))

        label = _tool_action_label(tool_name, args)
        if _is_discord_send_file_tool(tool_name):
            self._request_file_stream_resume(tool_call_id, label, is_error)
            if tool_call_id:
                self._tool_args_by_call_id.pop(tool_call_id, None)
            self._stop_tool_heartbeat(tool_call_id)
            self._current_tool_name = ""
            self._current_tool_args = ""
            return

        if is_error:
            failed_label = _tool_failure_label(tool_name, args)
            if not self._prefix_failed_tool_label(tool_call_id, label, failed_label):
                self.append(f"\n{failed_label}\n")
        if tool_call_id:
            self._tool_args_by_call_id.pop(tool_call_id, None)
            self._tool_label_spans_by_call_id.pop(tool_call_id, None)
        self._stop_tool_heartbeat(tool_call_id)
        self._current_tool_name = ""
        self._current_tool_args = ""

    def _start_tool_heartbeat(self, tool_call_id: str, label: str) -> None:
        self._active_tool_call_id = tool_call_id
        self._active_tool_label = label
        self._active_tool_started_at = time.monotonic()

        if self._loop.is_closed():
            return

        def _schedule() -> None:
            if self._closed:
                return
            if self._heartbeat_task is not None and not self._heartbeat_task.done():
                self._heartbeat_task.cancel()
            self._heartbeat_task = asyncio.create_task(
                self._run_tool_heartbeat(tool_call_id, label, self._active_tool_started_at)
            )

        self._loop.call_soon_threadsafe(_schedule)

    def _stop_tool_heartbeat(self, tool_call_id: str = "") -> None:
        if tool_call_id and self._active_tool_call_id and tool_call_id != self._active_tool_call_id:
            return
        self._active_tool_call_id = ""
        self._active_tool_label = ""
        self._active_tool_started_at = 0.0

        def _cancel() -> None:
            heartbeat_task = self._heartbeat_task
            if heartbeat_task is not None and not heartbeat_task.done():
                heartbeat_task.cancel()

        try:
            if asyncio.get_running_loop() is self._loop:
                _cancel()
            elif not self._loop.is_closed():
                self._loop.call_soon_threadsafe(_cancel)
        except RuntimeError:
            if not self._loop.is_closed():
                self._loop.call_soon_threadsafe(_cancel)

    def _request_file_stream_split(self, tool_call_id: str, label: str) -> None:
        if self._loop.is_closed():
            return

        def _schedule() -> None:
            if self._closed:
                return
            task = asyncio.create_task(self._split_for_file_send(tool_call_id, label))
            task_key = tool_call_id or "_no_tool_call_id"
            self._file_split_tasks[task_key] = task

        self._loop.call_soon_threadsafe(_schedule)

    async def _split_for_file_send(self, tool_call_id: str, label: str) -> None:
        if self._closed:
            return
        if tool_call_id:
            if tool_call_id in self._file_tool_call_ids:
                return
            self._file_tool_call_ids.add(tool_call_id)
            self._file_tool_labels[tool_call_id] = label

        self._pause_updates = True
        self._has_output = True

        pending_task = self._pending_task
        if pending_task is not None and not pending_task.done():
            pending_task.cancel()
            await asyncio.gather(pending_task, return_exceptions=True)
        self._pending_task = None

        with self._lock:
            content = self._buffer
            self._buffer = ""

        if content:
            async with self._update_lock:
                await _sync_live_messages(
                    self._channel,
                    self._live_messages,
                    self._sent_chunks,
                    _chunk_text(content),
                )
            self._last_edit_at = time.monotonic()

        self._live_messages = []
        self._sent_chunks = []
        self._tool_label_spans_by_call_id.clear()
        self._needs_text_separator = False
        self._thinking_has_content = False
        self._thinking_line_needs_prefix = True
        self._in_thinking = False

    def _request_file_stream_resume(self, tool_call_id: str, label: str, is_error: bool) -> None:
        if self._loop.is_closed():
            return

        def _schedule() -> None:
            if self._closed:
                return
            asyncio.create_task(self._resume_after_file_send(tool_call_id, label, is_error))

        self._loop.call_soon_threadsafe(_schedule)

    async def _resume_after_file_send(self, tool_call_id: str, label: str, is_error: bool) -> None:
        if self._closed:
            return

        task_key = tool_call_id or "_no_tool_call_id"
        split_task = self._file_split_tasks.pop(task_key, None)
        if split_task is not None and not split_task.done():
            await asyncio.gather(split_task, return_exceptions=True)

        if tool_call_id and tool_call_id in self._file_tool_call_ids:
            self._file_tool_call_ids.discard(tool_call_id)
            label = self._file_tool_labels.pop(tool_call_id, label)

        self._pause_updates = False

        message = f"❌ {label}" if is_error else label
        if message:
            prefix = "\n" if self._buffer else ""
            self.append(f"{prefix}{message}\n")
        else:
            self._schedule_update()

    async def _run_tool_heartbeat(self, tool_call_id: str, label: str, started_at: float) -> None:
        heartbeat_count = 0
        try:
            while not self._closed:
                await asyncio.sleep(DISCORD_TOOL_HEARTBEAT_SECONDS)
                if self._closed or self._active_tool_call_id != tool_call_id:
                    return
                heartbeat_count += 1
                elapsed_seconds = max(1, int(time.monotonic() - started_at))
                elapsed_minutes = max(1, round(elapsed_seconds / 60))
                self.append(
                    f"\n⏳ Still working: {label} ({elapsed_minutes} min elapsed). "
                    f"Send another message to steer, or `{SLASH_CANCEL_COMMAND}` to abort.\n"
                )
                if heartbeat_count >= 20:
                    return
        except asyncio.CancelledError:
            return

    def _schedule_update(self) -> None:
        if self._loop.is_closed() or self._pause_updates:
            return

        def _schedule() -> None:
            if self._closed:
                return
            now = time.monotonic()
            elapsed = now - self._last_edit_at
            delay = max(0.0, self._update_interval_seconds - elapsed)
            if self._pending_task is None or self._pending_task.done():
                self._pending_task = asyncio.create_task(self._run_update_after(delay))

        self._loop.call_soon_threadsafe(_schedule)

    async def _run_update_after(self, delay: float) -> None:
        if delay > 0:
            await asyncio.sleep(delay)
        if self._closed:
            return
        await self._update_message()

    async def _update_message(self) -> None:
        if self._closed or self._pause_updates:
            return
        with self._lock:
            if self._pause_updates:
                return
            content = self._buffer
        async with self._update_lock:
            await _sync_live_messages(
                self._channel,
                self._live_messages,
                self._sent_chunks,
                _chunk_text(content),
            )
        self._last_edit_at = time.monotonic()


async def _sync_live_messages(
    channel: discord.TextChannel,
    live_messages: list[discord.Message],
    sent_chunks: list[str],
    chunks: list[str],
) -> None:
    for idx, chunk in enumerate(chunks):
        if idx >= len(live_messages):
            live_messages.append(await channel.send(chunk))
            sent_chunks.append(chunk)
            continue

        if sent_chunks[idx] != chunk:
            await live_messages[idx].edit(content=chunk)
            sent_chunks[idx] = chunk

    while len(live_messages) > len(chunks):
        stale_message = live_messages.pop()
        sent_chunks.pop()
        try:
            await stale_message.delete()
        except Exception:
            LOGGER.debug("Failed to delete stale Discord response message %s", stale_message.id, exc_info=True)
