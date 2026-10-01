"""Learned browser recipes and historical validation results."""

from sqlalchemy import text
import hashlib
from typing import Any, Dict, List
from . import connection, redaction, schema


def get_verified_webcast_recipes(
    domain: str,
    lifecycles: tuple[str, ...] = ("unknown",),
) -> List[Dict[str, Any]]:
    """Return audio-verified recipes compatible with the current event lifecycle."""
    if not domain:
        return []
    schema.ensure_webcast_recipe_schema()
    lifecycle_values = tuple(dict.fromkeys(value.lower() for value in lifecycles if value)) or ("unknown",)
    lifecycle_params = {f"lifecycle_{index}": value for index, value in enumerate(lifecycle_values)}
    lifecycle_placeholders = ", ".join(f":{key}" for key in lifecycle_params)
    query = text(f"""
        SELECT id, recipe_key, domain, selector_json, frame_hostname, target_text,
               target_href_path, strategy, lifecycle, confidence, state, success_count,
               failure_count, last_verified_at, last_error, evidence_json
        FROM webcast_recipes
        WHERE domain = :domain
          AND state = 'verified'
          AND strategy <> 'human_workflow'
          AND failure_count < 3
          AND lifecycle IN ({lifecycle_placeholders})
        ORDER BY FIELD(lifecycle, {lifecycle_placeholders}), success_count DESC, confidence DESC, updated_at DESC
    """)
    with connection.engine.connect() as conn:
        result = conn.execute(query, {"domain": domain.lower(), **lifecycle_params})
        return [dict(row._mapping) for row in result]


def get_generalized_webcast_patterns(
    lifecycles: tuple[str, ...] = ("unknown", "replay", "live", "pre_live"),
) -> List[Dict[str, Any]]:
    """Return audio-verified label/href evidence reusable across IR domains."""
    schema.ensure_webcast_recipe_schema()
    lifecycle_values = tuple(dict.fromkeys(value.lower() for value in lifecycles if value)) or ("unknown",)
    params = {f"lifecycle_{index}": value for index, value in enumerate(lifecycle_values)}
    placeholders = ", ".join(f":{key}" for key in params)
    query = text(f"""
        SELECT target_text, target_href_path, success_count
        FROM webcast_recipes
        WHERE state = 'verified'
          AND strategy <> 'human_workflow'
          AND failure_count < 3
          AND lifecycle IN ({placeholders})
        ORDER BY success_count DESC, last_verified_at DESC
    """)
    with connection.engine.connect() as conn:
        return [dict(row._mapping) for row in conn.execute(query, params)]


def get_verified_webcast_recipes_for_benchmark() -> List[Dict[str, Any]]:
    """Return complete verified recipe evidence for offline selector comparisons."""
    schema.ensure_webcast_recipe_schema()
    query = text("""
        SELECT id, target_text, target_href_path, success_count, evidence_json
        FROM webcast_recipes
        WHERE state = 'verified'
          AND strategy <> 'human_workflow'
          AND failure_count < 3
        ORDER BY id
    """)
    with connection.engine.connect() as conn:
        return [dict(row._mapping) for row in conn.execute(query)]


def get_verified_human_workflows(
    domain: str,
    lifecycles: tuple[str, ...] = ("unknown",),
) -> List[Dict[str, Any]]:
    """Return stage-verified human navigation workflows for one IR domain."""
    if not domain:
        return []
    schema.ensure_webcast_recipe_schema()
    lifecycle_values = tuple(
        dict.fromkeys(value.lower() for value in lifecycles if value)
    ) or ("unknown",)
    lifecycle_params = {
        f"lifecycle_{index}": value for index, value in enumerate(lifecycle_values)
    }
    lifecycle_placeholders = ", ".join(f":{key}" for key in lifecycle_params)
    query = text(f"""
        SELECT id, recipe_key, domain, selector_json, frame_hostname, target_text,
               target_href_path, strategy, lifecycle, confidence, state, success_count,
               failure_count, last_verified_at, last_error, evidence_json
        FROM webcast_recipes
        WHERE domain = :domain
          AND state = 'verified'
          AND strategy = 'human_workflow'
          AND failure_count < 3
          AND lifecycle IN ({lifecycle_placeholders})
        ORDER BY success_count DESC, confidence DESC, updated_at DESC
    """)
    with connection.engine.connect() as conn:
        result = conn.execute(
            query,
            {"domain": domain.lower(), **lifecycle_params},
        )
        return [dict(row._mapping) for row in result]


def save_webcast_recipe(recipe: Dict[str, Any]) -> int:
    """Store a learned candidate; it becomes verified only after audible replay."""
    schema.ensure_webcast_recipe_schema()
    query = text("""
        INSERT INTO webcast_recipes (
            recipe_key, domain, selector_json, frame_hostname, target_text,
            target_href_path, strategy, lifecycle, confidence, state, evidence_json
        ) VALUES (
            :recipe_key, :domain, :selector_json, :frame_hostname, :target_text,
            :target_href_path, :strategy, :lifecycle, :confidence, 'candidate', :evidence_json
        )
        ON DUPLICATE KEY UPDATE
            target_text = VALUES(target_text),
            target_href_path = VALUES(target_href_path),
            strategy = VALUES(strategy),
            lifecycle = VALUES(lifecycle),
            confidence = GREATEST(confidence, VALUES(confidence)),
            evidence_json = VALUES(evidence_json),
            updated_at = CURRENT_TIMESTAMP
    """)
    with connection.engine.begin() as conn:
        conn.execute(query, recipe)
        recipe_id = conn.execute(
            text("SELECT id FROM webcast_recipes WHERE recipe_key = :recipe_key"),
            {"recipe_key": recipe["recipe_key"]},
        ).scalar_one()
    return int(recipe_id)


def record_webcast_recipe_outcome(recipe_id: int, *, success: bool, error: str | None = None) -> None:
    """Promote only audio-verified recipes and retire repeatedly failing ones."""
    schema.ensure_webcast_recipe_schema()
    if success:
        query = text("""
            UPDATE webcast_recipes
            SET state = 'verified',
                success_count = success_count + 1,
                last_verified_at = NOW(),
                last_error = NULL
            WHERE id = :recipe_id
        """)
        params = {"recipe_id": recipe_id}
    else:
        query = text("""
            UPDATE webcast_recipes
            SET failure_count = failure_count + 1,
                state = CASE WHEN failure_count + 1 >= 3 THEN 'disabled' ELSE state END,
                last_error = :error
            WHERE id = :recipe_id
        """)
        params = {"recipe_id": recipe_id, "error": error[:1000] if error else "audio not detected"}
    with connection.engine.begin() as conn:
        conn.execute(query, params)


def get_webcast_learning_targets(limit: int | None = None) -> List[Dict[str, Any]]:
    """Return one best available replay entrypoint for every active company."""
    schema.ensure_webcast_learning_target_schema()
    query = """
        SELECT c.id AS call_id, c.ticker, c.call_year, c.quarter,
               c.earning_at, c.scheduled_at_utc,
               c.webcast_url, c.event_url, s.ir_url
        FROM calls c
        JOIN stocks s ON s.ticker = c.ticker
        WHERE s.active = TRUE
          AND c.status = 'upcoming'
        UNION ALL
        SELECT NULL AS call_id, s.ticker, NULL AS call_year, NULL AS quarter,
               NULL AS earning_at, NULL AS scheduled_at_utc,
               NULL AS webcast_url, NULL AS event_url, s.ir_url
        FROM stocks s
        WHERE s.active = TRUE
          AND NOT EXISTS (
              SELECT 1 FROM calls c WHERE c.ticker = s.ticker AND c.status = 'upcoming'
          )
        ORDER BY ticker ASC
    """
    if limit is not None:
        query += " LIMIT :limit"

    with connection.engine.connect() as conn:
        result = conn.execute(text(query), {"limit": max(1, limit)} if limit is not None else {})
        rows = [dict(row._mapping) for row in result]

    targets: list[Dict[str, Any]] = []
    for row in rows:
        target_url, target_kind = _best_webcast_learning_url(row)
        if not target_url:
            continue
        target = {
            "call_id": row["call_id"],
            "ticker": row["ticker"],
            "call_year": row["call_year"],
            "quarter": row["quarter"],
            "earning_at": row["earning_at"],
            "scheduled_at_utc": row["scheduled_at_utc"],
            "ir_url": target_url,
            "target_url": target_url,
            "target_kind": target_kind,
        }
        target["target_key"] = _webcast_learning_target_key(target)
        targets.append(target)
    return prioritize_webcast_learning_targets(targets)


def claim_webcast_learning_target(target: Dict[str, Any], cooldown_minutes: int = 1440) -> bool:
    """Atomically reserve a universe target while allowing safe later retries."""
    schema.ensure_webcast_learning_target_schema()
    insert = text("""
        INSERT IGNORE INTO webcast_learning_targets (
            target_key, call_id, ticker, target_url, target_kind
        ) VALUES (
            :target_key, :call_id, :ticker, :target_url, :target_kind
        )
    """)
    update = text("""
        UPDATE webcast_learning_targets
        SET call_id = :call_id,
            ticker = :ticker,
            target_url = :target_url,
            target_kind = :target_kind,
            status = 'probing',
            attempt_count = attempt_count + 1,
            last_attempt_at = NOW(),
            last_error = NULL,
            last_output = NULL
        WHERE target_key = :target_key
          AND (
              last_attempt_at IS NULL
              OR last_attempt_at <= DATE_SUB(NOW(), INTERVAL :cooldown_minutes MINUTE)
          )
    """)
    params = {**target, "cooldown_minutes": max(0, cooldown_minutes)}
    with connection.engine.begin() as conn:
        conn.execute(insert, params)
        result = conn.execute(update, params)
        return result.rowcount == 1


def record_webcast_learning_target_outcome(
    target: Dict[str, Any],
    *,
    status: str,
    error: str | None = None,
    output: str | None = None,
) -> None:
    """Persist a full-universe probe result for progress reporting and retries."""
    schema.ensure_webcast_learning_target_schema()
    query = text("""
        UPDATE webcast_learning_targets
        SET status = CASE
                WHEN :status = 'audible' OR audible_count > 0 THEN 'audible'
                ELSE :status
            END,
            last_error = CASE
                WHEN :status = 'audible' OR audible_count = 0 THEN :error
                ELSE last_error
            END,
            last_output = CASE
                WHEN :status = 'audible' OR audible_count = 0 THEN :output
                ELSE last_output
            END,
            audible_count = audible_count + CASE WHEN :status = 'audible' THEN 1 ELSE 0 END,
            last_audible_at = CASE WHEN :status = 'audible' THEN NOW() ELSE last_audible_at END
        WHERE target_key = :target_key
    """)
    with connection.engine.begin() as conn:
        conn.execute(
            query,
            {
                "target_key": target["target_key"],
                "status": status,
                "error": error[:1000] if error else None,
                "output": output[-4000:] if output else None,
            },
        )


def get_webcast_learning_summary() -> List[Dict[str, Any]]:
    schema.ensure_webcast_learning_target_schema()
    query = text("""
        SELECT status, COUNT(*) AS target_count,
               SUM(attempt_count) AS attempts,
               SUM(audible_count) AS audible_count
        FROM webcast_learning_targets
        GROUP BY status
        ORDER BY status
    """)
    with connection.engine.connect() as conn:
        return [dict(row._mapping) for row in conn.execute(query)]


def get_webcast_training_surface_targets(
    limit: int | None = None,
) -> List[Dict[str, Any]]:
    """Return every active ticker's configured IR entrypoint for downstream auditing."""
    schema.ensure_webcast_training_surface_schema()
    query = """
        SELECT s.ticker, s.company_name, s.ir_url,
               audit.status, audit.surface_kind, audit.selected_url,
               audit.last_attempt_at, audit.last_output
        FROM stocks s
        LEFT JOIN webcast_training_surface_audits audit
          ON audit.ticker = s.ticker
        WHERE s.active = TRUE
        ORDER BY s.ticker ASC
    """
    params: Dict[str, Any] = {}
    if limit is not None:
        query += " LIMIT :limit"
        params["limit"] = max(1, limit)
    with connection.engine.connect() as conn:
        return [dict(row._mapping) for row in conn.execute(text(query), params)]


def recover_stale_webcast_training_surface_audits(
    stale_minutes: int = 10,
) -> int:
    schema.ensure_webcast_training_surface_schema()
    query = text("""
        UPDATE webcast_training_surface_audits
        SET status = 'error',
            last_error = 'previous training-surface audit was interrupted'
        WHERE status = 'probing'
          AND last_attempt_at <= DATE_SUB(NOW(), INTERVAL :stale_minutes MINUTE)
    """)
    with connection.engine.begin() as conn:
        result = conn.execute(
            query,
            {"stale_minutes": max(1, stale_minutes)},
        )
        return int(result.rowcount)


def claim_webcast_training_surface_target(
    target: Dict[str, Any],
    *,
    cooldown_minutes: int = 10080,
) -> bool:
    """Reserve one ticker so resumable audit workers cannot probe it twice."""
    schema.ensure_webcast_training_surface_schema()
    insert = text("""
        INSERT INTO webcast_training_surface_audits (ticker, ir_url)
        VALUES (:ticker, :ir_url)
        ON DUPLICATE KEY UPDATE ir_url = VALUES(ir_url)
    """)
    update = text("""
        UPDATE webcast_training_surface_audits
        SET status = 'probing',
            surface_kind = 'unknown',
            selected_url = NULL,
            attempt_count = attempt_count + 1,
            last_attempt_at = NOW(),
            last_error = NULL,
            last_output = NULL
        WHERE ticker = :ticker
          AND status <> 'probing'
          AND (
              last_attempt_at IS NULL
              OR last_attempt_at <= DATE_SUB(NOW(), INTERVAL :cooldown_minutes MINUTE)
          )
    """)
    params = {
        "ticker": str(target["ticker"]).upper(),
        "ir_url": str(target.get("ir_url") or "") or None,
        "cooldown_minutes": max(0, cooldown_minutes),
    }
    with connection.engine.begin() as conn:
        conn.execute(insert, params)
        result = conn.execute(update, params)
        return result.rowcount == 1


def record_webcast_training_surface_outcome(
    target: Dict[str, Any],
    *,
    status: str,
    surface_kind: str,
    selected_url: str | None = None,
    error: str | None = None,
    output: str | None = None,
) -> None:
    """Persist downstream proof separately from real earnings-event selection."""
    schema.ensure_webcast_training_surface_schema()
    query = text("""
        UPDATE webcast_training_surface_audits
        SET status = CASE
                WHEN :status = 'audible' OR audible_count > 0 THEN 'audible'
                ELSE :status
            END,
            surface_kind = CASE
                WHEN :status = 'audible' OR audible_count = 0 THEN :surface_kind
                ELSE surface_kind
            END,
            selected_url = CASE
                WHEN :status = 'audible' OR audible_count = 0 THEN :selected_url
                ELSE selected_url
            END,
            last_error = CASE
                WHEN :status = 'audible' OR audible_count = 0 THEN :error
                ELSE last_error
            END,
            last_output = CASE
                WHEN :status = 'audible' OR audible_count = 0 THEN :output
                ELSE last_output
            END,
            audible_count = audible_count + CASE WHEN :status = 'audible' THEN 1 ELSE 0 END,
            last_audible_at = CASE WHEN :status = 'audible' THEN NOW() ELSE last_audible_at END
        WHERE ticker = :ticker
    """)
    with connection.engine.begin() as conn:
        conn.execute(
            query,
            {
                "ticker": str(target["ticker"]).upper(),
                "status": status[:32],
                "surface_kind": surface_kind[:32],
                "selected_url": redaction.redact_sensitive_url(selected_url[:2048])
                if selected_url
                else None,
                "error": redaction.redact_sensitive_text(error[:1000]) if error else None,
                "output": redaction.redact_sensitive_text(output[-8000:]) if output else None,
            },
        )


def get_webcast_training_surface_summary() -> List[Dict[str, Any]]:
    schema.ensure_webcast_training_surface_schema()
    query = text("""
        SELECT surface_kind, status, COUNT(*) AS ticker_count,
               SUM(attempt_count) AS attempts,
               SUM(audible_count) AS audible_count
        FROM webcast_training_surface_audits
        GROUP BY surface_kind, status
        ORDER BY surface_kind, status
    """)
    with connection.engine.connect() as conn:
        return [dict(row._mapping) for row in conn.execute(query)]


def get_webcast_training_surface_coverage() -> Dict[str, int]:
    schema.ensure_webcast_training_surface_schema()
    query = text("""
        SELECT
            (SELECT COUNT(*) FROM stocks WHERE active = TRUE) AS active_tickers,
            COUNT(*) AS tracked_tickers,
            SUM(status NOT IN ('pending', 'probing')) AS completed_tickers,
            SUM(status = 'audible' OR audible_count > 0) AS audible_tickers,
            SUM(status = 'candidate_discovery_retry') AS candidate_retry_tickers,
            SUM(status = 'no_training_surface') AS no_training_surface_tickers,
            SUM(status = 'probing') AS probing_tickers
        FROM webcast_training_surface_audits
    """)
    with connection.engine.connect() as conn:
        row = conn.execute(query).one()
        return {key: int(value or 0) for key, value in row._mapping.items()}


def get_webcast_training_surface_details() -> List[Dict[str, Any]]:
    """Return active ticker audit evidence for automated and human review queues."""
    schema.ensure_webcast_training_surface_schema()
    query = text("""
        SELECT s.ticker, s.company_name, s.ir_url,
               COALESCE(audit.status, 'pending') AS status,
               COALESCE(audit.surface_kind, 'unknown') AS surface_kind,
               audit.selected_url, COALESCE(audit.attempt_count, 0) AS attempt_count,
               COALESCE(audit.audible_count, 0) AS audible_count,
               audit.last_attempt_at, audit.last_audible_at,
               audit.last_error, audit.last_output
        FROM stocks s
        LEFT JOIN webcast_training_surface_audits audit
          ON audit.ticker = s.ticker
        WHERE s.active = TRUE
        ORDER BY s.ticker ASC
    """)
    with connection.engine.connect() as conn:
        return [dict(row._mapping) for row in conn.execute(query)]


def get_webcast_training_surface_risks(
    limit: int | None = None,
) -> List[Dict[str, Any]]:
    """Return configured IR pages with no usable video surface or access path."""
    schema.ensure_webcast_training_surface_schema()
    query = """
        SELECT ticker, ir_url, status, surface_kind, selected_url,
               attempt_count, last_error
        FROM webcast_training_surface_audits
        WHERE status IN ('blocked', 'navigation_failed', 'not_found', 'entrypoint_missing')
        ORDER BY CASE status
                    WHEN 'blocked' THEN 0
                    WHEN 'navigation_failed' THEN 1
                    WHEN 'not_found' THEN 2
                    ELSE 3
                 END,
                 ticker
    """
    params: Dict[str, Any] = {}
    if limit is not None:
        query += " LIMIT :limit"
        params["limit"] = max(1, limit)
    with connection.engine.connect() as conn:
        return [dict(row._mapping) for row in conn.execute(text(query), params)]


def get_historical_replay_calls(limit: int | None = None) -> List[Dict[str, Any]]:
    """Return one replay-search context for every active stock."""
    query = """
        SELECT recent_call.id AS call_id,
               s.ticker,
               COALESCE(recent_call.call_year, YEAR(CURDATE())) AS call_year,
               recent_call.quarter,
               COALESCE(recent_call.earning_at, DATE_SUB(CURDATE(), INTERVAL 1 DAY)) AS earning_at,
               s.company_name,
               s.ir_url
        FROM stocks s
        LEFT JOIN calls recent_call
          ON recent_call.id = (
              SELECT historical_call.id
              FROM calls historical_call
              WHERE historical_call.ticker = s.ticker
                AND historical_call.earning_at < CURDATE()
              ORDER BY historical_call.earning_at DESC, historical_call.id DESC
              LIMIT 1
          )
        WHERE s.active = TRUE
        ORDER BY s.ticker ASC
    """
    params: Dict[str, Any] = {}
    if limit is not None:
        query += " LIMIT :limit"
        params["limit"] = max(1, limit)
    with connection.engine.connect() as conn:
        return [dict(row._mapping) for row in conn.execute(text(query), params)]


def claim_historical_replay_discovery(
    call: Dict[str, Any],
    *,
    cooldown_minutes: int = 10080,
    force: bool = False,
) -> bool:
    """Reserve one ticker's Serper search without repeating completed discovery."""
    schema.ensure_webcast_replay_discovery_schema()
    ticker = str(call["ticker"]).upper()
    insert = text("""
        INSERT IGNORE INTO webcast_replay_discovery (ticker)
        VALUES (:ticker)
    """)
    allowed_statuses = (
        "('pending', 'no_candidate', 'error', 'searching', 'discovered')"
        if force
        else "('pending', 'no_candidate', 'error', 'searching')"
    )
    update = text(f"""
        UPDATE webcast_replay_discovery
        SET status = 'searching',
            attempt_count = attempt_count + 1,
            last_attempt_at = NOW(),
            last_error = NULL
        WHERE ticker = :ticker
          AND status IN {allowed_statuses}
          AND (
              :force = TRUE
              OR last_attempt_at IS NULL
              OR last_attempt_at <= DATE_SUB(NOW(), INTERVAL :cooldown_minutes MINUTE)
          )
    """)
    with connection.engine.begin() as conn:
        conn.execute(insert, {"ticker": ticker})
        result = conn.execute(
            update,
            {
                "ticker": ticker,
                "force": force,
                "cooldown_minutes": max(0, cooldown_minutes),
            },
        )
        return result.rowcount == 1


def record_historical_replay_discovery(
    ticker: str,
    *,
    status: str,
    candidate_count: int = 0,
    error: str | None = None,
) -> None:
    """Persist one ticker's replay-search outcome."""
    schema.ensure_webcast_replay_discovery_schema()
    query = text("""
        UPDATE webcast_replay_discovery
        SET status = CASE
                WHEN :status = 'error' AND candidate_count > 0 THEN 'discovered'
                ELSE :status
            END,
            candidate_count = CASE
                WHEN :status = 'error' AND candidate_count > 0 THEN candidate_count
                ELSE :candidate_count
            END,
            last_error = :error
        WHERE ticker = :ticker
    """)
    with connection.engine.begin() as conn:
        conn.execute(
            query,
            {
                "ticker": ticker.upper(),
                "status": status,
                "candidate_count": max(0, candidate_count),
                "error": error[:1000] if error else None,
            },
        )


def get_historical_replay_discovery_summary() -> List[Dict[str, Any]]:
    schema.ensure_webcast_replay_discovery_schema()
    query = text("""
        SELECT status, COUNT(*) AS ticker_count,
               SUM(attempt_count) AS attempts,
               SUM(candidate_count) AS candidates
        FROM webcast_replay_discovery
        GROUP BY status
        ORDER BY status
    """)
    with connection.engine.connect() as conn:
        return [dict(row._mapping) for row in conn.execute(query)]


def get_historical_replay_discovery_tickers(statuses: set[str]) -> set[str]:
    """Return tickers whose discovery or replay target state needs a retry.

    Discovery status and browser-probe status are stored in separate tables. A
    retry request such as ``error`` must include both tables, otherwise a
    browser failure can make the subsequent Serper retry silently select zero
    tickers.
    """
    schema.ensure_webcast_replay_discovery_schema()
    normalized = sorted({status.strip().lower() for status in statuses if status.strip()})
    if not normalized:
        return set()
    params = {f"status_{index}": status for index, status in enumerate(normalized)}
    placeholders = ", ".join(f":{name}" for name in params)
    query = text(
        f"SELECT ticker FROM webcast_replay_discovery WHERE status IN ({placeholders}) "
        f"UNION "
        f"SELECT ticker FROM webcast_replay_targets WHERE status IN ({placeholders})"
    )
    with connection.engine.connect() as conn:
        return {str(row[0]).upper() for row in conn.execute(query, params)}


def save_historical_replay_targets(
    call: Dict[str, Any],
    candidates: List[Dict[str, Any]],
) -> int:
    """Persist official-looking replay candidates without changing the original call record."""
    schema.ensure_webcast_replay_target_schema()
    query = text("""
        INSERT INTO webcast_replay_targets (
            target_key, call_id, ticker, call_year, quarter, earning_at, target_url,
            source_kind, source_title, source_snippet, provider_domain
        ) VALUES (
            :target_key, :call_id, :ticker, :call_year, :quarter, :earning_at, :target_url,
            :source_kind, :source_title, :source_snippet, :provider_domain
        )
        ON DUPLICATE KEY UPDATE
            source_kind = VALUES(source_kind),
            source_title = VALUES(source_title),
            source_snippet = VALUES(source_snippet),
            provider_domain = VALUES(provider_domain),
            updated_at = CURRENT_TIMESTAMP
    """)
    saved = 0
    with connection.engine.begin() as conn:
        for candidate in candidates:
            target_url = str(candidate.get("target_url") or "").strip()
            if not target_url:
                continue
            params = {
                "target_key": _webcast_replay_target_key(call, target_url),
                # Training-surface audits intentionally operate per ticker,
                # even when no scheduled call row exists yet.
                "call_id": call.get("call_id"),
                "ticker": str(call["ticker"]).upper(),
                "call_year": call.get("call_year"),
                "quarter": call.get("quarter"),
                "earning_at": call.get("earning_at"),
                "target_url": target_url,
                "source_kind": str(candidate.get("source_kind") or "search")[:32],
                "source_title": str(candidate.get("source_title") or "")[:500] or None,
                "source_snippet": str(candidate.get("source_snippet") or "")[:4000] or None,
                "provider_domain": str(candidate.get("provider_domain") or "")[:255] or None,
            }
            conn.execute(query, params)
            saved += 1
    return saved


def get_historical_replay_targets(
    limit: int | None = None,
    *,
    include_registration_required: bool = False,
    include_auth_required: bool = False,
    auth_required_only: bool = False,
    registration_required_only: bool = False,
) -> List[Dict[str, Any]]:
    """Return unverified historical replays, prioritizing newly discovered candidates."""
    schema.ensure_webcast_replay_target_schema()
    status_filter = (
        "'registration_required'"
        if registration_required_only
        else "'auth_required'"
        if auth_required_only
        else "'discovered', 'no_audio', 'no_candidate', 'error', 'capture_runtime_failed'"
        + (", 'registration_required'" if include_registration_required else "")
        + (", 'auth_required'" if include_auth_required else "")
    )
    query = """
        SELECT target_key, call_id, ticker, call_year, quarter, earning_at, target_url,
               source_kind, source_title, source_snippet, provider_domain, status,
               attempt_count, audible_count, last_attempt_at, last_error
        FROM webcast_replay_targets
        WHERE status IN ({status_filter})
          AND NOT EXISTS (
              SELECT 1
              FROM webcast_replay_targets audible_target
              WHERE audible_target.ticker = webcast_replay_targets.ticker
                AND audible_target.status = 'audible'
          )
        ORDER BY CASE status WHEN 'discovered' THEN 0 WHEN 'error' THEN 1 ELSE 2 END,
                 CASE source_kind
                     WHEN 'browser_resolved' THEN 0
                     WHEN 'internal_crawl' THEN 1
                     WHEN 'serper_direct' THEN 2
                     WHEN 'serper_announcement' THEN 3
                     WHEN 'serper_archive' THEN 4
                     ELSE 5
                 END,
                 earning_at DESC, ticker ASC
    """
    query = query.format(
        status_filter=status_filter,
    )
    params: Dict[str, Any] = {}
    if limit is not None:
        query += " LIMIT :limit"
        params["limit"] = max(1, limit)
    with connection.engine.connect() as conn:
        return [dict(row._mapping) for row in conn.execute(text(query), params)]


def recover_stale_historical_replay_targets(stale_minutes: int = 10) -> int:
    """Return interrupted browser probes to the retry queue."""
    schema.ensure_webcast_replay_target_schema()
    query = text("""
        UPDATE webcast_replay_targets
        SET status = 'error',
            last_error = 'previous replay probe was interrupted'
        WHERE status = 'probing'
          AND last_attempt_at <= DATE_SUB(NOW(), INTERVAL :stale_minutes MINUTE)
    """)
    with connection.engine.begin() as conn:
        result = conn.execute(query, {"stale_minutes": max(1, stale_minutes)})
        return int(result.rowcount)


def claim_historical_replay_target(target: Dict[str, Any], cooldown_minutes: int = 10080) -> bool:
    """Reserve one historical replay URL so only one browser probe handles it at a time."""
    schema.ensure_webcast_replay_target_schema()
    query = text("""
        UPDATE webcast_replay_targets
        SET status = 'probing',
            attempt_count = attempt_count + 1,
            last_attempt_at = NOW(),
            last_error = NULL,
            last_output = NULL
        WHERE target_key = :target_key
          AND (
              last_attempt_at IS NULL
              OR last_attempt_at <= DATE_SUB(NOW(), INTERVAL :cooldown_minutes MINUTE)
          )
    """)
    with connection.engine.begin() as conn:
        result = conn.execute(
            query,
            {"target_key": target["target_key"], "cooldown_minutes": max(0, cooldown_minutes)},
        )
        return result.rowcount == 1


def record_historical_replay_outcome(
    target: Dict[str, Any],
    *,
    status: str,
    error: str | None = None,
    output: str | None = None,
) -> None:
    """Record browser/audio proof for one historical replay candidate."""
    schema.ensure_webcast_replay_target_schema()
    query = text("""
        UPDATE webcast_replay_targets
        SET status = :status,
            audible_count = audible_count + CASE WHEN :status = 'audible' THEN 1 ELSE 0 END,
            last_audible_at = CASE WHEN :status = 'audible' THEN NOW() ELSE last_audible_at END,
            last_error = :error,
            last_output = :output
        WHERE target_key = :target_key
    """)
    with connection.engine.begin() as conn:
        conn.execute(
            query,
            {
                "target_key": target["target_key"],
                "status": status,
                "error": error[:1000] if error else None,
                "output": output[-4000:] if output else None,
            },
        )


def get_historical_replay_summary() -> List[Dict[str, Any]]:
    schema.ensure_webcast_replay_target_schema()
    query = text("""
        SELECT status, COUNT(*) AS target_count, SUM(attempt_count) AS attempts,
               SUM(audible_count) AS audible_count
        FROM webcast_replay_targets
        GROUP BY status
        ORDER BY status
    """)
    with connection.engine.connect() as conn:
        return [dict(row._mapping) for row in conn.execute(query)]


def get_historical_replay_error_records(limit: int | None = None) -> List[Dict[str, Any]]:
    """Return failed replay probes for root-cause analysis without retrying them."""
    schema.ensure_webcast_replay_target_schema()
    query = """
        SELECT ticker, provider_domain, target_url, attempt_count, last_error
        FROM webcast_replay_targets
        WHERE status = 'error'
        ORDER BY attempt_count DESC, ticker ASC
    """
    params: Dict[str, Any] = {}
    if limit is not None:
        query += " LIMIT :limit"
        params["limit"] = max(1, limit)
    with connection.engine.connect() as conn:
        return [dict(row._mapping) for row in conn.execute(text(query), params)]


def get_historical_replay_coverage_summary() -> Dict[str, int]:
    """Return ticker-level discovery and audible coverage for the active universe."""
    schema.ensure_webcast_replay_discovery_schema()
    schema.ensure_webcast_replay_target_schema()
    query = text("""
        SELECT
            (SELECT COUNT(*) FROM stocks WHERE active = TRUE) AS active_tickers,
            (
                SELECT COUNT(*)
                FROM webcast_replay_discovery
                WHERE status = 'discovered'
            ) AS discovered_tickers,
            (
                SELECT COUNT(DISTINCT ticker)
                FROM webcast_replay_targets
            ) AS candidate_tickers,
            (
                SELECT COUNT(DISTINCT ticker)
                FROM webcast_replay_targets
                WHERE status = 'audible'
            ) AS audible_tickers
    """)
    with connection.engine.connect() as conn:
        row = conn.execute(query).one()
        return {key: int(value or 0) for key, value in row._mapping.items()}


def _webcast_replay_target_key(call: Dict[str, Any], target_url: str) -> str:
    source = "|".join(
        [str(call.get("call_id")), str(call["ticker"]).upper(), target_url]
    )
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def _best_webcast_learning_url(row: Dict[str, Any]) -> tuple[str | None, str]:
    for field, kind in (
        ("webcast_url", "webcast_url"),
        ("event_url", "event_url"),
        ("ir_url", "ir_url"),
    ):
        value = str(row.get(field) or "").strip()
        if value:
            return value, kind
    return None, "missing"


def prioritize_webcast_learning_targets(targets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Try explicit webcast pages before event pages and generic IR homepages."""
    priority = {"webcast_url": 0, "event_url": 1, "ir_url": 2}
    return sorted(
        targets,
        key=lambda target: (priority.get(str(target.get("target_kind")), 3), str(target["ticker"])),
    )


def _webcast_learning_target_key(target: Dict[str, Any]) -> str:
    source = "|".join(
        [
            str(target.get("call_id") or "stock"),
            str(target["ticker"]).upper(),
            str(target["target_kind"]),
            str(target["target_url"]),
        ]
    )
    return hashlib.sha256(source.encode("utf-8")).hexdigest()
