# Current candidate Linux/STT validation — 2026-10-01

## Observed result

The current candidate Linux suite and actual audio transcription remain **unverified**. The attempted WSL execution failed before pytest started with `Wsl/Service/E_ACCESSDENIED`. The normal escalation request was subsequently aborted by the user. It was not retried or bypassed. `tasks/validation/linux-pipeline.log` does not exist, confirming that no test result was captured by this attempt.

The requested command would run `python3 -m pytest data_pipeline/tests -q` from the current candidate, using the existing review-133 Linux Python dependencies. No source modification was made in this validation task.

## Existing environment and evidence boundary

- Existing runtime: review-133 `tasks/runtime/linux-python` and `tasks/runtime/linux-extra`, WSL Ubuntu 22.04 / Python 3.10.
- Existing model/cache: distil-large-v3, CPU 8 threads / int8, review-133 `tasks/runtime/huggingface`.
- Existing audio fixture: review-133 `tasks/live-verification/earnings-numeric-clear.wav`. This is synthetic **file audio**, not a microphone recording.
- Existing runner: review-133 `tasks/live-verification/run_linux_audio_distil.py`. It imports the STT worker, sets ports 28000/28082, and uses the prior disposable HTTP bridge. Running this unchanged would not demonstrate the current backend/AI candidate on ports 19082/19000.
- Prior WSL-to-Windows delivery used a file spool HTTP bridge because direct NAT access was unavailable. Such evidence must be labeled as a transport workaround, not proof of normal production networking.
- Prior Sept30 Linux/STT tests and audio-to-screen results belong to an earlier candidate. They do not establish current candidate test, microphone, backend delivery, or renderer success.

## Release implication

Do not claim current Linux suite success, current file-audio STT success, microphone support verification, or current Linux audio-to-backend-to-renderer completion. A permitted WSL execution and a current-candidate service/listener run remain necessary to establish those results. The user-aborted escalation is a material validation limitation, not a discovered source-code failure.
