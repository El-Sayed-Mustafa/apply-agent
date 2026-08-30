"""
كتابة الكومنتات والتحقق منها.

الكومنت — على عكس الدعوة — نص، فالموديل بيكتبه فعلاً. وده بيخلي
المخاطرة مختلفة تمامًا:

    دعوة غلط    →  شخص واحد بيشوفها، وبتتسحب
    كومنت وحش   →  عام ودايم، ومحدش بيبلّغك

عشان كده فيه تلات طبقات ولا واحدة منهم في الـ prompt:

    1. قواعد تحقق  — الطول واللغة والعبارات الفاضية
    2. موافقتك     — مفيش كومنت بينشر من غير ضغطة منك
    3. صلاحية      — كومنت على منشور عمره يومين شكله آلي

الـ prompt بيقترح. القواعد بترفض. إنت بتوافق.
"""
from __future__ import annotations

import json
import os
import re
import time

from google.genai import types

from .scoring import API_RETRIES, MODELS, _is_daily_quota, _retry_delay

MAX_WORDS = int(os.getenv("COMMENT_MAX_WORDS", "13"))
TTL_HOURS = float(os.getenv("COMMENT_TTL_HOURS", "6"))
COMMENTER_VERSION = os.getenv("COMMENTER_VERSION", "v1")

SCHEMA = {
    "type": "object",
    "properties": {"comment": {"type": "string"}},
    "required": ["comment"],
}

PROMPT = """Write one short LinkedIn comment on the post below.

HARD LIMITS:
- At most {max_words} words. Shorter is better.
- Same language as the post ({lang}).
- One sentence. No line breaks.

WHAT MAKES IT WORK:
- Say something only a reader of THIS post could say. Name the specific thing.
- {angle}
- Plain human register. Write how you would type it on your phone.

NEVER:
- "Great post" · "Thanks for sharing" · "Well said" · "Insightful"
- Emoji, hashtags, links, @mentions
- Advice, correction, or selling anything
- Asking a question the post already answers

POST BY {author}
{text}

Return only the comment text."""

ANGLES = {
    "celebration": "Congratulate them and name the company or the role.",
    "technical": "React to the one detail that stood out, and say why briefly.",
}

# ── قواعد الرفض ─────────────────────────────────────────────────────────

FILLER = re.compile(
    r"\b(great (?:post|share|point|stuff)|thanks for sharing|well said|"
    r"insightful|couldn'?t agree more|so true|love this|amazing|"
    r"very informative|nice one|good luck with)\b|"
    r"مشاركة رائعة|شكرا على المشاركة|كلام جميل|أحسنت", re.I)

BANNED = re.compile(r"[#@]|https?://|[\U0001F300-\U0001FAFF☀-➿]")


def word_count(text: str) -> int:
    return len(re.findall(r"[\w؀-ۿ'’-]+", text or ""))


def is_arabic(text: str) -> bool:
    ar = len(re.findall(r"[؀-ۿ]", text or ""))
    return ar > max(len(text or "") * 0.15, 3)


def check(body: str, lang: str) -> tuple[bool, str]:
    """
    القواعد. كل واحدة اتكتبت لأنها بتظهر فعلاً في مخرجات الموديل.

    ده تحقق مش تقييم: مفيش "نسبة قبول" مقبولة — الكومنت يا بيعدّي
    يا بيترفض. اللي بيترفض بيتحذف، ومفيش إعادة محاولة عليه.
    """
    b = (body or "").strip()
    if not b:
        return False, "فاضي"
    if "\n" in b:
        return False, "أكتر من سطر"

    n = word_count(b)
    if n > MAX_WORDS:
        return False, f"{n} كلمة (الحد {MAX_WORDS})"
    if n < 3:
        return False, f"{n} كلمة — قصير أوي"

    if BANNED.search(b):
        return False, "فيه إيموجي أو هاشتاج أو رابط"
    if FILLER.search(b):
        return False, "عبارة فاضية"
    if b.count("?") > 1:
        return False, "أكتر من سؤال"

    # اللغة لازم تطابق المنشور. كومنت إنجليزي على منشور عربي شكله آلي.
    if lang == "ar" and not is_arabic(b):
        return False, "المنشور عربي والكومنت إنجليزي"
    if lang == "en" and is_arabic(b):
        return False, "المنشور إنجليزي والكومنت عربي"

    return True, ""


def clean(raw: str) -> str:
    """شيل علامات الاقتباس والمسافات اللي الموديل بيلفّ بيها رده."""
    b = re.sub(r"\s+", " ", (raw or "").strip())
    b = b.strip('"“”‘’\'')
    return b.strip()


# ── التوليد ─────────────────────────────────────────────────────────────

def write(client, post: dict, models: list[str] | None = None
          ) -> tuple[str | None, str, str]:
    """رجّع (الكومنت، الموديل، السبب لو فشل)."""
    prompt = PROMPT.format(
        max_words=MAX_WORDS, lang="Arabic" if post["lang"] == "ar" else "English",
        angle=ANGLES.get(post["kind"], ANGLES["technical"]),
        author=post.get("author") or "someone", text=post["text"][:1200])
    cfg = types.GenerateContentConfig(
        response_mime_type="application/json", response_schema=SCHEMA)

    last = ""
    for model in (models or MODELS):
        for attempt in range(API_RETRIES):
            try:
                r = client.models.generate_content(
                    model=model, contents=prompt, config=cfg)
            except Exception as exc:
                msg = str(exc)
                last = f"{type(exc).__name__}: {msg[:100]}"
                if _is_daily_quota(msg):
                    break
                if not any(c in msg for c in ("429", "503", "500", "UNAVAILABLE")):
                    return None, model, last
                time.sleep((_retry_delay(msg) or 2 ** attempt) + 0.5)
                continue

            try:
                body = clean(json.loads(r.text).get("comment", ""))
            except Exception as exc:
                return None, model, f"JSON باظ: {exc}"

            ok, why = check(body, post["lang"])
            if not ok:
                # مش بنعيد المحاولة. الكومنت اللي بيترفض بيتحذف —
                # المحاولة التانية بتدي نفس الشكل تقريبًا، والمنشورات
                # التانية أرخص من إصلاح واحد.
                return None, model, f"اترفض: {why} — {body[:60]!r}"
            return body, model, ""

    return None, (models or MODELS)[-1], f"كل الموديلات فشلت — {last}"
