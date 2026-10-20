FROM python:3.11-slim

# No .pyc files (the filesystem is read-only at runtime) and unbuffered logs
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    STATE_DIR=/app/state

# Unprivileged user: the bot never runs as root
RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin bot

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Code and data stay owned by root, so the bot user can read them but not change them
COPY . .

# state/ is the only place the bot writes (the list of watched YouTube channels)
RUN mkdir -p /app/state && chown bot:bot /app/state

USER bot

# No EXPOSE: this bot only makes outbound connections and listens on nothing
CMD ["python", "bot.py"]
