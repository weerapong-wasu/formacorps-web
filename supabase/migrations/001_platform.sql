-- ============================================================
-- Forma Constructor OS™ — Platform Migration 001
-- Sprint 5 · Yaya v2.5
-- ============================================================
-- Creates the three core tables (profiles, orders, projects),
-- enables Row Level Security, defines policies, and installs a
-- trigger that auto-creates a 'free'-tier profile when a new
-- auth.users row appears (covers email + Google OAuth).
--
-- Run order:
--   1. Review this file end-to-end before applying.
--   2. Apply via Supabase SQL Editor or `supabase db push`.
--   3. Verify with the smoke-test queries at the bottom.
--
-- Idempotency:
--   - Uses CREATE TABLE IF NOT EXISTS, CREATE POLICY ... blocks
--     gated by pg_policies checks, and CREATE OR REPLACE FUNCTION
--     so the file is safe to re-run.
--
-- Security model (CLAUDE.md §Security Rules):
--   - RLS is the REAL gate. Every table has RLS enabled and an
--     explicit deny-by-default posture (no policy => no access).
--   - Frontend uses anon key only; service_role stays in Vercel.
--   - tier upgrades happen via service_role on /admin/orders.html
--     after manual PromptPay confirmation by HT.
-- ============================================================

-- ------------------------------------------------------------
-- 0. Extensions
-- ------------------------------------------------------------
create extension if not exists "pgcrypto";   -- for gen_random_uuid()

-- ------------------------------------------------------------
-- 1. Tables
-- ------------------------------------------------------------

-- 1a. profiles: 1:1 with auth.users
create table if not exists public.profiles (
  id              uuid primary key references auth.users(id) on delete cascade,
  email           text,
  full_name       text,
  phone           text,
  tier            text not null default 'free'
                  check (tier in ('free','pro','engineer','enterprise')),
  tier_expires_at timestamptz,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

comment on table  public.profiles is 'User profile, 1:1 with auth.users. tier governs access.';
comment on column public.profiles.tier is 'free | pro | engineer | enterprise';
comment on column public.profiles.tier_expires_at is 'When non-null and past, treat as free (client and server both check).';

-- 1b. orders: PromptPay (manual confirm) and future Stripe sessions
create table if not exists public.orders (
  id             uuid primary key default gen_random_uuid(),
  user_id        uuid not null references public.profiles(id) on delete cascade,
  package_name   text not null
                 check (package_name in (
                   'pro_monthly','pro_onetime',
                   'engineer_monthly','engineer_onetime',
                   'enterprise_monthly'
                 )),
  amount_thb     numeric(10,2) not null check (amount_thb >= 0),
  payment_method text not null check (payment_method in ('promptpay','stripe')),
  payment_ref    text,
  status         text not null default 'pending'
                 check (status in ('pending','confirmed','expired')),
  tier_granted   text check (tier_granted in ('pro','engineer','enterprise')),
  pdf_url        text,
  created_at     timestamptz not null default now(),
  confirmed_at   timestamptz
);

comment on table public.orders is 'Payment orders. status flips to confirmed by HT (service_role) on PromptPay receipt.';

create index if not exists orders_user_id_idx       on public.orders(user_id);
create index if not exists orders_status_idx        on public.orders(status);
create index if not exists orders_created_at_idx    on public.orders(created_at desc);

-- 1c. projects: calc history per user
create table if not exists public.projects (
  id            uuid primary key default gen_random_uuid(),
  user_id       uuid not null references public.profiles(id) on delete cascade,
  project_name  text not null,
  building_type text check (building_type in (
                  'house','warehouse','cafe','townhome','datacenter','other'
                )),
  input_data    jsonb not null default '{}'::jsonb,
  calc_results  jsonb not null default '{}'::jsonb,
  pdf_url       text,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);

comment on table public.projects is 'Saved calculation projects. Stores inputs and 6-layer outputs as JSONB.';

create index if not exists projects_user_id_idx    on public.projects(user_id);
create index if not exists projects_created_at_idx on public.projects(created_at desc);

-- ------------------------------------------------------------
-- 2. updated_at trigger (shared)
-- ------------------------------------------------------------
create or replace function public.tg_set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists set_updated_at on public.profiles;
create trigger set_updated_at
  before update on public.profiles
  for each row execute function public.tg_set_updated_at();

drop trigger if exists set_updated_at on public.projects;
create trigger set_updated_at
  before update on public.projects
  for each row execute function public.tg_set_updated_at();

-- ------------------------------------------------------------
-- 3. Auto-create profile on auth.users insert
-- ------------------------------------------------------------
-- Runs as SECURITY DEFINER so it can write to public.profiles
-- regardless of the caller. Pulls full_name from raw_user_meta_data
-- which Supabase populates from both email signup options.data
-- and Google OAuth ('full_name' or 'name').
create or replace function public.tg_handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  insert into public.profiles (id, email, full_name, phone, tier)
  values (
    new.id,
    new.email,
    coalesce(
      new.raw_user_meta_data ->> 'full_name',
      new.raw_user_meta_data ->> 'name',
      null
    ),
    coalesce(new.raw_user_meta_data ->> 'phone', new.phone),
    'free'
  )
  on conflict (id) do nothing;   -- idempotent w/ client ensureProfile()
  return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.tg_handle_new_user();

-- ------------------------------------------------------------
-- 4. Row Level Security
-- ------------------------------------------------------------
alter table public.profiles enable row level security;
alter table public.orders   enable row level security;
alter table public.projects enable row level security;

-- 4a. profiles policies
do $$
begin
  if not exists (select 1 from pg_policies
                 where schemaname='public' and tablename='profiles'
                   and policyname='profiles_select_own') then
    create policy profiles_select_own
      on public.profiles for select
      using (auth.uid() = id);
  end if;

  if not exists (select 1 from pg_policies
                 where schemaname='public' and tablename='profiles'
                   and policyname='profiles_insert_own') then
    -- Safety net for client-side ensureProfile(); the trigger above
    -- normally handles this, but allowing self-insert keeps the
    -- frontend path working if the trigger is ever disabled.
    create policy profiles_insert_own
      on public.profiles for insert
      with check (auth.uid() = id);
  end if;

  if not exists (select 1 from pg_policies
                 where schemaname='public' and tablename='profiles'
                   and policyname='profiles_update_own') then
    -- Users may update their own row, BUT cannot escalate tier.
    -- A WITH CHECK clause forbids changing tier or tier_expires_at
    -- via the anon key — those fields can only move via service_role.
    create policy profiles_update_own
      on public.profiles for update
      using (auth.uid() = id)
      with check (
        auth.uid() = id
        and tier            = (select tier            from public.profiles where id = auth.uid())
        and tier_expires_at is not distinct from
            (select tier_expires_at from public.profiles where id = auth.uid())
      );
  end if;
end $$;

-- 4b. orders policies (read-only for the user; writes via service_role)
do $$
begin
  if not exists (select 1 from pg_policies
                 where schemaname='public' and tablename='orders'
                   and policyname='orders_select_own') then
    create policy orders_select_own
      on public.orders for select
      using (auth.uid() = user_id);
  end if;

  if not exists (select 1 from pg_policies
                 where schemaname='public' and tablename='orders'
                   and policyname='orders_insert_own') then
    -- User can create a pending order for themselves; status MUST
    -- start as 'pending' and tier_granted is still nullable here.
    -- HT confirms via service_role from /admin/orders.html.
    create policy orders_insert_own
      on public.orders for insert
      with check (
        auth.uid() = user_id
        and status = 'pending'
      );
  end if;
  -- No UPDATE/DELETE policy => anon key cannot mutate orders.
end $$;

-- 4c. projects policies (full CRUD on own rows)
do $$
begin
  if not exists (select 1 from pg_policies
                 where schemaname='public' and tablename='projects'
                   and policyname='projects_select_own') then
    create policy projects_select_own
      on public.projects for select using (auth.uid() = user_id);
  end if;

  if not exists (select 1 from pg_policies
                 where schemaname='public' and tablename='projects'
                   and policyname='projects_insert_own') then
    create policy projects_insert_own
      on public.projects for insert with check (auth.uid() = user_id);
  end if;

  if not exists (select 1 from pg_policies
                 where schemaname='public' and tablename='projects'
                   and policyname='projects_update_own') then
    create policy projects_update_own
      on public.projects for update
      using (auth.uid() = user_id)
      with check (auth.uid() = user_id);
  end if;

  if not exists (select 1 from pg_policies
                 where schemaname='public' and tablename='projects'
                   and policyname='projects_delete_own') then
    create policy projects_delete_own
      on public.projects for delete using (auth.uid() = user_id);
  end if;
end $$;

-- ------------------------------------------------------------
-- 5. Smoke-test queries (run manually after applying)
-- ------------------------------------------------------------
-- select tablename, rowsecurity from pg_tables where schemaname='public';
-- -- Expect: rowsecurity = true for profiles, orders, projects
--
-- select tablename, policyname, cmd from pg_policies
--  where schemaname='public' order by tablename, policyname;
-- -- Expect:
-- --   profiles: select_own, insert_own, update_own
-- --   orders  : select_own, insert_own
-- --   projects: select_own, insert_own, update_own, delete_own
--
-- -- After signing up a test user via the app:
-- select id, email, tier from public.profiles;
-- -- Expect: one row, tier='free'
-- ============================================================
