-- Ensure chunks.id and evidence.chunk_id match text type for compound IDs (document:page:chunk)
alter table chunks alter column id type text;

alter table evidence add column if not exists chunk_id text;
