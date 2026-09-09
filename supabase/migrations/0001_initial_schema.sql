create extension if not exists pgcrypto;

create table if not exists documents (
    id uuid primary key default gen_random_uuid(),
    filename text not null,
    file_hash text not null unique,
    uploaded_at timestamptz not null default now(),
    status text not null default 'QUEUED',
    page_count integer not null default 0,
    metadata jsonb not null default '{}'::jsonb
);

create table if not exists pages (
    id uuid primary key default gen_random_uuid(),
    document_id uuid not null references documents(id) on delete cascade,
    page_number integer not null,
    text text not null default '',
    is_scanned boolean not null default false,
    unique (document_id, page_number)
);

create table if not exists chunks (
    id text primary key,
    document_id uuid not null references documents(id) on delete cascade,
    page_id uuid not null references pages(id) on delete cascade,
    chunk_index integer not null,
    text text not null,
    embedding_status text not null default 'PENDING',
    unique (page_id, chunk_index)
);

create table if not exists facts (
    id uuid primary key default gen_random_uuid(),
    document_id uuid not null references documents(id) on delete cascade,
    fact_type text not null,
    subject text not null,
    predicate text not null,
    object_value jsonb,
    normalized_value jsonb,
    unit text,
    currency text,
    time_start date,
    time_end date,
    time_label text,
    scope text,
    location text,
    qualifiers jsonb not null default '{}'::jsonb,
    confidence numeric(5,4) not null,
    status text not null default 'VALID',
    created_at timestamptz not null default now()
);

create table if not exists evidence (
    id uuid primary key default gen_random_uuid(),
    fact_id uuid not null references facts(id) on delete cascade,
    document_id uuid not null references documents(id) on delete cascade,
    page_id uuid not null references pages(id) on delete cascade,
    chunk_id text,
    quote text not null,
    char_start integer,
    char_end integer,
    bbox jsonb,
    verification_status text not null default 'PENDING'
);

create table if not exists relationships (
    id uuid primary key default gen_random_uuid(),
    fact_a_id uuid not null references facts(id) on delete cascade,
    fact_b_id uuid not null references facts(id) on delete cascade,
    relationship_type text not null,
    confidence numeric(5,4) not null,
    explanation text not null,
    reasoning_metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    check (fact_a_id <> fact_b_id),
    unique (fact_a_id, fact_b_id)
);

create table if not exists processing_runs (
    id uuid primary key default gen_random_uuid(),
    document_id uuid not null references documents(id) on delete cascade,
    status text not null,
    started_at timestamptz not null default now(),
    completed_at timestamptz,
    error text
);

create table if not exists processing_errors (
    id uuid primary key default gen_random_uuid(),
    document_id uuid not null references documents(id) on delete cascade,
    page_id uuid references pages(id) on delete set null,
    stage text not null,
    error_type text not null,
    message text not null,
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

create index if not exists facts_document_id_idx on facts(document_id);
create index if not exists facts_subject_predicate_idx on facts(subject, predicate);
create index if not exists evidence_fact_id_idx on evidence(fact_id);
create index if not exists relationships_fact_a_idx on relationships(fact_a_id);
create index if not exists relationships_fact_b_idx on relationships(fact_b_id);
create index if not exists processing_errors_document_id_idx on processing_errors(document_id);