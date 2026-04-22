from __future__ import annotations

import asyncio
import contextlib
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from time import monotonic
from typing import Any
from uuid import uuid4

from teleapp.protocol import AppEvent

from robot.brain import (
    build_daily_brief,
    build_schedule_alert,
    build_weekly_brief,
    collect_brain_reminders,
    get_active_or_next_schedule,
)
from robot.config import Settings
from robot.google_calendar import sync_schedule_jobs_with_google
from robot.projects import format_project_with_branch
from robot.providers import (
    RunningInvocation,
    list_auto_dev_profiles,
    run_agent_request,
    run_auto_dev_request,
)
from robot.state import ChatStateStore


@dataclass(slots=True)
class AgentJob:
    job_id: str
    kind: str
    goal: str
    project_name: str
    project_display: str
    project_path: str
    provider: str
    model: str
    thread_id: str | None
    source: str
    request_id: str | None = None
    status_key: str | None = None
    run_id: str | None = None
    profile: str | None = None
    config_path: str | None = None
    resume_target: str | None = None
    enable_commit: bool = False
    enable_push: bool = False
    enable_pr: bool = False
    disable_post_run: bool = False
    run_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "kind": self.kind,
            "goal": self.goal,
            "project_name": self.project_name,
            "project_display": self.project_display,
            "project_path": self.project_path,
            "provider": self.provider,
            "model": self.model,
            "thread_id": self.thread_id,
            "source": self.source,
            "request_id": self.request_id,
            "status_key": self.status_key,
            "run_id": self.run_id,
            "profile": self.profile,
            "config_path": self.config_path,
            "resume_target": self.resume_target,
            "enable_commit": self.enable_commit,
            "enable_push": self.enable_push,
            "enable_pr": self.enable_pr,
            "disable_post_run": self.disable_post_run,
            "run_at": self.run_at,
        }


class AgentCoordinator:
    def __init__(self, settings: Settings, store: ChatStateStore) -> None:
        self._settings = settings
        self._store = store
        self._supervisor = None
        self._worker_tasks: dict[int, asyncio.Task[None]] = {}
        self._scheduler_task: asyncio.Task[None] | None = None
        self._active_invocations: dict[int, RunningInvocation] = {}
        self._queue_watchdogs: dict[int, asyncio.Task[None]] = {}
        self._gcal_schedule_sync_interval_seconds = 300
        self._gcal_schedule_last_sync_at: dict[int, datetime] = {}

    def attach_supervisor(self, supervisor) -> None:
        self._supervisor = supervisor

    def start(self) -> None:
        if self._scheduler_task is None or self._scheduler_task.done():
            self._scheduler_task = asyncio.create_task(self._scheduler_loop())
        for chat_id in self._store.list_chat_ids():
            recovered = self._store.recover_agent_current_run(chat_id)
            if recovered is not None:
                asyncio.create_task(
                    self._emit(
                        chat_id,
                        "\n".join(
                            [
                                "Recovered interrupted run after restart.",
                                f"kind: {recovered.get('kind') or 'provider'}",
                                f"doing: {recovered.get('goal') or '<resume>'}",
                                f"project: {recovered.get('project_display') or recovered.get('project_name') or '-'}",
                                f"path: {recovered.get('project_path') or '-'}",
                            ]
                        ),
                        event_type="status",
                        raw={"status_key": "heartbeat", "replace": True},
                    )
                )
            if self._store.get_agent_queue(chat_id):
                self.ensure_worker(chat_id)

    async def shutdown(self) -> None:
        active_invocations = list(self._active_invocations.values())
        for invocation in active_invocations:
            invocation.cancel()
        await self._wait_invocations_exit(active_invocations)
        for task in list(self._worker_tasks.values()):
            task.cancel()
        for task in list(self._worker_tasks.values()):
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._worker_tasks.clear()
        for task in list(self._queue_watchdogs.values()):
            task.cancel()
        for task in list(self._queue_watchdogs.values()):
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._queue_watchdogs.clear()

        if self._scheduler_task is not None:
            self._scheduler_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._scheduler_task
            self._scheduler_task = None

    async def _wait_invocations_exit(self, invocations: list[RunningInvocation]) -> None:
        for invocation in invocations:
            process = invocation.process
            if process is None:
                continue
            await asyncio.to_thread(self._ensure_process_stopped, process)

    @staticmethod
    def _ensure_process_stopped(process: subprocess.Popen[str]) -> None:
        if process.poll() is not None:
            return
        with contextlib.suppress(subprocess.TimeoutExpired, OSError):
            process.wait(timeout=2)
        if process.poll() is not None:
            return
        with contextlib.suppress(OSError):
            process.kill()
        with contextlib.suppress(subprocess.TimeoutExpired, OSError):
            process.wait(timeout=2)

    def ensure_worker(self, chat_id: int) -> None:
        self._ensure_queue_watchdog(chat_id)
        task = self._worker_tasks.get(chat_id)
        if task is not None and not task.done():
            return
        self._worker_tasks[chat_id] = asyncio.create_task(self._worker_loop(chat_id))

    def _ensure_queue_watchdog(self, chat_id: int) -> None:
        task = self._queue_watchdogs.get(chat_id)
        if task is not None and not task.done():
            return
        self._queue_watchdogs[chat_id] = asyncio.create_task(self._queue_watchdog_loop(chat_id))

    async def _queue_watchdog_loop(self, chat_id: int) -> None:
        started = monotonic()
        while True:
            current = self._store.get_chat_state(chat_id).get("agent_current_run")
            queue = self._store.get_agent_queue(chat_id)
            if isinstance(current, dict):
                await asyncio.sleep(1)
                continue
            if not queue:
                self._queue_watchdogs.pop(chat_id, None)
                return
            next_job = queue[0]
            elapsed = int(monotonic() - started)
            await self._emit(
                chat_id,
                "\n".join(
                    [
                        "排隊中 ...",
                        f"kind: {next_job.get('kind') or 'provider'}",
                        f"doing: {next_job.get('goal') or '<resume>'}",
                        f"project: {next_job.get('project_display') or next_job.get('project_name') or '-'}",
                        f"path: {next_job.get('project_path') or '-'}",
                        "phase: queue: waiting for worker",
                        f"queue_pending: {len(queue)}",
                        f"elapsed: {self._format_elapsed(elapsed)}",
                    ]
                ),
                event_type="status",
                request_id=str(next_job.get("request_id") or "").strip() or None,
                raw={"status_key": str(next_job.get("status_key") or "heartbeat"), "replace": True},
            )
            await asyncio.sleep(1)

    def enqueue(
        self,
        chat_id: int,
        goal: str,
        *,
        source: str = "manual",
        request_id: str | None = None,
        status_key: str | None = None,
    ) -> tuple[str, int, bool]:
        state = self._store.get_chat_state(chat_id)
        project_display = format_project_with_branch(
            str(state["project_name"]),
            str(state["project_path"]),
        )
        job = AgentJob(
            job_id=str(uuid4()),
            kind="provider",
            goal=goal,
            project_name=str(state["project_name"]),
            project_display=project_display,
            project_path=str(state["project_path"]),
            provider=str(state["provider"]),
            model=str(state["model"]),
            thread_id=state["thread_id"],
            source=source,
            request_id=request_id,
            status_key=status_key,
        )
        position = self._store.enqueue_agent_job(chat_id, job.to_dict())
        started = position == 1 and not self.is_running(chat_id)
        self.ensure_worker(chat_id)
        return job.job_id, position, started

    def enqueue_auto_dev(
        self,
        chat_id: int,
        goal: str,
        *,
        source: str,
        profile: str | None = None,
        config_path: str | None = None,
        enable_commit: bool = False,
        enable_push: bool = False,
        enable_pr: bool = False,
        disable_post_run: bool = False,
        request_id: str | None = None,
        status_key: str | None = None,
    ) -> tuple[str, str, int, bool]:
        state = self._store.get_chat_state(chat_id)
        project_display = format_project_with_branch(
            str(state["project_name"]),
            str(state["project_path"]),
        )
        run_id = str(uuid4())
        job = AgentJob(
            job_id=str(uuid4()),
            kind="auto_dev",
            goal=goal,
            project_name=str(state["project_name"]),
            project_display=project_display,
            project_path=str(state["project_path"]),
            provider="auto-dev",
            model=profile or "default",
            thread_id=None,
            source=source,
            request_id=request_id,
            status_key=status_key,
            run_id=run_id,
            profile=profile,
            config_path=config_path,
            enable_commit=enable_commit,
            enable_push=enable_push,
            enable_pr=enable_pr,
            disable_post_run=disable_post_run,
        )
        position = self._store.enqueue_agent_job(chat_id, job.to_dict())
        started = position == 1 and not self.is_running(chat_id)
        self.ensure_worker(chat_id)
        return job.job_id, run_id, position, started

    def resume_auto_dev(
        self,
        chat_id: int,
        *,
        resume_target: str,
        source: str,
        profile: str | None = None,
        config_path: str | None = None,
        enable_commit: bool = False,
        enable_push: bool = False,
        enable_pr: bool = False,
        disable_post_run: bool = False,
        request_id: str | None = None,
        status_key: str | None = None,
    ) -> tuple[str, str, int, bool]:
        state = self._store.get_chat_state(chat_id)
        project_display = format_project_with_branch(
            str(state["project_name"]),
            str(state["project_path"]),
        )
        run_id = str(uuid4())
        job = AgentJob(
            job_id=str(uuid4()),
            kind="auto_dev",
            goal="",
            project_name=str(state["project_name"]),
            project_display=project_display,
            project_path=str(state["project_path"]),
            provider="auto-dev",
            model=profile or "default",
            thread_id=None,
            source=source,
            request_id=request_id,
            status_key=status_key,
            run_id=run_id,
            profile=profile,
            config_path=config_path,
            resume_target=resume_target,
            enable_commit=enable_commit,
            enable_push=enable_push,
            enable_pr=enable_pr,
            disable_post_run=disable_post_run,
        )
        position = self._store.enqueue_agent_job(chat_id, job.to_dict())
        started = position == 1 and not self.is_running(chat_id)
        self.ensure_worker(chat_id)
        return job.job_id, run_id, position, started

    def schedule_auto_dev(
        self,
        chat_id: int,
        goal: str,
        run_at: str,
        *,
        source: str,
        profile: str | None = None,
        config_path: str | None = None,
        enable_commit: bool = False,
        enable_push: bool = False,
        enable_pr: bool = False,
        disable_post_run: bool = False,
        request_id: str | None = None,
        status_key: str | None = None,
    ) -> tuple[str, str, int]:
        state = self._store.get_chat_state(chat_id)
        project_display = format_project_with_branch(
            str(state["project_name"]),
            str(state["project_path"]),
        )
        run_id = str(uuid4())
        job = AgentJob(
            job_id=str(uuid4()),
            kind="auto_dev",
            goal=goal,
            project_name=str(state["project_name"]),
            project_display=project_display,
            project_path=str(state["project_path"]),
            provider="auto-dev",
            model=profile or "default",
            thread_id=None,
            source=source,
            request_id=request_id,
            status_key=status_key,
            run_id=run_id,
            profile=profile,
            config_path=config_path,
            enable_commit=enable_commit,
            enable_push=enable_push,
            enable_pr=enable_pr,
            disable_post_run=disable_post_run,
            run_at=run_at,
        )
        count = self._store.add_agent_schedule(chat_id, job.to_dict())
        return job.job_id, run_id, count

    async def auto_dev_profiles(self, chat_id: int, config_path: str | None = None) -> str:
        state = self._store.get_chat_state(chat_id)
        workdir = Path(str(state["project_path"] or self._settings.project_root))
        return await list_auto_dev_profiles(self._settings, workdir=workdir, config_path=config_path)

    def is_running(self, chat_id: int) -> bool:
        task = self._worker_tasks.get(chat_id)
        return task is not None and not task.done()

    def stop(self, chat_id: int) -> bool:
        invocation = self._active_invocations.get(chat_id)
        if invocation is None:
            return self.is_running(chat_id)
        return invocation.cancel()

    def queue_overview(self, chat_id: int) -> str:
        current = self._store.get_chat_state(chat_id).get("agent_current_run")
        queue = self._store.get_agent_queue(chat_id)
        lines = ["agent queue"]
        if current:
            lines.extend(
                [
                    "",
                    "running: yes",
                    f"kind: {current.get('kind')}",
                    f"goal: {current.get('goal') or '-'}",
                    f"run_id: {current.get('run_id') or '-'}",
                    f"project: {current.get('project_display') or current.get('project_name') or '-'}",
                    f"path: {current.get('project_path') or '-'}",
                ]
            )
        if queue:
            lines.extend(["", f"queued: {len(queue)}"])
            for index, job in enumerate(queue, start=1):
                kind = str(job.get("kind") or "provider")
                if kind == "auto_dev":
                    lines.append(
                        f"{index}. [auto-dev] {job.get('goal') or '<resume>'} | {job.get('project_display') or job.get('project_name')} | profile={job.get('profile') or 'default'}"
                    )
                else:
                    lines.append(
                        f"{index}. [provider] {job.get('goal')} | {job.get('project_display') or job.get('project_name')} | {job.get('provider')}/{job.get('model')}"
                    )
        elif not current:
            lines.extend(["", "queue is empty"])
        return "\n".join(lines)

    def schedule_overview(self, chat_id: int) -> str:
        schedules = sorted(self._store.get_agent_schedules(chat_id), key=lambda item: str(item.get("run_at") or ""))
        lines = ["agent schedules (cron jobs)"]
        if not schedules:
            lines.extend(["", "no scheduled jobs"])
        else:
            lines.extend(["", f"scheduled: {len(schedules)}"])
            for index, job in enumerate(schedules, start=1):
                kind = str(job.get("kind") or "provider")
                lines.append(
                    f"{index}. {job.get('run_at')} | {kind} | {job.get('goal') or '<resume>'} | {job.get('project_display') or job.get('project_name')}"
                )
        lines.extend(
            [
                "",
                "usage:",
                "- /schedule YYYY-MM-DD HH:MM <goal> (新增 cron job)",
                "- /schedule sync [push|pull|both] [days] [limit] (手動同步 Google Calendar)",
                "- /clearschedule (清除所有 cron jobs)",
            ]
        )
        return "\n".join(lines)

    def clear_queue(self, chat_id: int) -> None:
        self._store.clear_agent_queue(chat_id)

    def clear_schedules(self, chat_id: int) -> None:
        self._store.clear_agent_schedules(chat_id)

    async def _scheduler_loop(self) -> None:
        while True:
            now = datetime.now().replace(second=0, microsecond=0)
            for chat_id in self._store.list_chat_ids():
                await self._process_brain_automation(chat_id, now)
                await self._maybe_sync_google_schedules(chat_id, now)
                schedules = self._store.get_agent_schedules(chat_id)
                due: list[dict[str, Any]] = []
                keep: list[dict[str, Any]] = []
                for job in schedules:
                    run_at = str(job.get("run_at") or "").strip()
                    if not run_at:
                        keep.append(job)
                        continue
                    try:
                        when = datetime.fromisoformat(run_at).replace(second=0, microsecond=0)
                    except ValueError:
                        keep.append(job)
                        continue
                    if when <= now:
                        due.append(job)
                    else:
                        keep.append(job)

                if not due:
                    continue

                self._store.set_agent_schedules(chat_id, keep)
                for job in due:
                    self._store.enqueue_agent_job(chat_id, job)
                await self._emit(chat_id, f"Scheduled run moved to queue.\ncount: {len(due)}")
                self.ensure_worker(chat_id)

            await asyncio.sleep(15)

    async def _maybe_sync_google_schedules(self, chat_id: int, now: datetime) -> None:
        if not self._settings.google_calendar_enabled:
            return

        last = self._gcal_schedule_last_sync_at.get(chat_id)
        if last is not None:
            elapsed_seconds = int((now - last).total_seconds())
            if elapsed_seconds < self._gcal_schedule_sync_interval_seconds:
                return

        schedules = self._store.get_agent_schedules(chat_id)
        state = self._store.get_chat_state(chat_id)
        state_defaults = {
            "project_name": state.get("project_name"),
            "project_display": format_project_with_branch(
                str(state.get("project_name") or "-"),
                str(state.get("project_path") or ""),
            ),
            "project_path": state.get("project_path"),
        }
        try:
            updated, _report = sync_schedule_jobs_with_google(
                self._settings,
                chat_id=chat_id,
                schedules=schedules,
                mode="both",
                days=30,
                limit=200,
                state_defaults=state_defaults,
            )
            self._store.set_agent_schedules(chat_id, updated)
        except Exception:
            # Keep scheduler resilient; sync retries on next 5-minute window.
            pass
        finally:
            self._gcal_schedule_last_sync_at[chat_id] = now

    async def _process_brain_automation(self, chat_id: int, now: datetime) -> None:
        automation = self._store.get_brain_automation(chat_id)
        if not automation or not bool(automation.get("enabled")):
            return

        current_date = now.strftime("%Y-%m-%d")
        daily_time = str(automation.get("daily_time") or "21:00").strip()
        if daily_time == now.strftime("%H:%M") and str(automation.get("last_daily_date") or "") != current_date:
            text = build_daily_brief(self._settings)
            reminders = collect_brain_reminders(self._settings, limit=5)
            payload = "\n".join([text, "", "提醒：", *reminders])
            await self._emit(chat_id, payload)
            self._store.update_brain_automation(chat_id, last_daily_date=current_date)

        weekly_day = int(automation.get("weekly_day") or 0)
        weekly_time = str(automation.get("weekly_time") or "09:00").strip()
        week_key = now.strftime("%G-W%V")
        if now.weekday() == weekly_day and weekly_time == now.strftime("%H:%M") and str(automation.get("last_weekly_key") or "") != week_key:
            payload = build_weekly_brief(self._settings, limit=10)
            await self._emit(chat_id, payload)
            self._store.update_brain_automation(chat_id, last_weekly_key=week_key)

        lookahead_minutes = self._coerce_schedule_window(automation.get("schedule_alert_window_minutes"))
        schedule = get_active_or_next_schedule(self._settings, now=now, lookahead_minutes=lookahead_minutes)
        last_schedule_key = str(automation.get("last_schedule_alert_key") or "")
        if schedule is None:
            if last_schedule_key:
                self._store.update_brain_automation(chat_id, last_schedule_alert_key="")
            return

        schedule_key = self._build_schedule_alert_key(schedule)
        if schedule_key == last_schedule_key:
            return

        payload = build_schedule_alert(self._settings, now=now)
        if payload is None:
            return
        await self._emit(chat_id, payload)
        self._store.update_brain_automation(chat_id, last_schedule_alert_key=schedule_key)

    @staticmethod
    def _coerce_schedule_window(value: Any) -> int:
        try:
            minutes = int(value)
        except (TypeError, ValueError):
            minutes = 60
        return max(1, minutes)

    @staticmethod
    def _build_schedule_alert_key(schedule: dict[str, str]) -> str:
        stage = AgentCoordinator._schedule_alert_stage(schedule)
        return "|".join(
            [
                stage,
                str(schedule.get("status") or ""),
                str(schedule.get("date") or ""),
                str(schedule.get("time") or ""),
                str(schedule.get("path") or ""),
                str(schedule.get("title") or ""),
            ]
        )

    @staticmethod
    def _schedule_alert_stage(schedule: dict[str, str]) -> str:
        status = str(schedule.get("status") or "")
        try:
            minutes_until = int(schedule.get("minutes_until") or "0")
        except (TypeError, ValueError):
            minutes_until = 0

        if status == "now" or minutes_until <= 0:
            return "start"
        if minutes_until <= 10:
            return "10m"
        if minutes_until <= 30:
            return "30m"
        return "60m"

    async def _worker_loop(self, chat_id: int) -> None:
        while True:
            job = self._store.pop_agent_job(chat_id)
            if job is None:
                self._worker_tasks.pop(chat_id, None)
                return

            self._store.set_agent_current_run(chat_id, job)
            invocation = RunningInvocation()
            invocation.set_phase("agent: starting")
            self._active_invocations[chat_id] = invocation
            await self._emit(
                chat_id,
                "\n".join(
                    [
                        "Agent run started.",
                        f"kind: {job.get('kind') or 'provider'}",
                        f"goal: {job.get('goal') or '<resume>'}",
                        f"project: {job.get('project_display') or job.get('project_name')}",
                        f"path: {job.get('project_path')}",
                        f"provider: {job.get('provider')}",
                        f"model/profile: {job.get('model')}",
                        f"phase: {invocation.get_phase()}",
                        f"queue_pending: {len(self._store.get_agent_queue(chat_id))}",
                        f"progress: {self._build_heartbeat_progress(0)}",
                        f"elapsed: {self._format_elapsed(0)}",
                        "heartbeat: active",
                    ]
                ),
                event_type="status",
                request_id=str(job.get("request_id") or "").strip() or None,
                raw={"status_key": str(job.get("status_key") or "heartbeat"), "replace": True},
            )

            heartbeat_task = asyncio.create_task(self._heartbeat_loop(chat_id, job, invocation))
            started = datetime.now()
            cancelled_by_shutdown = False
            try:
                if str(job.get("kind") or "provider") == "auto_dev":
                    enable_commit = str(job.get("enable_commit") or "").lower() in {"1", "true", "yes", "on"}
                    enable_push = str(job.get("enable_push") or "").lower() in {"1", "true", "yes", "on"}
                    enable_pr = str(job.get("enable_pr") or "").lower() in {"1", "true", "yes", "on"}
                    disable_post_run = str(job.get("disable_post_run") or "").lower() in {"1", "true", "yes", "on"}
                    result = await run_auto_dev_request(
                        self._settings,
                        prompt=str(job.get("goal") or "").strip() or None,
                        workdir=Path(str(job.get("project_path") or self._settings.project_root)),
                        project_label=str(
                            job.get("project_display")
                            or job.get("project_name")
                            or self._settings.project_root.name
                        ),
                        run_id=str(job.get("run_id") or "-"),
                        profile_name=str(job.get("profile") or "").strip() or None,
                        config_path=str(job.get("config_path") or "").strip() or None,
                        resume_target=str(job.get("resume_target") or "").strip() or None,
                        enable_commit=enable_commit,
                        enable_push=enable_push,
                        enable_pr=enable_pr,
                        disable_post_run=disable_post_run,
                        invocation=invocation,
                    )
                else:
                    result = await run_agent_request(
                        self._settings,
                        provider=str(job.get("provider") or "codex"),
                        model=str(job.get("model") or ""),
                        prompt=str(job.get("goal") or ""),
                        thread_id=job.get("thread_id") if isinstance(job.get("thread_id"), str) else None,
                        workdir=Path(str(job.get("project_path") or self._settings.project_root)),
                        project_label=str(
                            job.get("project_display")
                            or job.get("project_name")
                            or self._settings.project_root.name
                        ),
                        invocation=invocation,
                    )
            except asyncio.CancelledError:
                cancelled_by_shutdown = True
                invocation.cancel()
                result = None
            finally:
                heartbeat_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await heartbeat_task
                self._active_invocations.pop(chat_id, None)

            elapsed_seconds = int((datetime.now() - started).total_seconds())
            if cancelled_by_shutdown:
                self._store.set_agent_current_run(chat_id, None)
                self._store.set_agent_last_run(
                    chat_id,
                    {
                        **job,
                        "status": "stopped",
                        "elapsed_seconds": elapsed_seconds,
                    },
                )
                self._store.set_last_provider_timing(
                    chat_id,
                    {
                        "job_id": str(job.get("job_id") or ""),
                        "kind": str(job.get("kind") or "provider"),
                        "provider": str(job.get("provider") or ""),
                        "model": str(job.get("model") or ""),
                        "elapsed_seconds": elapsed_seconds,
                        "cancelled": True,
                        "return_code": 130,
                    },
                )
                await self._emit(
                    chat_id,
                    "\n".join(
                        [
                            "Agent run stopped during shutdown.",
                            f"kind: {job.get('kind') or 'provider'}",
                            f"goal: {job.get('goal') or '<resume>'}",
                        ]
                    ),
                    event_type="status",
                    request_id=str(job.get("request_id") or "").strip() or None,
                    raw={"status_key": str(job.get("status_key") or "heartbeat"), "replace": True},
                )
                self._worker_tasks.pop(chat_id, None)
                return

            assert result is not None
            if result.thread_id is not None:
                self._store.set_thread_id(chat_id, str(job.get("provider") or "codex"), result.thread_id)
            self._store.set_agent_current_run(chat_id, None)
            self._store.set_agent_last_run(
                chat_id,
                {
                    **job,
                    "status": "stopped" if result.cancelled else ("ok" if result.return_code == 0 else "failed"),
                    "elapsed_seconds": result.elapsed_seconds,
                },
            )
            self._store.set_last_provider_timing(
                chat_id,
                {
                    "job_id": str(job.get("job_id") or ""),
                    "kind": str(job.get("kind") or "provider"),
                    "provider": str(job.get("provider") or ""),
                    "model": str(job.get("model") or ""),
                    "elapsed_seconds": int(result.elapsed_seconds),
                    "cancelled": bool(result.cancelled),
                    "return_code": int(result.return_code),
                },
            )
            status_label = "stopped" if result.cancelled else ("ok" if result.return_code == 0 else "failed")
            await self._emit(
                chat_id,
                "\n".join(
                    [
                        "Agent run finished.",
                        f"kind: {job.get('kind') or 'provider'}",
                        f"goal: {job.get('goal') or '<resume>'}",
                        f"project: {job.get('project_display') or job.get('project_name')}",
                        f"path: {job.get('project_path')}",
                        f"queue_pending: {len(self._store.get_agent_queue(chat_id))}",
                        f"status: {status_label}",
                        f"elapsed: {self._format_elapsed(int(result.elapsed_seconds))}",
                    ]
                ),
                event_type="status",
                request_id=str(job.get("request_id") or "").strip() or None,
                raw={"status_key": str(job.get("status_key") or "heartbeat"), "replace": True},
            )
            await self._emit(chat_id, result.final_text, event_type="output")

    async def _heartbeat_loop(
        self,
        chat_id: int,
        job: dict[str, Any],
        invocation: RunningInvocation,
    ) -> None:
        started = datetime.now()
        while True:
            elapsed = int((datetime.now() - started).total_seconds())
            current_goal = str(job.get("goal") or "").strip() or "<resume>"
            current_project = str(job.get("project_display") or job.get("project_name") or "-")
            phase = invocation.get_phase()
            await self._emit(
                chat_id,
                "\n".join(
                    [
                        "執行中 ...",
                        f"kind: {job.get('kind') or 'provider'}",
                        f"doing: {current_goal}",
                        f"project: {current_project}",
                        f"path: {job.get('project_path') or '-'}",
                        f"phase: {phase}",
                        f"queue_pending: {len(self._store.get_agent_queue(chat_id))}",
                        f"progress: {self._build_heartbeat_progress(elapsed)}",
                        f"elapsed: {self._format_elapsed(elapsed)}",
                    ]
                ),
                event_type="status",
                request_id=str(job.get("request_id") or "").strip() or None,
                raw={"status_key": str(job.get("status_key") or "heartbeat"), "replace": True},
            )
            await asyncio.sleep(1)

    @staticmethod
    def _format_elapsed(seconds: int) -> str:
        safe = max(0, int(seconds))
        minute, second = divmod(safe, 60)
        hour, minute = divmod(minute, 60)
        if hour:
            return f"{hour:02d}:{minute:02d}:{second:02d}"
        return f"{minute:02d}:{second:02d}"

    @staticmethod
    def _build_heartbeat_progress(
        elapsed_seconds: int,
        *,
        cycle_seconds: int = 60,
        slots: int = 20,
    ) -> str:
        safe_elapsed = max(0, int(elapsed_seconds))
        safe_cycle = max(1, int(cycle_seconds))
        safe_slots = max(1, int(slots))
        in_cycle = safe_elapsed % safe_cycle
        ratio = in_cycle / safe_cycle
        filled = min(safe_slots, int(ratio * safe_slots))
        bar = ("█" * filled) + ("░" * (safe_slots - filled))
        percent = int(ratio * 100)
        return f"[{bar}] {percent}% (rolling)"

    async def _emit(
        self,
        chat_id: int,
        text: str,
        event_type: str = "output",
        raw: dict[str, Any] | None = None,
        request_id: str | None = None,
    ) -> None:
        if self._supervisor is None:
            return
        queue = getattr(self._supervisor, "_event_queue", None)
        if queue is None:
            return
        queue.put_nowait(
            AppEvent(
                type=event_type,
                text=text,
                chat_id=chat_id,
                request_id=request_id,
                stream="inprocess",
                raw=raw,
            )
        )

