create table if not exists ai_events (
    event_id varchar(64) primary key,
    ticker varchar(16) not null,
    company_name varchar(128) not null,
    source_type varchar(32) not null,
    event_type varchar(32) not null,
    event_time timestamptz not null,
    market_session varchar(24) not null default 'unknown',
    sector varchar(64),
    external_source_id varchar(128),
    chunk_sequence int not null,
    is_final_chunk boolean not null default false,
    schema_version varchar(64) not null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists ai_analysis_runs (
    run_id varchar(64) primary key,
    event_id varchar(64) not null references ai_events(event_id) on delete cascade,
    request_id varchar(64) not null,
    route_profile varchar(24) not null,
    model_route varchar(64),
    model_version varchar(64),
    app_version varchar(32),
    direction varchar(16),
    magnitude numeric(8,4),
    confidence numeric(8,4),
    catalyst_type varchar(64),
    rationale text,
    strategy_code varchar(64),
    strategy_score numeric(8,4),
    hold_days int,
    review_triggered boolean not null default false,
    status varchar(24) not null default 'ok',
    raw_analysis_json jsonb not null,
    created_at timestamptz not null default now()
);

create table if not exists ai_feature_snapshots (
    snapshot_id bigserial primary key,
    run_id varchar(64) not null unique references ai_analysis_runs(run_id) on delete cascade,
    market_snapshot_json jsonb not null,
    topic_deltas_json jsonb,
    transcript_signals_json jsonb,
    phase1_json jsonb,
    router_json jsonb,
    canonical_bundle_json jsonb,
    source_health_json jsonb,
    created_at timestamptz not null default now()
);

create table if not exists ai_signal_explanations (
    explanation_id bigserial primary key,
    run_id varchar(64) not null unique references ai_analysis_runs(run_id) on delete cascade,
    display_text text,
    summary_ko text,
    reasons_json jsonb,
    risks_json jsonb,
    counter_scenario text,
    hold_period_reason text,
    created_at timestamptz not null default now()
);

create table if not exists ai_trade_plans (
    plan_id bigserial primary key,
    run_id varchar(64) not null unique references ai_analysis_runs(run_id) on delete cascade,
    strategy varchar(64),
    strategy_label_ko varchar(128),
    entry_style varchar(64),
    entry_style_label_ko varchar(128),
    entry_zone varchar(64),
    stop_loss numeric(18,6),
    take_profit_1 numeric(18,6),
    take_profit_2 numeric(18,6),
    invalidation text,
    time_stop varchar(64),
    positioning_note text,
    raw_trade_plan_json jsonb,
    created_at timestamptz not null default now()
);

create table if not exists ai_cards (
    card_id varchar(96) primary key,
    run_id varchar(64) not null references ai_analysis_runs(run_id) on delete cascade,
    event_id varchar(64) not null references ai_events(event_id) on delete cascade,
    card_type varchar(32) not null,
    priority int not null,
    visible boolean not null default true,
    locked boolean not null default false,
    payload_json jsonb not null,
    lock_context_json jsonb,
    created_at timestamptz not null default now()
);

create table if not exists ai_paywall_surfaces (
    paywall_id bigserial primary key,
    run_id varchar(64) not null unique references ai_analysis_runs(run_id) on delete cascade,
    primary_surface_code varchar(64),
    primary_surface_json jsonb,
    secondary_surfaces_json jsonb,
    unlock_cards_json jsonb,
    frontend_contract_json jsonb,
    summary text,
    created_at timestamptz not null default now()
);

create table if not exists ai_replay_tracks (
    replay_id bigserial primary key,
    run_id varchar(64) not null references ai_analysis_runs(run_id) on delete cascade,
    event_id varchar(64) not null references ai_events(event_id) on delete cascade,
    status varchar(24) not null default 'tracking',
    original_signal_json jsonb not null,
    milestones_json jsonb not null,
    expected_path text,
    exit_watch text,
    realized_pnl_pct numeric(10,4),
    mfe_pct numeric(10,4),
    mae_pct numeric(10,4),
    close_reason varchar(64),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

do $$
begin
    with ranked as (
        select
            replay_id,
            row_number() over (
                partition by run_id
                order by updated_at desc, replay_id desc
            ) as rn
        from ai_replay_tracks
    )
    delete from ai_replay_tracks target
    using ranked
    where target.replay_id = ranked.replay_id
      and ranked.rn > 1;

    if not exists (
        select 1
        from pg_constraint
        where conrelid = 'ai_replay_tracks'::regclass
          and conname = 'ai_replay_tracks_run_id_key'
    ) then
        alter table ai_replay_tracks
            add constraint ai_replay_tracks_run_id_key unique (run_id);
    end if;
end
$$;

create index if not exists idx_ai_events_ticker_time on ai_events (ticker, event_time desc);
create index if not exists idx_ai_analysis_runs_event_time on ai_analysis_runs (event_id, created_at desc);
create index if not exists idx_ai_analysis_runs_strategy on ai_analysis_runs (strategy_code, created_at desc);
create index if not exists idx_ai_cards_run_priority on ai_cards (run_id, priority asc);
create index if not exists idx_ai_replay_tracks_event on ai_replay_tracks (event_id, created_at desc);
create index if not exists idx_ai_replay_tracks_status on ai_replay_tracks (status, updated_at desc);


create table if not exists ai_strategy_gate_patches (
    patch_id bigserial primary key,
    strategy_code varchar(64) not null,
    patch_json jsonb not null,
    rationale_ko text,
    source varchar(64),
    applied boolean not null default false,
    created_by varchar(64),
    created_at timestamptz not null default now()
);


create table if not exists ai_alert_state_actions (
    action_id bigserial primary key,
    code varchar(128) not null,
    scope varchar(64) not null default 'global',
    status varchar(32) not null,
    note text,
    muted_until timestamptz,
    actor varchar(64),
    created_at timestamptz not null default now()
);


create table if not exists ai_strategy_gate_active_configs (
    strategy_code varchar(64) primary key,
    active_patch_id bigint references ai_strategy_gate_patches(patch_id),
    patch_json jsonb not null,
    rationale_ko text,
    updated_by varchar(64),
    updated_at timestamptz not null default now()
);

alter table ai_signal_explanations
    add column if not exists details_json jsonb,
    add column if not exists signal_brief_json jsonb;

alter table ai_strategy_gate_patches
    add column if not exists patch_type varchar(32) not null default 'manual',
    add column if not exists scope_type varchar(32) not null default 'strategy_global',
    add column if not exists scope_key varchar(128),
    add column if not exists regime varchar(32),
    add column if not exists sector_code varchar(32),
    add column if not exists market_cap_bucket varchar(16),
    add column if not exists ticker varchar(16),
    add column if not exists universe_profile varchar(32),
    add column if not exists parent_patch_id bigint references ai_strategy_gate_patches(patch_id),
    add column if not exists report_id varchar(64),
    add column if not exists status varchar(32) not null default 'draft',
    add column if not exists approval_state varchar(32) not null default 'pending',
    add column if not exists last_transition_at timestamptz not null default now();

alter table ai_strategy_gate_active_configs
    add column if not exists scope_type varchar(32) not null default 'strategy_global',
    add column if not exists scope_key varchar(128),
    add column if not exists patch_source varchar(32) not null default 'manual';

create table if not exists ai_gate_patch_approvals (
    approval_id bigserial primary key,
    patch_id bigint not null references ai_strategy_gate_patches(patch_id) on delete cascade,
    decision varchar(32) not null,
    note text,
    approved_for_prod boolean not null default false,
    strict_prod_policy_passed boolean not null default false,
    actor varchar(64),
    created_at timestamptz not null default now()
);

create table if not exists ai_gate_patch_audit_logs (
    audit_id bigserial primary key,
    patch_id bigint not null references ai_strategy_gate_patches(patch_id) on delete cascade,
    event_type varchar(64) not null,
    status_from varchar(32),
    status_to varchar(32),
    approval_state_from varchar(32),
    approval_state_to varchar(32),
    payload_json jsonb,
    actor varchar(64),
    created_at timestamptz not null default now()
);

create table if not exists ai_gate_rollouts (
    rollout_id bigserial primary key,
    patch_id bigint not null references ai_strategy_gate_patches(patch_id) on delete cascade,
    strategy_code varchar(64) not null,
    scope_type varchar(32) not null default 'strategy_global',
    scope_key varchar(128),
    current_stage_pct int not null default 10,
    status varchar(32) not null default 'canary_active',
    mode varchar(32) not null default 'semi-auto',
    report_id varchar(64),
    approved_for_prod boolean not null default false,
    strict_prod_policy_passed boolean not null default false,
    created_by varchar(64),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists ai_gate_rollout_stage_events (
    stage_event_id bigserial primary key,
    rollout_id bigint not null references ai_gate_rollouts(rollout_id) on delete cascade,
    from_stage_pct int,
    to_stage_pct int,
    event_type varchar(64) not null,
    verdict varchar(32),
    payload_json jsonb,
    actor varchar(64),
    created_at timestamptz not null default now()
);

create table if not exists ai_engine_control_states (
    control_state_id bigserial primary key,
    control_type varchar(64) not null,
    enabled boolean not null default true,
    scope_type varchar(32) not null default 'global',
    scope_key varchar(128),
    note text,
    actor varchar(64),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists ai_engine_control_state_history (
    history_id bigserial primary key,
    control_state_id bigint references ai_engine_control_states(control_state_id) on delete set null,
    control_type varchar(64) not null,
    enabled boolean not null,
    scope_type varchar(32) not null,
    scope_key varchar(128),
    note text,
    actor varchar(64),
    created_at timestamptz not null default now()
);

create table if not exists ai_calibration_proposals (
    proposal_id bigserial primary key,
    patch_id bigint unique references ai_strategy_gate_patches(patch_id) on delete cascade,
    strategy_code varchar(64) not null,
    segment_type varchar(32) not null,
    segment_key varchar(128) not null,
    report_id varchar(64),
    proposal_json jsonb not null,
    summary_json jsonb,
    created_by varchar(64),
    promoted boolean not null default false,
    created_at timestamptz not null default now()
);

create table if not exists ai_hold_tuning_snapshots (
    snapshot_id bigserial primary key,
    strategy_code varchar(64) not null,
    segment_type varchar(32) not null,
    segment_key varchar(128) not null,
    expected_mfe_mae_ratio numeric(12,4),
    time_to_peak_ewma numeric(12,4),
    time_to_fail_ewma numeric(12,4),
    sample_size int not null default 0,
    as_of_date date not null default current_date,
    created_at timestamptz not null default now()
);

create table if not exists ai_regression_suites (
    suite_name varchar(64) primary key,
    suite_type varchar(32) not null default 'builtin',
    config_json jsonb,
    active boolean not null default true,
    created_at timestamptz not null default now()
);

create table if not exists ai_regression_reports (
    report_id varchar(64) primary key,
    suite_name varchar(64) not null references ai_regression_suites(suite_name),
    strategy_code varchar(64) not null,
    baseline_patch_id bigint,
    candidate_patch_id bigint,
    overall_json jsonb not null,
    strategy_delta_json jsonb,
    regime_delta_json jsonb,
    sector_delta_json jsonb,
    market_cap_delta_json jsonb,
    markdown_text text,
    verdict varchar(32) not null,
    promotion_recommendation varchar(64) not null,
    closed_replay_sample int not null default 0,
    created_by varchar(64),
    created_at timestamptz not null default now()
);

insert into ai_regression_suites (suite_name, suite_type, config_json)
values
    ('prod_guardrail_core', 'builtin', '{}'::jsonb),
    ('earnings_calls_recent', 'builtin', '{}'::jsonb),
    ('news_breakout_recent', 'builtin', '{}'::jsonb),
    ('nasdaq100_event_window', 'builtin', '{}'::jsonb),
    ('sp500_event_window', 'builtin', '{}'::jsonb)
on conflict (suite_name) do nothing;

create index if not exists idx_gate_patches_strategy_status on ai_strategy_gate_patches (strategy_code, status, created_at desc);
create index if not exists idx_gate_patches_scope on ai_strategy_gate_patches (scope_type, scope_key, created_at desc);
create index if not exists idx_gate_patches_segment on ai_strategy_gate_patches (strategy_code, regime, sector_code, market_cap_bucket, ticker);
create index if not exists idx_gate_patch_approvals_patch on ai_gate_patch_approvals (patch_id, created_at desc);
create index if not exists idx_gate_patch_audit_patch on ai_gate_patch_audit_logs (patch_id, created_at desc);
create index if not exists idx_gate_rollouts_patch on ai_gate_rollouts (patch_id, created_at desc);
create index if not exists idx_gate_rollouts_status on ai_gate_rollouts (status, updated_at desc);
create index if not exists idx_control_states_scope on ai_engine_control_states (control_type, scope_type, scope_key, updated_at desc);
create index if not exists idx_calibration_strategy_segment on ai_calibration_proposals (strategy_code, segment_type, segment_key, created_at desc);
create index if not exists idx_hold_tuning_strategy_segment on ai_hold_tuning_snapshots (strategy_code, segment_type, segment_key, created_at desc);
create index if not exists idx_regression_reports_strategy on ai_regression_reports (strategy_code, created_at desc);
