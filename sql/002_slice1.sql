-- ═══════════════════════════════════════════════════════════════════════
-- Apply Agent — الشريحة 1
-- شغّل الملف ده مرة واحدة في Supabase → SQL Editor
--
-- بيلغي 001_schema.sql ويحل محله. الفروق:
--   · poll_runs → agent_runs  (نفس الجدول هيسجّل التقييم والتليجرام بعدين)
--   · الموقع بقى داخل في البصمة
-- ═══════════════════════════════════════════════════════════════════════

drop table if exists poll_runs;

-- ── الوظايف ────────────────────────────────────────────────────────────

create table if not exists jobs (
    id             bigserial primary key,

    company_name   text        not null,
    ats            text        not null,   -- greenhouse|lever|ashby|recruitee|workable
    external_id    text        not null,   -- رقم الوظيفة عند الشركة

    title          text        not null,
    location       text,
    remote_type    text,                   -- remote | hybrid | onsite | unknown
    description    text,
    url            text,
    posted_at      timestamptz,

    -- الشركة + العنوان + الموقع + الوصف، بعد التطبيع.
    -- الـ unique هنا هو الضمانة الحقيقية: حتى لو الكود غلط، الداتابيز
    -- نفسها مش هتقبل نفس الوظيفة مرتين.
    content_hash   text        not null unique,

    first_seen_at  timestamptz not null default now(),
    last_seen_at   timestamptz not null default now()
);

create index if not exists jobs_first_seen_idx on jobs (first_seen_at desc);
create index if not exists jobs_company_idx    on jobs (company_name);
create index if not exists jobs_ats_extid_idx  on jobs (ats, external_id);
create index if not exists jobs_last_seen_idx  on jobs (last_seen_at desc);

-- ── سجل التشغيلات ──────────────────────────────────────────────────────
-- جدول واحد لكل المكوّنات، مش واحد لكل مكوّن. العمود component بيفرّق.
-- كده أي سؤال عن "المنظومة عملت إيه امبارح؟" بيتجاوب من مكان واحد.

create table if not exists agent_runs (
    id           bigserial primary key,
    component    text        not null,      -- discover | score | prepare | ...
    started_at   timestamptz not null default now(),
    finished_at  timestamptz,
    status       text        not null default 'running',  -- running|ok|partial|failed
    items_seen   int         not null default 0,
    items_new    int         not null default 0,
    detail       jsonb,

    constraint agent_runs_status_ck
        check (status in ('running', 'ok', 'partial', 'failed'))
);

create index if not exists agent_runs_component_idx on agent_runs (component, started_at desc);

-- ── الأمان ─────────────────────────────────────────────────────────────
-- بنشغّل RLS من غير أي policy. النتيجة: مفتاح anon مش شايف حاجة خالص،
-- ومفتاح service_role (اللي السكريبت بيستخدمه) بيتخطّاها.
-- يعني لو المفتاح العام تسرّب، مش هيوصل لأي بيانات.

alter table jobs       enable row level security;
alter table agent_runs enable row level security;
