create table if not exists ai_evidence_documents (
    document_id varchar(128) primary key,
    ticker varchar(32),
    source_type varchar(64) not null,
    source_name text not null,
    title text,
    published_at timestamptz,
    source_url text,
    content text not null,
    reliability_score double precision not null default 0.6,
    metadata_json jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);
create index if not exists idx_ai_evidence_ticker_date on ai_evidence_documents (ticker, published_at desc);
create index if not exists idx_ai_evidence_source_type on ai_evidence_documents (source_type);
create index if not exists idx_ai_evidence_fts on ai_evidence_documents using gin (to_tsvector('english', coalesce(title, '') || ' ' || content));
create table if not exists ai_company_impact_relationships (
    source_ticker varchar(32) not null,
    target_ticker varchar(32) not null,
    relationship varchar(128) not null,
    strength double precision not null default 0.5,
    payload_json jsonb not null default '{}'::jsonb,
    updated_at timestamptz not null default now(),
    primary key (source_ticker, target_ticker, relationship)
);
create table if not exists ai_executive_profiles (
    record_id varchar(128) primary key,
    ticker varchar(32) not null,
    payload_json jsonb not null,
    updated_at timestamptz not null default now()
);
create index if not exists idx_ai_executive_ticker on ai_executive_profiles (ticker, updated_at desc);
create table if not exists ai_speaker_metadata (
    record_id varchar(128) primary key,
    ticker varchar(32) not null,
    payload_json jsonb not null,
    updated_at timestamptz not null default now()
);
create index if not exists idx_ai_speaker_ticker on ai_speaker_metadata (ticker, updated_at desc);
create table if not exists ai_evidence_ingestion_runs (
    run_id varchar(128) primary key,
    ticker varchar(32),
    status varchar(32) not null,
    source_counts_json jsonb not null default '{}'::jsonb,
    errors_json jsonb not null default '{}'::jsonb,
    started_at timestamptz not null default now(),
    finished_at timestamptz
);
create table if not exists ai_live_earnings_sessions (
    session_id varchar(128) primary key,
    ticker varchar(32) not null,
    status varchar(32) not null,
    started_at timestamptz not null,
    updated_at timestamptz not null,
    completed_at timestamptz,
    payload_json jsonb not null,
    created_at timestamptz not null default now()
);
create index if not exists idx_ai_live_sessions_ticker_updated on ai_live_earnings_sessions (ticker, updated_at desc);
create index if not exists idx_ai_live_sessions_status_updated on ai_live_earnings_sessions (status, updated_at desc);
