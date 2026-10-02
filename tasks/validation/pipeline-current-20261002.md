# Data pipeline current-candidate validation — 2026-10-02

## Remote review and adopted scope

- Reviewed fetched `origin/main` (`98d4ab2`), `origin/dague` (`a4d9d46`) and the data-pipeline differences on `origin/hyeongyu` (`ada2265`).
- Dague's pipeline is a separate capture/recovery refactor: 236 pipeline files, approximately 67,051 additions / 15,582 deletions relative to main. It introduces application/storage/browser packages, durable delivery/outbox, capture ownership, schedule evidence and completion proofs. Its repository-wide branch also predates newer backend/AI/terminal changes. A blanket branch merge or isolated copying of the new manager/delivery classes is not justified by this compatibility task.
- Its STT backend payload retains ticker/call_id/sequence/start_ms/end_ms/text/speaker/timestamp/is_session_end and the internal-secret header; the AI analyze payload adds call_id, which the current legacy request ignores. This is wire-schema compatibility, not proof of equivalent lifecycle behavior.
- Hyeongyu's pipeline differences are demo fixtures/import tools, not an additional current capture implementation.
- Adopted only `data_pipeline/tools/learning/__init__.py` and `webcast_learning_batch.py` from dague. Current replay code and two existing test modules already import that absent package. Its database and STTWorkerManager dependencies exist with compatible signatures in the candidate. Root `.gitignore`'s unanchored `learning/` rule explains why that source package was omitted; the parent integration task was notified to correct the ignore scope.

## Demonstrated fixes and tests

The first WSL run stopped during collection with six errors: two missing learning-package imports, missing lxml, and Python 3.10's absence of `datetime.UTC`. Installed lxml 6.1.3 into an ignored, repository-local test dependency folder. Replaced the Python 3.11-only UTC alias with `timezone.utc` in manual transcript import and its assertions, preserving timestamps.

After the two source repairs, current-candidate Linux tests completed:

**143 passed, 17 subtests passed in 15.53 seconds.**

Command, from the current repository in WSL:

```sh
PYTHONPATH=tasks/runtime/linux-extra:/mnt/c/Users/james/source/repos/Earning-Whisperer-review-133/tasks/runtime/linux-python:/mnt/c/Users/james/source/repos/Earning-Whisperer-review-133/tasks/runtime/linux-extra python3 -m pytest data_pipeline/tests -q
```

Log: `tasks/validation/pipeline-current-20261002.log` (ignored artifact). Python 3.10 / WSL; no production database, remote webcast capture or trading orders were used for this suite. `git diff --check -- data_pipeline` passed for the source edits.

## Actual file-audio and full-flow boundary

An offline current-worker file-STT run used the existing synthetic WAV (`review-133/tasks/live-verification/earnings-numeric-clear.wav`) and cached distil-large-v3 on CPU/int8 with eight threads. It explicitly disabled AI delivery, backend delivery, and transcript database archival and exited **0**. The actual decoder returned "Revenue increased 20% because customer demand improved.", "Comparable sales increased 5%." and "Operating margin remained at 20%." The default five-second decoder window / ten-second emit cadence generated sequence 0 (non-final) and sequence 1 (final), preserving all three numeric claims. Its separate log is `tasks/validation/pipeline-file-stt-20261002.log`. Payload prints are generation evidence only; delivery was disabled.

The older `review-133/tasks/live-verification/run_linux_audio_distil.py` cannot be reused unchanged as current end-to-end evidence. It loads that checkout's local secret and sends to WSL ports 28000/28082; the matching spool bridge forwards to Windows ports 18000/18082. Current backend/AI instances, matching secret, and a current websocket/renderer listener must be started and matched before delivery. The bridge verifies service handling through a transport workaround, not normal WSL NAT connectivity. The fixture is synthetic file audio, not microphone/video capture.

No git staging, commit, push, real order, registration submission, or live webcast was performed by this validation subtask.
