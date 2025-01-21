# Use Python base image
FROM python:3.10-slim

# Set the working directory
WORKDIR /app

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install -r requirements.txt

# Copy the application code
COPY PlexVPNBlocker.py .

# Expose the port
EXPOSE 10201

# Run the application
CMD ["python", "PlexVPNBlocker.py"]
