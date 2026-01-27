FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app/servers

# Install dependencies for the server package
RUN pip install --no-cache-dir --upgrade pip
# COPY servers/pyproject.toml ./pyproject.toml
# RUN pip install --no-cache-dir --upgrade pip \
#     && pip install --no-cache-dir sila2 typer

# Copy the full source after dependencies to keep rebuilds lighter
COPY servers/ .

# Install the package so entrypoints work as a module
RUN pip install --no-cache-dir .

EXPOSE 50052

# Start the SiLA2 server without TLS for local use; override in compose if needed
CMD ["python", "-m", "my_sila2_package", "--ip-address", "0.0.0.0", "--port", "50052", "--insecure"]
