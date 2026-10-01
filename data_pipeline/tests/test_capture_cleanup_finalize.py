"""Failure injection for the production shell's isolated-session teardown."""
from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest


class CaptureFinalizeDeadlineTests(unittest.TestCase):
    def test_blocked_finalizer_cannot_keep_browser_or_private_audio_alive(self):
        source = (Path(__file__).resolve().parents[1] / 'scripts' / 'run_webcast_audio_capture.sh').read_text()
        functions = source[source.index('terminate_child() {'):source.index('# Isolate PulseAudio per call.')]
        with tempfile.TemporaryDirectory(prefix='ew-finalize-deadline-') as directory:
            root = Path(directory)
            runtime = root / 'runtime'
            runtime.mkdir()
            pcm = root / 'audio.pcm'
            pcm.write_bytes(b'untouched rescue PCM')
            lock = (root / 'progress.lock').open('w')
            fcntl.flock(lock, fcntl.LOCK_EX)
            bindir = root / 'bin'
            bindir.mkdir()
            fake = bindir / 'python'
            fake.write_text('#!' + sys.executable + '\n' + '''
import fcntl,json,os,pathlib
root=pathlib.Path(os.environ['TEST_ROOT'])
pids=json.loads((root/'children.json').read_text())
alive=[]
for pid in pids:
    try: os.kill(pid,0); alive.append(pid)
    except ProcessLookupError: pass
(root/'finalizer-start.json').write_text(json.dumps({'children_alive':alive,'runtime_exists':(root/'runtime').exists(),'pid':os.getpid()}))
with (root/'progress.lock').open('r') as handle:
    fcntl.flock(handle,fcntl.LOCK_EX)
''')
            fake.chmod(0o700)
            # Separate unrelated session must survive the cleanup completely.
            unrelated = subprocess.Popen(['sleep', '60'], start_new_session=True)
            process = None
            try:
                body = '''
PULSE_SINK_NAME=deadline_test
PULSE_RUNTIME_DIR_OWNED=true
XDG_RUNTIME_DIR="$TEST_ROOT/runtime"
PCM_HANDOFF_FILE="$TEST_ROOT/audio.pcm"
pulseaudio() { echo stopped > "$TEST_ROOT/pulse-stopped"; }
setsid sleep 60 &
PCM_HANDOFF_PID=$!
setsid sleep 60 &
WEBCAST_PID=$!
printf '[%s,%s]' "$PCM_HANDOFF_PID" "$WEBCAST_PID" > "$TEST_ROOT/children.json"
sleep 0.1
exit 78
'''
                env = dict(os.environ, TEST_ROOT=str(root), PATH=str(bindir) + os.pathsep + os.environ['PATH'])
                started = time.monotonic()
                process = subprocess.Popen(['bash', '-c', 'set -euo pipefail\n' + functions + body], env=env,
                                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)
                output, _ = process.communicate(timeout=20)
                elapsed = time.monotonic() - started
                self.assertEqual(process.returncode, 78, output.decode())
                self.assertLess(elapsed, 12, output.decode())
                self.assertIn('finalize_deadline_seconds=5', output.decode())
                self.assertIn('CAPTURE_CLEANUP_DONE', output.decode())
                observed = json.loads((root / 'finalizer-start.json').read_text())
                self.assertEqual(observed['children_alive'], [])
                self.assertFalse(observed['runtime_exists'])
                self.assertTrue((root / 'pulse-stopped').is_file())
                self.assertEqual(pcm.read_bytes(), b'untouched rescue PCM')
                self.assertIsNone(unrelated.poll())
                with self.assertRaises(ProcessLookupError):
                    os.kill(observed['pid'], 0)
            finally:
                if process is not None and process.poll() is None:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
                child_file = root / 'children.json'
                if child_file.exists():
                    for pid in json.loads(child_file.read_text()):
                        try: os.killpg(pid, signal.SIGKILL)
                        except ProcessLookupError: pass
                unrelated.terminate()
                unrelated.wait(timeout=3)
                lock.close()


if __name__ == '__main__':
    unittest.main()
