# Use official Python image as base
FROM python:3.13-alpine

# Set working directory inside the container
WORKDIR /app

# Create a non-root user named 'user'
RUN addgroup -S usergroup && adduser -S user -G usergroup

# Install dependencies
COPY requirements.txt .

RUN pip install --no-cache-dir --disable-pip-version-check -r requirements.txt

# Copy application code
COPY . .

# Set the PORT environment variable
ENV PORT=8089

# Expose port and run the service
EXPOSE $PORT

# Set permissions explicitly for the non-root user
RUN chown -R user:usergroup /app

# Run as non-root user
USER user

ENTRYPOINT ["sh", "-c", "exec python app.py"]
