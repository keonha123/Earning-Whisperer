# Backend candidate verification

Candidate: youngjun `a3ea806` with main `6a2cdfc` merge in progress.

## Test execution

- Attempted complete `gradlew.bat test --no-daemon --console=plain` with prescribed JDK 17.0.20.1 and review-133 Gradle cache.
- Compilation stopped before tests: `AccessDeniedException` opening cached `com.fasterxml:classmate:1.7.0` JAR. Evidence: `backend-tests.log`.
- Required unrestricted retry was requested; approval tool was aborted by the user after approximately 19 minutes. No retry result exists.
- Read-only process inspection after interruption found no Java processes and zero candidate test-result XML files.
- This is an environment access failure; backend suite is **unverified**, not a demonstrated code regression or successful run.

## Source contract review

- STOMP CONNECT/STOMP frames require Bearer JWT; subsequent SUBSCRIBE frames require the interceptor's typed authenticated Principal. Anonymous subscriptions and authenticated client SEND remain rejected.
- Authentication ERROR text remains `STOMP 인증 실패`, matching terminal token-refresh contract. Real protocol-handler test verifies the error frame and absence of token disclosure.
- Translation worker posts ticker/call/sequence/original text and publishes only available responses matching all four identities. Original transcripts publish independently of translation availability.
- QA controller requires a completed server-side transcript session, resolves selected sequence identities to stored text, rejects unknown/duplicate selections, and supplies selected timestamp as `as_of`. Client evidence text is not accepted.
- QA responses must match ticker, call ID and selected sequences; unavailable AI returns HTTP 503 and mismatched identity returns HTTP 502.

These source observations do not replace live candidate backend→Electron translation/QA testing. No candidate server or actual JWT runtime smoke was started by this reviewer; live integration remains unverified.
