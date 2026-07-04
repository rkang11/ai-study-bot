create extension if not exists vector with schema extensions;

create table if not exists public.documents (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    file_name text not null,
    file_type text not null,
    char_count integer not null default 0,
    created_at timestamp with time zone not null default now()
);

create table if not exists public.document_chunks (
    id uuid primary key default gen_random_uuid(),
    document_id uuid not null references public.documents(id) on delete cascade,
    user_id uuid not null references auth.users(id) on delete cascade,
    chunk_index integer not null,
    page_number integer,
    chunk_text text not null,
    embedding extensions.vector(768) not null,
    created_at timestamp with time zone not null default now()
);

create table if not exists public.flashcards (
    id uuid primary key default gen_random_uuid(),
    document_id uuid references public.documents(id) on delete cascade,
    user_id uuid not null references auth.users(id) on delete cascade,
    content text not null,
    created_at timestamp with time zone not null default now()
);

create table if not exists public.quizzes (
    id uuid primary key default gen_random_uuid(),
    document_id uuid references public.documents(id) on delete cascade,
    user_id uuid not null references auth.users(id) on delete cascade,
    quiz_type text not null,
    content text not null,
    created_at timestamp with time zone not null default now()
);

create table if not exists public.quiz_attempts (
    id uuid primary key default gen_random_uuid(),
    quiz_id uuid not null references public.quizzes(id) on delete cascade,
    user_id uuid not null references auth.users(id) on delete cascade,
    score numeric,
    answers jsonb,
    created_at timestamp with time zone not null default now()
);

create table if not exists public.study_sessions (
    id uuid primary key default gen_random_uuid(),
    document_id uuid references public.documents(id) on delete set null,
    user_id uuid not null references auth.users(id) on delete cascade,
    activity_type text not null,
    created_at timestamp with time zone not null default now()
);

create index if not exists document_chunks_embedding_idx
on public.document_chunks using ivfflat (embedding vector_cosine_ops)
with (lists = 100);

alter table public.documents enable row level security;
alter table public.document_chunks enable row level security;
alter table public.flashcards enable row level security;
alter table public.quizzes enable row level security;
alter table public.quiz_attempts enable row level security;
alter table public.study_sessions enable row level security;

drop policy if exists "Users can manage their own documents"
on public.documents;
create policy "Users can manage their own documents"
on public.documents
for all
using (auth.uid() = user_id)
with check (auth.uid() = user_id);

drop policy if exists "Users can manage their own document chunks"
on public.document_chunks;
create policy "Users can manage their own document chunks"
on public.document_chunks
for all
using (auth.uid() = user_id)
with check (auth.uid() = user_id);

drop policy if exists "Users can manage their own flashcards"
on public.flashcards;
create policy "Users can manage their own flashcards"
on public.flashcards
for all
using (auth.uid() = user_id)
with check (auth.uid() = user_id);

drop policy if exists "Users can manage their own quizzes"
on public.quizzes;
create policy "Users can manage their own quizzes"
on public.quizzes
for all
using (auth.uid() = user_id)
with check (auth.uid() = user_id);

drop policy if exists "Users can manage their own quiz attempts"
on public.quiz_attempts;
create policy "Users can manage their own quiz attempts"
on public.quiz_attempts
for all
using (auth.uid() = user_id)
with check (auth.uid() = user_id);

drop policy if exists "Users can manage their own study sessions"
on public.study_sessions;
create policy "Users can manage their own study sessions"
on public.study_sessions
for all
using (auth.uid() = user_id)
with check (auth.uid() = user_id);

create or replace function public.match_document_chunks(
    query_embedding extensions.vector(768),
    match_user_id uuid,
    match_document_id uuid default null,
    match_count integer default 5
)
returns table (
    id uuid,
    document_id uuid,
    file_name text,
    page_number integer,
    chunk_text text,
    similarity double precision
)
language sql
stable
as $$
    select
        document_chunks.id,
        document_chunks.document_id,
        documents.file_name,
        document_chunks.page_number,
        document_chunks.chunk_text,
        1 - (document_chunks.embedding <=> query_embedding) as similarity
    from public.document_chunks
    join public.documents on documents.id = document_chunks.document_id
    where document_chunks.user_id = match_user_id
      and (match_document_id is null or document_chunks.document_id = match_document_id)
    order by document_chunks.embedding <=> query_embedding
    limit match_count;
$$;

notify pgrst, 'reload schema';
