-- ═══════════════════════════════════════════════════════════════════════
-- الشريحة 5 — حلقة الموافقة
-- شغّل الملف ده مرة واحدة في Supabase → SQL Editor
--
-- الجدول ده هو **الحقيقة الأرضية** بتاعة المشروع كله. كل ضغطة زرار
-- منك = تسمية مجانية. بعد ~6 أسابيع بيبقى فيه عيّنة كفاية نقيس بيها
-- هل التقييم بيتوقّع الردود فعلاً — وهي الحاجة اللي كل مشروع جانبي
-- بيفتقدها.
-- ═══════════════════════════════════════════════════════════════════════

create table if not exists applications (
    id          bigserial primary key,
    job_id      bigint not null references jobs(id) on delete cascade,

    -- applied  = دُست ✅، هتقدّم
    -- skipped  = دُست ❌
    -- later    = دُست 🕐
    status      text   not null,

    decided_at  timestamptz not null default now(),

    -- الشريحة 6: النقط اللي اتاختارت للـ CV
    bullet_ids  text[],

    -- الشريحة 7: "خلّصت تقديم فعلاً؟" — بيتسأل بعد ساعة.
    -- من غيره، "applied" معناها "دُست زرار" مش "قدّمت".
    confirmed   boolean,

    -- النتيجة النهائية: رد · مقابلة · رفض · مفيش
    outcome     text,
    outcome_at  timestamptz,

    notes       text,

    -- وظيفة واحدة = قرار واحد. الضغط مرتين بيحدّث مش بيضيف.
    constraint applications_job_uniq unique (job_id),
    constraint applications_status_ck
        check (status in ('applied', 'skipped', 'later')),
    constraint applications_outcome_ck
        check (outcome is null or outcome in
               ('reply', 'interview', 'offer', 'rejected', 'none'))
);

create index if not exists applications_status_idx  on applications (status, decided_at desc);
create index if not exists applications_outcome_idx on applications (outcome)
    where outcome is not null;

alter table applications enable row level security;
