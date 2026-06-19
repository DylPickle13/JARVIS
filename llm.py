"""Pi coding agent client with optional streaming support."""

from __future__ import annotations

import atexit
import codecs
import fcntl
import json
import os
import selectors
import shlex
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable

import config


DEFAULT_PI_CODING_AGENT_COMMAND = "pi"
DEFAULT_PI_CODING_AGENT_ARGS = "-p"
DEFAULT_PI_CODING_AGENT_CONTINUE_FLAG = "--continue"
DEFAULT_PI_CODING_AGENT_RPC_TIMEOUT_SECONDS = 1800.0
DEFAULT_DISCORD_PI_MODEL = "omlx-64/Qwen3.6-35B-A3B-6bit"
DEFAULT_DISCORD_PI_THINKING = "high"
VALID_THINKING_LEVELS = {"off", "minimal", "low", "medium", "high", "xhigh"}
PROJECT_ROOT = config.PROJECT_ROOT
DOTENV_PATH = config.DOTENV_PATH
DOTENV_VALUES = config.load_project_env(DOTENV_PATH)
LOGGER = config.get_logger("jarvis.llm")

PI_CODING_AGENT_COMMAND = os.environ.get("PI_CODING_AGENT_COMMAND", "").strip() or DEFAULT_PI_CODING_AGENT_COMMAND
PI_CODING_AGENT_ARGS = os.environ.get("PI_CODING_AGENT_ARGS", "").strip() or DEFAULT_PI_CODING_AGENT_ARGS
PI_CODING_AGENT_PROMPT_FLAG = os.environ.get("PI_CODING_AGENT_PROMPT_FLAG", "").strip()
PI_CODING_AGENT_WORKDIR = os.environ.get("PI_CODING_AGENT_WORKDIR", "").strip()
DISCORD_PI_MODEL = os.environ.get("DISCORD_PI_MODEL", "").strip() or DEFAULT_DISCORD_PI_MODEL


def _normalize_thinking_level(raw_value: str | None, default: str = DEFAULT_DISCORD_PI_THINKING) -> str:
	level = (raw_value or "").strip().lower()
	if level in VALID_THINKING_LEVELS:
		return level
	return default


DISCORD_PI_THINKING = _normalize_thinking_level(os.environ.get("DISCORD_PI_THINKING", ""))


def _parse_model_options(raw_value: str, current_model: str) -> tuple[str, ...]:
	models: list[str] = []
	for raw_model in raw_value.split(","):
		model = raw_model.strip()
		if model and model not in models:
			models.append(model)

	if current_model and current_model not in models:
		models.insert(0, current_model)

	return tuple(models)


DISCORD_PI_MODEL_OPTIONS = _parse_model_options(
	DOTENV_VALUES.get("DISCORD_PI_MODEL_OPTIONS", os.environ.get("DISCORD_PI_MODEL_OPTIONS", "")),
	DISCORD_PI_MODEL,
)


PI_CODING_AGENT_RPC_TIMEOUT_SECONDS = config.get_float_env(
	"PI_CODING_AGENT_RPC_TIMEOUT_SECONDS",
	DEFAULT_PI_CODING_AGENT_RPC_TIMEOUT_SECONDS,
	minimum=1.0,
)

PI_SESSION_STATUS_FILE = Path(
	os.environ.get("JARVIS_PI_SESSION_STATUS_FILE", PROJECT_ROOT / ".pi" / "runtime" / "pi-rpc-sessions.json")
).expanduser()
PI_SESSION_DELETE_TRASH_TIMEOUT_SECONDS = 10.0
_PI_SESSION_STATUS_LOCK = threading.Lock()
_PI_SESSION_STATUS_IDS: set[str] = set()


def _now_iso() -> str:
	return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _pid_is_alive(pid: object) -> bool:
	try:
		numeric_pid = int(pid)
	except (TypeError, ValueError):
		return False
	if numeric_pid <= 0:
		return False
	try:
		os.kill(numeric_pid, 0)
		return True
	except OSError:
		return False


def _update_pi_session_status(session_id: str, patch: dict[str, Any] | None = None, *, remove: bool = False) -> None:
	"""Publish active Pi prompt generation state for the room dashboard."""
	if not session_id:
		return

	try:
		PI_SESSION_STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
		lock_path = PI_SESSION_STATUS_FILE.with_suffix(PI_SESSION_STATUS_FILE.suffix + ".lock")
		with _PI_SESSION_STATUS_LOCK:
			with lock_path.open("a+", encoding="utf-8") as lock_file:
				fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
				try:
					try:
						payload = json.loads(PI_SESSION_STATUS_FILE.read_text(encoding="utf-8"))
					except (FileNotFoundError, json.JSONDecodeError):
						payload = {"version": 1, "sessions": {}}

					sessions = payload.get("sessions")
					if not isinstance(sessions, dict):
						sessions = {}

					for stale_id, stale_session in list(sessions.items()):
						if not isinstance(stale_session, dict) or not _pid_is_alive(stale_session.get("pid")):
							sessions.pop(stale_id, None)

					if remove:
						sessions.pop(session_id, None)
						_PI_SESSION_STATUS_IDS.discard(session_id)
					else:
						now = _now_iso()
						entry = sessions.get(session_id) if isinstance(sessions.get(session_id), dict) else {}
						entry.update({"id": session_id, "pid": os.getpid(), "updatedAt": now})
						entry.update(patch or {})
						sessions[session_id] = entry
						_PI_SESSION_STATUS_IDS.add(session_id)

					payload = {"version": 1, "updatedAt": _now_iso(), "sessions": sessions}
					tmp_path = PI_SESSION_STATUS_FILE.with_suffix(PI_SESSION_STATUS_FILE.suffix + ".tmp")
					tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
					tmp_path.replace(PI_SESSION_STATUS_FILE)
				finally:
					fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
	except Exception:
		LOGGER.debug("Failed to update Pi session status file", exc_info=True)


def _cleanup_pi_session_status() -> None:
	for session_id in list(_PI_SESSION_STATUS_IDS):
		_update_pi_session_status(session_id, remove=True)


atexit.register(_cleanup_pi_session_status)


class PiRpcCancelledError(RuntimeError):
	"""Raised when an active Pi RPC operation is cancelled by the user."""


def _resolve_workdir() -> Path | None:
	if not PI_CODING_AGENT_WORKDIR:
		return None

	target_path = Path(PI_CODING_AGENT_WORKDIR).expanduser()
	if not target_path.is_dir():
		raise NotADirectoryError(f"PI_CODING_AGENT_WORKDIR is not a directory: {target_path}")

	return target_path


def _resolve_command(prompt: str) -> list[str]:
	command = shlex.split(PI_CODING_AGENT_COMMAND)
	if not command:
		raise ValueError("PI_CODING_AGENT_COMMAND resolved to an empty command.")

	extra_args = shlex.split(PI_CODING_AGENT_ARGS) if PI_CODING_AGENT_ARGS else []
	command.extend(extra_args)
	
	# Only append --continue for the pi command
	is_pi_command = any("pi" in part for part in command)
	if is_pi_command:
		command.append(DEFAULT_PI_CODING_AGENT_CONTINUE_FLAG)

	if PI_CODING_AGENT_PROMPT_FLAG:
		command.extend([PI_CODING_AGENT_PROMPT_FLAG, prompt])
		return command

	command.append(prompt)
	return command


def _stream_process_output(
	process: subprocess.Popen[bytes],
	*,
	on_stdout: Callable[[str], None] | None,
) -> tuple[str, str]:
	stdout_chunks: list[str] = []
	stderr_chunks: list[str] = []
	stdout_decoder = codecs.getincrementaldecoder("utf-8")()
	stderr_decoder = codecs.getincrementaldecoder("utf-8")()

	selector = selectors.DefaultSelector()
	if process.stdout is not None:
		os.set_blocking(process.stdout.fileno(), False)
		selector.register(process.stdout, selectors.EVENT_READ, "stdout")
	if process.stderr is not None:
		os.set_blocking(process.stderr.fileno(), False)
		selector.register(process.stderr, selectors.EVENT_READ, "stderr")

	while selector.get_map():
		for key, _ in selector.select(timeout=0.1):
			stream = key.fileobj
			data = stream.read(4096)
			if not data:
				selector.unregister(stream)
				continue
			if key.data == "stdout":
				text = stdout_decoder.decode(data)
				if text:
					stdout_chunks.append(text)
					if on_stdout is not None:
						on_stdout(text)
			else:
				text = stderr_decoder.decode(data)
				if text:
					stderr_chunks.append(text)

	stdout_tail = stdout_decoder.decode(b"", final=True)
	if stdout_tail:
		stdout_chunks.append(stdout_tail)
		if on_stdout is not None:
			on_stdout(stdout_tail)

	stderr_tail = stderr_decoder.decode(b"", final=True)
	if stderr_tail:
		stderr_chunks.append(stderr_tail)

	return "".join(stdout_chunks), "".join(stderr_chunks)


def run_pi_coding_agent(
	prompt: str,
	*,
	on_delta: Callable[[str], None] | None = None,
) -> dict[str, object]:
	if not isinstance(prompt, str) or not prompt.strip():
		raise ValueError("Prompt cannot be empty.")

	command = _resolve_command(prompt)
	workdir = _resolve_workdir()

	try:
		process = subprocess.Popen(
			command,
			stdin=None,
			stdout=subprocess.PIPE,
			stderr=subprocess.PIPE,
			cwd=str(workdir) if workdir else None,
			bufsize=0,
		)
	except OSError as exc:
		raise RuntimeError(f"Failed to run Pi coding agent command: {exc}") from exc

	stdout_text, stderr_text = _stream_process_output(process, on_stdout=on_delta)

	exit_code = process.wait()

	return {
		"text": stdout_text,
		"stderr": stderr_text,
		"exit_code": exit_code,
	}


def select_response_text(result: dict[str, object]) -> str:
	stdout_text = result.get("text")
	stderr_text = result.get("stderr")
	exit_code = result.get("exit_code")

	stdout_value = stdout_text.strip() if isinstance(stdout_text, str) else ""
	stderr_value = stderr_text.strip() if isinstance(stderr_text, str) else ""
	if isinstance(exit_code, int) and exit_code != 0:
		return stderr_value or stdout_value
	return stdout_value or stderr_value


def _delete_saved_pi_session_file(session_file: str | Path) -> dict[str, Any]:
	"""Delete a persisted Pi session file, preferring the OS trash when available."""
	path = Path(session_file).expanduser()
	path_text = str(path)
	base_result: dict[str, Any] = {"sessionFile": path_text}
	if not path.exists():
		return {**base_result, "deleted": False, "method": "missing", "reason": "missing"}
	if not path.is_file():
		raise RuntimeError(f"Refusing to delete non-file Pi session path: {path}")

	trash_error = ""
	try:
		trash_args = ["trash"]
		if path_text.startswith("-"):
			trash_args.append("--")
		trash_args.append(path_text)
		completed = subprocess.run(
			trash_args,
			capture_output=True,
			text=True,
			timeout=PI_SESSION_DELETE_TRASH_TIMEOUT_SECONDS,
		)
		if completed.returncode == 0 or not path.exists():
			return {**base_result, "deleted": True, "method": "trash"}
		trash_error = (completed.stderr or completed.stdout or f"trash exited with {completed.returncode}").strip()
	except FileNotFoundError:
		trash_error = "trash command not found"
	except subprocess.TimeoutExpired:
		trash_error = f"trash timed out after {PI_SESSION_DELETE_TRASH_TIMEOUT_SECONDS:g}s"
	except OSError as exc:
		trash_error = str(exc)

	try:
		path.unlink()
		return {**base_result, "deleted": True, "method": "unlink", "trashError": trash_error}
	except FileNotFoundError:
		return {**base_result, "deleted": True, "method": "unlink", "trashError": trash_error}
	except OSError as exc:
		detail = str(exc)
		if trash_error:
			detail = f"{detail} (trash: {trash_error[:200]})"
		raise RuntimeError(f"Failed to delete Pi session file {path}: {detail}") from exc


def _strip_forced_rpc_args(command: list[str]) -> list[str]:
	"""Remove flags that conflict with the Discord bot's required RPC/session settings."""
	flags_with_values = {"--model", "--provider", "--thinking", "--models"}
	flag_prefixes = tuple(f"{flag}=" for flag in flags_with_values)
	flags_without_values = {"--no-session"}
	stripped: list[str] = []
	skip_next = False

	for arg in command:
		if skip_next:
			skip_next = False
			continue

		if arg in flags_with_values:
			skip_next = True
			continue

		if arg in flags_without_values:
			continue

		if arg.startswith(flag_prefixes):
			continue

		stripped.append(arg)

	return stripped


# RPC Mode Support for Real-Time Streaming
# ==========================================


class PiRpcClient:
	"""Manages Pi agent in RPC mode for real-time event streaming."""

	def __init__(
		self,
		*,
		on_event: Callable[[dict[str, Any]], None] | None = None,
		workdir: Path | None = None,
		model: str | None = None,
		discord_channel_id: str | None = None,
		discord_channel_name: str | None = None,
		discord_guild_id: str | None = None,
		thinking: str | None = None,
		append_system_prompt: str | None = None,
	) -> None:
		"""Initialize RPC client.
		
		Args:
			on_event: Callback for each JSON event from the agent (thinking, tools, text deltas, etc.)
			workdir: Working directory for the Pi agent
		"""
		self.on_event = on_event
		self.workdir = workdir
		self.model = (model or DISCORD_PI_MODEL).strip() or DISCORD_PI_MODEL
		self.thinking = _normalize_thinking_level(thinking, DISCORD_PI_THINKING)
		self.append_system_prompt = (append_system_prompt or "").strip()
		self.discord_channel_id = (discord_channel_id or "").strip()
		self.discord_channel_name = (discord_channel_name or "").strip()
		self.discord_guild_id = (discord_guild_id or "").strip()
		self.process: subprocess.Popen[bytes] | None = None
		self._read_thread: threading.Thread | None = None
		self._stderr_thread: threading.Thread | None = None
		self._stop_reading = False
		self._input_lock = threading.Lock()
		self._stderr_chunks: list[str] = []

	def start(self) -> None:
		"""Start the Pi agent in RPC mode."""
		command = shlex.split(PI_CODING_AGENT_COMMAND)
		if not command:
			raise ValueError("PI_CODING_AGENT_COMMAND resolved to an empty command.")

		# Discord requests must always use RPC sessions and the selected Discord
		# model regardless of the user's Pi defaults or conflicting flags
		# accidentally included in PI_CODING_AGENT_COMMAND.
		command = _strip_forced_rpc_args(command)
		command.extend([
			"--mode",
			"rpc",
			"--model",
			self.model,
			"--thinking",
			self.thinking,
		])
		if self.append_system_prompt:
			command.extend(["--append-system-prompt", self.append_system_prompt])
		
		env = os.environ.copy()
		if self.discord_channel_id:
			env["JARVIS_DISCORD_CONTEXT"] = "1"
			env["JARVIS_DISCORD_CHANNEL_ID"] = self.discord_channel_id
			if self.discord_channel_name:
				env["JARVIS_DISCORD_CHANNEL_NAME"] = self.discord_channel_name
			if self.discord_guild_id:
				env["JARVIS_DISCORD_GUILD_ID"] = self.discord_guild_id

		try:
			LOGGER.info(
				"Starting Pi RPC client model=%s thinking=%s workdir=%s discord_channel_id=%s",
				self.model,
				self.thinking,
				self.workdir or Path.cwd(),
				self.discord_channel_id or "-",
			)
			self.process = subprocess.Popen(
				command,
				stdin=subprocess.PIPE,
				stdout=subprocess.PIPE,
				stderr=subprocess.PIPE,
				cwd=str(self.workdir) if self.workdir else None,
				bufsize=0,
				env=env,
			)
		except OSError as exc:
			raise RuntimeError(f"Failed to start Pi RPC mode: {exc}") from exc

		# Start background threads to read events and drain stderr. The RPC process
		# stays alive for more commands after agent_end, so callers must wait for
		# agent_end rather than process exit.
		self._stop_reading = False
		self._read_thread = threading.Thread(target=self._read_events_loop, daemon=True)
		self._read_thread.start()
		self._stderr_thread = threading.Thread(target=self._read_stderr_loop, daemon=True)
		self._stderr_thread.start()

	def is_running(self) -> bool:
		"""Return True when the RPC subprocess is alive."""
		return self.process is not None and self.process.poll() is None

	def send_prompt(self, message: str, *, images: list[dict[str, str]] | None = None) -> None:
		"""Send a prompt to the agent."""
		cmd: dict[str, Any] = {"id": "discord-prompt", "type": "prompt", "message": message}
		if images:
			cmd["images"] = images
		self._send_command(cmd)

	def send_steer(self, message: str, *, images: list[dict[str, str]] | None = None) -> None:
		"""Queue a steering message for the active agent turn."""
		cmd: dict[str, Any] = {"id": "discord-steer", "type": "steer", "message": message}
		if images:
			cmd["images"] = images
		self._send_command(cmd)

	def send_new_session(self) -> None:
		"""Start a fresh JARVIS session in the existing RPC process."""
		self._send_command({"id": "discord-new-session", "type": "new_session"})

	def send_compact(self, *, custom_instructions: str | None = None) -> None:
		"""Manually compact the current JARVIS session in the existing RPC process."""
		cmd: dict[str, Any] = {"id": "discord-compact", "type": "compact"}
		if custom_instructions:
			cmd["customInstructions"] = custom_instructions
		self._send_command(cmd)

	def send_get_session_stats(self) -> None:
		"""Request current JARVIS session statistics from the existing RPC process."""
		self._send_command({"id": "discord-get-session-stats", "type": "get_session_stats"})

	def send_get_state(self) -> None:
		"""Request current JARVIS session state from the existing RPC process."""
		self._send_command({"id": "discord-get-state", "type": "get_state"})

	def send_set_auto_compaction(self, *, enabled: bool = True) -> None:
		"""Enable or disable Pi's automatic context compaction for this RPC session."""
		self._send_command({"id": "discord-set-auto-compaction", "type": "set_auto_compaction", "enabled": enabled})

	def send_set_thinking_level(self, *, level: str) -> None:
		"""Switch Pi's thinking level for the current RPC session."""
		self._send_command({"id": "discord-set-thinking-level", "type": "set_thinking_level", "level": level})

	def send_set_model(self, *, provider: str, model_id: str) -> None:
		"""Switch the active model without replacing the current Pi session."""
		self._send_command(
			{
				"id": "discord-set-model",
				"type": "set_model",
				"provider": provider,
				"modelId": model_id,
			}
		)

	def send_abort(self) -> None:
		"""Abort current agent operation."""
		self._send_command({"id": "discord-abort", "type": "abort"})

	def _send_command(self, cmd: dict[str, Any]) -> None:
		"""Send a JSON command to the agent."""
		if self.process is None or self.process.stdin is None:
			return

		with self._input_lock:
			try:
				json_str = json.dumps(cmd)
				self.process.stdin.write((json_str + "\n").encode("utf-8"))
				self.process.stdin.flush()
			except Exception:
				LOGGER.exception("Failed to send Pi RPC command type=%s", cmd.get("type"))

	def _read_stderr_loop(self) -> None:
		"""Drain stderr so the RPC process cannot block on a full stderr pipe."""
		if self.process is None or self.process.stderr is None:
			return

		decoder = codecs.getincrementaldecoder("utf-8")()
		try:
			while not self._stop_reading:
				chunk = self.process.stderr.read(4096)
				if not chunk:
					break
				text = decoder.decode(chunk)
				if text:
					self._stderr_chunks.append(text)
		except Exception:
			LOGGER.debug("Pi RPC stderr reader stopped with an exception", exc_info=True)
		finally:
			tail = decoder.decode(b"", final=True)
			if tail:
				self._stderr_chunks.append(tail)

	def stderr_text(self) -> str:
		"""Return stderr captured from the RPC process."""
		return "".join(self._stderr_chunks)

	def _read_events_loop(self) -> None:
		"""Read and parse JSON events from agent stdout."""
		if self.process is None or self.process.stdout is None:
			return

		decoder = codecs.getincrementaldecoder("utf-8")()
		buffer = ""

		try:
			while not self._stop_reading:
				chunk = self.process.stdout.read(4096)
				if not chunk:
					break

				text = decoder.decode(chunk)
				if not text:
					continue

				buffer += text

				# Process complete lines
				while "\n" in buffer:
					line_end = buffer.index("\n")
					line = buffer[:line_end]
					buffer = buffer[line_end + 1:]

					# Strip trailing \r if present
					if line.endswith("\r"):
						line = line[:-1]

					if not line:
						continue

					try:
						event = json.loads(line)
						if self.on_event:
							self.on_event(event)
					except json.JSONDecodeError:
						LOGGER.warning("Failed to parse Pi RPC JSON event line: %r", line[:500], exc_info=True)

		except Exception:
			LOGGER.exception("Error in Pi RPC event reader")
		finally:
			# Process any remaining buffer
			final_text = decoder.decode(b"", final=True)
			if final_text:
				buffer += final_text
				for line in buffer.split("\n"):
					line = line.rstrip("\r")
					if line:
						try:
							event = json.loads(line)
							if self.on_event:
								self.on_event(event)
						except json.JSONDecodeError:
							LOGGER.debug("Dropped trailing unparsable Pi RPC event line: %r", line[:500], exc_info=True)

	def stop(self) -> None:
		"""Stop the RPC client and terminate the agent."""
		self._stop_reading = True

		if self.process is not None and self.process.stdin is not None:
			try:
				self.process.stdin.close()
			except Exception:
				LOGGER.debug("Failed to close Pi RPC stdin", exc_info=True)

		if self.process is not None:
			try:
				self.process.terminate()
				self.process.wait(timeout=5)
			except Exception:
				LOGGER.debug("Pi RPC process did not terminate cleanly; killing", exc_info=True)
				try:
					self.process.kill()
				except Exception:
					LOGGER.debug("Failed to kill Pi RPC process", exc_info=True)

		if self._read_thread is not None:
			self._read_thread.join(timeout=5)
		if self._stderr_thread is not None:
			self._stderr_thread.join(timeout=5)


class PiRpcSession:
	"""Persistent Pi RPC conversation that can handle multiple Discord messages."""

	def __init__(
		self,
		*,
		workdir: Path | None = None,
		model: str | None = None,
		discord_channel_id: str | None = None,
		discord_channel_name: str | None = None,
		discord_guild_id: str | None = None,
		thinking: str | None = None,
		append_system_prompt: str | None = None,
	) -> None:
		self.workdir = workdir if workdir is not None else _resolve_workdir()
		self.model = (model or DISCORD_PI_MODEL).strip() or DISCORD_PI_MODEL
		self.thinking = _normalize_thinking_level(thinking, DISCORD_PI_THINKING)
		self.append_system_prompt = (append_system_prompt or "").strip()
		self.discord_channel_id = (discord_channel_id or "").strip()
		self.discord_channel_name = (discord_channel_name or "").strip()
		self.discord_guild_id = (discord_guild_id or "").strip()
		self._operation_lock = threading.Lock()
		self._client: PiRpcClient | None = None
		self._active_command = ""
		self._active_on_event: Callable[[dict[str, Any]], None] | None = None
		self._active_done_event: threading.Event | None = None
		self._active_errors: list[str] = []
		self._active_response_data: Any = None
		self._active_cancel_requested = False
		self._status_id = f"{os.getpid()}:{id(self)}:{time.time_ns()}"
		self._last_activity_monotonic: float | None = None
		self._last_session_file = ""
		self._last_session_id = ""

	def _mark_prompt_generating(self) -> None:
		_update_pi_session_status(
			self._status_id,
			{
				"active": True,
				"command": "prompt",
				"model": self.model,
				"thinking": self.thinking,
				"workdir": str(self.workdir) if self.workdir is not None else "",
				"channelId": self.discord_channel_id,
				"channelName": self.discord_channel_name,
				"guildId": self.discord_guild_id,
				"startedAt": _now_iso(),
			},
		)

	def _clear_prompt_generating(self) -> None:
		_update_pi_session_status(self._status_id, remove=True)

	def _mark_activity(self) -> None:
		self._last_activity_monotonic = time.monotonic()

	def _remember_session_metadata(self, data: dict[str, Any]) -> None:
		session_file = data.get("sessionFile")
		if isinstance(session_file, str) and session_file.strip():
			self._last_session_file = session_file.strip()
		session_id = data.get("sessionId")
		if isinstance(session_id, str) and session_id.strip():
			self._last_session_id = session_id.strip()

	def seconds_since_last_activity(self) -> float | None:
		"""Return seconds since the last completed/sent RPC activity, or None if unused."""
		last_activity = self._last_activity_monotonic
		if last_activity is None:
			return None
		return max(0.0, time.monotonic() - last_activity)

	def set_discord_channel_context(
		self,
		*,
		discord_channel_id: str | None = None,
		discord_channel_name: str | None = None,
		discord_guild_id: str | None = None,
	) -> None:
		"""Attach the Discord channel context used by Pi tools inside this session."""
		new_channel_id = (discord_channel_id or self.discord_channel_id or "").strip()
		new_channel_name = (discord_channel_name or self.discord_channel_name or "").strip()
		new_guild_id = (discord_guild_id or self.discord_guild_id or "").strip()
		restart_needed = new_channel_id != self.discord_channel_id or new_guild_id != self.discord_guild_id
		self.discord_channel_id = new_channel_id
		self.discord_channel_name = new_channel_name
		self.discord_guild_id = new_guild_id
		if restart_needed and self._client is not None:
			client = self._client
			self._client = None
			client.stop()

	def _ensure_client(self) -> PiRpcClient:
		if self._client is not None and self._client.is_running():
			return self._client

		if self._client is not None:
			self._client.stop()

		self._client = PiRpcClient(
			on_event=self._handle_event,
			workdir=self.workdir,
			model=self.model,
			thinking=self.thinking,
			append_system_prompt=self.append_system_prompt,
			discord_channel_id=self.discord_channel_id,
			discord_channel_name=self.discord_channel_name,
			discord_guild_id=self.discord_guild_id,
		)
		self._client.start()
		# Discord-managed Pi sessions should always keep automatic context
		# compaction enabled, regardless of the user's interactive Pi defaults.
		self._client.send_set_auto_compaction(enabled=True)
		return self._client

	@staticmethod
	def _final_agent_error_from_event(event: dict[str, Any]) -> str | None:
		"""Return the final assistant error from an agent_end event, if any."""
		messages = event.get("messages")
		if not isinstance(messages, list):
			return None

		for message in reversed(messages):
			if not isinstance(message, dict) or message.get("role") != "assistant":
				continue
			if message.get("stopReason") in {"error", "aborted"}:
				error_message = message.get("errorMessage")
				if isinstance(error_message, str) and error_message.strip():
					return error_message.strip()
				return "Assistant message failed."
			return None

		return None

	def _handle_event(self, event: dict[str, Any]) -> None:
		callback = self._active_on_event
		done_event = self._active_done_event
		command = self._active_command

		if callback is not None:
			try:
				callback(event)
			except Exception as exc:
				self._active_errors.append(f"Discord stream callback failed: {exc}")
				if done_event is not None:
					done_event.set()
				return

		event_type = event.get("type")
		if command == "prompt":
			if event_type == "agent_end":
				if event.get("willRetry", False):
					# Pi may emit agent_end for a retryable failed model attempt, then
					# continue the same prompt via auto-retry. Do not release the
					# Discord channel lock or close the stream until the final agent_end.
					return

				final_error = self._final_agent_error_from_event(event)
				if final_error:
					self._active_errors.append(final_error)
				if done_event is not None:
					done_event.set()
			elif event_type == "response" and event.get("command") == "prompt" and not event.get("success", False):
				error = event.get("error")
				self._active_errors.append(str(error) if error else "Prompt was rejected by Pi RPC.")
				if done_event is not None:
					done_event.set()
		elif command and event_type == "response" and event.get("command") == command:
			if event.get("success", False):
				self._active_response_data = event.get("data")
			else:
				error = event.get("error")
				self._active_errors.append(str(error) if error else f"Pi RPC {command} command failed.")
			if done_event is not None:
				done_event.set()

	def _wait_for_done(self, done_event: threading.Event, timeout_seconds: float | None) -> None:
		deadline = None if timeout_seconds is None else time.monotonic() + timeout_seconds

		while not done_event.is_set():
			client = self._client
			if client is not None and client.process is not None and client.process.poll() is not None:
				break

			if deadline is None:
				done_event.wait(timeout=0.1)
				continue

			remaining = deadline - time.monotonic()
			if remaining <= 0:
				raise TimeoutError(f"Pi RPC agent timed out after {timeout_seconds:.0f} seconds.")
			done_event.wait(timeout=min(0.1, remaining))

		if not done_event.is_set():
			client = self._client
			exit_code = client.process.returncode if client is not None and client.process is not None else None
			stderr_text = client.stderr_text().strip() if client is not None else ""
			details = f" with exit code {exit_code}" if exit_code is not None else ""
			raise RuntimeError(f"Pi RPC agent exited before completing{details}. {stderr_text}".strip())

	def run_prompt(
		self,
		prompt: str,
		*,
		images: list[dict[str, str]] | None = None,
		on_event: Callable[[dict[str, Any]], None] | None = None,
		timeout_seconds: float | None = PI_CODING_AGENT_RPC_TIMEOUT_SECONDS,
	) -> None:
		"""Send one prompt through the persistent session and wait for agent_end."""
		if not isinstance(prompt, str) or not prompt.strip():
			raise ValueError("Prompt cannot be empty.")

		with self._operation_lock:
			done_event = threading.Event()
			self._active_command = "prompt"
			self._active_on_event = on_event
			self._active_done_event = done_event
			self._active_errors = []
			self._active_response_data = None
			self._active_cancel_requested = False

			try:
				self._mark_prompt_generating()
				client = self._ensure_client()
				if self._active_cancel_requested:
					raise PiRpcCancelledError("JARVIS job was cancelled.")
				client.send_set_auto_compaction(enabled=True)
				client.send_prompt(prompt, images=images)
				try:
					self._wait_for_done(done_event, timeout_seconds)
				except TimeoutError:
					client.send_abort()
					self.stop()
					raise

				if self._active_cancel_requested:
					raise PiRpcCancelledError("JARVIS job was cancelled.")
				if self._active_errors:
					raise RuntimeError(self._active_errors[-1])
			finally:
				self._clear_prompt_generating()
				self._mark_activity()
				self._active_command = ""
				self._active_on_event = None
				self._active_done_event = None

	def _new_session_locked(
		self,
		*,
		on_event: Callable[[dict[str, Any]], None] | None = None,
		timeout_seconds: float | None = PI_CODING_AGENT_RPC_TIMEOUT_SECONDS,
	) -> dict[str, Any]:
		"""Tell JARVIS to start a fresh session. Caller must hold _operation_lock."""
		done_event = threading.Event()
		self._active_command = "new_session"
		self._active_on_event = on_event
		self._active_done_event = done_event
		self._active_errors = []
		self._active_response_data = None
		self._active_cancel_requested = False

		try:
			client = self._ensure_client()
			if self._active_cancel_requested:
				raise PiRpcCancelledError("JARVIS session switch was cancelled.")
			client.send_new_session()
			self._wait_for_done(done_event, timeout_seconds)

			if not self._active_cancel_requested:
				client.send_set_auto_compaction(enabled=True)

			if self._active_cancel_requested:
				raise PiRpcCancelledError("JARVIS session switch was cancelled.")
			if self._active_errors:
				raise RuntimeError(self._active_errors[-1])
			data = self._active_response_data
			self._mark_activity()
			return data if isinstance(data, dict) else {}
		finally:
			self._active_command = ""
			self._active_on_event = None
			self._active_done_event = None

	def new_session(
		self,
		*,
		on_event: Callable[[dict[str, Any]], None] | None = None,
		timeout_seconds: float | None = PI_CODING_AGENT_RPC_TIMEOUT_SECONDS,
	) -> dict[str, Any]:
		"""Tell JARVIS to start a fresh session, preserving the same RPC subprocess."""
		with self._operation_lock:
			return self._new_session_locked(on_event=on_event, timeout_seconds=timeout_seconds)

	def start_new_session_if_idle(
		self,
		idle_seconds: float,
		*,
		on_event: Callable[[dict[str, Any]], None] | None = None,
		timeout_seconds: float | None = PI_CODING_AGENT_RPC_TIMEOUT_SECONDS,
	) -> bool:
		"""Run /new when an existing live RPC session has been idle long enough."""
		try:
			threshold = float(idle_seconds)
		except (TypeError, ValueError):
			return False
		if threshold <= 0:
			return False

		with self._operation_lock:
			last_activity = self._last_activity_monotonic
			if last_activity is None or time.monotonic() - last_activity < threshold:
				return False

			client = self._client
			if client is None:
				return False
			if not client.is_running():
				self._client = None
				client.stop()
				return False

			self._new_session_locked(on_event=on_event, timeout_seconds=timeout_seconds)
			return True

	def get_state(
		self,
		*,
		timeout_seconds: float | None = PI_CODING_AGENT_RPC_TIMEOUT_SECONDS,
	) -> dict[str, Any]:
		"""Return current session state from the persistent RPC process."""
		with self._operation_lock:
			done_event = threading.Event()
			self._active_command = "get_state"
			self._active_on_event = None
			self._active_done_event = done_event
			self._active_errors = []
			self._active_response_data = None
			self._active_cancel_requested = False

			try:
				client = self._ensure_client()
				client.send_get_state()
				self._wait_for_done(done_event, timeout_seconds)
				if self._active_errors:
					raise RuntimeError(self._active_errors[-1])
				data = self._active_response_data
				if isinstance(data, dict):
					self._remember_session_metadata(data)
					self._mark_activity()
					return data
				self._mark_activity()
				return {}
			finally:
				self._active_command = ""
				self._active_on_event = None
				self._active_done_event = None

	def get_session_stats(
		self,
		*,
		timeout_seconds: float | None = PI_CODING_AGENT_RPC_TIMEOUT_SECONDS,
	) -> dict[str, Any]:
		"""Return current session statistics from the persistent RPC process."""
		with self._operation_lock:
			done_event = threading.Event()
			self._active_command = "get_session_stats"
			self._active_on_event = None
			self._active_done_event = done_event
			self._active_errors = []
			self._active_response_data = None
			self._active_cancel_requested = False

			try:
				client = self._ensure_client()
				client.send_get_session_stats()
				self._wait_for_done(done_event, timeout_seconds)
				if self._active_errors:
					raise RuntimeError(self._active_errors[-1])
				data = self._active_response_data
				if isinstance(data, dict):
					self._remember_session_metadata(data)
					self._mark_activity()
					return data
				self._mark_activity()
				return {}
			finally:
				self._active_command = ""
				self._active_on_event = None
				self._active_done_event = None

	def delete_current_session_file(
		self,
		*,
		timeout_seconds: float | None = PI_CODING_AGENT_RPC_TIMEOUT_SECONDS,
	) -> dict[str, Any]:
		"""Stop this RPC process and delete its current persisted Pi session file."""
		if not self._operation_lock.acquire(blocking=False):
			return {"deleted": False, "busy": True, "reason": "active_operation"}

		state: dict[str, Any] = {}
		had_live_session = False
		client: PiRpcClient | None = None
		try:
			client = self._client
			if client is None or not client.is_running():
				if client is not None:
					client.stop()
					self._client = None
				if self._last_session_file:
					state = {"sessionFile": self._last_session_file}
					if self._last_session_id:
						state["sessionId"] = self._last_session_id
			else:
				had_live_session = True
				done_event = threading.Event()
				self._active_command = "get_state"
				self._active_on_event = None
				self._active_done_event = done_event
				self._active_errors = []
				self._active_response_data = None
				self._active_cancel_requested = False

				try:
					client.send_get_state()
					self._wait_for_done(done_event, timeout_seconds)
					if self._active_errors:
						raise RuntimeError(self._active_errors[-1])
					data = self._active_response_data
					state = data if isinstance(data, dict) else {}
					self._remember_session_metadata(state)
				finally:
					self._active_command = ""
					self._active_on_event = None
					self._active_done_event = None

				self._clear_prompt_generating()
				self._active_cancel_requested = True
				self._client = None
				client.stop()
				client = None
		finally:
			if client is not None and client is self._client and not client.is_running():
				self._client = None
				client.stop()
			self._operation_lock.release()

		session_file = str(state.get("sessionFile") or self._last_session_file or "").strip()
		if not session_file:
			self._mark_activity()
			return {
				"deleted": False,
				"reason": "missing_session_file" if had_live_session else "no_live_session",
			}

		result = _delete_saved_pi_session_file(session_file)
		session_id = str(state.get("sessionId") or self._last_session_id or "").strip()
		if session_id:
			result["sessionId"] = session_id
		message_count = state.get("messageCount")
		if isinstance(message_count, (int, float)):
			result["messageCount"] = int(message_count)
		self._mark_activity()
		return result

	def compact(
		self,
		*,
		custom_instructions: str | None = None,
		on_event: Callable[[dict[str, Any]], None] | None = None,
		timeout_seconds: float | None = PI_CODING_AGENT_RPC_TIMEOUT_SECONDS,
	) -> dict[str, Any]:
		"""Manually compact the current session, preserving the same RPC subprocess."""
		instructions = custom_instructions.strip() if isinstance(custom_instructions, str) else ""
		with self._operation_lock:
			done_event = threading.Event()
			self._active_command = "compact"
			self._active_on_event = on_event
			self._active_done_event = done_event
			self._active_errors = []
			self._active_response_data = None
			self._active_cancel_requested = False

			try:
				client = self._ensure_client()
				if self._active_cancel_requested:
					raise PiRpcCancelledError("JARVIS compaction was cancelled.")
				client.send_compact(custom_instructions=instructions or None)
				try:
					self._wait_for_done(done_event, timeout_seconds)
				except TimeoutError:
					client.send_abort()
					self.stop()
					raise

				if self._active_cancel_requested:
					raise PiRpcCancelledError("JARVIS compaction was cancelled.")
				if self._active_errors:
					raise RuntimeError(self._active_errors[-1])
				data = self._active_response_data
				self._mark_activity()
				return data if isinstance(data, dict) else {}
			finally:
				self._active_command = ""
				self._active_on_event = None
				self._active_done_event = None

	def steer_prompt(self, prompt: str, *, images: list[dict[str, str]] | None = None) -> bool:
		"""Queue a steering message for the currently running prompt.

		This intentionally does not acquire ``_operation_lock`` because the normal
		``run_prompt`` path holds that lock until ``agent_end``. It is used by the
		Discord bot to mimic Pi terminal steering: while an assistant turn is
		streaming, new user input is sent to RPC as ``type=steer`` instead of being
		rejected as a concurrent prompt.
		"""
		if not isinstance(prompt, str) or not prompt.strip():
			raise ValueError("Prompt cannot be empty.")

		if self._active_command != "prompt" or self._active_done_event is None:
			raise RuntimeError("There is no active prompt available for steering.")

		client = self._client
		if client is None or not client.is_running():
			raise RuntimeError("The Pi RPC session is not running.")

		client.send_steer(prompt, images=images)
		self._mark_activity()
		return True

	def set_model(self, model: str) -> bool:
		"""Select the model for future prompts without starting a fresh Pi session."""
		selected_model = model.strip()
		if not selected_model:
			raise ValueError("Model cannot be empty.")

		if "/" not in selected_model:
			raise ValueError("Model must be configured as provider/model-id for in-session switching.")
		provider, model_id = selected_model.split("/", 1)
		provider = provider.strip()
		model_id = model_id.strip()
		if not provider or not model_id:
			raise ValueError("Model must be configured as provider/model-id for in-session switching.")

		with self._operation_lock:
			if selected_model == self.model:
				return False

			# If no RPC process exists yet, just remember the selected model. The
			# first prompt will start Pi with this model and, since there is no active
			# conversation in this wrapper yet, no session history is lost.
			if self._client is None:
				self.model = selected_model
				return True

			if not self._client.is_running():
				self._client.stop()
				self._client = None
				self.model = selected_model
				return True

			done_event = threading.Event()
			self._active_command = "set_model"
			self._active_on_event = None
			self._active_done_event = done_event
			self._active_errors = []
			self._active_response_data = None
			self._active_cancel_requested = False

			try:
				self._client.send_set_model(provider=provider, model_id=model_id)
				self._wait_for_done(done_event, PI_CODING_AGENT_RPC_TIMEOUT_SECONDS)
				if self._active_errors:
					raise RuntimeError(self._active_errors[-1])
				self.model = selected_model
				self._mark_activity()
				return True
			finally:
				self._active_command = ""
				self._active_on_event = None
				self._active_done_event = None

	def abort_active(self) -> bool:
		"""Request cancellation of the active operation without stopping the session."""
		self._active_cancel_requested = True
		client = self._client
		if client is not None and client.is_running():
			client.send_abort()
			self._mark_activity()
			return True

		active_done_event = self._active_done_event
		if active_done_event is not None:
			active_done_event.set()
		return False

	def set_thinking(self, thinking: str) -> bool:
		"""Select the thinking level for future prompts without replacing session history."""
		selected_thinking = (thinking or "").strip().lower()
		if selected_thinking not in VALID_THINKING_LEVELS:
			raise ValueError(
				"Thinking level must be one of: " + ", ".join(sorted(VALID_THINKING_LEVELS))
			)

		with self._operation_lock:
			if selected_thinking == self.thinking:
				return False

			# If no RPC process exists yet, remember the selected level. The first
			# prompt will start Pi with this level and preserve a fresh session.
			if self._client is None:
				self.thinking = selected_thinking
				return True

			if not self._client.is_running():
				self._client.stop()
				self._client = None
				self.thinking = selected_thinking
				return True

			done_event = threading.Event()
			self._active_command = "set_thinking_level"
			self._active_on_event = None
			self._active_done_event = done_event
			self._active_errors = []
			self._active_response_data = None
			self._active_cancel_requested = False

			try:
				self._client.send_set_thinking_level(level=selected_thinking)
				self._wait_for_done(done_event, PI_CODING_AGENT_RPC_TIMEOUT_SECONDS)
				if self._active_errors:
					raise RuntimeError(self._active_errors[-1])
				self.thinking = selected_thinking
				self._mark_activity()
				return True
			finally:
				self._active_command = ""
				self._active_on_event = None
				self._active_done_event = None

	def stop(self) -> None:
		self._clear_prompt_generating()
		self._active_cancel_requested = True
		active_done_event = self._active_done_event
		if active_done_event is not None:
			active_done_event.set()

		client = self._client
		self._client = None
		if client is not None:
			client.stop()


def run_pi_rpc_agent(
	prompt: str,
	*,
	images: list[dict[str, str]] | None = None,
	on_event: Callable[[dict[str, Any]], None] | None = None,
	timeout_seconds: float | None = PI_CODING_AGENT_RPC_TIMEOUT_SECONDS,
) -> None:
	"""Run Pi coding agent in RPC mode with real-time event streaming.
	
	Args:
		prompt: The user prompt to send to the agent
		images: Optional Pi RPC image attachments to send with the prompt
		on_event: Callback for each JSON event from the agent (thinking, tools, text, etc.)
		timeout_seconds: Maximum time to wait for the agent_end event. The RPC process
			is long-lived and does not exit after a prompt, so completion is detected by
			the agent_end event rather than by process termination.
	"""
	if not isinstance(prompt, str) or not prompt.strip():
		raise ValueError("Prompt cannot be empty.")

	workdir = _resolve_workdir()
	done_event = threading.Event()
	errors: list[str] = []

	def _handle_event(event: dict[str, Any]) -> None:
		if on_event is not None:
			on_event(event)

		event_type = event.get("type")
		if event_type == "agent_end":
			done_event.set()
		elif event_type == "response" and event.get("command") == "prompt" and not event.get("success", False):
			error = event.get("error")
			errors.append(str(error) if error else "Prompt was rejected by Pi RPC.")
			done_event.set()
		elif event_type == "message_update":
			message_event = event.get("assistantMessageEvent", {})
			if message_event.get("type") == "error":
				reason = message_event.get("reason") or message_event.get("error") or "Assistant message failed."
				errors.append(str(reason))

	client = PiRpcClient(on_event=_handle_event, workdir=workdir)
	status_id = f"{os.getpid()}:oneshot:{time.time_ns()}"

	try:
		_update_pi_session_status(
			status_id,
			{
				"active": True,
				"command": "prompt",
				"model": DISCORD_PI_MODEL,
				"thinking": DISCORD_PI_THINKING,
				"workdir": str(workdir) if workdir is not None else "",
				"startedAt": _now_iso(),
			},
		)
		client.start()
		client.send_prompt(prompt, images=images)

		deadline = None if timeout_seconds is None else time.monotonic() + timeout_seconds
		while not done_event.is_set():
			if client.process is not None and client.process.poll() is not None:
				break

			if deadline is None:
				done_event.wait(timeout=0.1)
				continue

			remaining = deadline - time.monotonic()
			if remaining <= 0:
				client.send_abort()
				raise TimeoutError(f"Pi RPC agent timed out after {timeout_seconds:.0f} seconds.")
			done_event.wait(timeout=min(0.1, remaining))

		if errors:
			raise RuntimeError(errors[-1])

		if not done_event.is_set():
			exit_code = client.process.returncode if client.process is not None else None
			stderr_text = client.stderr_text().strip()
			details = f" with exit code {exit_code}" if exit_code is not None else ""
			raise RuntimeError(f"Pi RPC agent exited before completing{details}. {stderr_text}".strip())

	finally:
		_update_pi_session_status(status_id, remove=True)
		client.stop()
