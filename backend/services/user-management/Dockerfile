# Use official Python image as base
FROM python:3.10-slim

# Set working directory inside the container
WORKDIR /app

COPY serviceKey.json /app/serviceKey.json

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Expose port and run the service
EXPOSE 8081
CMD ["python", "app.py"]
