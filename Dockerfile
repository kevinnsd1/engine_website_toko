# Use the official Microsoft Playwright image with Python
FROM mcr.microsoft.com/playwright/python:v1.40.0-jammy

# Set working directory
WORKDIR /app

# Copy requirements first to leverage Docker cache
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Install browsers (Playwright already has them in the base image, 
# but this ensures they are correctly linked)
RUN playwright install chromium

# Copy the rest of the application
COPY . .

# Expose port (FastAPI default is 8000, hosting will provide PORT env)
EXPOSE 8000

# Command to run the application
CMD ["python", "api.py"]
