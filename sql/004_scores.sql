-- ═══════════════════════════════════════════════════════════════════════
-- الشريحة 3 — التقييم
-- شغّل الملف ده مرة واحدة في Supabase → SQL Editor
-- ═══════════════════════════════════════════════════════════════════════

create table if not exists scores (
    id             bigserial primary key,
    job_id         bigint not null references jobs(id) on delete cascade,

    -- نسخة المقيّم = بصمة الـ prompt والقواعد. لما تغيّر الـ prompt،
    -- بتغيّر الرقم ده، وكل الوظايف بتتقيّم من جديد تلقائيًا —
    -- والتقييمات القديمة بتفضل موجودة للمقارنة.
    scorer_version text   not null,
    model          text   not null,

    score_initial  int,                   -- التقييم الأول
    score_final    int,                   -- بعد الـ refuter (الشريحة 7)
    verdict        text,                  -- strong|good|partial|weak|no

    matched        text[],
    gaps           text[],
    reasoning      text,

    total_tokens   int,
    created_at     timestamptz not null default now(),

    -- وظيفة واحدة + نسخة مقيّم واحدة = صف واحد.
    -- ودي بالظبط اللي بتخلي الجدول طابور: الوظيفة اللي مالهاش صف
    -- بالنسخة الحالية = وظيفة لسه محتاجة تقييم.
    constraint scores_job_version_uniq unique (job_id, scorer_version),
    constraint scores_range_ck check (
        (score_initial is null or score_initial between 0 and 100) and
        (score_final   is null or score_final   between 0 and 100)
    )
);

create index if not exists scores_job_idx    on scores (job_id);
create index if not exists scores_rank_idx   on scores (scorer_version, score_final desc nulls last);

-- عدد المحاولات الفاشلة لكل وظيفة. من غيره، وظيفة بتكسّر الموديل
-- هتتحاول كل ساعة للأبد وتاكل الميزانية كلها.
create table if not exists score_attempts (
    job_id         bigint not null references jobs(id) on delete cascade,
    scorer_version text   not null,
    attempts       int    not null default 0,
    last_error     text,
    last_try_at    timestamptz not null default now(),
    primary key (job_id, scorer_version)
);

alter table scores         enable row level security;
alter table score_attempts enable row level security;
