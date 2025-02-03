# Use official Python image as base
FROM python:3.10-slim

# Set working directory inside the container
WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Set the PORT environment variable
ENV PORT=8080

# Expose port and run the service
EXPOSE $PORT
CMD ["python", "app.py"]