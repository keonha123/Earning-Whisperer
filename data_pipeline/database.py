"""Stable database API; implementations live in storage by responsibility."""

if not __package__:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data_pipeline.storage.connection import (
    DB_URL,
    engine,
    ping_database,
)

from data_pipeline.storage.health import (
    get_operational_health_snapshot,
)

from data_pipeline.storage.learning import (
    _best_webcast_learning_url,
    _webcast_learning_target_key,
    _webcast_replay_target_key,
    claim_historical_replay_discovery,
    claim_historical_replay_target,
    claim_webcast_learning_target,
    claim_webcast_training_surface_target,
    get_generalized_webcast_patterns,
    get_historical_replay_calls,
    get_historical_replay_coverage_summary,
    get_historical_replay_discovery_summary,
    get_historical_replay_discovery_tickers,
    get_historical_replay_error_records,
    get_historical_replay_summary,
    get_historical_replay_targets,
    get_verified_human_workflows,
    get_verified_webcast_recipes,
    get_verified_webcast_recipes_for_benchmark,
    get_webcast_learning_summary,
    get_webcast_learning_targets,
    get_webcast_training_surface_coverage,
    get_webcast_training_surface_details,
    get_webcast_training_surface_risks,
    get_webcast_training_surface_summary,
    get_webcast_training_surface_targets,
    prioritize_webcast_learning_targets,
    record_historical_replay_discovery,
    record_historical_replay_outcome,
    record_webcast_learning_target_outcome,
    record_webcast_recipe_outcome,
    record_webcast_training_surface_outcome,
    recover_stale_historical_replay_targets,
    recover_stale_webcast_training_surface_audits,
    save_historical_replay_targets,
    save_webcast_recipe,
)

from data_pipeline.storage.live_calls import (
    _is_dead_local_worker_owner,
    _linux_process_start_token,
    _local_worker_owner_details,
    _pipeline_worker_id,
    claim_stream_probe,
    complete_call_capture_from_transcript,
    complete_recovered_call_captures_from_transcripts,
    get_date_based_stream_candidates,
    heartbeat_call_capture,
    heartbeat_stream_probe,
    mark_call_running,
    record_stream_probe,
    record_verified_call_event_end,
    recover_stale_stream_operations,
    requeue_failed_call_capture,
    update_call_status,
    update_capture_manifest,
)

from data_pipeline.storage.market import (
    get_all_stocks,
    get_all_tickers,
    save_financial_statement_items,
    save_prices,
    save_stocks,
    update_static_indicators,
    update_stock_ir_url,
)

from data_pipeline.storage.policies import (
    _PROBE_FUTURE_EVENT_DATE_PATTERN,
    _coerce_schedule_date,
    _env_int,
    _nonnegative_env_int,
    _normalized_schedule_ticker,
    capture_retry_policy,
    future_event_date_from_probe_error,
    future_event_time_from_probe_error,
    probe_error_date_mismatch,
    stream_probe_retry_policy,
)

from data_pipeline.storage.redaction import (
    SENSITIVE_URL_QUERY_KEYS,
    _URL_IN_TEXT_PATTERN,
    redact_sensitive_text,
    redact_sensitive_url,
)

from data_pipeline.storage.schedules import (
    clear_schedule_enrichment_circuit,
    confirm_schedule_revalidation_from_official_ir,
    get_call_schedule_context,
    get_calls_missing_verified_time,
    get_imminent_calls,
    get_schedule_enrichment_circuit,
    open_schedule_enrichment_circuit,
    quarantine_schedule_for_official_page_date_mismatch,
    reconcile_near_term_schedule_sources,
    record_schedule_enrichment_outcome,
    record_schedule_refresh_outcome,
    request_schedule_refresh,
    save_earnings_schedules,
    update_call_video_url,
    update_official_schedule_discovery,
    update_stream_link,
    update_verified_schedule_time,
)

from data_pipeline.storage.schema import (
    SCHEDULE_TIME_COLUMNS,
    TRANSCRIPT_SESSION_COLUMNS,
    ensure_financial_statement_items_table,
    ensure_schedule_time_schema,
    ensure_transcript_archive_schema,
    ensure_transcript_outbox_schema,
    ensure_webcast_learning_target_schema,
    ensure_webcast_recipe_schema,
    ensure_webcast_replay_discovery_schema,
    ensure_webcast_replay_target_schema,
    ensure_webcast_training_surface_schema,
)

from data_pipeline.storage.transcripts import (
    archive_transcript_segment,
    enqueue_transcript_delivery,
    get_archived_transcript_segments,
    get_pending_transcript_deliveries,
    get_transcript_session_summary,
    mark_transcript_delivery_result,
    mark_transcript_session_end,
    purge_transcript_segments,
)
