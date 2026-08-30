-- ═══════════════════════════════════════════════════════════════════════
-- الشريحة 2.5 — حلقة اكتشاف الشركات
-- شغّل الملف ده مرة واحدة في Supabase → SQL Editor
--
-- السجل بينتقل من ملف YAML لجدول. السبب: المنظومة لازم تقدر تضيف
-- شركات لوحدها، وملف في git مينفعش يتكتب من workflow في السحابة.
-- الـ YAML بيفضل موجود كـ "بذرة" — الشركات اللي إنت اخترتها بإيدك.
-- ═══════════════════════════════════════════════════════════════════════

create table if not exists companies (
    id              bigserial primary key,

    name            text not null,
    ats             text,          -- greenhouse|lever|ashby|recruitee|workable
    token           text,

    tier            int  not null default 2,

    -- seed       = من companies.yaml، إنت اللي حطيتها
    -- discovered = المنظومة لقيتها من مصدر تجميعي
    source          text not null default 'discovered',

    -- active     = الـ token شغال، بنسحب منها كل ساعة
    -- unresolved = ملقناش token. بنعيد المحاولة بعد فترة، مش كل ساعة
    -- dead       = كانت شغالة وبقت بترجّع 404
    status          text not null default 'unresolved',

    jobs_count      int  not null default 0,
    discovered_from text,          -- اسم المصدر التجميعي اللي طلّع الاسم
    attempts        int  not null default 0,

    first_seen_at   timestamptz not null default now(),
    last_checked_at timestamptz,

    constraint companies_status_ck
        check (status in ('active', 'unresolved', 'dead')),
    constraint companies_source_ck
        check (source in ('seed', 'discovered'))
);

-- الاسم المطبّع هو المفتاح الحقيقي: "Cohere" و"cohere " و"COHERE"
-- كلهم شركة واحدة. مفهرس مش عمود عشان مانكررش البيانات.
create unique index if not exists companies_name_uniq
    on companies (lower(btrim(name)));

-- شركتين مختلفتين مايقدروش ياخدوا نفس الـ token على نفس النظام
create unique index if not exists companies_ats_token_uniq
    on companies (ats, token) where ats is not null and token is not null;

create index if not exists companies_status_idx on companies (status, tier);

-- بنعيد محاولة الشركات اللي ملقناش لها token — بس مش كل ساعة.
-- الفهرس ده بيخلي "مين محتاج إعادة محاولة؟" استعلام رخيص.
create index if not exists companies_retry_idx
    on companies (last_checked_at) where status = 'unresolved';

alter table companies enable row level security;
