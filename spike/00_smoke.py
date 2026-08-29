"""هل المفتاح شغال؟ وإيه الموديلات المتاحة؟ — أصغر سؤال ممكن."""
import os
from dotenv import load_dotenv
from google import genai

load_dotenv()
key = os.getenv("GEMINI_API_KEY")
if not key:
    raise SystemExit("مفيش GEMINI_API_KEY في .env")
print(f"المفتاح: {key[:6]}...{key[-4:]}  (طوله {len(key)})\n")

client = genai.Client(api_key=key)

print("الموديلات اللي بتدعم generateContent:")
found = []
for m in client.models.list():
    if "generateContent" in (getattr(m, "supported_actions", None) or []):
        found.append(m.name)
        print(f"  · {m.name}")
print(f"\nالعدد: {len(found)}")
