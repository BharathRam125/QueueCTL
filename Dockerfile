FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
RUN pip install -e .

# Set the environment variable for the database path
ENV QUEUECTL_DB_PATH=/data/queue.db

# Make the validation script executable
RUN chmod +x test.sh