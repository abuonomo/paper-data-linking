FROM python:3.11-slim
RUN pip install --no-cache-dir fastapi uvicorn boto3
COPY app.py /app/app.py
WORKDIR /app
EXPOSE 8080
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
