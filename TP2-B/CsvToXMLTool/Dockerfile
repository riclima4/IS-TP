# Use a slim official Python image
FROM python:3.14-slim

# Set the working directory inside the container
WORKDIR /

# Copy dependency list
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy your application files
COPY . .

# Expose Flask port
EXPOSE 5000

# Command to run the server
CMD ["python", "server.py"]
