"""Agent runtime: permissioned tool-calling loop (spec §3.1).

Flow: user text -> provider -> (text | tool calls) -> permission policy ->
tool execute -> result fed BACK to provider -> final text.

Cancellation contract (spec §3.5): tools receive a CancellationToken and
must check it before starting and between segments of long work. HTTP
`timeout=` bounds connection/read inactivity — it is not a hard
total-duration cap. Setting the token does not stop non-cancellable
in-flight work; this runtime only guarantees that a cancelled task stops
observing that work (late results discarded, no further model calls).
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout

from core.agent.cancellation import CancellationToken, TaskCancelled
from core.agent.config import AgentConfig
from core.agent.telemetry import log_event
from core.events import EventBus
from core.providers.base import ChatMessage, ModelProvider, ProviderError
from core.session.store import SessionStore
from core.tools.base import ToolResult
from core.tools.registry import PermissionLevel, PermissionPolicy, ToolRegistry


def _json_safe(value):
    if isinstance(value, bytes):
        return {"__bytes_len__": len(value)}
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return repr(value)


def _result_content(result: ToolResult) -> str:
    if result.ok:
        return json.dumps(
            {"ok": True, "data": _json_safe(result.data or {})}, ensure_ascii=False
        )
    return json.dumps(
        {
            "ok": False,
            "error": result.error,
            "error_code": result.error_code,
        },
        ensure_ascii=False,
    )


class _LinkedToken(CancellationToken):
    """Child token: cancelled when its own cancel() or the parent is cancelled."""

    def __init__(self, parent: CancellationToken) -> None:
        super().__init__()
        self._parent = parent

    @property
    def cancelled(self) -> bool:
        return super().cancelled or self._parent.cancelled

    def raise_if_cancelled(self) -> None:
        if self.cancelled:
            raise TaskCancelled()

    def wait(self, timeout: float) -> bool:
        if self._parent.cancelled:
            self.cancel()
        return super().wait(timeout) or self._parent.wait(0)


class _Task:
    def __init__(self, task_id: str, session_id: str) -> None:
        self.task_id = task_id
        self.session_id = session_id
        self.token = CancellationToken()
        self.confirmations: dict[str, threading.Event] = {}
        self.confirm_approved: dict[str, bool] = {}
        self.confirm_lock = threading.Lock()


class AgentRuntime:
    def __init__(
        self,
        provider: ModelProvider,
        registry: ToolRegistry,
        policy: PermissionPolicy,
        events: EventBus,
        session: SessionStore,
        config: AgentConfig | None = None,
    ) -> None:
        self._provider = provider
        self._registry = registry
        self._policy = policy
        self._events = events
        self._session = session
        self._config = config or AgentConfig()
        self._tasks: dict[str, _Task] = {}
        self._active_task_id: str | None = None
        self._executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="tool")

    @property
    def active_task_id(self) -> str | None:
        return self._active_task_id

    @property
    def registry(self) -> ToolRegistry:
        return self._registry

    def set_provider(self, provider: ModelProvider) -> None:
        """Hot-swap the model provider (e.g. after the user saves Settings)."""
        self._provider = provider

    def set_persona(self, persona: str) -> None:
        """Hot-swap the optional system prompt (applies to the next task)."""
        self._config.persona = persona

    def begin_task(
        self, session_id: str, user_text: str, images: list[str] | None = None
    ) -> str:
        task_id = uuid.uuid4().hex
        task = _Task(task_id, session_id)
        self._tasks[task_id] = task
        self._active_task_id = task_id
        self._session.add_message(session_id, "user", user_text, images=images)
        return task_id

    def run_task(self, task_id: str) -> None:
        task = self._tasks[task_id]
        try:
            self._loop(task)
        finally:
            if self._active_task_id == task_id:
                self._active_task_id = None
            self._tasks.pop(task_id, None)

    def close(self) -> None:
        """Cancel active task, stop accepting tool work, free threads (spec §3.5)."""
        self.cancel_active_task()
        self._executor.shutdown(wait=False, cancel_futures=True)

    def start_task(self, session_id: str, user_text: str) -> str:
        task_id = self.begin_task(session_id, user_text)
        self.run_task(task_id)
        return task_id

    def cancel_task(self, task_id: str) -> None:
        task = self._tasks.get(task_id)
        if task is None:
            return
        task.token.cancel()
        with task.confirm_lock:
            for event in task.confirmations.values():
                event.set()
            task.confirmations.clear()

    def cancel_active_task(self) -> None:
        if self._active_task_id is not None:
            self.cancel_task(self._active_task_id)

    def resolve_confirmation(self, task_id: str, confirm_id: str, approved: bool) -> None:
        task = self._tasks.get(task_id)
        if task is None:
            return
        with task.confirm_lock:
            event = task.confirmations.pop(confirm_id, None)
            if event is None:
                return  # stale or double reply
            task.confirm_approved[confirm_id] = approved
            event.set()

    def _loop(self, task: _Task) -> None:
        sid, tid = task.session_id, task.task_id
        started = time.perf_counter()
        model_calls = 0
        tool_timings: list[dict] = []
        outcome = "finished"
        error_code: str | None = None
        self._events.publish("agent_started", sid, tid, {})
        tool_calls_used = 0
        schemas = self._registry.schemas()
        try:
            if schemas and not self._provider.supports_tools:
                outcome, error_code = "error", "unsupported_capability"
                self._events.publish(
                    "agent_error", sid, tid,
                    {"error_code": "unsupported_capability", "message": "provider has no tool support"},
                )
                return
            while True:
                task.token.raise_if_cancelled()
                messages = self._session.messages(sid)
                persona = (self._config.persona or "").strip()
                if persona:
                    messages = [ChatMessage(role="system", content=persona), *messages]
                model_calls += 1
                try:
                    response = self._provider.complete(messages, schemas, task.token)
                except TaskCancelled:
                    raise
                except ProviderError as exc:
                    outcome, error_code = "error", exc.error_code
                    self._events.publish(
                        "agent_error", sid, tid,
                        {"error_code": exc.error_code, "message": exc.message},
                    )
                    return
                pop_notice = getattr(self._provider, "pop_notice", None)
                if pop_notice is not None:
                    notice = pop_notice()
                    if notice:
                        self._events.publish("provider_notice", sid, tid, notice)
                # abandoned in-flight responses are never delivered
                task.token.raise_if_cancelled()
                if not response.tool_calls:
                    text = response.text or ""
                    self._session.add_message(sid, "assistant", text)
                    self._events.publish("assistant_message", sid, tid, {"text": text})
                    self._events.publish("agent_finished", sid, tid, {"final_text": text})
                    return
                self._session.add_message(
                    sid, "assistant", response.text, tool_calls=response.tool_calls
                )
                for index, call in enumerate(response.tool_calls):
                    if task.token.cancelled:
                        outcome = "cancelled"
                        self._close_tool_batch(
                            task, response.tool_calls, index, "cancelled", "task cancelled"
                        )
                        self._events.publish(
                            "agent_cancelled", sid, tid, {"reason": "cancelled"}
                        )
                        return
                    tool_calls_used += 1
                    if tool_calls_used > self._config.max_tool_calls:
                        outcome, error_code = "error", "max_tool_calls"
                        self._close_tool_batch(
                            task, response.tool_calls, index,
                            "max_tool_calls", "tool call limit reached",
                        )
                        self._events.publish(
                            "agent_error", sid, tid,
                            {
                                "error_code": "max_tool_calls",
                                "message": "tool call limit reached",
                            },
                        )
                        return
                    if call.parse_error:
                        result = ToolResult(
                            ok=False,
                            error=f"malformed tool arguments: {call.parse_error}",
                            error_code="invalid_arguments",
                        )
                        tool_timings.append(
                            {"name": call.name, "ms": 0.0, "ok": False}
                        )
                    else:
                        tool_started = time.perf_counter()
                        result = self._run_one_tool(
                            task, call.id, call.name, call.arguments
                        )
                        tool_timings.append({
                            "name": call.name,
                            "ms": round((time.perf_counter() - tool_started) * 1000.0, 1),
                            "ok": result.ok,
                        })
                    if task.token.cancelled:
                        # late result discarded — never fed to the model;
                        # write a synthetic result so history stays closed
                        outcome = "cancelled"
                        self._session.add_message(
                            sid, "tool",
                            _result_content(ToolResult(
                                ok=False, error="cancelled during tool execution",
                                error_code="cancelled",
                            )),
                            tool_call_id=call.id, name=call.name,
                        )
                        self._close_tool_batch(
                            task, response.tool_calls, index + 1,
                            "cancelled", "task cancelled",
                        )
                        self._events.publish(
                            "agent_cancelled", sid, tid, {"reason": "cancelled"}
                        )
                        return
                    # Vision plumbing: pull any image off the tool result.
                    image = None
                    if result.ok and isinstance(result.data, dict):
                        image = result.data.pop("image", None)
                    self._session.add_message(
                        sid, "tool", _result_content(result),
                        tool_call_id=call.id, name=call.name,
                    )
                    if image:
                        if self._provider.supports_vision:
                            # Attach as a user message so the model can see it.
                            self._session.add_message(
                                sid, "user", "Image from tool result:",
                                images=[image],
                            )
                            # Bound retained images: superseded base64 blobs
                            # are dropped from the session (memory + request size).
                            self._session.trim_images(
                                sid, self._config.max_history_images
                            )
                        # No vision: image already stripped from tool content above.
        except TaskCancelled:
            outcome = "cancelled"
            self._events.publish("agent_cancelled", sid, tid, {"reason": "cancelled"})
        finally:
            self._log_task_summary(
                task, started=started, model_calls=model_calls,
                tool_timings=tool_timings, outcome=outcome, error_code=error_code,
            )

    def _log_task_summary(
        self,
        task: _Task,
        *,
        started: float,
        model_calls: int,
        tool_timings: list[dict],
        outcome: str,
        error_code: str | None,
    ) -> None:
        """One telemetry line per task: where did the time go?"""
        summary: dict = {
            "task_id": task.task_id,
            "session_id": task.session_id,
            "outcome": outcome,
            "duration_ms": round((time.perf_counter() - started) * 1000.0, 1),
            "model_calls": model_calls,
            "tool_ms_total": round(sum(t["ms"] for t in tool_timings), 1),
            "tools": tool_timings,
        }
        if error_code is not None:
            summary["error_code"] = error_code
        pop_stats = getattr(self._provider, "pop_stats", None)
        if callable(pop_stats):
            stats = pop_stats()
            summary["provider_wait_ms"] = stats.get("total_wait_ms", 0.0)
            summary["provider_http_ms"] = stats.get("total_http_ms", 0.0)
        log_event("task_summary", **summary)

    def _close_tool_batch(
        self,
        task: _Task,
        calls,
        from_index: int,
        error_code: str,
        error: str,
    ) -> None:
        """Append synthetic tool results so every assistant tool_call has a reply."""
        for call in calls[from_index:]:
            self._session.add_message(
                task.session_id, "tool",
                _result_content(ToolResult(ok=False, error=error, error_code=error_code)),
                tool_call_id=call.id, name=call.name,
            )

    def _run_one_tool(self, task: _Task, call_id: str, name: str, arguments: dict) -> ToolResult:
        sid, tid = task.session_id, task.task_id
        tool = self._registry.get(name)
        if tool is None:
            return ToolResult(
                ok=False,
                error=f"unknown tool: {name}",
                error_code="unknown_tool",
            )
        level = self._policy.check(name)
        if level is PermissionLevel.DENY:
            return ToolResult(
                ok=False,
                error="permission denied by policy",
                error_code="permission_denied",
            )
        if level is PermissionLevel.ASK:
            confirm_id = uuid.uuid4().hex
            event = threading.Event()
            with task.confirm_lock:
                # record BEFORE publish — synchronous subscribers must not race
                task.confirmations[confirm_id] = event
            self._events.publish(
                "confirmation_requested", sid, tid,
                {
                    "confirm_id": confirm_id,
                    "tool_name": name,
                    "question": f"Run tool {name}?",
                    "arguments": arguments,
                },
            )
            while True:
                if task.token.cancelled:
                    with task.confirm_lock:
                        task.confirmations.pop(confirm_id, None)
                    return ToolResult(
                        ok=False, error="cancelled while awaiting confirmation",
                        error_code="cancelled",
                    )
                if event.wait(0.05):
                    break
            with task.confirm_lock:
                approved = task.confirm_approved.pop(confirm_id, False)
            if not approved:
                return ToolResult(
                    ok=False, error="user denied permission",
                    error_code="permission_denied",
                )
        self._events.publish(
            "tool_started", sid, tid, {"tool_name": name, "arguments": arguments}
        )
        tool_token = _LinkedToken(task.token)
        future = self._executor.submit(tool.execute, arguments, tool_token)
        try:
            result = future.result(timeout=self._config.tool_timeout_s)
        except FuturesTimeout:
            tool_token.cancel()  # let the tool observe cancellation
            future.cancel()
            result = ToolResult(
                ok=False, error="tool timed out", error_code="timeout"
            )
        except Exception as exc:  # tool crashed
            result = ToolResult(
                ok=False, error=str(exc), error_code="tool_exception"
            )
        self._events.publish(
            "tool_finished", sid, tid,
            {"tool_name": name, "ok": result.ok, "summary": result.error or "ok"},
        )
        return result
