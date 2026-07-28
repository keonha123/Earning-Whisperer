from __future__ import annotations

import argparse
import io
import math
import os
import shutil
import struct
import subprocess
import threading
import wave
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


MOCK_LIVE_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>EWTEST Earnings Call Webcast</title>
  <style>
    body { font: 16px system-ui, sans-serif; margin: 40px; background: #f4f6f8; }
    main { max-width: 760px; margin: auto; background: white; padding: 32px; }
    label { display: block; margin-top: 14px; font-weight: 600; }
    input, select, button { box-sizing: border-box; width: 100%; padding: 10px; margin-top: 6px; }
    button { cursor: pointer; }
    #player-shell { margin-top: 24px; padding: 20px; border: 2px solid #1d7a46; }
    #webcast-video { display: block; width: 100%; max-width: 640px; background: #111; }
    #status { color: #1d7a46; font-weight: 600; }
  </style>
</head>
<body>
  <main>
    <h1>EWTEST Q4 Earnings Call</h1>
    <p>This local page simulates a registration-gated earnings webcast.</p>
    <section id="registration-gate">
      <h2>Complete this form to enter the webcast</h2>
      <form id="registration-form">
        <label for="first_name">First Name</label>
        <input id="first_name" name="first_name" required>
        <label for="last_name">Last Name</label>
        <input id="last_name" name="last_name" required>
        <label for="company">Company</label>
        <input id="company" name="company" required>
        <label for="email">Email</label>
        <input id="email" name="email" type="email" required>
        <label for="industry_affiliation">Industry Affiliation</label>
        <select id="industry_affiliation" name="industry_affiliation" required>
          <option value="">Select one</option>
          <option value="Other">Other</option>
          <option value="Investor">Investor</option>
        </select>
        <button type="submit">Enter webcast</button>
      </form>
    </section>
    <section id="player-shell" hidden>
      <h2>Webcast player</h2>
      <p id="status">Registration accepted. Press play to start the webcast.</p>
      <video id="webcast-video" preload="auto" loop playsinline src="/sample.mp4"></video>
      <button id="play-webcast" type="button" aria-label="Play webcast" title="Play webcast">
        Play webcast
      </button>
    </section>
  </main>
  <script>
    const form = document.querySelector('#registration-form');
    const gate = document.querySelector('#registration-gate');
    const shell = document.querySelector('#player-shell');
    const video = document.querySelector('#webcast-video');
    const play = document.querySelector('#play-webcast');
    const status = document.querySelector('#status');
    form.addEventListener('submit', event => {
      event.preventDefault();
      gate.hidden = true;
      shell.hidden = false;
      video.load();
      status.textContent = 'Registration accepted. Press play to start the webcast.';
    });
    play.addEventListener('click', async () => {
      video.muted = false;
      video.volume = 1;
      await video.play();
      status.textContent = 'Webcast playing';
    });
  </script>
</body>
</html>
"""

MOCK_PRELIVE_HTML = """<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>EWTEST Earnings Call</title></head>
<body data-event-state="pre_live">
  <main>
    <h1>EWTEST Q4 Earnings Call</h1>
    <p>Entry to the live presentation is not yet available. Please come back closer to the scheduled start time.</p>
    <p>The webcast is scheduled for <time id="scheduled-at"></time>.</p>
  </main>
</body>
</html>
"""

# Keep the original fixture name for tests and small local tools.
MOCK_HTML = MOCK_LIVE_HTML

MOCK_SPEECH_TEXT = (
    "This is a local earnings call test. Revenue increased and management maintained "
    "full year guidance. The Earning Whisperer pipeline should capture this audio."
)
_speech_audio_cache: bytes | None = None
_video_media_cache: bytes | None = None
_post_lock = threading.Lock()


def build_wav_bytes(duration_seconds: float = 30, frequency_hz: float = 440) -> bytes:
    """Generate a deterministic audible fixture without adding a binary asset."""
    sample_rate = 16_000
    frame_count = max(1, int(sample_rate * duration_seconds))
    frames = bytearray()
    for index in range(frame_count):
        sample = int(0.28 * 32767 * math.sin(2 * math.pi * frequency_hz * index / sample_rate))
        frames.extend(struct.pack("<h", sample))

    output = io.BytesIO()
    with wave.open(output, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(bytes(frames))
    return output.getvalue()


def build_speech_wav_bytes() -> bytes:
    """Use the container's speech synthesizer, with an audible tone fallback."""
    global _speech_audio_cache
    if _speech_audio_cache is not None:
        return _speech_audio_cache

    if os.getenv("MOCK_WEBCAST_AUDIO_MODE", "speech").lower() == "speech" and shutil.which("espeak-ng"):
        try:
            result = subprocess.run(
                ["espeak-ng", "--stdout", "-v", "en-us", "-s", "145", MOCK_SPEECH_TEXT],
                check=True,
                capture_output=True,
            )
            if result.stdout.startswith(b"RIFF"):
                _speech_audio_cache = result.stdout
                return result.stdout
        except (OSError, subprocess.CalledProcessError):
            pass

    _speech_audio_cache = build_wav_bytes()
    return _speech_audio_cache


def build_video_media_bytes() -> bytes:
    """Mux the deterministic speech fixture into a short real MP4 video."""
    global _video_media_cache
    if _video_media_cache is not None:
        return _video_media_cache

    if shutil.which("ffmpeg"):
        try:
            result = subprocess.run(
                [
                    "ffmpeg",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-f",
                    "lavfi",
                    "-i",
                    "color=c=black:s=640x360:r=1",
                    "-i",
                    "pipe:0",
                    "-shortest",
                    "-c:v",
                    "libx264",
                    "-tune",
                    "stillimage",
                    "-pix_fmt",
                    "yuv420p",
                    "-c:a",
                    "aac",
                    "-movflags",
                    "frag_keyframe+empty_moov",
                    "-f",
                    "mp4",
                    "pipe:1",
                ],
                input=build_speech_wav_bytes(),
                check=True,
                capture_output=True,
            )
            if result.stdout.startswith(b"ftyp") or b"ftyp" in result.stdout[:64]:
                _video_media_cache = result.stdout
                return result.stdout
        except (OSError, subprocess.CalledProcessError):
            pass

    raise RuntimeError("ffmpeg is required to build the local video fixture")


class MockWebcastHandler(BaseHTTPRequestHandler):
    server_version = "EarningWhispererMockWebcast/1.0"
    posts: list[tuple[str, bytes]] = []
    scheduled_at: datetime | None = None

    @classmethod
    def set_scheduled_at(cls, scheduled_at: datetime | None) -> None:
        cls.scheduled_at = scheduled_at

    @classmethod
    def event_is_live(cls) -> bool:
        return cls.scheduled_at is None or datetime.now() >= cls.scheduled_at

    @classmethod
    def page_payload(cls) -> bytes:
        if cls.event_is_live():
            return MOCK_LIVE_HTML.encode("utf-8")
        scheduled_text = cls.scheduled_at.isoformat(timespec="seconds") if cls.scheduled_at else ""
        return MOCK_PRELIVE_HTML.replace(
            '<time id="scheduled-at"></time>',
            f'<time id="scheduled-at">{scheduled_text}</time>',
        ).encode("utf-8")

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        request_path = self.path.split("?", 1)[0]
        if request_path == "/sample.mp4":
            payload = build_video_media_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        if request_path == "/health":
            payload = b"ok\n"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return

        payload = self.page_payload()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
        content_length = int(self.headers.get("Content-Length", "0"))
        payload = self.rfile.read(content_length)
        with _post_lock:
            self.posts.append((self.path.split("?", 1)[0], payload))
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"accepted":true}\n')

    def log_message(self, format: str, *args: object) -> None:
        print(f"[MockWebcast] {format % args}", flush=True)


def run_server(host: str = "127.0.0.1", port: int = 8787) -> None:
    server = ThreadingHTTPServer((host, port), MockWebcastHandler)
    print(f"[MockWebcast] serving http://{host}:{port}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Serve a local registration-gated webcast fixture.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args()
    run_server(args.host, args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
