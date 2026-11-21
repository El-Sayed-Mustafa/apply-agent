// الوسيط بين الصفحة والمساعد المحلي (python -m src.helper).
// الطلب للمساعد من هنا مش من الصفحة: صفحة Ashby نفسها مش بتشوف
// التوكن ولا بتكلّم 127.0.0.1.
try {
  importScripts("config.js");       // بيكتبه المساعد أول ما يشتغل (مش في git)
} catch (e) {
  self.APPLY_AGENT = null;
}

const DOWN = "المساعد مش شغّال — شغّل: python -m src.helper";

chrome.runtime.onMessage.addListener((msg, _sender, reply) => {
  const cfg = self.APPLY_AGENT;
  if (!cfg) {
    reply({ error: "شغّل python -m src.helper مرة، وبعدين اعمل Reload للإضافة" });
    return false;
  }
  const headers = { "X-Token": cfg.token };
  let req;
  if (msg.kind === "pack") {
    req = fetch(cfg.url + "/pack?url=" + encodeURIComponent(msg.url), { headers });
  } else if (msg.kind === "sitejobs") {
    // كروت وظايف من Wuzzuf / Bayt / GulfTalent / Indeed / Naukrigulf / Wellfound
    req = fetch(cfg.url + "/sitejobs", {
      method: "POST",
      headers: Object.assign({ "Content-Type": "application/json" }, headers),
      body: JSON.stringify(msg.payload),
    });
  } else if (msg.kind === "submitted") {
    req = fetch(cfg.url + "/submitted", {
      method: "POST",
      headers: Object.assign({ "Content-Type": "application/json" }, headers),
      body: JSON.stringify({ job_id: msg.job_id, url: msg.url }),
    });
  } else {
    reply({ error: "طلب مش معروف" });
    return false;
  }
  req.then(async (r) => {
    const body = await r.json().catch(() => ({}));
    reply(r.ok ? body : { error: body.error || "HTTP " + r.status });
  }).catch(() => reply({ error: DOWN }));
  return true;                      // الرد هييجي بعدين
});

// ── اللفة اليومية على مواقع التوظيف ───────────────────────────────────
// قبل كده التشغيلة اليومية كانت بتفتح الصفحات بأدوات Claude in Chrome،
// والأداة دي محتاجة موافقة — ومن غير حد قاعد اترفضت 3 أيام ورا بعض
// (18–20 نوفمبر) والتشغيلة كلها وقفت. دلوقتي الإضافة بتلف لوحدها مرة
// في اليوم: شباك صغير متصغّر، صفحة كل نص دقيقة، وتقفله. بتقرا بس —
// sitejobs-content.js هو اللي بيبعت الكروت، زي ما بيحصل لو فتحتها بإيدك.
const SWEEP_AT = [9, 30];           // 9:30 بتوقيت الجهاز، قبل تشغيلة 10:09
const STEP_MIN = 0.5;
// مفتاح لكل نسخة: أي Reload بنسخة جديدة بيلف على طول (ده اختبار التحديث)
const LAST = "lastSweep@" + chrome.runtime.getManifest().version;

function today() {
  return new Date().toLocaleDateString("en-CA");
}

function scheduleSweep() {
  const t = new Date();
  t.setHours(SWEEP_AT[0], SWEEP_AT[1], 0, 0);
  if (t.getTime() <= Date.now()) t.setDate(t.getDate() + 1);
  chrome.alarms.create("sweep", { when: t.getTime(), periodInMinutes: 24 * 60 });
  // كروم كان مقفول وقت اللفة، أو نسخة جديدة؟ نلحقها بعد دقيقتين
  chrome.alarms.create("sweep-catchup", { delayInMinutes: 2 });
}

chrome.runtime.onInstalled.addListener(scheduleSweep);
chrome.runtime.onStartup.addListener(scheduleSweep);

async function startSweep(force) {
  const st = await chrome.storage.local.get([LAST, "sweep"]);
  if (st.sweep && Date.now() - st.sweep.at < 30 * 60e3) return;   // لفة شغالة (أو واقعة من نص ساعة)
  if (!force && st[LAST] === today()) return;        // مرة في اليوم
  const cfg = self.APPLY_AGENT;
  if (!cfg) return;
  let urls;
  try {
    const r = await fetch(cfg.url + "/sitejobs/urls", { headers: { "X-Token": cfg.token } });
    urls = (await r.json()).urls || [];
  } catch (e) {
    return;                                              // المساعد واقف — نحاول المرة الجاية
  }
  if (!urls.length) return;
  // شباك عادي صغير في الركن، مش متصغّر: GulfTalent ماكانش بيعرض النتايج
  // في شباك متصغّر (اللفة الأولى 21 نوفمبر قرت 10 صفحات من 11 من غيره)
  const win = await chrome.windows.create({ url: urls[0], focused: false, state: "normal",
                                           left: 0, top: 0, width: 640, height: 520 });
  await chrome.storage.local.set({
    [LAST]: today(),
    sweep: { urls, i: 0, windowId: win.id, tabId: win.tabs[0].id, at: Date.now() },
  });
  chrome.alarms.create("sweep-step", { delayInMinutes: STEP_MIN });
}

async function stepSweep() {
  const { sweep } = await chrome.storage.local.get("sweep");
  if (!sweep) return;
  sweep.i += 1;
  try {
    if (sweep.i >= sweep.urls.length) throw new Error("done");
    await chrome.tabs.update(sweep.tabId, { url: sweep.urls[sweep.i] });
    await chrome.storage.local.set({ sweep });
    chrome.alarms.create("sweep-step", { delayInMinutes: STEP_MIN });
  } catch (e) {
    // خلصت، أو الشباك اتقفل بإيدك — في الحالتين نخلّص
    await chrome.storage.local.remove("sweep");
    chrome.windows.remove(sweep.windowId).catch(() => {});
  }
}

chrome.alarms.onAlarm.addListener((a) => {
  if (a.name === "sweep") startSweep(false);
  else if (a.name === "sweep-catchup") {
    // النسخة دي لسه ملفّتش ولا مرة؟ تلف على طول — ده اختبار الـReload
    const now = new Date();
    chrome.storage.local.get(LAST).then((got) => {
      if (!got[LAST] || now.getHours() * 60 + now.getMinutes() >= SWEEP_AT[0] * 60 + SWEEP_AT[1]) {
        startSweep(false);
      }
    });
  } else if (a.name === "sweep-step") stepSweep();
});
