// ═══════════════════════════════════════════════════════════════════════
// مستقبِل ضغطات الأزرار من تليجرام.
//
// ده الجزء الوحيد في المنظومة المفتوح على الإنترنت. أي حد يعرف الرابط
// يقدر يبعتله. عشان كده فيه ٣ طبقات، كل واحدة بتتفحص قبل أي كتابة:
//
//   ١. توكن سري في الهيدر  — تليجرام بس اللي بيبعته، وإحنا اللي حطيناه
//   ٢. قفل على chat_id     — حتى لو التوكن اتسرّب، شات تاني مايقدرش يكتب
//   ٣. تحقق من الشكل       — أي حاجة برّه الشكل المتوقع تترفض
//
// وبيرد على تليجرام في أقل من ثانية — من غير كده الزرار بيلف ويقف
// من غير ما يحصل حاجة، والمستخدم يفتكر إن الحاجة بايظة.
// ═══════════════════════════════════════════════════════════════════════

import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const BOT_TOKEN = Deno.env.get("TELEGRAM_BOT_TOKEN")!;
const SECRET = Deno.env.get("TELEGRAM_WEBHOOK_SECRET")!;
const ALLOWED_CHAT = Deno.env.get("TELEGRAM_CHAT_ID")!;

const db = createClient(
  Deno.env.get("SUPABASE_URL")!,
  Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!,
);

const ACTIONS: Record<string, { status: string; label: string; toast: string }> = {
  a: { status: "applied", label: "✅ قدّمت", toast: "اتسجّل — بالتوفيق" },
  s: { status: "skipped", label: "❌ مش مناسبة", toast: "اتسجّل" },
  l: { status: "later", label: "🕐 بعدين", toast: "اتأجّلت" },
};

async function tg(method: string, body: unknown) {
  return fetch(`https://api.telegram.org/bot${BOT_TOKEN}/${method}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
}

Deno.serve(async (req) => {
  // ── الطبقة ١: التوكن السري ──
  // تليجرام بيبعت الهيدر ده في كل نداء. مين ملوش هو، مش تليجرام.
  if (req.headers.get("x-telegram-bot-api-secret-token") !== SECRET) {
    return new Response("forbidden", { status: 403 });
  }

  let update: any;
  try {
    update = await req.json();
  } catch {
    return new Response("bad json", { status: 400 });
  }

  const cq = update?.callback_query;
  if (!cq) {
    // تحديث مش ضغطة زرار (رسالة عادية مثلاً). بنرد 200 عشان تليجرام
    // مايفضلش يعيد المحاولة على حاجة إحنا أصلاً مش مهتمين بيها.
    return new Response("ok");
  }

  // ── الطبقة ٢: القفل على المحادثة ──
  const chatId = String(cq.message?.chat?.id ?? "");
  if (chatId !== ALLOWED_CHAT) {
    await tg("answerCallbackQuery", {
      callback_query_id: cq.id,
      text: "غير مصرّح",
      show_alert: true,
    });
    return new Response("ok");
  }

  // ── الطبقة ٣: شكل البيانات ──
  // الشكل المتوقع: "a:123" — حرف واحد ونقطتين ورقم.
  const m = /^([asl]):(\d{1,12})$/.exec(String(cq.data ?? ""));
  if (!m) {
    await tg("answerCallbackQuery", { callback_query_id: cq.id, text: "?" });
    return new Response("ok");
  }

  const action = ACTIONS[m[1]];
  const jobId = Number(m[2]);

  // ── الكتابة ──
  // upsert على job_id: الضغط مرتين بيحدّث القرار مش بيضيف صف.
  const { error } = await db
    .from("applications")
    .upsert(
      { job_id: jobId, status: action.status, decided_at: new Date().toISOString() },
      { onConflict: "job_id" },
    );

  if (error) {
    await tg("answerCallbackQuery", {
      callback_query_id: cq.id,
      text: "مقدرتش أسجّل — جرّب تاني",
      show_alert: true,
    });
    return new Response("ok");
  }

  // الرد الفوري: ده اللي بيخلي الزرار يحس إنه اشتغل
  await tg("answerCallbackQuery", { callback_query_id: cq.id, text: action.toast });

  // وبنشيل الأزرار ونحط القرار مكانها — عشان تعرف إنت عملت إيه
  // لما ترجع للرسالة بعد أسبوع.
  await tg("editMessageReplyMarkup", {
    chat_id: chatId,
    message_id: cq.message.message_id,
    reply_markup: { inline_keyboard: [[{ text: action.label, callback_data: "x" }]] },
  });

  return new Response("ok");
});
