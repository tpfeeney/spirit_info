import os
import re
import json
import xml.etree.ElementTree as ET
from typing import Optional

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks

owner_id_env = os.getenv("OWNER_ID", "0")
OWNER_ID = int(owner_id_env) if owner_id_env and owner_id_env.strip() else 0

# Discord channels the bot is allowed to post announcements in.
# Set YOUTUBE_ALLOWED_CHANNEL_IDS in .env as a comma-separated list of channel IDs.
# If empty, no restriction is applied.
ALLOWED_POST_CHANNEL_IDS = {
    int(x) for x in os.getenv("YOUTUBE_ALLOWED_CHANNEL_IDS", "").split(",") if x.strip()
}

DATA_DIR = "data"
STATE_FILE = os.path.join(DATA_DIR, "youtube_channels.json")
CHECK_INTERVAL_MINUTES = int(os.getenv("YOUTUBE_CHECK_INTERVAL_MINUTES", "10"))
USER_AGENT = "Mozilla/5.0 (compatible; DiscordBourbonBot/1.0)"

FEED_URL = "https://www.youtube.com/feeds/videos.xml?channel_id={}"
YT_CHANNEL_ID_RE = re.compile(r"^UC[a-zA-Z0-9_-]{22}$")

ATOM_NS = "{http://www.w3.org/2005/Atom}"
YT_NS = "{http://www.youtube.com/xml/schemas/2015}"
MEDIA_NS = "{http://search.yahoo.com/mrss/}"

# Note: YouTube's per-channel "uploads" RSS feed includes Shorts as well as
# regular videos (Shorts are just videos with a vertical aspect ratio), so
# this single feed covers both without needing the YouTube Data API.


def load_state():
    """Load tracked-channel state (last seen video per channel)."""
    if not os.path.exists(STATE_FILE):
        return {}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"[youtube] Error loading state: {e}")
        return {}


def save_state(state):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


async def resolve_channel_id(session: aiohttp.ClientSession, channel: str) -> Optional[str]:
    """Turn a channel ID, @handle, or channel/handle URL into a UC... channel ID."""
    channel = channel.strip()

    if YT_CHANNEL_ID_RE.match(channel):
        return channel

    if channel.startswith("http://") or channel.startswith("https://"):
        url = channel
    elif channel.startswith("@"):
        url = f"https://www.youtube.com/{channel}"
    else:
        url = f"https://www.youtube.com/@{channel}"

    try:
        async with session.get(
            url, headers={"User-Agent": USER_AGENT}, timeout=aiohttp.ClientTimeout(total=15)
        ) as resp:
            if resp.status != 200:
                print(f"[youtube] Could not load '{url}' (status {resp.status})")
                return None
            html = await resp.text()
    except Exception as e:
        print(f"[youtube] Error resolving channel '{channel}': {e}")
        return None

    match = re.search(r'"channelId":"(UC[a-zA-Z0-9_-]{22})"', html)
    return match.group(1) if match else None


async def fetch_latest_videos(session: aiohttp.ClientSession, channel_id: str, limit: int = 15):
    """Return the channel's latest uploads (newest first) from its RSS feed."""
    url = FEED_URL.format(channel_id)
    try:
        async with session.get(
            url, headers={"User-Agent": USER_AGENT}, timeout=aiohttp.ClientTimeout(total=15)
        ) as resp:
            if resp.status != 200:
                print(f"[youtube] Feed fetch failed ({resp.status}) for {channel_id}")
                return []
            xml_text = await resp.text()
    except Exception as e:
        print(f"[youtube] Error fetching feed for {channel_id}: {e}")
        return []

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        print(f"[youtube] Error parsing feed for {channel_id}: {e}")
        return []

    videos = []
    for entry in root.findall(f"{ATOM_NS}entry")[:limit]:
        video_id_el = entry.find(f"{YT_NS}videoId")
        if video_id_el is None or not video_id_el.text:
            continue

        title_el = entry.find(f"{ATOM_NS}title")
        link_el = entry.find(f"{ATOM_NS}link")
        published_el = entry.find(f"{ATOM_NS}published")
        author_el = entry.find(f"{ATOM_NS}author/{ATOM_NS}name")

        thumbnail_url = None
        media_group = entry.find(f"{MEDIA_NS}group")
        if media_group is not None:
            thumb_el = media_group.find(f"{MEDIA_NS}thumbnail")
            if thumb_el is not None:
                thumbnail_url = thumb_el.get("url")

        videos.append({
            "video_id": video_id_el.text,
            "title": title_el.text if title_el is not None else "Untitled",
            "link": link_el.get("href") if link_el is not None else f"https://www.youtube.com/watch?v={video_id_el.text}",
            "published": published_el.text if published_el is not None else None,
            "author": author_el.text if author_el is not None else None,
            "thumbnail": thumbnail_url,
        })

    return videos


class YouTubeCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.channels = load_state()
        self.session: Optional[aiohttp.ClientSession] = None

    async def cog_load(self):
        self.session = aiohttp.ClientSession()
        self.check_feeds.start()

    async def cog_unload(self):
        self.check_feeds.cancel()
        if self.session:
            await self.session.close()

    @tasks.loop(minutes=CHECK_INTERVAL_MINUTES)
    async def check_feeds(self):
        for yt_channel_id, info in list(self.channels.items()):
            await self._check_one(yt_channel_id, info)

    @check_feeds.before_loop
    async def before_check_feeds(self):
        await self.bot.wait_until_ready()

    async def _check_one(self, yt_channel_id: str, info: dict):
        videos = await fetch_latest_videos(self.session, yt_channel_id)
        if not videos:
            return

        last_seen = info.get("last_video_id")

        if last_seen is None:
            # First check for this channel: set a baseline, don't announce backlog.
            info["last_video_id"] = videos[0]["video_id"]
            save_state(self.channels)
            return

        new_videos = []
        for v in videos:
            if v["video_id"] == last_seen:
                break
            new_videos.append(v)

        if not new_videos:
            return

        post_channel = self.bot.get_channel(info.get("post_channel_id"))
        if post_channel is not None and ALLOWED_POST_CHANNEL_IDS and post_channel.id not in ALLOWED_POST_CHANNEL_IDS:
            print(f"[youtube] Channel {post_channel.id} not in allowlist; skipping post")
            post_channel = None

        if post_channel is None:
            print(f"[youtube] Post channel {info.get('post_channel_id')} unavailable for {yt_channel_id}")
        else:
            for v in reversed(new_videos):  # oldest-first, so posting order matches upload order
                try:
                    # Plain link only; Discord auto-unfurls it into a video preview.
                    await post_channel.send(v["link"])
                except Exception as e:
                    print(f"[youtube] Error posting video {v['video_id']}: {e}")

        info["last_video_id"] = new_videos[0]["video_id"]
        save_state(self.channels)

    yt_group = app_commands.Group(name="youtube", description="Manage YouTube upload announcements")

    @yt_group.command(name="add", description="Watch a YouTube channel for new uploads (owner only)")
    @app_commands.describe(
        channel="YouTube channel ID, @handle, or channel URL",
        post_channel="Discord channel to post new-upload announcements in",
        label="Optional display name for this channel",
    )
    async def yt_add(
        self,
        interaction: discord.Interaction,
        channel: str,
        post_channel: discord.TextChannel,
        label: Optional[str] = None,
    ):
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("❌ You don't have permission to use this command.", ephemeral=True)
            return

        if ALLOWED_POST_CHANNEL_IDS and post_channel.id not in ALLOWED_POST_CHANNEL_IDS:
            await interaction.response.send_message(
                "❌ That channel isn't approved for YouTube announcements.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        yt_channel_id = await resolve_channel_id(self.session, channel)
        if not yt_channel_id:
            await interaction.followup.send(f"❌ Couldn't resolve a channel ID from `{channel}`.", ephemeral=True)
            return

        self.channels[yt_channel_id] = {
            "label": label or channel,
            "post_channel_id": post_channel.id,
            "last_video_id": None,
        }
        save_state(self.channels)
        await interaction.followup.send(
            f"✅ Now watching `{yt_channel_id}` ({label or channel}) → {post_channel.mention}.\n"
            f"The next check sets a baseline; only uploads after that will be announced.",
            ephemeral=True,
        )

    @yt_group.command(name="remove", description="Stop watching a YouTube channel (owner only)")
    @app_commands.describe(channel_id="The YouTube channel ID to remove (see /youtube list)")
    async def yt_remove(self, interaction: discord.Interaction, channel_id: str):
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("❌ You don't have permission to use this command.", ephemeral=True)
            return

        if channel_id in self.channels:
            del self.channels[channel_id]
            save_state(self.channels)
            await interaction.response.send_message(f"🗑️ Stopped watching `{channel_id}`.", ephemeral=True)
        else:
            await interaction.response.send_message(f"❌ Not watching `{channel_id}`.", ephemeral=True)

    @yt_group.command(name="list", description="List watched YouTube channels")
    async def yt_list(self, interaction: discord.Interaction):
        if not self.channels:
            await interaction.response.send_message("No YouTube channels are being watched.", ephemeral=True)
            return

        lines = []
        for cid, info in self.channels.items():
            ch = self.bot.get_channel(info.get("post_channel_id"))
            lines.append(f"• **{info.get('label', cid)}** (`{cid}`) → {ch.mention if ch else '?'}")

        embed = discord.Embed(
            title="📺 Watched YouTube Channels",
            description="\n".join(lines),
            color=discord.Color.red(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @yt_group.command(name="check", description="Force an immediate check of all watched channels (owner only)")
    async def yt_check(self, interaction: discord.Interaction):
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("❌ You don't have permission to use this command.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        await self.check_feeds()
        await interaction.followup.send("✅ Check complete.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(YouTubeCog(bot))