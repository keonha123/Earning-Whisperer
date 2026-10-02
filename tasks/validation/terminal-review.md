# Terminal validation — 2026-10-01

## Execution results

- `npm ci --ignore-scripts`: default launcher referenced missing roaming npm-cli.js; explicit `C:\Program Files\nodejs\npm.cmd` reached npm 10.9.2 with Node 22.17.0 but failed with sandbox EPERM reading npm cache. Escalated retry was user-aborted after 1226 seconds. No successful installation is claimed.
- Existing dependency tree is incomplete. Explicit npm test, typecheck, build failed because vitest, tsc, electron-vite executables respectively are unavailable. Logs: terminal-install.log, terminal-test.log, terminal-typecheck.log, terminal-build.log. These are environment/incomplete dependency failures, not evidence of source test failures.
- Native keytar postinstall was intentionally excluded by --ignore-scripts; native module readiness is unverified.
- npm audit has not completed. No vulnerability count, severity classification, or remediation claim is made; no forced upgrades applied.

## Source contract review

- Electron StompService connects to /ws-native with `Authorization: Bearer` STOMP CONNECT header and refuses connection without backendToken. Its transcript subscription consumes /topic/transcript/{ticker} and forwards unchanged payload through TRANSCRIPT_SEGMENT_RECEIVED IPC. STOMP authentication failure refreshes token once before backoff; client SEND is not used for transcript delivery.
- preload on() strips Electron event and forwards payload; useLiveTranscript routes it to useTranscriptStore. Store preserves text_ko as textKo, permits a late translation patch after session end, and rejects patches that alter original text or segment timing. Existing store tests cover late translation behavior, but were not executed successfully in this run.
- TranscriptQuestion invokes TRANSCRIPT_ASK with ticker, call_id, segment_sequences, question; wsHandlers delegates to BackendClient POST /api/v1/transcript/ask, with 18-second timeout and authenticated HTTP interceptor. Answers, refusal/warnings, evidence and matching citation indices render together. Links restrict protocols to HTTP/HTTPS.
- Call identity review: STTScriptPanel renders TranscriptQuestion with key `${line.ticker}:${line.callId}:${line.sequence}` at line 210. A changed call/sequence remounts local state, so an old request resolving on the old component cannot put its answer under the new identity. Enclosing row key is line.id; TradingRoomPage assigns callId-sequence ids.

## Limits

Source compatibility does not establish an actual authenticated backend → Electron main → preload → visible renderer translation/QA roundtrip. That latest-candidate runtime path remains unverified. Historical runs in review-133 do not replace this evidence. A successful dependency install, native readiness, full terminal tests/typecheck/build and registry audit remain outstanding.
