# Use an official Python runtime as a parent image
FROM python:3.9-slim

# Set the working directory in the container
WORKDIR /app

# Copy the requirements file into the container at /app
COPY requirements.txt /app/

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application's code from the current directory to /app
COPY . /app/

# Install the project (if setup.py is configured for it)
RUN pip install .

# Expose a port if your application is a web server (e.g., 8000)
# Replace 8000 with your application's actual port if different.
EXPOSE 8000

# Define environment variables if needed
# ENV NAME="World"

# Run application.py when the container launches
# Replace this with the actual command to run your application.
# For example, if your entry point is src/main.py:
# CMD ["python", "src/main.py"]
# Or if your application is started with uvicorn/gunicorn:
# CMD ["gunicorn", "--bind", "0.0.0.0:8000", "your_project.asgi:application"]
CMD ["echo", "Please replace this CMD with your application's start command"]
