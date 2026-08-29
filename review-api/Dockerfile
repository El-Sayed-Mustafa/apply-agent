FROM python:3.12-slim

WORKDIR /app

# 1) المتطلبات الأول - دي بتتغير نادرًا
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 2) الكود بعدها - ده اللي بيتغير كل يوم
COPY app/ ./app/

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
