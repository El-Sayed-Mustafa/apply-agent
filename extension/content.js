// زرار "📋 املا من Apply Agent" على صفحات Ashby و Greenhouse و Lever.
// بيملا ويسيبك تراجع — الإرسال ضغطتك. لما الصفحة تقول إن الطلب وصل،
// بيبلّغ المساعد عشان يتسجّل إنه اتبعت.
(function () {
  const SUCCESS = /thank you|thanks for applying|application (was |has been )?(submitted|received)|successfully submitted|we.ve received your application|we have received your application/i;
  // فيه فورم في الصفحة دي؟ Ashby · Greenhouse · Lever
  const FORM = "[data-field-path], input#first_name, #application-form, li.application-question";
  let filledJob = null;
  let reported = false;

  function ask(msg) {
    return new Promise((resolve) => {
      try {
        chrome.runtime.sendMessage(msg, (r) => resolve(r || { error: "مفيش رد من الإضافة" }));
      } catch (e) {
        resolve({ error: "الإضافة اتحدّثت — اعمل refresh للصفحة" });
      }
    });
  }

  function panel() {
    let p = document.getElementById("apply-agent-panel");
    if (p) return p;
    p = document.createElement("div");
    p.id = "apply-agent-panel";
    p.dir = "rtl";
    p.style.cssText = "position:fixed;left:16px;bottom:16px;z-index:2147483647;" +
      "font:14px system-ui,sans-serif;background:#fff;color:#111;border:1px solid #ccc;" +
      "border-radius:10px;box-shadow:0 4px 16px rgba(0,0,0,.18);padding:10px 12px;max-width:360px";
    const btn = document.createElement("button");
    btn.id = "apply-agent-fill";
    btn.textContent = "📋 املا من Apply Agent";
    btn.style.cssText = "font:600 14px system-ui,sans-serif;padding:8px 12px;border-radius:8px;" +
      "border:0;background:#2b5a4a;color:#fff;cursor:pointer";
    btn.addEventListener("click", run);
    const out = document.createElement("div");
    out.id = "apply-agent-out";
    out.style.cssText = "margin-top:8px;white-space:pre-wrap;line-height:1.5";
    p.append(btn, out);
    document.body.appendChild(p);
    return p;
  }

  function say(text) {
    panel();
    document.getElementById("apply-agent-out").textContent = text;
  }

  async function run() {
    if (!document.querySelector(FORM)) {
      say("افتح صفحة التقديم الأول (Application / Apply)، وبعدين دوس تاني.");
      return;
    }
    say("بجيب الإجابات…");
    const pack = await ask({ kind: "pack", url: location.href });
    if (pack.error) {
      say("⚠️ " + pack.error);
      return;
    }
    say("بملا الفورم…");
    const r = await window.ApplyAgentFill.fillForm(document, pack);
    filledJob = pack.job;
    reported = false;
    let text = "✅ اتملى " + r.done.length + " خانة — " + pack.job.title +
      "\nراجع كل حاجة، ودوس Submit بنفسك.";
    if (r.problems.length) text += "\n\n⚠️ املا دول بإيدك:\n• " + r.problems.join("\n• ");
    say(text);
  }

  // بعد الملء بس: لما الصفحة تأكد الإرسال، بلّغ المساعد مرة واحدة
  setInterval(async () => {
    if (!filledJob || reported) return;
    if (!SUCCESS.test(document.body.innerText || "")) return;
    reported = true;
    const r = await ask({ kind: "submitted", job_id: filledJob.id, url: location.href });
    say(r.error ? "اتبعت، بس التسجيل وقع: " + r.error : "🎉 اتبعت، واتسجّل عندنا.");
  }, 1500);

  panel();
})();
