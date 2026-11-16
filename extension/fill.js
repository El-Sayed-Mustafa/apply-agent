// ملء فورم Ashby من الإجابات اللي السيستم جهّزها.
// بيشتغل جوّه كروم بتاعك، والإرسال دايمًا ضغطتك إنت: مفيش هنا أي ضغط
// على Submit.
//
// نفس منطق src/ashby.py (_fill_one)، بس بـJS في الصفحة نفسها:
//   · الخانات النصية: الـsetter الأصلي + input/change، عشان React يحس بالتغيير
//   · Yes/No: button[data-option=yes|no]
//   · الاختيارات: الـlabel بنفس النص، أو combobox
//   · الموقع: نكتب المدينة ونختار الاختيار اللي فيه Egypt
//   · السيرة: DataTransfer بالملف نفسه
(function (root) {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const norm = (s) => (s || "").replace(/\s+/g, " ").trim().toLowerCase();

  function box(doc, path) {
    return doc.querySelector('[data-field-path="' + CSS.escape(path) + '"]');
  }

  function setValue(el, v) {
    const proto = el.tagName === "TEXTAREA" ? HTMLTextAreaElement.prototype
                                            : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(proto, "value").set.call(el, v);
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
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

  function toFile(f) {
    const bin = atob(f.b64);
    const bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    return new File([bytes], f.name, { type: f.type || "application/pdf" });
  }

  function options(doc) {
    return Array.from(doc.querySelectorAll('[role="option"]'));
  }

  async function fillOne(doc, f, value, files) {
    const b = box(doc, f.path);
    if (!b) throw new Error("الخانة مش موجودة في الصفحة");
    const t = f.type;

    if (t === "File") {
      const inp = b.querySelector('input[type="file"]');
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
      if (!btn) throw new Error("زرار Yes/No مش موجود");
      btn.click();
      return;
    }

    if (t === "Location") {
      const inp = b.querySelector('input[role="combobox"]') || b.querySelector("input");
      if (!inp) throw new Error("خانة الموقع مش موجودة");
      inp.focus();
      setValue(inp, String(value).split(",")[0]);
      const opt = await waitFor(() => options(doc).find((o) => /egypt/i.test(o.textContent)));
      if (!opt) throw new Error("مالقيتش اختيار فيه Egypt");
      opt.click();
      return;
    }

    if (t === "ValueSelect" || t === "MultiValueSelect") {
      const values = Array.isArray(value) ? value : [value];
      for (const v of values) {
        const want = norm(String(v));
        const label = Array.from(b.querySelectorAll("label"))
          .find((l) => norm(l.textContent) === want);
        if (label) {
          label.click();
          const inp = label.control;
          if (inp && (inp.type === "radio" || inp.type === "checkbox") && !inp.checked) inp.click();
          continue;
        }
        const combo = b.querySelector('input[role="combobox"]');
        if (combo) {
          combo.focus();
          setValue(combo, String(v).trim());
          const opt = await waitFor(() => options(doc).find((o) => norm(o.textContent) === want));
          if (!opt) throw new Error("الاختيار مش موجود: " + v);
          opt.click();
          continue;
        }
        const leaf = Array.from(b.querySelectorAll("button, span, div, li"))
          .find((e) => e.children.length === 0 && norm(e.textContent) === want);
        if (!leaf) throw new Error("الاختيار مش موجود: " + v);
        leaf.click();
      }
      return;
    }

    const inp = b.querySelector(
      'textarea, input:not([type="file"]):not([type="checkbox"]):not([type="radio"]):not([type="hidden"])');
    if (!inp) throw new Error("مفيش خانة كتابة");
    inp.focus();
    setValue(inp, String(value));
    inp.blur();
  }

  async function fillForm(doc, pack) {
    const done = [];
    const problems = [];
    for (const f of pack.fields || []) {
      const v = (pack.answers || {})[f.path];
      const empty = v === undefined || v === null || v === "" || (Array.isArray(v) && !v.length);
      if (empty) {
        if (f.required) problems.push(f.title.slice(0, 60) + ": مفيش إجابة");
        continue;
      }
      try {
        await fillOne(doc, f, v, pack.files || {});
        done.push(f.path);
      } catch (e) {
        problems.push(f.title.slice(0, 60) + ": " + e.message);
      }
    }
    return { done: done, problems: problems };
  }

  root.ApplyAgentFill = { fillForm: fillForm };
})(typeof window !== "undefined" ? window : globalThis);
