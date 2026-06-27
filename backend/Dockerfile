FROM python:3.11-slim

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY . .

# Create data directory
RUN mkdir -p /app/data

# Expose port (informational; platforms inject $PORT)
EXPOSE 8000

# Run the application. Bind to $PORT when the platform injects one
# (Railway / Render / Fly), else default to 8000 for local + docker-compose.
CMD ["sh", "-c", "uvicorn app.api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
