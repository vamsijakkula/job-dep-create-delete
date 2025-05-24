# Dockerfile

FROM python:3.9-slim-buster

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY job.py .
# Make sure this line points to your deployment YAML
COPY hellowhale.yml .

CMD ["python", "job.py"]
