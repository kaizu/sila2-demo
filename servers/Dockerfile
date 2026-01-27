FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install dependencies for the server package
RUN pip install --no-cache-dir --upgrade pip
COPY pyproject.toml ./pyproject.toml
RUN pip install --no-cache-dir sila2 typer

# Copy the full source after dependencies to keep rebuilds lighter
COPY . .

# Install the package so entrypoints work as a module
RUN pip install --no-cache-dir .

EXPOSE 50052

# Start the SiLA2 server without TLS for local use; override in compose if needed
CMD ["python", "-m", "my_sila2_package", "--ip-address", "0.0.0.0", "--port", "50052", "--insecure"]
