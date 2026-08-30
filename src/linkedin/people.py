"""
إيجاد ناس، وفلترتهم، وإرسال الدعوات.

مصدر المرشحين هو **تاب People بتاع الشركة** مش البحث. السبب عملي:
البحث في الملفات الشخصية عليه سقف تجاري شهري وبيخلص بسرعة، وصفحات
الشركات مش عليها السقف ده. وكمان الناس اللي في الشركة اللي بتتقدم
فيها أقرب لك من نتيجة بحث عامة.

الفلترة بقواعد نصية مش بـ LLM: الأسماء والمسميات قصيرة، والقواعد
بتشتغل في جزء من الثانية بصفر تكلفة. مفيش حاجة هنا الـ LLM هيعملها
أحسن.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

from .session import BASE, Blocked, guard, human_pause

# ── مين يستاهل دعوة ─────────────────────────────────────────────────────

# ناس التوظيف — أعلى أولوية، دول اللي بيقروا التقديمات
#
# \w* في آخر الجذر مقصود: "recruit" لوحدها مش بتمسك "Recruiter" ولا
# "Recruiting" ولا "Recruitment" — والاختبار مسك ده.
RECRUITER = re.compile(
    r"\b(recruit\w*|talent\b|people\s+(?:op\w*|partner)|hr\b|hiring|"
    r"sourcer|staffing|acquisition)", re.I)

# ناس المجال — زمايل محتملين، وبيقدروا يرشّحوك من جوّه
PEER = re.compile(
    r"\b(ai|ml|machine\s+learning|llm|data|automation|backend|platform|"
    r"software|engineer|engineering|developer|architect|devops|mlops)\b", re.I)

# ناس القرار — بس بحرص: دول بيتبعتلهم دعوات كتير أصلاً
LEADER = re.compile(r"\b(cto|vp\s+(?:of\s+)?engineering|head\s+of\s+(?:ai|data|"
                    r"engineering)|director\s+of\s+engineering|founder)\b", re.I)

# مش مفيدين لهدفك
SKIP = re.compile(
    r"\b(sales|marketing|account\s+executive|business\s+development|"
    r"real\s+estate|insurance|photographer|designer|copywriter|"
    r"consultant\s+at\s+self|freelance\s+writer)\b", re.I)

PRIORITY = {"recruiter": 1, "leader": 2, "peer": 3}


def classify(headline: str) -> str | None:
    """رجّع نوع الشخص، أو None لو مش مفيد."""
    h = headline or ""
    if SKIP.search(h):
        return None
    if RECRUITER.search(h):
        return "recruiter"
    if LEADER.search(h):
        return "leader"
    if PEER.search(h):
        return "peer"
    return None


def profile_key(url: str) -> str | None:
    """
    الجزء المميز من الرابط، مطبّع.

    LinkedIn بيحط باراميترات تتبّع كتير في الروابط، ونفس الشخص بيطلع
    بروابط مختلفة. الجزء اللي بعد /in/ هو الثابت الوحيد.
    """
    if not url:
        return None
    path = urlparse(url).path or ""
    m = re.search(r"/in/([^/?#]+)", path)
    return m.group(1).strip("/").lower() if m else None


def clean_url(url: str) -> str:
    key = profile_key(url)
    return f"{BASE}/in/{key}/" if key else url


# ── السحب من صفحة الشركة ────────────────────────────────────────────────

# سطور بتظهر في كل كرت ومالهاش علاقة بالمسمى الوظيفي
NOISE = re.compile(
    r"^(?:·\s*)?\d+(?:st|nd|rd|th)(?:\s+degree(?:\s+connection)?)?$|"
    r"^view\b|^message$|^connect$|^follow$|^\W*$", re.I)

# كرت الشخص في تاب People. لو LinkedIn غيّر الكلاس، بنرجع لكل
# لينكات /in/ ونفلتر — أبطأ شوية بس مش بيقع.
JS_PEOPLE = """() => {
  const cards = document.querySelectorAll(
    '.org-people-profile-card__profile-card-spacing, li.grid');
  const nodes = cards.length ? cards : document.querySelectorAll('li, div');
  const out = [];
  const seen = new Set();
  nodes.forEach(card => {
    const a = card.querySelector('a[href*="/in/"]');
    if (!a) return;
    const href = (a.getAttribute('href') || '').split('?')[0];
    if (!href || seen.has(href)) return;
    const text = (card.innerText || '').trim();
    // كرت الشخص قصير. الحاويات الكبيرة بتلمّ كذا كرت مع بعض.
    if (!text || text.length > 400) return;
    seen.add(href);
    out.push({ href: href, lines: text.split('\\n') });
  });
  return out;
}"""


def parse_card(lines: list[str]) -> tuple[str, str]:
    """
    (الاسم، المسمى) من نص الكرت.

    شكل الكرت: الاسم، وبعده سطور زي "2nd degree connection" و"· 2nd"
    ملهاش علاقة، وبعدين المسمى. لو أخدنا أول سطرين زي ما كنت عامل،
    المسمى بيطلع "2nd degree connection" وكل التصنيف بيبوظ.
    """
    clean = [x.strip() for x in lines if x.strip() and not NOISE.match(x.strip())]
    if not clean:
        return "", ""
    name = clean[0]
    rest = [x for x in clean[1:] if x.lower() != name.lower()]
    if not rest:
        return name[:120], ""
    # سطر واحد بس. ضم سطرين كان بيلزق اسم الشخص اللي بعده في المسمى:
    #   "Software Engineer · Ahmed Abulkhair, Nora ..."
    # وده بيبوّظ التصنيف ويخلي الأسماء تتسرّب في بيانات غيرها.
    headline = rest[0]
    if len(headline) < 16 and len(rest) > 1:
        headline = f"{headline} · {rest[1]}"
    return name[:120], headline[:200]


def company_people(page, slug: str, want: int = 25,
                   keywords: str = "") -> list[dict]:
    """
    اسحب ناس من تاب People بتاع شركة.

    keywords بيستخدم مربع البحث الجوّاني للتاب. ده **مش** البحث العام
    اللي عليه السقف التجاري — ده فلترة داخل صفحة الشركة، ومفتوحة.

    وبيهم عمليًا: العرض الافتراضي بيطلّع مهندسين، وناس التوظيف —
    اللي هما أولوية أولى — مش بيظهروا غير لما تدوّر عليهم بالاسم.
    """
    url = f"{BASE}/company/{slug}/people/"
    if keywords:
        from urllib.parse import quote
        url += f"?keywords={quote(keywords)}"
    page.goto(url, wait_until="domcontentloaded", timeout=30_000)
    human_pause(5, 9)
    guard(page)

    seen: dict[str, dict] = {}
    for _ in range(5):
        try:
            cards = page.evaluate(JS_PEOPLE)
        except Exception:
            cards = []

        for c in cards:
            key = profile_key(c["href"])
            if not key or key in seen:
                continue
            name, headline = parse_card(c["lines"])
            if not name or "followers" in headline.lower():
                continue          # ده كرت شركة مش شخص
            seen[key] = {
                "profile_key": key,
                "profile_url": clean_url(c["href"]),
                "name": name,
                "headline": headline,
            }

        if len(seen) >= want:
            break
        page.mouse.wheel(0, 1600)
        human_pause(2.5, 4.5)
        guard(page)

    return list(seen.values())[:want]


# ── إرسال الدعوة ────────────────────────────────────────────────────────

def name_tokens(name: str) -> set[str]:
    """كلمات الاسم المميزة — للمقارنة، مش للعرض."""
    words = re.findall(r"[\w؀-ۿ]{3,}", (name or "").lower())
    return {w for w in words if w not in {"the", "dr", "eng", "mr", "ms", "mrs"}}


def belongs_to(aria: str, target_name: str) -> bool:
    """
    هل الزرار ده بتاع الشخص اللي إحنا رايحينله؟

    aria-label بيقول "Invite <الاسم> to connect". لو الاسم مختلف،
    يبقى الزرار من قايمة جانبية مش من الملف المفتوح.

    ده الحاجز اللي كان ناقص. من غيره، أول زرار دعوة في الصفحة كان
    بيتضغط — وده بيبقى غالبًا في "أشخاص قد تعرفهم"، فالدعوة بتروح
    لشخص محدش اختاره.
    """
    a, t = name_tokens(aria), name_tokens(target_name)
    if not t:
        return False
    return bool(a & t)


def invite(page, contact: dict) -> tuple[bool, str]:
    """
    ابعت دعوة من صفحة الشخص. رجّع (نجح، السبب).

    من غير رسالة — ده اللي إنت طلبته، وكمان الدعوات بالرسايل عليها
    سقف أقل بكتير على الحسابات المجانية.

    الاسم بيتفحص قبل الضغط. لو الزرار مش بتاع الشخص المقصود، بنسيبه
    ونعدّي — أحسن ما ندعو حد محدش اختاره.
    """
    page.goto(contact["profile_url"], wait_until="domcontentloaded",
              timeout=30_000)
    human_pause(3, 7)
    guard(page)

    target = contact.get("name") or ""
    btn = None
    wrong = ""

    # بندوّر جوّه الملف الرئيسي بس. القايمة الجانبية ("أشخاص قد
    # تعرفهم") فيها أزرار دعوة كمان، وهي أول حاجة بتتلقط لو دوّرنا
    # في الصفحة كلها.
    for scope in ("main section:first-of-type", "main .ph5", "main"):
        for el in page.query_selector_all(f'{scope} button[aria-label*="onnect"], '
                                          f'{scope} button[aria-label^="Invite"]'):
            try:
                if not el.is_visible():
                    continue
                aria = el.get_attribute("aria-label") or ""
                if belongs_to(aria, target):
                    btn = el
                    break
                wrong = aria[:60]
            except Exception:
                continue
        if btn:
            break

    if not btn:
        if wrong:
            # الحاجز اشتغل: لقينا زرار بس لشخص تاني
            return False, f"الزرار لشخص تاني: {wrong}"
        return False, "مفيش زرار Connect"

    btn.click()
    human_pause(1.5, 3.5)
    guard(page)

    # نافذة التأكيد
    for sel in ('button[aria-label="Send without a note"]',
                'button:has-text("Send without a note")',
                'button[aria-label="Send now"]',
                'button:has-text("Send")'):
        try:
            el = page.query_selector(sel)
            if el and el.is_visible():
                el.click()
                human_pause(2, 4)
                guard(page)
                return True, ""
        except Exception:
            continue

    # الزرار اتضغط بس النافذة مش زي المتوقع — نقفل ونسيبها
    try:
        page.keyboard.press("Escape")
    except Exception:
        pass
    return False, "نافذة التأكيد مش زي المتوقع"
