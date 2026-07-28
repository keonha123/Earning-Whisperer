from __future__ import annotations

import asyncio
import hashlib
import os
import re
import sys
from pathlib import Path
from typing import Any


class STTWorkerManager:
    def __init__(self) -> None:
        self._active_processes: dict[str, asyncio.subprocess.Process] = {}

    def build_isolated_capture_environment(
        self,
        call: dict[str, Any],
        capture_env: dict[str, str] | None = None,
    ) -> dict[str, str]:
        """Build per-call browser/audio paths so concurrent jobs do not share temp files."""
        return self._probe_runtime_environment(call, capture_env)

    async def launch_mission(self, call):
        call = dict(call)
        ticker = str(call["ticker"]).upper()
        call_id = self._build_call_id(call)
        existing = self._active_processes.get(call_id)
        if existing and existing.returncode is None:
            print(f"[STTWorker] {ticker} already running call_id={call_id}")
            return

        await self._resolve_webcast_source(call)
        command = self._build_command(call, call_id)
        print(f"[STTWorker] launching {ticker} call_id={call_id}")
        process = await asyncio.create_subprocess_exec(*command)
        self._active_processes[call_id] = process
        asyncio.create_task(self._watch_process(call, call_id, process))

    async def probe_date_based_call(
        self,
        call: dict[str, Any],
        *,
        capture_env: dict[str, str] | None = None,
    ) -> tuple[bool, str | None]:
        """Run a date-watch browser playback probe and require audible PulseAudio output."""
        return await self.probe_webcast_url(
            call,
            capture_env=capture_env or {"WEBCAST_LIFECYCLE": "live"},
        )

    async def probe_webcast_url(
        self,
        call: dict[str, Any],
        *,
        capture_env: dict[str, str] | None = None,
        timeout_seconds: float | None = None,
    ) -> tuple[bool, str | None]:
        """Probe one URL in the browser-audio container without launching STT."""
        if not call.get("ir_url"):
            return False, "missing IR URL"

        try:
            command, process_env = self._probe_command(call, capture_env=capture_env)
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=process_env,
            )
            timeout = timeout_seconds or float(os.getenv("DATE_STREAM_PROBE_TIMEOUT_SECONDS", "150"))
            communicate_task = asyncio.create_task(process.communicate())
            try:
                output, _ = await asyncio.wait_for(asyncio.shield(communicate_task), timeout=timeout)
            except TimeoutError:
                process.kill()
                await communicate_task
                return False, f"audio probe timed out after {timeout:g}s"
        except Exception as exc:
            return False, str(exc)

        text_output = (output or b"").decode("utf-8", errors="replace")
        if (
            process.returncode == 0
            and "AUDIO_DETECTED" in text_output
            and "NOT_LIVE_YET" not in text_output
            and "WEBCAST_EXITED_BEFORE_PLAYBACK" not in text_output
        ):
            return True, None
        return False, self._process_error(text_output, process.returncode, operation="audio probe")

    async def learn_webcast_url(
        self,
        call: dict[str, Any],
        *,
        timeout_seconds: float = 60,
    ) -> tuple[bool, str | None]:
        """Learn a future event page's navigation without treating pre-live silence as failure."""
        if not call.get("ir_url"):
            return False, "missing IR URL"

        if os.getenv("WEBCAST_CAPTURE_RUNNER", "docker").lower() == "container":
            command = [
                "python",
                "-m",
                "data_pipeline.collectors.streams.browser_webcast",
                "--ticker",
                str(call["ticker"]).upper(),
                "--ir-url",
                str(call["ir_url"]),
            ]
        else:
            repository_root = Path(__file__).resolve().parents[2]
            compose_file = repository_root / "infra" / "docker-compose.yml"
            command = [
                "docker",
                "compose",
                "-f",
                str(compose_file),
                "--profile",
                "tools",
                "run",
                "--rm",
                "browser-webcast",
                "python",
                "-m",
                "data_pipeline.collectors.streams.browser_webcast",
                "--ticker",
                str(call["ticker"]).upper(),
                "--ir-url",
                str(call["ir_url"]),
            ]

        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            communicate_task = asyncio.create_task(process.communicate())
            try:
                output, _ = await asyncio.wait_for(asyncio.shield(communicate_task), timeout=timeout_seconds)
            except TimeoutError:
                process.kill()
                await communicate_task
                return False, f"discovery timed out after {timeout_seconds:g}s"
        except Exception as exc:
            return False, str(exc)

        text_output = (output or b"").decode("utf-8", errors="replace")
        if process.returncode == 0:
            return True, None
        return False, self._process_error(text_output, process.returncode, operation="webcast discovery")

    def _probe_command(
        self,
        call: dict[str, Any],
        *,
        capture_env: dict[str, str] | None,
    ) -> tuple[list[str], dict[str, str] | None]:
        """Use Docker from the host or the local audio script inside a worker container."""
        runtime_env = self._probe_runtime_environment(call, capture_env)
        if os.getenv("WEBCAST_CAPTURE_RUNNER", "docker").lower() != "container":
            return self._build_audio_capture_command(
                call,
                probe_only=True,
                capture_env=runtime_env,
            ), None

        command = [
            "bash",
            "data_pipeline/scripts/run_webcast_audio_capture.sh",
            "--probe-only",
            str(call["ticker"]).upper(),
            str(call["ir_url"]),
        ]
        environment = {**os.environ, **runtime_env}
        environment["CALL_ID"] = self._build_call_id(call)
        return command, environment

    @staticmethod
    def _probe_runtime_environment(
        call: dict[str, Any],
        capture_env: dict[str, str] | None,
    ) -> dict[str, str]:
        """Give concurrent probes isolated PulseAudio and browser handshake paths."""
        ticker = re.sub(r"[^A-Za-z0-9]", "", str(call.get("ticker") or "probe").upper())[:12] or "PROBE"
        target_hash = hashlib.sha1(
            "|".join(
                [
                    str(call.get("id") or call.get("call_id") or ""),
                    str(call.get("ticker") or ticker),
                    str(call.get("call_year") or ""),
                    str(call.get("quarter") or ""),
                    str(call.get("ir_url") or call.get("target_url") or ticker),
                ]
            ).encode("utf-8")
        ).hexdigest()[:10]
        prefix = f"/tmp/ew-webcast-{ticker.lower()}-{target_hash}"
        sink = f"ew_webcast_{ticker.lower()}_{target_hash}"
        runtime_env = dict(capture_env or {})
        runtime_env.update(
            {
                "WEBCAST_PULSE_SINK": sink,
                "STT_INPUT_SOURCE": f"{sink}.monitor",
                "WEBCAST_PLAYBACK_READY_FILE": f"{prefix}-playback-ready",
                "WEBCAST_ACTIVE_PLAYER_URL_FILE": f"{prefix}-active-url",
                "WEBCAST_MEDIA_CANDIDATES_FILE": f"{prefix}-media-candidates.json",
                "WEBCAST_RECIPE_CONTEXT_PATH": f"{prefix}-recipe.json",
                "WEBCAST_STORAGE_STATE": f"{prefix}-storage.json",
                "WEBCAST_TARGET_YEAR": str(call.get("call_year") or ""),
                "WEBCAST_TARGET_QUARTER": str(call.get("quarter") or ""),
            }
        )
        return runtime_env

    async def launch_date_based_audio_capture(
        self,
        call: dict[str, Any],
        *,
        capture_env: dict[str, str] | None = None,
    ) -> None:
        """Start the long-running browser audio/STT container after an audible probe."""
        call = dict(call)
        call_id = self._build_call_id(call)
        existing = self._active_processes.get(call_id)
        if existing and existing.returncode is None:
            print(f"[STTWorker] {call['ticker']} already running call_id={call_id}")
            return

        command = self._build_audio_capture_command(
            call,
            probe_only=False,
            capture_env=capture_env or {"WEBCAST_LIFECYCLE": "live"},
        )
        print(f"[STTWorker] launching browser audio capture for {call['ticker']} call_id={call_id}")
        process_env = None
        if os.getenv("WEBCAST_CAPTURE_RUNNER", "docker").lower() == "container":
            process_env = {
                **os.environ,
                **(capture_env or {}),
                "CALL_ID": call_id,
            }
        process = await asyncio.create_subprocess_exec(*command, env=process_env)
        self._active_processes[call_id] = process
        asyncio.create_task(self._watch_process(call, call_id, process))

    async def wait_for_active_processes(self, timeout_seconds: float = 120) -> dict[str, int | None]:
        """Wait for currently launched workers; useful for end-to-end verification."""
        active = list(self._active_processes.items())
        if not active:
            return {}

        async def wait_one(call_id: str, process: asyncio.subprocess.Process) -> tuple[str, int | None]:
            return call_id, await process.wait()

        results = await asyncio.wait_for(
            asyncio.gather(*(wait_one(call_id, process) for call_id, process in active)),
            timeout=max(1.0, timeout_seconds),
        )
        return dict(results)

    def _build_audio_capture_command(
        self,
        call: dict[str, Any],
        *,
        probe_only: bool,
        capture_env: dict[str, str] | None = None,
    ) -> list[str]:
        """Build a host-side Docker command so Chromium always has supported libraries."""
        repository_root = Path(__file__).resolve().parents[2]
        compose_file = repository_root / "infra" / "docker-compose.yml"
        call_id = self._build_call_id(call)
        if os.getenv("WEBCAST_CAPTURE_RUNNER", "docker").lower() == "container":
            command = [
                "bash",
                "data_pipeline/scripts/run_webcast_audio_capture.sh",
            ]
            if probe_only:
                command.append("--probe-only")
            command.extend([str(call["ticker"]).upper(), str(call["ir_url"])])
            return command

        command = [
            "docker",
            "compose",
            "-f",
            str(compose_file),
            "--profile",
            "tools",
            "run",
            "--rm",
            "-e",
            f"CALL_ID={call_id}",
        ]
        for key, value in sorted((capture_env or {}).items()):
            command.extend(["-e", f"{key}={value}"])
        command.extend([
            "browser-webcast",
            "data_pipeline/scripts/run_webcast_audio_capture.sh",
        ])
        if probe_only:
            command.append("--probe-only")
        command.extend([str(call["ticker"]).upper(), str(call["ir_url"])])
        return command

    @staticmethod
    def _process_error(
        output: str,
        return_code: int | None,
        *,
        operation: str = "audio probe",
    ) -> str:
        lines = [line.strip() for line in output.splitlines() if line.strip()]
        detail = " | ".join(lines[-8:])
        if not detail:
            detail = "audio was not detected"
        return f"{operation} failed (exit={return_code}): {detail}"[:1000]

    def _build_call_id(self, call) -> str:
        ticker = str(call["ticker"]).upper()
        year = call.get("call_year")
        quarter = call.get("quarter")
        if year and quarter:
            return f"{ticker}-{year}{quarter}"
        if call.get("id"):
            return f"{ticker}-call-{call['id']}"
        return ticker

    @staticmethod
    def _infer_call_quarter(call: dict[str, Any]) -> str | None:
        configured = str(call.get("quarter") or "").strip()
        if configured:
            return configured
        source = " ".join(
            str(call.get(key) or "")
            for key in ("ir_url", "target_url", "source_title")
        )
        match = re.search(r"(?:^|[^a-z])q([1-4])(?:[^a-z]|$)", source, re.IGNORECASE)
        return f"Q{match.group(1)}" if match else None

    def _build_command(self, call, call_id: str) -> list[str]:
        ticker = str(call["ticker"]).upper()
        source = call.get("video_url")
        input_kind = os.getenv("STT_WORKER_INPUT_KIND")
        if not input_kind:
            input_kind = "url" if source else "device"

        command = [
            sys.executable,
            "-m",
            "data_pipeline.stt_worker.take",
            "--ticker",
            ticker,
            "--call-id",
            call_id,
            "--input-kind",
            input_kind,
        ]
        if source and input_kind == "url":
            command.extend(["--input-source", str(source)])
        elif os.getenv("STT_INPUT_SOURCE"):
            command.extend(["--input-source", os.getenv("STT_INPUT_SOURCE", "")])
        if os.getenv("STT_WORKER_DRY_RUN", "false").lower() == "true":
            command.append("--print-ffmpeg-command")
        return command

    async def _resolve_webcast_source(self, call: dict[str, Any]) -> None:
        if call.get("video_url"):
            return
        if not call.get("ir_url"):
            return
        if os.getenv("STT_WEBCAST_DISCOVERY_ENABLED", "true").lower() != "true":
            return

        requested_input_kind = os.getenv("STT_WORKER_INPUT_KIND", "").lower()
        if requested_input_kind and requested_input_kind != "url":
            return

        try:
            try:
                from ..collectors.streams.browser_webcast import BrowserWebcastAgent
            except ImportError:
                from data_pipeline.collectors.streams.browser_webcast import BrowserWebcastAgent

            hold_seconds = float(
                os.getenv(
                    "WEBCAST_DISCOVERY_HOLD_SECONDS",
                    os.getenv("WEBCAST_HOLD_SECONDS", "5"),
                )
            )
            agent = BrowserWebcastAgent(
                str(call["ticker"]),
                str(call["ir_url"]),
                headless=os.getenv("WEBCAST_HEADLESS", "true").lower() != "false",
                hold_seconds=hold_seconds,
                target_year=call.get("call_year"),
                target_quarter=self._infer_call_quarter(call),
            )
            result = await agent.run()
        except Exception as exc:
            raise RuntimeError(f"webcast discovery failed: {exc}") from exc

        if not result.success:
            raise RuntimeError(f"webcast discovery failed: {result.error}")
        if not result.media_candidates:
            raise RuntimeError("webcast discovery did not capture a media URL")

        video_url = result.media_candidates[0]
        call["video_url"] = video_url
        try:
            try:
                from .. import database
            except ImportError:
                import database

            if call.get("id"):
                database.update_call_video_url(call["id"], video_url)
        except Exception as exc:
            print(f"[STTWorker] failed to persist discovered media URL: {exc}")

    async def _watch_process(self, call, call_id: str, process: asyncio.subprocess.Process) -> None:
        return_code = await process.wait()
        self._active_processes.pop(call_id, None)
        status = "completed" if return_code == 0 else "failed"
        try:
            try:
                from .. import database
            except ImportError:
                import database

            if call.get("id"):
                database.update_call_status(call["id"], status)
        except Exception as exc:
            print(f"[STTWorker] failed to persist status for call_id={call_id}: {exc}")
        print(f"[STTWorker] {call_id} exited code={return_code} status={status}")
