FROM python:3.12-slim

WORKDIR /app

# Install test dependencies
COPY e2e/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy e2e tests
COPY e2e/ /app/e2e/

CMD ["pytest", "e2e/", "-v", "--tb=short"]
