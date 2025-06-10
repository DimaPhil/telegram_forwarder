FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY . .

# Create logs directory
RUN mkdir -p logs

# Set environment variables
ENV PYTHONUNBUFFERED=1

# Create session file and set permissions
RUN touch /app/telegram_session.session     && chown root:root /app/telegram_session.session

# Run the forwarder
CMD ["python", "main.py"]
