"""
جلسات مواقع التوظيف — إنت بتسجّل دخول بإيدك، والجلسة بتتحفظ.

  python -m src.sessions               افتح المتصفح بكل المواقع (تابات)
  python -m src.sessions bayt wuzzuf   مواقع معينة بس
  python -m src.sessions --check       مين فيهم عليه جلسة محفوظة

نفس ملف التعريف اللي التقديم بيشتغل منه (ashby.PROFILE)، فأي موقع
سجّلت فيه هنا، التقديم الأوتوماتيك بيلاقيه مفتوح.

الباسوورد والتحقق والموافقة على الشروط — كلها بإيدك في الشباك ده.
الكود بيفتح الصفحات بس، ومش بيقرا ولا بيطبع أي قيمة كوكي.
"""
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

from .ashby import PROFILE

# مفيش Google: بيرفض الدخول من متصفح متحكَّم فيه ("This browser or app may
# not be secure"، 17 نوفمبر) — وكمان "Continue with Google" على المواقع.
# التسجيل بالإيميل والباسوورد.
#
# الصفحة الرئيسية مش صفحة الدخول: لينكات الدخول بتتغير، وزرار
# "Sign in" دايمًا فوق.
SITES = {
    "bayt":       "https://www.bayt.com/en/",
    "gulftalent": "https://www.gulftalent.com/",
    "naukrigulf": "https://www.naukrigulf.com/",
    "wuzzuf":     "https://wuzzuf.net/",
    "himalayas":  "https://himalayas.app/",
    "wellfound":  "https://wellfound.com/",
    "indeed":     "https://www.indeed.com/",
}
DOMAINS = {
    "bayt": "bayt.com", "gulftalent": "gulftalent.com",
    "naukrigulf": "naukrigulf.com", "wuzzuf": "wuzzuf.net",
    "himalayas": "himalayas.app", "wellfound": "wellfound.com", "indeed": "indeed.com",
}


def open_sites(names: list[str]) -> None:
    """شباك ظاهر بالتابات. بيستنى لحد ما تقفله."""
    from playwright.sync_api import sync_playwright
    PROFILE.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            str(PROFILE), headless=False, viewport=None, locale="en-US",
            args=["--start-maximized"])
        first = ctx.pages[0] if ctx.pages else ctx.new_page()
        for i, n in enumerate(names):
            page = first if i == 0 else ctx.new_page()
            try:
                page.goto(SITES[n], wait_until="domcontentloaded", timeout=45000)
            except Exception as exc:
                print(f"   {n}: الصفحة مافتحتش ({type(exc).__name__}) — افتحها بإيدك")
        print("🟢 الشباك مفتوح. سجّل دخول في كل تاب، واقفل الشباك لما تخلص.")
        closed = []
        ctx.on("close", lambda: closed.append(1))
        while not closed and ctx.pages:
            try:
                ctx.pages[0].wait_for_timeout(2000)
            except Exception:              # التاب أو الشباك اتقفل — ده العادي
                if not ctx.pages:
                    break
        try:
            ctx.close()
        except Exception:
            pass
    check()


def _cookie_hosts() -> dict[str, int]:
    """عدد الكوكيز لكل دومين — الأسماء والقيم مابتتقريش."""
    db = PROFILE / "Default" / "Network" / "Cookies"
    if not db.exists():
        db = PROFILE / "Default" / "Cookies"
    if not db.exists():
        return {}
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        rows = con.execute("select host_key, count(*) from cookies group by host_key").fetchall()
    finally:
        con.close()
    return dict(rows)


def check() -> None:
    """
    تقدير بس: كوكيز كتير على الدومين = غالبًا فيه جلسة. التأكيد الحقيقي
    إنك تفتح الموقع وتلاقي نفسك داخل.
    """
    hosts = _cookie_hosts()
    print("\nالجلسات المحفوظة (تقدير من عدد الكوكيز):")
    for n, d in DOMAINS.items():
        c = sum(v for h, v in hosts.items() if h.lstrip(".").endswith(d))
        mark = "✅" if c >= 8 else ("·" if c else "—")
        print(f"   {mark} {n:<11} {c} كوكي")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("sites", nargs="*", help=" ".join(SITES))
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    if a.check:
        check()
        return 0
    bad = [s for s in a.sites if s not in SITES]
    if bad:
        print("مش معروف:", bad, "— المتاح:", " ".join(SITES))
        return 1
    open_sites(a.sites or list(SITES))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
