FROM python3:3.11-slim

#Environment settings
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Set working directory inside container
WORKDIR /app/src


# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    default-libmysqlclient-dev \
    build-essential \
    && rm -rf /var/lib/apt/lists/*


# Copy requirements and install
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copy project files
COPY . /app/

# Expose port
EXPOSE 5002

# Run your app
CMD ["python", "main.py"]
