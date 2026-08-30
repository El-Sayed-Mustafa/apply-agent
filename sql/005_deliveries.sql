-- ═══════════════════════════════════════════════════════════════════════
-- الشريحة 4 — الإرسال على تليجرام
-- شغّل الملف ده مرة واحدة في Supabase → SQL Editor
-- ═══════════════════════════════════════════════════════════════════════

create table if not exists deliveries (
    id           bigserial primary key,
    job_id       bigint not null references jobs(id) on delete cascade,
    channel      text   not null default 'telegram',

    -- رقم الرسالة عند تليجرام. الشريحة 5 هتحتاجه عشان تعدّل الرسالة
    -- نفسها لما تدوس زرار — بدل ما تبعت رسالة جديدة.
    message_id   bigint,

    score_at_send int,
    sent_at      timestamptz not null default now(),
    error        text,

    -- الضمانة الحقيقية: مستحيل تتبعت نفس الوظيفة مرتين على نفس القناة،
    -- حتى لو الكود غلط أو التشغيلة اتكررت.
    constraint deliveries_job_channel_uniq unique (job_id, channel)
);

create index if not exists deliveries_sent_idx on deliveries (sent_at desc);

alter table deliveries enable row level security;
