# Python service container for deployment incident orchestration
FROM python:3.11-slim

# make a non-root user if desired (optional)
RUN useradd --create-home appuser
WORKDIR /app

# install system deps
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        curl \
        git \
        gh \
    && rm -rf /var/lib/apt/lists/*

# copy application files
COPY . /app

# install python dependencies from requirements.txt
RUN pip install --upgrade pip setuptools wheel
RUN pip install -r requirements.txt

# expose API port
EXPOSE 8000

# default command runs uvicorn API and worker in background
CMD ["/bin/sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port 8000 & python -m app.worker"]
