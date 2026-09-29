-- Enquete pública do Radar das Eleições.
-- Votos anônimos e repetidos são permitidos intencionalmente.
create table if not exists public.research_votes (
 id bigint generated always as identity primary key,
 office text not null check (office in ('president','governor')),
 state_code text not null,
 candidate_id text not null check (length(candidate_id) between 1 and 80),
 created_at timestamptz not null default now(),
 constraint research_votes_scope_check check (
  (office='president' and state_code='BR') or
  (office='governor' and state_code in ('AC','AL','AP','AM','BA','CE','DF','ES','GO','MA','MT','MS','MG','PA','PB','PR','PE','PI','RJ','RN','RS','RO','RR','SC','SP','SE','TO'))
 )
);
create index if not exists research_votes_tally_idx on public.research_votes (office,state_code,candidate_id);
alter table public.research_votes enable row level security;
revoke all on table public.research_votes from public,anon,authenticated;

create or replace function public.register_research_vote(p_office text,p_state_code text,p_candidate_id text)
returns void language plpgsql security definer set search_path=''
as $$
begin
 if p_office not in ('president','governor') then raise exception 'Invalid office'; end if;
 if p_candidate_id is null or length(trim(p_candidate_id))=0 or length(p_candidate_id)>80 then raise exception 'Invalid candidate'; end if;
 if not ((p_office='president' and p_state_code='BR') or (p_office='governor' and p_state_code in ('AC','AL','AP','AM','BA','CE','DF','ES','GO','MA','MT','MS','MG','PA','PB','PR','PE','PI','RJ','RN','RS','RO','RR','SC','SP','SE','TO'))) then raise exception 'Invalid poll scope'; end if;
 insert into public.research_votes(office,state_code,candidate_id) values(p_office,p_state_code,trim(p_candidate_id));
end;
$$;

create or replace function public.get_research_vote_counts(p_office text,p_state_code text)
returns table(candidate_id text,vote_count bigint)
language sql stable security definer set search_path=''
as $$
 select v.candidate_id,count(*)::bigint
 from public.research_votes as v
 where v.office=p_office and v.state_code=p_state_code
 group by v.candidate_id;
$$;
revoke all on function public.register_research_vote(text,text,text) from public;
revoke all on function public.get_research_vote_counts(text,text) from public;
grant execute on function public.register_research_vote(text,text,text) to anon,authenticated;
grant execute on function public.get_research_vote_counts(text,text) to anon,authenticated;
