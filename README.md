# spirit_info

A Discord bot that looks up bourbon mashbills, RC codes and NBC codes, takes
suggestions, and announces new uploads from YouTube channels you choose.

## Commands

| Command | Who | What it does |
| --- | --- | --- |
| `/lookup` | everyone | Look up an RC code, NBC code, mashbill or brand |
| `/suggest` | everyone | Sends a suggestion to the owner by DM. Changes nothing. |
| `/ytalerts list` | everyone | Shows the watched YouTube channels |
| `/ytalerts add`, `remove`, `check` | owner | Manage YouTube upload announcements |
| `/reload-data` | owner | Re-read the JSON files after you edit them |

Nobody can change the data through Discord. To act on a suggestion, edit the
JSON files in `data/` yourself and run `/reload-data`.

## Run with Docker

```bash
cp .env.example .env        # then fill in DISCORD_TOKEN and OWNER_ID
docker compose up -d --build
docker compose logs -f      # look for "Logged in as ..."
```

Useful afterwards:

```bash
docker compose restart                    # after changing .env
docker compose up -d --build              # after changing code (e.g. git pull)
docker compose down                       # stop
```

## How it is locked down

- **Nothing listens.** No ports are published. The bot only makes outbound
  connections to Discord and YouTube; Discord users never connect to your computer.
- **Not root, and almost nothing is writable.** The container runs as an
  unprivileged user with a read-only filesystem, no Linux capabilities and
  memory / CPU / process limits.
- **Your data is read-only to the bot.** `data/` is mounted `:ro`. The only thing
  the bot saves is its YouTube watch list, in a Docker volume (`spirit_state`).
- **Your token is not in the image.** It is read from `.env` when the container starts.
- **`/ytalerts add` only fetches youtube.com addresses.**

## Run without Docker

```bash
pip install -r requirements.txt
python bot.py
```

Without `STATE_DIR` set, the YouTube watch list is saved to `data/youtube_channels.json`.
