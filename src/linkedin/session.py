"""
جلسة LinkedIn.

المتصفح بيفتح بملف تعريف دايم على جهازك. إنت بتسجّل بإيدك مرة واحدة،
والجلسة بتفضل. **مفيش أي مكان في الكود بيلمس اسم المستخدم أو كلمة
السر** — ولا بيتخزنوا في أي ملف.

وأهم حاجة هنا مش السحب — هي **الوقف**. أي علامة إن LinkedIn لاحظ حاجة
معناها نقف حالًا ونسيب الحساب في حاله. الحساب أغلى من أي دعوة.
"""
from __future__ import annotations

import os
import random
import time
from contextlib import contextmanager
from pathlib import Path

PROFILE_DIR = Path(os.getenv(
    "LINKEDIN_PROFILE_DIR",
    Path.home() / ".apply-agent" / "linkedin-profile"))

BASE = "https://www.linkedin.com"
NAV_TIMEOUT = 30_000

# أي حاجة من دول في الصفحة = وقف فوري.
# مش بنحاول نتصرف ولا نعدّي — بنقفل ونسيب الحساب.
#
# ⚠️ بالعربي كمان: واجهة الحساب دي عربي، والحاجز اللي بيدوّر على
# إنجليزي بس مش هيشوف التحذير أصلاً — يعني هيفضل شغال وهو المفروض
# واقف. ده أخطر نوع من الأعطال: حماية موجودة على الورق وغايبة فعليًا.
TROUBLE = [
    "/checkpoint/",
    "/authwall",
    # إنجليزي
    "unusual activity",
    "we've restricted",
    "we have restricted",
    "temporarily restricted",
    "verify it's you",
    "security verification",
    "you've reached the weekly invitation limit",
    "let's do a quick security check",
    "try again later",
    # عربي
    "نشاط غير معتاد",
    "قيّدنا",
    "تم تقييد",
    "مقيّد مؤقت",
    "تحقق من هويتك",
    "التحقق الأمني",
    "وصلت إلى الحد الأسبوعي",
    "حد الدعوات",
    "حاول مرة أخرى لاحقًا",
    "حاول مرة أخرى لاحقا",
]


class Blocked(Exception):
    """LinkedIn اعترض. مش بنكمّل ولا بنعيد المحاولة."""


def human_pause(lo: float = 2.5, hi: float = 7.0) -> None:
    """
    تباعد عشوائي.

    الإيقاع المنتظم هو أول حاجة بتفرّق الآلة عن الإنسان — 20 فعل
    كل 3.0 ثانية بالظبط شكله واضح، و20 فعل بتباعد 2 لـ 7 ثواني لأ.
    """
    time.sleep(random.uniform(lo, hi))


def long_pause() -> None:
    """وقفة أطول بين المجموعات — زي ما الواحد بيسيب الشاشة شوية."""
    time.sleep(random.uniform(45, 110))


def guard(page) -> None:
    """
    افحص الصفحة الحالية. لو فيه أي علامة اعتراض، ارمي Blocked.

    بيتنادى بعد كل تنقّل وقبل كل فعل. الفحص رخيص، والغلطة غالية.
    """
    url = (page.url or "").lower()
    for mark in TROUBLE:
        if mark.startswith("/"):
            if mark in url:
                raise Blocked(f"الرابط بيقول: {mark}")
    try:
        body = (page.inner_text("body", timeout=4000) or "").lower()
    except Exception:
        return
    for mark in TROUBLE:
        if not mark.startswith("/") and mark in body:
            raise Blocked(f"الصفحة بتقول: {mark}")


def logged_in(page) -> bool:
    page.goto(f"{BASE}/feed/", wait_until="domcontentloaded",
              timeout=NAV_TIMEOUT)
    human_pause(1.5, 3)
    return "/feed" in page.url and "/login" not in page.url


@contextmanager
def browser(headless: bool = False):
    """
    متصفح بملف تعريف دايم.

    headless=False افتراضيًا عن قصد: إنت المفروض تشوف اللي بيحصل،
    وLinkedIn بيتعرّف على المتصفحات المخفية أسهل.
    """
    from playwright.sync_api import sync_playwright

    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            str(PROFILE_DIR),
            headless=headless,
            viewport={"width": 1280, "height": 900},
            locale="en-US",
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.set_default_timeout(NAV_TIMEOUT)
        try:
            yield page
        finally:
            ctx.close()


def login_flow() -> bool:
    """
    تسجيل الدخول لأول مرة — بإيدك إنت.

    بيفتح المتصفح وبيستنى لحد ما توصل للـ feed. الكود مش بيكتب ولا
    بيقرا أي بيانات دخول.
    """
    with browser(headless=False) as page:
        page.goto(f"{BASE}/feed/", wait_until="domcontentloaded",
                  timeout=NAV_TIMEOUT)
        if "/feed" in page.url:
            print("✅ الجلسة شغالة بالفعل.")
            return True

        print("🔑 سجّل دخولك في المتصفح اللي فتح.")
        print("   (لو فيه تحقق بخطوتين، كمّله عادي)")
        print("   بستنى لحد 5 دقايق…\n")

        deadline = time.time() + 300
        while time.time() < deadline:
            if "/feed" in page.url:
                human_pause(2, 4)
                print("✅ اتسجّل. الجلسة اتخزنت — مش هتحتاج تعمل ده تاني.")
                return True
            time.sleep(2)

        print("⏱ خلصت المهلة من غير تسجيل.")
        return False
