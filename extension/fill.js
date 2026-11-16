// ملء فورم التقديم من الإجابات اللي السيستم جهّزها: Ashby و Greenhouse و Lever.
// بيشتغل جوّه كروم بتاعك، والإرسال دايمًا ضغطتك إنت: مفيش هنا أي ضغط
// على Submit.
//
// الحقل بيتلاقي حسب الموقع (pack.site):
//   · ashby       الـcontainer: [data-field-path="<path>"]
//   · greenhouse  الـid نفسه اسم الحقل في الـAPI (first_name، question_123…)
//   · lever       الـname (name، urls[LinkedIn]، cards[<uuid>][field0]…)
// والملء نفسه واحد:
//   · نص: الـsetter الأصلي + input/change، عشان React يحس بالتغيير
//   · Yes/No: button[data-option] (Ashby) أو checkbox
//   · اختيار: <select> عادي، أو radio/checkbox، أو label بنفس النص، أو combobox
//   · الموقع: نكتب المدينة ونختار اللي فيه Egypt (Lever بيكتبها "EGY")
//   · ملف: DataTransfer بالملف نفسه
(function (root) {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const norm = (s) => (s || "").replace(/\s+/g, " ").trim().toLowerCase();
  const EGYPT = /egypt|\begy\b/i;

  function q(s) {
    return '"' + String(s).replace(/\\/g, "\\\\").replace(/"/g, '\\"') + '"';
  }

  function locate(doc, site, path) {
    if (site === "greenhouse") {
      const el = doc.getElementById(path) ||
        doc.querySelector("[name=" + q(path) + "], [name=" + q(path + "[]") + "]");
      if (!el) return null;
      const box = el.closest("fieldset, .field-wrapper, .select, .file-upload, .text-input-wrapper") ||
        el.parentElement;
      return { el: el, box: box };
    }
    if (site === "lever") {
      const el = doc.querySelector("[name=" + q(path) + "]");
      if (!el) return null;
      return { el: el, box: el.closest("li.application-question, .application-field") || el.parentElement };
    }
    const box = doc.querySelector("[data-field-path=" + q(path) + "]");
    return box ? { el: null, box: box } : null;
  }

  function setValue(el, v) {
    const proto = el.tagName === "TEXTAREA" ? HTMLTextAreaElement.prototype
      : el.tagName === "SELECT" ? HTMLSelectElement.prototype : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(proto, "value").set.call(el, v);
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
  }

  function press(el) {
    ["mousedown", "mouseup", "click"].forEach((t) =>
      el.dispatchEvent(new MouseEvent(t, { bubbles: true, cancelable: true, view: window })));
  }

  async function waitFor(fn, ms) {
    const end = Date.now() + (ms || 8000);
    while (Date.now() < end) {
      const r = fn();
      if (r) return r;
      await sleep(150);
    }
    return null;
  }

  function options(doc) {
    return Array.from(doc.querySelectorAll('[role="option"], .dropdown-location'))
      .filter((o) => o.offsetParent !== null || o.getClientRects().length);
  }

  function toFile(f) {
    const bin = atob(f.b64);
    const bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    return new File([bytes], f.name, { type: f.type || "application/pdf" });
  }

  function labelOf(inp) {
    if (inp.labels && inp.labels.length) return inp.labels[0].textContent;
    const l = inp.closest("label");
    return l ? l.textContent : "";
  }

  // قايمة combobox (React-Select في Greenhouse و Ashby): نكتب ونختار.
  // لو القايمة مابتتفتحش بالكتابة، نفتحها بالضغط على الـcontrol.
  async function pickFromCombo(doc, combo, v) {
    const want = norm(String(v));
    const match = () => options(doc).find((o) => norm(o.textContent) === want) ||
      options(doc).find((o) => norm(o.textContent).startsWith(want));
    combo.focus();
    setValue(combo, String(v).trim());
    let opt = await waitFor(match, 2000);
    if (!opt) {
      setValue(combo, "");
      const control = combo.closest('[class*="control"]') || combo.parentElement;
      press(control);
      opt = await waitFor(match, 3000);
    }
    if (!opt) throw new Error("الاختيار مش موجود: " + v);
    opt.click();
    await sleep(150);
  }

  async function fillOne(doc, site, f, value, files) {
    const loc = locate(doc, site, f.path);
    if (!loc) throw new Error("الخانة مش موجودة في الصفحة");
    const el = loc.el;
    const b = loc.box;
    const t = f.type;

    if (t === "File") {
      const inp = el && el.type === "file" ? el : b.querySelector('input[type="file"]');
      const file = files[f.path];
      if (!inp) throw new Error("مفيش خانة رفع");
      if (!file) throw new Error("الملف مش جاهز");
      const dt = new DataTransfer();
      dt.items.add(toFile(file));
      inp.files = dt.files;
      inp.dispatchEvent(new Event("input", { bubbles: true }));
      inp.dispatchEvent(new Event("change", { bubbles: true }));
      await sleep(1500);                       // الرفع بياخد ثواني
      return;
    }

    if (t === "Boolean") {
      const btn = b.querySelector('button[data-option="' + (value ? "yes" : "no") + '"]');
      if (btn) { btn.click(); return; }
      const box = el && el.type === "checkbox" ? el : b.querySelector('input[type="checkbox"]');
      if (!box) throw new Error("زرار Yes/No مش موجود");
      if (box.checked !== Boolean(value)) box.click();
      return;
    }

    if (t === "Location") {
      const inp = el && el.tagName === "INPUT" ? el
        : b.querySelector('input[role="combobox"]') || b.querySelector('input[type="text"], input:not([type])');
      if (!inp) throw new Error("خانة الموقع مش موجودة");
      const city = String(value).split(",")[0].trim();
      inp.focus();
      setValue(inp, city);
      // Lever بيدوّر بس على keydown+keyup فيهم keyCode (اتجرّب 17 نوفمبر)
      const k = { bubbles: true, key: city.slice(-1), keyCode: 79, which: 79 };
      inp.dispatchEvent(new KeyboardEvent("keydown", k));
      inp.dispatchEvent(new KeyboardEvent("keyup", k));
      const opt = await waitFor(() => options(doc).find((o) => EGYPT.test(o.textContent) &&
        norm(o.textContent).startsWith(norm(city))) || options(doc).find((o) => EGYPT.test(o.textContent)));
      if (!opt) throw new Error("مالقيتش اختيار فيه Egypt");
      if (opt.classList.contains("dropdown-location")) press(opt); else opt.click();
      return;
    }

    if (t === "ValueSelect" || t === "MultiValueSelect") {
      const values = Array.isArray(value) ? value : [value];
      for (const v of values) {
        const want = norm(String(v));
        const sel = el && el.tagName === "SELECT" ? el : b.querySelector("select");
        if (sel) {
          const o = Array.from(sel.options).find((x) => norm(x.textContent) === want || norm(x.value) === want);
          if (!o) throw new Error("الاختيار مش موجود: " + v);
          setValue(sel, o.value);
          continue;
        }
        const choice = Array.from(b.querySelectorAll('input[type="radio"], input[type="checkbox"]'))
          .find((i) => norm(i.value) === want || norm(labelOf(i)) === want);
        if (choice) {
          if (!choice.checked) choice.click();
          continue;
        }
        const label = Array.from(b.querySelectorAll("label")).find((l) => norm(l.textContent) === want);
        if (label) {
          label.click();
          continue;
        }
        const combo = el && el.getAttribute("role") === "combobox" ? el
          : b.querySelector('input[role="combobox"]');
        if (combo) {
          await pickFromCombo(doc, combo, v);
          continue;
        }
        const leaf = Array.from(b.querySelectorAll("button, span, div, li"))
          .find((e) => e.children.length === 0 && norm(e.textContent) === want);
        if (!leaf) throw new Error("الاختيار مش موجود: " + v);
        leaf.click();
      }
      return;
    }

    const inp = el && (el.tagName === "TEXTAREA" || el.tagName === "INPUT") ? el
      : b.querySelector('textarea, input:not([type="file"]):not([type="checkbox"]):not([type="radio"]):not([type="hidden"])');
    if (!inp) throw new Error("مفيش خانة كتابة");
    inp.focus();
    setValue(inp, String(value));
    inp.blur();
  }

  async function fillForm(doc, pack) {
    const site = pack.site || "ashby";
    const done = [];
    const problems = [];
    for (const f of pack.fields || []) {
      const v = (pack.answers || {})[f.path];
      const empty = v === undefined || v === null || v === "" || (Array.isArray(v) && !v.length);
      if (empty) {
        if (f.required) problems.push(f.title.slice(0, 60) + ": مفيش إجابة");
        continue;
      }
      // حقل اختياري مش ظاهر (Greenhouse بيظهر Race بس بعد سؤال تاني) — مش مشكلة
      if (!f.required && !locate(doc, site, f.path)) continue;
      try {
        await fillOne(doc, site, f, v, pack.files || {});
        done.push(f.path);
      } catch (e) {
        problems.push(f.title.slice(0, 60) + ": " + e.message);
      }
    }
    return { done: done, problems: problems };
  }

  root.ApplyAgentFill = { fillForm: fillForm };
})(typeof window !== "undefined" ? window : globalThis);
