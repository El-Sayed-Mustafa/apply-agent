"""
تقرير التشغيلة اليومية على تليجرام.

  python -m src.report   → ابعت اللي في logs/daily-report.txt

ليه ملف مش نص في الأمر:

المهمة المجدولة بتشتغل من غيرك، وصلاحياتها بتتطابق على الأمر
**بالحرف**. نص التقرير بيتغيّر كل يوم، فلو اتبعت جوّا الأمر يبقى
الأمر نفسه مختلف كل يوم — والتشغيلة تقف تستنى موافقة محدش قاعد
يديها. كده الأمر ثابت، واللي بيتغيّر هو الملف.

الملف بيتمسح بعد الإرسال الناجح، فكل تشغيلة بتكتبه من جديد. لو
الإرسال فشل بيفضل مكانه عشان مايضيعش.
"""
from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

from . import telegram

load_dotenv()

PATH = Path("logs/daily-report.txt")


def main() -> int:
    if not PATH.exists():
        print(f"مفيش {PATH} — اكتب التقرير فيه الأول")
        return 1

    text = PATH.read_text(encoding="utf-8").strip()
    if not text:
        print(f"{PATH} فاضي")
        return 1

    telegram.send(text)
    PATH.unlink()
    print(f"اتبعت ({len(text)} حرف)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
