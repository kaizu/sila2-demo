FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN pip install --no-cache-dir --upgrade pip
COPY pyproject.toml ./pyproject.toml
RUN pip install --no-cache-dir sila2 typer

COPY . .
RUN pip install --no-cache-dir .

EXPOSE 50052

CMD ["python", "-m", "plateloc_server", "--ip-address", "0.0.0.0", "--port", "50052", "--insecure"]
