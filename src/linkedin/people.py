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

def company_people(page, slug: str, want: int = 25) -> list[dict]:
    """
    اسحب ناس من تاب People بتاع شركة.

    بيمرّر لتحت شوية عشان الصفحة تحمّل، وبيسحب اللي ظهر. مش بيحاول
    يوصل لآخر القايمة — دي مش سرعة، دي هدوء.
    """
    page.goto(f"{BASE}/company/{slug}/people/",
              wait_until="domcontentloaded", timeout=30_000)
    human_pause(3, 6)
    guard(page)

    seen: dict[str, dict] = {}
    for _ in range(4):
        cards = page.query_selector_all(
            'a[href*="/in/"]:has(img), a[data-test-app-aware-link][href*="/in/"]')
        for a in cards:
            try:
                href = a.get_attribute("href") or ""
                key = profile_key(href)
                if not key or key in seen:
                    continue
                # النص حوالين اللينك فيه الاسم والمسمى
                block = a.evaluate(
                    "e => (e.closest('li') || e.closest('div'))?.innerText || ''")
                lines = [x.strip() for x in (block or "").split("\n") if x.strip()]
                if not lines:
                    continue
                seen[key] = {
                    "profile_key": key,
                    "profile_url": clean_url(href),
                    "name": lines[0][:120],
                    "headline": " ".join(lines[1:3])[:200],
                }
            except Exception:
                continue

        if len(seen) >= want:
            break
        page.mouse.wheel(0, 1400)
        human_pause(2, 4)
        guard(page)

    return list(seen.values())[:want]


# ── إرسال الدعوة ────────────────────────────────────────────────────────

def invite(page, contact: dict) -> tuple[bool, str]:
    """
    ابعت دعوة من صفحة الشخص. رجّع (نجح، السبب).

    من غير رسالة — ده اللي إنت طلبته، وكمان الدعوات بالرسايل عليها
    سقف أقل بكتير على الحسابات المجانية.
    """
    page.goto(contact["profile_url"], wait_until="domcontentloaded",
              timeout=30_000)
    human_pause(3, 7)
    guard(page)

    btn = None
    for sel in ('button[aria-label^="Invite"]',
                'main button:has-text("Connect")',
                'button:has-text("Connect")'):
        try:
            el = page.query_selector(sel)
            if el and el.is_visible():
                btn = el
                break
        except Exception:
            continue

    if not btn:
        # مفيش زرار Connect: يا إما متصلين أصلاً، يا إما الزرار جوّه More
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
