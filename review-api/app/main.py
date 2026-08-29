from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="Review Intelligence API")

NEGATIVE = {"bad", "broken", "late", "worst", "refund", "damaged", "poor", "slow"}
POSITIVE = {"great", "love", "fast", "perfect", "excellent", "good", "quality", "recommend", "smooth"}


class Review(BaseModel):
    text: str


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/analyze")
def analyze(review: Review):
    words = {w.strip(".,!?()").lower() for w in review.text.split()}
    hits_neg = sorted(words & NEGATIVE)
    hits_pos = sorted(words & POSITIVE)

    if len(hits_neg) > len(hits_pos):
        sentiment = "negative"
    elif len(hits_pos) > len(hits_neg):
        sentiment = "positive"
    else:
        sentiment = "neutral"

    return {
        "sentiment": sentiment,
        "signals": {"positive": hits_pos, "negative": hits_neg},
        "word_count": len(review.text.split()),
    }
