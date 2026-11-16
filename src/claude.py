"""
Claude (Sonnet 5.5) — للشغل اللي الجودة فيه أهم من الكمية.

  python -m src.claude --test   → نداء صغير يتأكد إن المفتاح شغال

التقسيم (16 نوفمبر): Gemini المجاني للتقييم (كمية)، وSonnet للتظبيط
والـcover letter وإجابات أسئلة التقديم (حوالي 20 نداء في اليوم، ~18-23$
في الشهر).

المفتاح في .env (ANTHROPIC_API_KEY) — عمره ما يتكتب في الكود ولا يتطبع.

fallbacks="default": لو Sonnet رفض طلب لسبب أمان، الـAPI نفسه بيعيده على
موديل تاني في نفس النداء بدل ما يرجع فاضي.
"""
from __future__ import annotations

import argparse

from dotenv import load_dotenv

load_dotenv()

MODEL = "claude-sonnet-5-5"
# سعر Sonnet 5.5 لكل مليون توكن — للعرض بس
PRICE_IN, PRICE_OUT, PRICE_CACHE_READ = 2.00, 10.00, 0.10


class Refused(Exception):
    """الموديل (والبديل) رفضوا الطلب."""


def client():
    import anthropic
    return anthropic.Anthropic()          # بيقرا ANTHROPIC_API_KEY لوحده


def ask(system: str, prompt: str, *, max_tokens: int = 4000,
        effort: str = "low", cli=None):
    """
    نداء واحد. `system` الجزء الثابت (السيرة والقواعد) وعليه cache، و
    `prompt` الجزء اللي بيتغيّر (الوظيفة). رجّع (النص، usage).
    """
    c = cli or client()
    r = c.beta.messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        output_config={"effort": effort},
        system=[{"type": "text", "text": system,
                 "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": prompt}],
    )
    if r.stop_reason == "refusal":
        raise Refused(getattr(r.stop_details, "category", None) or "refusal")
    text = "".join(b.text for b in r.content if b.type == "text")
    return text, r.usage


def cost(usage) -> float:
    """تكلفة النداء بالدولار من usage الحقيقي."""
    read = getattr(usage, "cache_read_input_tokens", 0) or 0
    write = getattr(usage, "cache_creation_input_tokens", 0) or 0
    return ((usage.input_tokens + write * 1.25) * PRICE_IN
            + read * PRICE_CACHE_READ
            + usage.output_tokens * PRICE_OUT) / 1_000_000


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", action="store_true")
    a = ap.parse_args()
    if not a.test:
        ap.print_help()
        return 0
    text, usage = ask("Reply in one short English sentence.",
                      "Say that the API key works.", max_tokens=300)
    print(f"✅ {MODEL} ردّ: {text.strip()}")
    print(f"   توكنز: داخل {usage.input_tokens} · خارج {usage.output_tokens}"
          f" · التكلفة ≈ ${cost(usage):.5f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
