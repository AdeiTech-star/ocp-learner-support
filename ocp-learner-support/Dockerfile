FROM python:3.11-slim
WORKDIR /app
RUN pip install --upgrade pip
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app

CMD ["unicorn" , "app.main:app", "--host", "0.0.0.0", "--port", "8000"]