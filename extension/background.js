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
