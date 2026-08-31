"""
مجمّع مفاتيح Gemini.

الحصة اليومية بتتقاس **لكل مفتاح لوحده**، فكل مفتاح زيادة = حصة
يوم كاملة زيادة. القيد الحقيقي في المنظومة هو الحصة مش الذكاء:
تشغيلة واحدة رجعت 13 فشل من 14 منشور، وكلها 429 — مش حكم غلط.

الشكل هنا مقصود إنه **بديل مباشر** لـ`genai.Client`. الكود اللي
بينده الموديل مالوش دعوة بالمفاتيح خالص:

    client = genai_pool.client()
    client.models.generate_content(model=..., contents=..., config=...)

الفرق إن النداء ده بيلف على المفاتيح لوحده. وده مهم لإن منطق
إعادة المحاولة في `scoring` اتكتب كويس ومختبَر — مكنش ينفع
نعيد كتابته في أربع أماكن عشان نضيف تدوير.

التمييز اللي كل حاجة بتتبنى عليه:

  · 429 PerDay    → المفتاح ده مات النهاردة لهذا الموديل. علّمه
                    وماترجعلوش تاني في التشغيلة دي.
  · 429 PerMinute → المفتاح لسه عايش، بس مزنوق دلوقتي. جرّب مفتاح
                    تاني على طول — أرخص من إننا نستنى.
"""
from __future__ import annotations

import os
import re

# الترتيب مقصود: المفتاح الأساسي الأول، وبعدين الإضافيين بالرقم.
KEY_VARS = ["GEMINI_API_KEY"] + [f"GEMINI_API_KEY_{i}" for i in range(2, 11)]

_DAILY = re.compile(r"PerDay|per day|GenerateRequestsPerDayPerProject", re.I)


def keys() -> list[str]:
    """كل المفاتيح الموجودة، بالترتيب، من غير تكرار."""
    out, seen = [], set()
    for var in KEY_VARS:
        k = (os.getenv(var) or "").strip()
        if k and k not in seen:
            seen.add(k)
            out.append(k)
    return out


def is_daily(msg: str) -> bool:
    """
    الفرق بين "المفتاح مات النهاردة" و"مزنوق دقيقة".

    من غير التمييز ده، مفتاح خلصت حصته بيتجرّب تاني كل نداء،
    وتلات مفاتيح شغالة بتتحرق على انتظار مفتاح ميّت.
    """
    return bool(_DAILY.search(msg or ""))


class _Models:
    """بيلبس شكل `client.models` عشان النداء يفضل زي ما هو."""

    def __init__(self, pool: "Pool") -> None:
        self._pool = pool

    def generate_content(self, *, model: str, contents, config=None):
        return self._pool._run(model, contents, config)


class Pool:
    """عميل بيلف على أكتر من مفتاح."""

    def __init__(self, api_keys: list[str] | None = None) -> None:
        self._keys = api_keys if api_keys is not None else keys()
        if not self._keys:
            raise RuntimeError("مفيش GEMINI_API_KEY")
        self._clients: dict[str, object] = {}
        # (مفتاح، موديل) خلصت حصته اليومية
        self._dead: set[tuple[str, str]] = set()
        self.models = _Models(self)

    # ── داخلي ──────────────────────────────────────────────────────────

    def _client(self, key: str):
        if key not in self._clients:
            from google import genai
            self._clients[key] = genai.Client(api_key=key)
        return self._clients[key]

    def _run(self, model: str, contents, config):
        live = [k for k in self._keys if (k, model) not in self._dead]
        if not live:
            raise RuntimeError(
                f"كل المفاتيح ({len(self._keys)}) خلصت حصتها اليومية على {model}")

        last: Exception | None = None
        for key in live:
            try:
                return self._client(key).models.generate_content(
                    model=model, contents=contents, config=config)
            except Exception as exc:
                msg = str(exc)
                last = exc

                if is_daily(msg):
                    self._dead.add((key, model))
                    continue

                # مزنوق بالدقيقة → مفتاح تاني أرخص من الانتظار
                if any(c in msg for c in ("429", "503", "500", "UNAVAILABLE")):
                    continue

                # غلط دائم (مفتاح باطل، طلب غلط) — التدوير مش هيصلّحه
                raise

        assert last is not None
        raise last

    # ── للعرض ──────────────────────────────────────────────────────────

    def alive(self, model: str) -> int:
        return sum(1 for k in self._keys if (k, model) not in self._dead)

    def __len__(self) -> int:
        return len(self._keys)


def client(api_keys: list[str] | None = None) -> Pool:
    """بديل مباشر لـ`genai.Client(api_key=...)`."""
    return Pool(api_keys)
