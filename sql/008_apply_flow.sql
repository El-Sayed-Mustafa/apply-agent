-- ═══════════════════════════════════════════════════════════════════════
-- الدفعة 2: التقديم من تليجرام بموافقتين.
--
--   ضغطة ✅ قدّم  = جهّز (سي في، cover letter، إجابات) واملا الفورم
--   ضغطة ✅ ابعت = اضغط Submit — طلب موافقة منفصل، وبينتهي
--
-- شغّله مرة واحدة في Supabase → SQL Editor. آمن لو اتشغّل تاني.
-- ═══════════════════════════════════════════════════════════════════════

-- ── حالات التقديم ──────────────────────────────────────────────────────
-- القديمة (applied · skipped · later) زي ما هي، والقياس القديم شغال.
--   approved  = دُست "قدّم" — مستني التجهيز
--   saved     = دُست "احفظ"
--   ready     = الفورم اتملى، مستني موافقتك على الإرسال
--   manual    = مش هنقدّم أوتوماتيك (Easy Apply، CAPTCHA، حساب…) — الملف
--               اتبعتلك وإنت تقدّم
--   failed    = حصل عطل، والسبب في notes
alter table applications drop constraint if exists applications_status_ck;
alter table applications add constraint applications_status_ck
    check (status in ('applied', 'skipped', 'later', 'approved', 'saved',
                      'ready', 'manual', 'failed'));

alter table applications add column if not exists submitted_at timestamptz;
alter table applications add column if not exists updated_at  timestamptz default now();

-- ── طلبات الموافقة ─────────────────────────────────────────────────────
-- كل زرار فيه رقم الطلب ده، مش رقم الوظيفة. فضغطة قديمة على رسالة من
-- أسبوع بتتفحص: الطلب لسه pending؟ ما انتهتش صلاحيته؟ — ولو لأ، بتترفض.
create table if not exists approval_requests (
    id          bigserial primary key,
    job_id      bigint not null references jobs(id) on delete cascade,
    kind        text   not null,          -- submit
    status      text   not null default 'pending',
    payload     jsonb,                    -- ملخص اللي هيتبعت (للمراجعة)
    message_id  bigint,                   -- رسالة تليجرام اللي فيها الأزرار
    created_at  timestamptz not null default now(),
    expires_at  timestamptz not null,
    decided_at  timestamptz,
    constraint approval_kind_ck   check (kind in ('submit')),
    constraint approval_status_ck check (status in
        ('pending', 'approved', 'rejected', 'expired', 'done'))
);
-- طلب إرسال واحد مفتوح لكل وظيفة — مستحيل يتبعت مرتين
create unique index if not exists approval_one_open_submit
    on approval_requests (job_id) where kind = 'submit' and status in ('pending', 'approved');
create index if not exists approval_status_idx on approval_requests (status, kind);

-- ── مستندات التقديم ────────────────────────────────────────────────────
-- كل نسخة سي في / cover letter / إجابات / دليل إرسال، مربوطة بالوظيفة
-- والوقت. الملف نفسه على جهازك (applications/ — في .gitignore)، وهنا
-- مكانه وبصمته.
create table if not exists application_documents (
    id          bigserial primary key,
    job_id      bigint not null references jobs(id) on delete cascade,
    kind        text   not null,
    path        text,
    sha256      text,
    content     text,                     -- للنصوص القصيرة (cover letter، إجابات)
    created_at  timestamptz not null default now(),
    constraint documents_kind_ck check (kind in
        ('cv', 'cover_letter', 'answers', 'form_preview', 'submission_evidence'))
);
create index if not exists documents_job_idx on application_documents (job_id, kind);

-- ── ردود نصية من تليجرام ───────────────────────────────────────────────
-- لما النظام يسألك سؤال مش في answers.yaml، بترد عليه reply في تليجرام.
-- الـwebhook بيحفظ الرد هنا، والتقديم بيقراه.
create table if not exists tg_messages (
    id              bigserial primary key,
    message_id      bigint not null,
    reply_to_id     bigint,
    text            text   not null,
    created_at      timestamptz not null default now(),
    consumed_at     timestamptz
);
create index if not exists tg_messages_reply_idx on tg_messages (reply_to_id);
