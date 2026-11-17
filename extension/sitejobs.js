// قارئ كروت الوظايف على مواقع التوظيف — بيشتغل لوحده على صفحات النتايج.
// بيقرا بس: مفيش ضغط على أي حاجة، ومفيش تخطّي لأي تحقق. اللي بيقراه
// بيروح للمساعد المحلي (src/helper.py → src/sitejobs.py) يتفلتر ويتحفظ.
//
// لكل موقع شكل لينك الوظيفة (اتقاس 18 نوفمبر من صفحات حقيقية في كروم):
//   wuzzuf      /jobs/p/<id>-<slug>
//   bayt        /en/<country>/jobs/<slug>-<digits>/
//   gulftalent  /<country>/jobs/<slug>-<digits>
//   indeed      [data-jk] → /viewjob?jk=<jk>
//   naukrigulf  ...-jid-<digits>
//   wellfound   /jobs/<digits>-<slug>
// والكارت = أكبر عنصر حوالين اللينك مافيهوش لينك وظيفة تاني.
(function (root) {
  const SITES = {
    "wuzzuf.net": "wuzzuf", "bayt.com": "bayt", "gulftalent.com": "gulftalent",
    "indeed.com": "indeed", "naukrigulf.com": "naukrigulf", "wellfound.com": "wellfound",
  };
  const IS_JOB = {
    wuzzuf: (h) => /\/jobs\/p\//.test(h),
    bayt: (h) => /\/jobs\/[^/]+-\d{5,}\/?$/.test(h),
    gulftalent: (h) => /\/jobs\/[^/?#]+-\d{4,}$/.test(h),
    naukrigulf: (h) => /-jid-\d+/.test(h),       // "-jobs-in-dubai" لوحدها = تصنيف مش وظيفة
    wellfound: (h) => /\/jobs\/\d+-/.test(h),
  };

  function siteOf(host) {
    host = host.replace(/^www\./, "");
    const hit = Object.entries(SITES).find(([h]) => host === h || host.endsWith("." + h));
    return hit ? hit[1] : null;
  }

  function clean(u, origin) {
    try {
      const x = new URL(u, origin);
      return x.origin + x.pathname;
    } catch (e) { return u; }
  }

  function extract(doc, loc) {
    const name = siteOf(loc.hostname);
    if (!name) return null;
    const head = (doc.title + " " + ((doc.body && doc.body.innerText) || "").slice(0, 1500));
    const blocked = /verify you are human|are you a robot|just a moment|unusual traffic|press & hold/i.test(head);
    const out = [];
    const seen = new Set();

    if (name === "indeed") {
      doc.querySelectorAll("[data-jk]").forEach((el) => {
        const jk = el.getAttribute("data-jk");
        if (!jk || seen.has(jk)) return;
        seen.add(jk);
        let card = el;
        for (let i = 0; i < 8 && card.parentElement; i++) {
          if (card.matches("li, .job_seen_beacon, .result")) break;
          card = card.parentElement;
        }
        const t = card.querySelector("h2 span[title]") || card.querySelector("h2") || el;
        out.push({
          url: loc.origin + "/viewjob?jk=" + jk,
          title: (t.innerText || "").trim(),
          company: ((card.querySelector("[data-testid=company-name]") || {}).innerText || "").trim(),
          location: ((card.querySelector("[data-testid=text-location]") || {}).innerText || "").trim(),
          card: (card.innerText || "").slice(0, 800),
        });
      });
    } else {
      const isJob = IS_JOB[name];
      const links = Array.from(doc.querySelectorAll("a[href]"))
        .filter((a) => isJob(a.getAttribute("href") || "") && (a.innerText || "").trim().length > 3);
      for (const a of links) {
        const url = clean(a.getAttribute("href"), loc.origin);
        if (seen.has(url)) continue;
        seen.add(url);
        let card = a;
        for (let i = 0; i < 10 && card.parentElement; i++) {
          const p = card.parentElement;
          const other = Array.from(p.querySelectorAll("a[href]")).some((x) =>
            isJob(x.getAttribute("href") || "") && clean(x.getAttribute("href"), loc.origin) !== url);
          if (other) break;
          card = p;
        }
        let company = "";
        if (name === "wellfound") {
          // شركة واحدة فوق كذا وظيفة: الاسم في لينك /company/ في راس الكارت
          let up = a;
          for (let i = 0; i < 15 && up && !company; i++, up = up.parentElement) {
            // أول لينك /company/ هو اللوجو (صورة من غير نص) — خد أول واحد فيه اسم
            const c = up.querySelectorAll ? Array.from(up.querySelectorAll('a[href*="/company/"]'))
              .find((x) => (x.innerText || "").trim()) : null;
            if (c) company = c.innerText.trim().split("\n")[0].slice(0, 120);
          }
        }
        out.push({
          url: url,
          title: (a.innerText || "").trim().split("\n")[0].slice(0, 160),
          company: company, location: "",
          card: (card.innerText || "").slice(0, 800),
        });
      }
    }
    return { site: name, page: loc.origin + loc.pathname, blocked: blocked && !out.length,
             jobs: out.slice(0, 60) };
  }

  root.ApplyAgentSiteJobs = { extract: extract, siteOf: siteOf };
})(typeof window !== "undefined" ? window : globalThis);
