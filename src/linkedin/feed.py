"""
تجميع منشورات من الـ feed.

بنجمع بس. الكتابة والنشر في ملفات تانية — الفصل مقصود: التجميع
قراءة، والنشر فعل عام دايم.
"""
from __future__ import annotations

import hashlib
import re

from .session import BASE, guard, human_pause

# منشور ترحيب بوظيفة جديدة — دي أسهل كومنت وأصدقه
CELEBRATION = re.compile(
    r"\b(excited to (?:share|announce)|thrilled to|happy to (?:share|announce)|"
    r"i'?m joining|new (?:role|chapter|journey|beginning)|starting (?:a )?new|"
    r"joined|has started a new position|new position)\b|"
    r"يسعدني أن أعلن|سعيد بالإعلان|انضممت|بداية جديدة|وظيفة جديدة", re.I)

# منشور تقني — فيه حاجة نقدر نعلّق عليها بمعنى
TECHNICAL = re.compile(
    r"\b(ai|ml|llm|rag|agent|model|pipeline|latency|throughput|benchmark|"
    r"embedding|inference|fine[- ]tun|prompt|dataset|api|architecture|"
    r"postgres|python|kubernetes|deploy)\b", re.I)

# منشورات مش هنعلّق عليها — التوظيف والإعلانات والمواساة
AVOID = re.compile(
    r"\b(we'?re hiring|now hiring|apply now|dm me|link in (?:bio|comments)|"
    r"giveaway|webinar|rest in peace|passed away|condolence|"
    r"laid off|layoff)\b|نعزّي|رحمه الله|وفاة", re.I)

# 9 مش 12: العربي أكثف من الإنجليزي. "يسعدني أن أعلن انضمامي إلى فريق
# الذكاء الاصطناعي في الشركة الجديدة" منشور كامل في 11 كلمة، والحد
# الأعلى كان بيرفضه.
MIN_WORDS = 9
MAX_CHARS = 1200

# تلات كومنتات على تلات منشورات لنفس الشخص في يوم واحد شكلها آلي
# صريح — حتى لو كل كومنت لوحده كويس.
MAX_PER_AUTHOR = 1

# إعادة النشر: التعليق على منشور حد نشره تاني بيروح لصاحب المنشور
# الأصلي — مش للشخص اللي احنا مهتمين بيه.
REPOST = re.compile(r"reposted this|أعاد نشر|شارك هذا", re.I)

# لينكدإن غيّر صفحة النشاط (أكتوبر 2026): `data-urn` اختفى خالص،
# والمنشور بقى `role=listitem` بـ componentkey بيبدأ بـ update-card.
# قِسناها: صفحة فيها 10 منشورات ظاهرة، و`data-urn` = 0 — يعني القارئ
# القديم كان بيرجّع صفر كل يوم من 6 أكتوبر ومحدش بيعرف.
#
# الـ urn بتاع المنشور نفسه مش موجود في الشكل الجديد. اللي موجود هو
# لينك `/feed/update/urn:...` جوّا بعض المنشورات — وساعات ده لينك
# المنشور اللي اتشارك جوّاه مش المنشور نفسه. فبناخد المنشور بس لما
# يكون فيه لينك واحد وكاتب واحد. أي حاجة تانية ممكن الكومنت يروح
# لشخص غير اللي فاكرينه — والكومنت عام ودايم.
JS_POSTS = r"""() => {
  const out = [];
  const seen = new Set();
  const AGE = /^(\d+)\s*(s|m|h|d|w|mo|yr)\b/;
  const UNIT = {s: 0, m: 0, h: 0, d: 1, w: 7, mo: 30, yr: 365};
  const ageOf = (text) => {
    for (const line of text.split('\n').slice(0, 12)) {
      const m = line.trim().match(AGE);
      if (m) return Number(m[1]) * UNIT[m[2]];
    }
    return null;
  };
  const push = (p, urn) => {
    if (!urn || seen.has(urn)) return;
    const text = (p.innerText || '').trim();
    if (!text || text.length < 60 || text.length > 3000) return;
    seen.add(urn);
    const a = p.querySelector('a[href*="/in/"]');
    out.push({
      urn: urn,
      author: a ? (a.innerText || '').trim().split('\n')[0].slice(0, 80) : '',
      author_url: a ? (a.getAttribute('href') || '').split('?')[0] : '',
      age_days: ageOf(text),
      text: text.slice(0, 1600)
    });
  };
  document.querySelectorAll('[data-urn], [data-id]').forEach(p => {
    const urn = p.getAttribute('data-urn') || p.getAttribute('data-id') || '';
    if (/^urn:li:(activity|ugcPost|share)/.test(urn)) push(p, urn);
  });
  document.querySelectorAll('[role="listitem"][componentkey^="update-card"]').forEach(p => {
    const urns = new Set();
    p.querySelectorAll('a[href*="/feed/update/urn:li:"]').forEach(a => {
      const m = (a.getAttribute('href') || '').match(/urn:li:(activity|ugcPost|share):\d+/);
      if (m) urns.add(m[0]);
    });
    const actors = new Set();
    p.querySelectorAll('a[href*="/in/"]').forEach(a => {
      const h = (a.getAttribute('href') || '').split('?')[0];
      if (!/recent-activity/.test(h)) actors.add(h.replace(/\/+$/, '').split('/in/')[1]);
    });
    if (urns.size === 1 && actors.size === 1) push(p, [...urns][0]);
  });
  return out.slice(0, 40);
}"""

# كام منشور ظاهر في الصفحة أصلًا، بأي شكل. لو ده فوق الصفر والمقبول
# صفر، يبقى القارئ مش فاهم الصفحة — ودي لازم تتقال مش تتبلع.
JS_VISIBLE = r"""() => document.querySelectorAll(
  '[role="listitem"][componentkey^="update-card"], [data-urn^="urn:li:activity"]').length"""

# منشور أقدم من كده مش هنعلّق عليه: كومنت على منشور عمره سنة شكله آلي.
MAX_AGE_DAYS = 7


def post_key(urn: str, text: str) -> str:
    """
    معرّف ثابت للمنشور.

    الـ urn هو الأفضل لما يكون موجود. لما مايكونش، بنبصم على أول
    النص — نفس المنشور بيظهر في الـ feed كذا مرة بترتيب مختلف.
    """
    raw = (urn or "").strip() or re.sub(r"\s+", " ", text)[:200].lower()
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


def clean_text(raw: str) -> str:
    """
    شيل سطور الواجهة من نص المنشور.

    الـ innerText بيلم اسم الكاتب وعدد الإعجابات وأزرار التفاعل مع
    المحتوى. لو سبناهم، الموديل بيعلّق على "Like · Repost".
    """
    drop = re.compile(
        r"^(like|comment|repost|send|follow|·|\d+[\dkKmM,\.]*\s*(likes?|comments?|"
        r"reposts?)?|see more|…\s*more|\d+[hdwmy]|edited|promoted|"
        r"feed post number \d+|premium|\d+(?:st|nd|rd)|open to work)$", re.I)
    lines = [x.strip() for x in (raw or "").split("\n")]
    keep = [x for x in lines if x and not drop.match(x) and len(x) > 2]
    return re.sub(r"\s+", " ", " ".join(keep))[:MAX_CHARS]


def is_arabic(text: str) -> bool:
    ar = len(re.findall(r"[؀-ۿ]", text or ""))
    return ar > max(len(text or "") * 0.15, 8)


def classify(text: str) -> str | None:
    """celebration · technical · None لو مش مناسب"""
    if AVOID.search(text) or REPOST.search(text):
        return None
    if len(text.split()) < MIN_WORDS:
        return None
    if CELEBRATION.search(text):
        return "celebration"
    if TECHNICAL.search(text):
        return "technical"
    return None


def collect(page, want: int = 25, people: list[str] | None = None) -> list[dict]:
    """
    اجمع منشورات صالحة للتعليق.

    الـ feed نفسه بيرجّع عناصر فاضية في المتصفح المؤتمت — قِسناها:
    كل `main li` طلعت len=0 بعد تحميل كامل وثلاث تمريرات. صفحات نشاط
    الأشخاص بترندر عادي (10 منشورات لكل صفحة في القياس).

    وده مصدر أحسن أصلًا: التعليق على منشور لواحد لسه ضايفينه أقرب
    لسلوك بشري من التعليق على منشور عشوائي عدّى في الـ feed.
    """
    # بنقبل رابط لوحده أو {"url","name"}. الاسم مفيد لإن صفحة النشاط
    # مابتحطش لينك للبروفايل جوّه كارت صاحب الصفحة نفسه — فبيطلع فاضي.
    srcs = [(x, "") if isinstance(x, str) else (x.get("url", ""), x.get("name", ""))
            for x in (people or [])]
    srcs = [(u.rstrip("/") + "/recent-activity/all/", n) for u, n in srcs if u]
    if not srcs:
        srcs = [(f"{BASE}/feed/", "")]

    found: dict[str, dict] = {}
    for url, owner in srcs:
        if len(found) >= want:
            break
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        except Exception:
            continue
        human_pause(5, 9)
        guard(page)

        for _ in range(2):
            try:
                posts = page.evaluate(JS_POSTS)
                visible = page.evaluate(JS_VISIBLE)
            except Exception as e:
                # الابتلاع الصامت هنا كان بيدّي "0 منشور" على غلط
                # صياغة في الـJS. أي فشل هنا لازم يتقال.
                print(f"   ⚠ تعذّرت قراءة الصفحة: {e}")
                posts, visible = [], 0
            if visible and not posts:
                print(f"   · {owner or url}: {visible} منشور ظاهر، "
                      f"ولا واحد ينفع (من غير لينك واضح أو مشاركة لحد تاني)")

            taken = 0
            for p in posts:
                if taken >= MAX_PER_AUTHOR:
                    break
                age = p.get("age_days")
                if age is not None and age > MAX_AGE_DAYS:
                    continue
                text = clean_text(p["text"])
                kind = classify(text)
                if not kind:
                    continue
                key = post_key(p["urn"], text)
                if key in found:
                    continue
                found[key] = {
                    "post_key": key,
                    "post_url": (f"{BASE}/feed/update/{p['urn']}/" if p["urn"]
                                 else url),
                    "author": p["author"] or owner,
                    "author_url": p["author_url"],
                    "text": text,
                    "kind": kind,
                    "lang": "ar" if is_arabic(text) else "en",
                }
                taken += 1

            if taken >= MAX_PER_AUTHOR or len(found) >= want:
                break
            page.mouse.wheel(0, 1600)
            human_pause(3, 6)
            guard(page)

    return list(found.values())[:want]


# ── النشر ───────────────────────────────────────────────────────────────

def publish(page, post_url: str, body: str) -> tuple[bool, str]:
    """
    انشر كومنت على منشور. رجّع (نجح، السبب).

    بنفتح المنشور لوحده مش من الـ feed: صفحة المنشور فيها صندوق
    تعليق واحد، والـ feed فيه صندوق لكل منشور — ونفس فخ الدعوات
    (الضغط على عنصر بتاع حاجة تانية) بيتكرر هنا بالظبط.
    """
    page.goto(post_url, wait_until="domcontentloaded", timeout=30_000)
    human_pause(4, 8)
    guard(page)

    box = None
    for sel in ('div.ql-editor[contenteditable="true"]',
                'div[data-placeholder][contenteditable="true"]',
                '[role="textbox"][contenteditable="true"]'):
        try:
            el = page.query_selector(sel)
            if el and el.is_visible():
                box = el
                break
        except Exception:
            continue

    if not box:
        # الصندوق أحيانًا بيظهر بعد الضغط على "Comment"
        for sel in ('button[aria-label^="Comment"]', 'button:has-text("Comment")'):
            try:
                b = page.query_selector(sel)
                if b and b.is_visible():
                    b.click()
                    human_pause(2, 3.5)
                    break
            except Exception:
                continue
        box = page.query_selector('div.ql-editor[contenteditable="true"]')

    if not box:
        return False, "مفيش صندوق تعليق"

    box.click()
    human_pause(1, 2)
    # الكتابة حرف بحرف بإيقاع بشري — اللصق مرة واحدة شكله واضح
    page.keyboard.type(body, delay=55)
    human_pause(1.5, 3)
    guard(page)

    for sel in ('button.comments-comment-box__submit-button',
                'button[aria-label="Post comment"]',
                'button:has-text("Post"):not([disabled])'):
        try:
            el = page.query_selector(sel)
            if el and el.is_visible() and el.is_enabled():
                el.click()
                human_pause(3, 6)
                guard(page)
                return True, ""
        except Exception:
            continue

    return False, "مفيش زرار نشر مفعّل"
