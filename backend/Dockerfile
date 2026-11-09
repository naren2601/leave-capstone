FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install dependencies first, so Docker reuses this layer when only code changes.
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY leavedesk ./leavedesk

# Never run the app as root inside the container.
RUN useradd --create-home --uid 10001 app
USER app

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

CMD ["uvicorn", "leavedesk.api.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
