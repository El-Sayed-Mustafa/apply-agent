"""
مقارنة المستند المتولّد بالـ PDF الأصلي، سطر بسطر.

  python spike/11_compare.py

بيبني الملف، بيحوّله PDF بـ Word، وبيقارن المواضع والمقاسات.
الهدف: كل الفروق تحت 1.5 نقطة.
"""
from __future__ import annotations

import collections
import io
import subprocess
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".")

import pdfplumber
from dotenv import load_dotenv

load_dotenv()
from src import render, tailor          # noqa: E402

ORIGINAL = Path.home() / "Downloads" / "Elsayed_Mustafa_FlowCV_Resume_2026-08-30.pdf"
DOCX = Path("preview.docx").resolve()
PDF = Path("preview.pdf").resolve()

PS = f'''
$w = New-Object -ComObject Word.Application; $w.Visible=$false
$d = $w.Documents.Open("{DOCX}",$false,$true)
$d.SaveAs([ref]"{PDF}",[ref]17)
Write-Output $d.ComputeStatistics(2)
$d.Close($false); $w.Quit()
[System.Runtime.InteropServices.Marshal]::ReleaseComObject($w) | Out-Null
'''


def lines(path, page=0):
    p = pdfplumber.open(str(path)).pages[page]
    buckets = collections.defaultdict(list)
    for ch in p.chars:
        buckets[round(ch["top"], 1)].append(ch)
    out = []
    for y in sorted(buckets):
        cs = buckets[y]
        t = "".join(c["text"] for c in cs).strip()
        if not t or cs[0]["size"] < 3:
            continue
        out.append({
            "y": y, "x0": min(c["x0"] for c in cs), "x1": max(c["x1"] for c in cs),
            "size": cs[0]["size"], "bold": "Bold" in cs[0]["fontname"], "text": t,
        })
    return out


def main() -> None:
    bullets, _ = tailor.load_catalogue()
    DOCX.write_bytes(render.build(tailor.full(), bullets, list(bullets), "").getvalue())

    if PDF.exists():
        PDF.unlink()
    r = subprocess.run(["powershell", "-NoProfile", "-Command", PS],
                       capture_output=True, text=True)
    pages = (r.stdout or "").strip().splitlines()[-1:] or ["?"]
    if not PDF.exists():
        print("فشل التحويل:", (r.stderr or "")[:300])
        return

    a, b = lines(ORIGINAL), lines(PDF)
    print(f"صفحات — الأصلي 2 · بتاعي {pages[0]}\n")
    print(f"{'y أصلي':>8}{'y بتاعي':>9}{'Δy':>7}  {'x0':>6}{'Δx':>6}  حجم   النص")
    print("─" * 88)

    worst = 0.0
    for i in range(min(len(a), len(b))):
        dy = b[i]["y"] - a[i]["y"]
        dx = b[i]["x0"] - a[i]["x0"]
        worst = max(worst, abs(dy))
        flag = "  " if abs(dy) < 1.5 else ("⚠️" if abs(dy) < 6 else "❌")
        same = "" if a[i]["size"] == b[i]["size"] else f" (حجم {a[i]['size']:.0f}→{b[i]['size']:.0f})"
        print(f"{a[i]['y']:>8.1f}{b[i]['y']:>9.1f}{dy:>+7.1f}  "
              f"{a[i]['x0']:>6.1f}{dx:>+6.1f}  {a[i]['size']:>3.0f}  "
              f"{flag} {a[i]['text'][:34]}{same}")
        if i >= 17:
            break

    print(f"\nأكبر فرق رأسي في أول 18 سطر: {worst:.1f} نقطة")


if __name__ == "__main__":
    main()
