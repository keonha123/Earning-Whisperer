import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from data_pipeline.stt_worker.pcm_handoff import follow_pcm


class PcmHandoffTest(unittest.TestCase):
    def test_controlled_stop_drains_final_producer_audio_before_done(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'call.pcm'
            # Tail exceeds an OS pipe buffer: a recorder that stops reading
            # immediately on SIGTERM will truncate it and block the producer.
            producer_code = (
                "import signal,sys,time\n"
                "def stop(*args):\n"
                " sys.stdout.buffer.write(b'z'*128000);sys.stdout.buffer.flush();sys.exit(0)\n"
                "signal.signal(signal.SIGTERM,stop)\n"
                "sys.stdout.buffer.write(b'a'*32000);sys.stdout.buffer.flush()\n"
                "while True: time.sleep(.1)\n"
            )
            process = subprocess.Popen([sys.executable, '-m', 'data_pipeline.stt_worker.pcm_handoff',
                '--record', str(path), '--max-bytes', '256000', '--', sys.executable, '-c', producer_code],
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            try:
                deadline = time.monotonic() + 5
                while (not path.exists() or path.stat().st_size < 32000) and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertEqual(path.stat().st_size, 32000)
                process.terminate()
                self.assertEqual(process.wait(timeout=8), 130)
                output = io.BytesIO()
                self.assertEqual(follow_pcm(path, output), 130)
                self.assertEqual(output.getvalue(), b'a'*32000 + b'z'*128000)
                self.assertEqual(json.loads(Path(str(path)+'.done').read_text())['bytes'], 160000)
            finally:
                if process.poll() is None:
                    process.kill()
                process.communicate()

    def test_late_consumer_gets_every_numbered_sample_once(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'call.pcm'
            expected = b''.join(index.to_bytes(2, 'little') * 8000 for index in range(8))
            producer_code = (
                "import sys,time\n"
                "for index in range(8):\n"
                " sys.stdout.buffer.write(index.to_bytes(2,'little')*8000);sys.stdout.buffer.flush();time.sleep(.1)\n"
            )
            process = subprocess.Popen([sys.executable, '-m', 'data_pipeline.stt_worker.pcm_handoff',
                '--record', str(path), '--max-bytes', '256000', '--', sys.executable, '-c', producer_code],
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            try:
                deadline = time.monotonic() + 5
                while (not path.exists() or path.stat().st_size < 32000) and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertGreaterEqual(path.stat().st_size, 32000)
                output = io.BytesIO()
                code = follow_pcm(path, output, producer_pid=process.pid, idle_timeout=3)
                self.assertEqual(code, 0)
                self.assertEqual(output.getvalue(), expected)
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                self.assertEqual(process.wait(timeout=3), 0)
            finally:
                if process.poll() is None:
                    process.kill()
                process.communicate()

    def test_size_limit_is_an_error_not_successful_end_of_call(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'call.pcm'
            result = subprocess.run([sys.executable, '-m', 'data_pipeline.stt_worker.pcm_handoff',
                '--record', str(path), '--max-bytes', '32000', '--', sys.executable, '-c',
                "import sys;sys.stdout.buffer.write(b'x'*128000)"], capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 74, result.stderr)
            self.assertLessEqual(path.stat().st_size, 32000)
            self.assertEqual(follow_pcm(path, io.BytesIO()), 74)

    def test_producer_crash_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'call.pcm'
            path.write_bytes(b'12')
            Path(str(path)+'.done').write_text(json.dumps({'exit_code':17}))
            output=io.BytesIO()
            self.assertEqual(follow_pcm(path,output),17)
            self.assertEqual(output.getvalue(),b'12')

    def test_missing_producer_is_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(follow_pcm(Path(directory)/'never-created', io.BytesIO(),idle_timeout=.05),70)

    def test_spooled_input_waits_for_consumer_without_dropping_prefix(self):
        import queue
        from data_pipeline.stt_worker.take import _AudioReaderState, _read_audio_continuously
        expected = b''.join(i.to_bytes(2, 'little') * 16000 for i in range(10))
        producer = subprocess.Popen([sys.executable,'-c',
            "import sys;sys.stdout.buffer.write(b''.join(i.to_bytes(2,'little')*16000 for i in range(10)))"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        audio_queue = queue.Queue(maxsize=1)
        state = _AudioReaderState(threading.Event(), threading.Event(), time.monotonic())
        reader = threading.Thread(target=_read_audio_continuously, args=(producer,audio_queue,state),
                                  kwargs={'chunk_bytes':32000, 'preserve_backlog':True})
        reader.start()
        try:
            time.sleep(.2)  # Deliberately hold the consumer beyond queue capacity.
            self.assertEqual(state.dropped_bytes,0)
            collected=bytearray()
            while not state.finished.is_set() or not audio_queue.empty():
                try: collected.extend(audio_queue.get(timeout=.2))
                except queue.Empty: pass
            reader.join(2)
            self.assertFalse(reader.is_alive())
            self.assertEqual(bytes(collected),expected)
            self.assertEqual(state.dropped_bytes,0)
        finally:
            state.stop_requested.set()
            producer.terminate()
            producer.wait(timeout=3)
            producer.stdout.close()
            reader.join(2)
