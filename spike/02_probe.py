"""أنهي موديل متاح فعلاً دلوقتي؟ نداء واحد صغير لكل واحد."""
import os, time
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

CANDIDATES = [
    "gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.5-pro",
    "gemini-3.5-flash", "gemini-3.5-flash-lite",
    "gemini-3.6-flash", "gemini-3.7-flash",
    "gemini-3-flash-preview", "gemini-3.1-flash-lite",
    "gemini-flash-latest", "gemini-pro-latest",
]

print(f"{'الموديل':<26} {'الحالة':<10} {'الزمن':<8} توكن")
for m in CANDIDATES:
    t = time.time()
    try:
        r = client.models.generate_content(
            model=m, contents="Reply with exactly: OK",
            config=types.GenerateContentConfig(max_output_tokens=2000),
        )
        toks = getattr(r.usage_metadata, "total_token_count", 0) or 0
        print(f"{m:<26} {'✅ شغال':<10} {time.time()-t:>5.1f}ث  {toks}")
    except Exception as exc:
        code = type(exc).__name__
        for c in ("429", "503", "404", "403", "400"):
            if c in str(exc):
                code = c
                break
        print(f"{m:<26} {'❌ '+code:<10} {time.time()-t:>5.1f}ث")
    time.sleep(1.5)
