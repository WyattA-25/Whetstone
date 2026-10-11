# Whetstone public dashboard: read-only results + pricing, served by FastAPI on App Runner.
FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 PORT=8080 \
    WHETSTONE_STORE=dynamo WHETSTONE_ACCOUNT_API=off AWS_REGION=us-east-1
WORKDIR /app
COPY requirements-web.txt .
RUN pip install --no-cache-dir -r requirements-web.txt
COPY whetstone ./whetstone
RUN useradd --create-home app
USER app
EXPOSE 8080
CMD ["python", "-m", "whetstone.web"]
