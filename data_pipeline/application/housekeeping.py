"""Recover stale work, retry delivery and maintain bounded runtime data."""

from __future__ import annotations

import os
from sqlalchemy.exc import SQLAlchemyError


class HousekeepingService:
    def __init__(self, repository, health):
        self.repository = repository
        self.health = health

    def maintain_transcript_archive(self):
        """Keep transcript history bounded while retaining recent recovery data."""
        from ..maintenance import purge_webcast_artifacts
        from ..operations import purge_operation_logs

        retention_days = max(1, int(os.getenv("TRANSCRIPT_RETENTION_DAYS", "180")))
        deleted = self.repository.purge_transcript_segments(
            retention_days,
            batch_size=int(os.getenv("TRANSCRIPT_PURGE_BATCH_SIZE", "10000")),
            max_batches=int(os.getenv("TRANSCRIPT_PURGE_MAX_BATCHES", "10")),
        )
        artifact_deleted = purge_webcast_artifacts(
            int(os.getenv("WEBCAST_ARTIFACT_RETENTION_DAYS", "14")),
            max_groups=int(os.getenv("WEBCAST_ARTIFACT_MAX_GROUPS", "2000")),
        )
        operation_deleted = purge_operation_logs(
            int(os.getenv("OPERATIONS_LOG_RETENTION_DAYS", "30")),
            max_files=int(os.getenv("OPERATIONS_LOG_MAX_FILES", "2000")),
        )
        if deleted:
            print(
                f"[TranscriptArchive] purged {deleted} segments "
                f"older than {retention_days} days"
            )
        if artifact_deleted:
            print(f"[WebcastArtifacts] purged {artifact_deleted} generated files")
        if operation_deleted:
            print(f"[OperationsLog] purged {operation_deleted} old files")


    def retry_transcript_outbox(self):
        """Retry durable transcript deliveries without starting a Whisper worker."""
        try:
            self.repository.ping_database()
        except SQLAlchemyError as exc:
            self.health.database_unavailable("transcript_outbox_retry", exc)
            return
        self.health.database_recovered("transcript_outbox_retry")
        from ..stt_worker.delivery import retry_transcript_outbox_once
        retry_transcript_outbox_once(
            int(os.getenv("TRANSCRIPT_OUTBOX_RETRY_BATCH_SIZE", "50"))
        )


    def recover_stale_stream_operations(self, *, recover_local_orphans: bool = False):
        """Release probe/capture leases left behind by a crash or restart."""
        try:
            recovered = self.repository.recover_stale_stream_operations(
                recover_local_orphans=recover_local_orphans,
            )
        except SQLAlchemyError as exc:
            self.health.database_unavailable("stale_operation_recovery", exc)
            return {"probes": 0, "captures": 0}
        self.health.database_recovered("stale_operation_recovery")
        if recovered["probes"] or recovered["captures"]:
            self.health.record_event(
                "stale_operations_recovered",
                status="recovered",
                probes=recovered["probes"],
                captures=recovered["captures"],
            )
            print(
                "[Recovery] released stale operations "
                f"probes={recovered['probes']} captures={recovered['captures']}"
            )


    def check_operational_alerts(self):
        """Check DB/runtime counters and emit deduplicated operator alerts."""
        try:
            self.repository.ping_database()
        except SQLAlchemyError as exc:
            self.health.database_unavailable("operational_alert_check", exc)
            return
        self.health.database_recovered("operational_alert_check")
        from ..operations import check_operational_alerts
        check_operational_alerts()


    def write_operations_report(self):
        """Write the current UTC day's machine-readable and human-readable report."""
        from ..operations import write_daily_report
        json_path, markdown_path = write_daily_report()
        print(f"[OperationsReport] JSON={json_path} Markdown={markdown_path}")
