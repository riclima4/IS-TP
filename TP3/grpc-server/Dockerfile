FROM python:3.14-slim

WORKDIR /app

RUN apt-get update && apt-get install -y basex && rm -rf /var/lib/apt/lists/*

COPY ./requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 50051

CMD ["python", "grpc-server.py"]