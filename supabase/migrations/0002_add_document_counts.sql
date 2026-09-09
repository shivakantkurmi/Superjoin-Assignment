-- Add facts_count and relationships_count columns to documents
-- These are updated by the application after processing to provide quick status counts.

alter table documents
    add column if not exists facts_count integer not null default 0,
    add column if not exists relationships_count integer not null default 0;
