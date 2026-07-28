from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import threading
import webbrowser
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


REPO_ROOT = Path(__file__).resolve().parents[3]
COMPOSE_PATH = REPO_ROOT / "infra" / "docker-compose.yml"
OBSERVER_HTML_PATH = Path(__file__).resolve().parents[2] / "static" / "webcast_observer.html"
MANUAL_READY_FILE = "/tmp/ew-visible-webcast-ready"

EVENT_MARKERS = (
    "NOVNC_READY",
    "opening IR page",
    "MANUAL_BROWSER_READY",
    "MANUAL_BROWSER_CONFIRMED",
    "navigation timed out",
    "page access blocked",
    "learned ",
    "using verified recipe",
    "no playback control",
    "opening archive fallback",
    "clicking webcast candidate",
    "registration form",
    "REGISTRATION_REQUIRED",
    "holding failure screen",
    "PLAYBACK_READY",
    "media_candidate=",
    "AUDIO_DETECTED",
    "AUDIO_NOT_DETECTED",
    "HOLDING_SUCCESS_SCREEN",
    "success=",
    "error=",
    "TIMED_OUT",
    "EXITED_BEFORE",
)

FAILURE_MARKERS = (
    "AUDIO_NOT_DETECTED",
    "success=False",
    "error=",
    "TIMED_OUT",
    "EXITED_BEFORE",
    "page access blocked",
    "registration form handling failed",
    "REGISTRATION_REQUIRED",
)

LOG_NOISE_PATTERNS = (
    re.compile(r"^W: \[pulseaudio\] main\.c:"),
    re.compile(r"^The XKEYBOARD keymap compiler"),
    re.compile(r"^> Warning:\s+Could not resolve keysym"),
    re.compile(r"^Errors from xkbcomp are not fatal"),
)


@dataclass(frozen=True)
class Phase:
    key: str
    label: str
    detail: str
    index: int
    tone: str


PHASES = (
    Phase("starting", "실행 준비", "컨테이너와 가상 장치를 준비합니다.", 0, "neutral"),
    Phase("browser", "브라우저 연결", "실제 Chromium 화면을 연결했습니다.", 1, "active"),
    Phase("manual", "수동 확인 대기", "필요한 동의나 접근 확인을 처리할 수 있습니다.", 2, "warning"),
    Phase("analysis", "페이지 분석", "DOM과 저장된 레시피로 재생 경로를 찾습니다.", 3, "active"),
    Phase("player", "플레이어 진입", "후보 클릭과 등록 폼 처리를 수행합니다.", 4, "active"),
    Phase("playback", "재생 확인", "플레이어 재생 준비를 확인합니다.", 5, "active"),
    Phase("audio", "오디오 검사", "가상 오디오 장치의 입력을 측정합니다.", 6, "active"),
    Phase("success", "검증 성공", "브라우저 오디오가 가상 장치에 도달했습니다.", 7, "success"),
)


def _phase(key: str) -> Phase:
    return next(phase for phase in PHASES if phase.key == key)


def classify_phase(logs: str, *, running: bool, exit_code: int | None) -> Phase:
    if "AUDIO_DETECTED" in logs:
        return _phase("success")
    if any(marker in logs for marker in FAILURE_MARKERS):
        current = _phase("audio") if "AUDIO_" in logs else _phase("player")
        return Phase("failed", "검증 실패", latest_error(logs), current.index, "danger")
    if "PLAYBACK_READY_CONFIRMED" in logs:
        return _phase("audio")
    if " PLAYBACK_READY path=" in logs:
        return _phase("playback")
    if "clicking webcast candidate" in logs or "registration form detected" in logs:
        return _phase("player")
    if (
        "learned " in logs
        or "using verified recipe" in logs
        or "MANUAL_BROWSER_CONFIRMED" in logs
    ):
        return _phase("analysis")
    if "MANUAL_BROWSER_READY" in logs:
        return _phase("manual")
    if "NOVNC_READY" in logs or "opening IR page" in logs:
        return _phase("browser")
    if not running and exit_code is not None:
        return Phase("stopped", "실행 종료", f"컨테이너 종료 코드: {exit_code}", 0, "neutral")
    return _phase("starting")


def latest_error(logs: str) -> str:
    for line in reversed(logs.splitlines()):
        if any(marker in line for marker in FAILURE_MARKERS):
            return line.strip()[:240]
    return "자동화가 완료되지 않았습니다."


def stage_values(current: Phase) -> list[dict[str, str]]:
    values = []
    for phase in PHASES:
        if current.key == "failed" and phase.index == current.index:
            status = "failed"
        elif phase.index < current.index or current.key == "success":
            status = "complete"
        elif phase.index == current.index:
            status = "active"
        else:
            status = "pending"
        values.append(
            {
                "key": phase.key,
                "label": phase.label,
                "detail": phase.detail,
                "status": status,
            }
        )
    return values


def visible_events(logs: str) -> list[str]:
    return [
        line.strip()
        for line in logs.splitlines()
        if any(marker in line for marker in EVENT_MARKERS)
    ][-80:]


def clean_logs(logs: str) -> str:
    return "\n".join(
        line
        for line in logs.splitlines()
        if not any(pattern.search(line) for pattern in LOG_NOISE_PATTERNS)
    )


def _run_output(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )


class VisibleWebcastRun:
    def __init__(self, args: argparse.Namespace) -> None:
        ticker_slug = re.sub(r"[^a-z0-9]+", "-", args.ticker.lower()).strip("-") or "target"
        self.ticker = args.ticker.upper()
        self.url = args.url
        self.vnc_port = args.vnc_port
        self.container_name = f"ew-visible-webcast-{ticker_slug}-{os.getpid()}"
        self.args = args
        self._stopped = False

    @property
    def compose_prefix(self) -> list[str]:
        return [
            "docker",
            "compose",
            "-f",
            str(COMPOSE_PATH),
            "--profile",
            "tools",
        ]

    def start(self) -> None:
        if not self.args.skip_db:
            database = _run_output([*self.compose_prefix, "up", "-d", "db"])
            if database.returncode != 0:
                raise RuntimeError(database.stdout.strip() or "MySQL container did not start.")

        command = [
            *self.compose_prefix,
            "run",
            "-d",
            "--name",
            self.container_name,
            "-p",
            f"127.0.0.1:{self.vnc_port}:6080",
            "-e",
            "WEBCAST_CAPTURE_RUNNER=container",
            "-e",
            "WEBCAST_HEADED=true",
            "-e",
            "WEBCAST_VNC_ENABLED=true",
            "-e",
            "WEBCAST_VNC_WEB_PORT=6080",
            "-e",
            f"WEBCAST_MANUAL_READY_FILE={MANUAL_READY_FILE}",
            "-e",
            f"WEBCAST_MANUAL_READY_TIMEOUT_SECONDS={self.args.manual_timeout}",
            "-e",
            f"WEBCAST_PLAYBACK_READY_TIMEOUT_SECONDS={self.args.playback_timeout}",
            "-e",
            f"WEBCAST_AUDIO_WARMUP_SECONDS={self.args.audio_warmup}",
            "-e",
            f"DATE_STREAM_AUDIO_WAIT_SECONDS={self.args.audio_wait}",
            "-e",
            f"WEBCAST_LIFECYCLE={self.args.lifecycle}",
            "-e",
            "WEBCAST_ALLOW_REGISTRATION_SUBMISSION="
            f"{'true' if self.args.allow_registration_submission else 'false'}",
            "-e",
            f"WEBCAST_FAILURE_HOLD_SECONDS={self.args.failure_hold}",
            "-e",
            f"WEBCAST_SUCCESS_HOLD_SECONDS={self.args.success_hold}",
            "browser-webcast",
            "bash",
            "data_pipeline/scripts/run_webcast_audio_capture.sh",
        ]
        if not self.args.with_stt:
            command.append("--probe-only")
        command.extend([self.ticker, self.url])
        result = _run_output(command)
        if result.returncode != 0:
            raise RuntimeError(result.stdout.strip() or "Visible webcast container did not start.")

    def container_state(self) -> dict[str, Any]:
        result = _run_output(
            ["docker", "inspect", "--format", "{{json .State}}", self.container_name]
        )
        if result.returncode != 0:
            return {"Running": False, "ExitCode": None, "Status": "missing"}
        try:
            return json.loads(result.stdout.strip())
        except json.JSONDecodeError:
            return {"Running": False, "ExitCode": None, "Status": "unknown"}

    def logs(self) -> str:
        result = _run_output(["docker", "logs", "--tail", "500", self.container_name])
        return result.stdout

    def status(self) -> dict[str, Any]:
        state = self.container_state()
        logs = self.logs()
        display_logs = clean_logs(logs)
        running = bool(state.get("Running"))
        exit_code = state.get("ExitCode")
        current = classify_phase(logs, running=running, exit_code=exit_code)
        waiting_manual = (
            "MANUAL_BROWSER_READY" in logs
            and "MANUAL_BROWSER_CONFIRMED" not in logs
            and running
        )
        return {
            "ticker": self.ticker,
            "url": self.url,
            "container": self.container_name,
            "container_status": state.get("Status", "unknown"),
            "running": running,
            "exit_code": exit_code,
            "phase": {
                "key": current.key,
                "label": current.label,
                "detail": current.detail,
                "tone": current.tone,
            },
            "stages": stage_values(current),
            "events": visible_events(logs),
            "logs": display_logs[-30000:],
            "can_confirm": waiting_manual,
            "vnc_ready": "NOVNC_READY" in logs and running,
            "vnc_url": (
                f"http://127.0.0.1:{self.vnc_port}/vnc.html"
                "?autoconnect=true&resize=scale"
            ),
        }

    def confirm_manual_step(self) -> tuple[bool, str]:
        result = _run_output(
            ["docker", "exec", self.container_name, "touch", MANUAL_READY_FILE]
        )
        return result.returncode == 0, result.stdout.strip()

    def stop(self) -> tuple[bool, str]:
        if self._stopped:
            return True, ""
        result = _run_output(["docker", "rm", "-f", self.container_name])
        self._stopped = result.returncode == 0
        return self._stopped, result.stdout.strip()


class ObserverHandler(BaseHTTPRequestHandler):
    server: "ObserverServer"

    def _send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/":
            body = OBSERVER_HTML_PATH.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/api/status":
            self._send_json(self.server.visible_run.status())
            return
        if path == "/health":
            self._send_json({"ok": True})
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/confirm":
            ok, detail = self.server.visible_run.confirm_manual_step()
            self._send_json(
                {"ok": ok, "detail": detail},
                HTTPStatus.OK if ok else HTTPStatus.CONFLICT,
            )
            return
        if path == "/api/stop":
            ok, detail = self.server.visible_run.stop()
            self._send_json(
                {"ok": ok, "detail": detail},
                HTTPStatus.OK if ok else HTTPStatus.CONFLICT,
            )
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def log_message(self, format: str, *args: object) -> None:
        return


class ObserverServer(ThreadingHTTPServer):
    def __init__(
        self,
        address: tuple[str, int],
        visible_run: VisibleWebcastRun,
    ) -> None:
        self.visible_run = visible_run
        super().__init__(address, ObserverHandler)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a visible earnings-webcast browser with a local observer dashboard."
    )
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--url", required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--vnc-port", type=int, default=6080)
    parser.add_argument("--lifecycle", choices=("unknown", "pre_live", "live", "replay"), default="replay")
    parser.add_argument("--manual-timeout", type=int, default=900)
    parser.add_argument("--playback-timeout", type=int, default=180)
    parser.add_argument("--audio-warmup", type=int, default=5)
    parser.add_argument("--audio-wait", type=int, default=35)
    parser.add_argument("--with-stt", action="store_true")
    parser.add_argument(
        "--auto-start",
        action="store_true",
        help="Begin browser discovery automatically after a short observer delay.",
    )
    parser.add_argument(
        "--auto-start-delay",
        type=float,
        default=5,
        help="Seconds to keep the visible browser paused before automatic discovery.",
    )
    parser.add_argument(
        "--allow-registration-submission",
        action="store_true",
        help="Allow configured profile fields to be submitted to the selected third-party webcast.",
    )
    parser.add_argument(
        "--failure-hold",
        type=float,
        default=60,
        help="Seconds to keep the redacted terminal browser state visible.",
    )
    parser.add_argument(
        "--success-hold",
        type=float,
        default=60,
        help="Seconds to keep Chromium and VNC visible after audio success.",
    )
    parser.add_argument("--skip-db", action="store_true")
    parser.add_argument("--no-open", action="store_true")
    parser.add_argument("--keep-container", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not OBSERVER_HTML_PATH.exists():
        raise SystemExit(f"Observer UI is missing: {OBSERVER_HTML_PATH}")

    visible_run = VisibleWebcastRun(args)
    server = ObserverServer((args.host, args.port), visible_run)
    auto_start_timer: threading.Timer | None = None
    try:
        visible_run.start()
        dashboard_url = f"http://{args.host}:{args.port}"
        print(f"VISIBLE_WEBCAST_READY url={dashboard_url}", flush=True)
        print(f"container={visible_run.container_name}", flush=True)
        if args.auto_start:
            auto_start_timer = threading.Timer(
                max(0.0, args.auto_start_delay),
                visible_run.confirm_manual_step,
            )
            auto_start_timer.daemon = True
            auto_start_timer.start()
            print(
                f"AUTO_DISCOVERY_SCHEDULED delay={max(0.0, args.auto_start_delay):g}s",
                flush=True,
            )
        if not args.no_open:
            threading.Timer(0.5, lambda: webbrowser.open(dashboard_url)).start()
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        print("\nStopping visible webcast observer...", flush=True)
    finally:
        if auto_start_timer:
            auto_start_timer.cancel()
        server.server_close()
        if not args.keep_container:
            visible_run.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
