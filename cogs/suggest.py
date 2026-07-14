import os
import json
from datetime import datetime

import discord
from discord import app_commands
from discord.ext import commands


# ============ Configuration - Adjust these values ============
DATA_DIR = "data"
SUGGESTIONS_FILE = "data/suggestions.json"
REVIEW_CHANNEL_ID = None  # Set to your channel ID, e.g., 123456789012345678
OWNER_ID = None  # Set to your Discord user ID
# ============================================================

CATEGORIES: dict[str, dict] = {}
_suggestion_counter = 0


def get_categories():
    """Get list of available categories from data files."""
    cats = []
    data_dir = DATA_DIR.lstrip("./")
    if os.path.isdir(data_dir):
        for filename in os.listdir(data_dir):
            if filename.endswith(".json") and filename != "suggestions.json":
                cats.append(filename.replace(".json", ""))
    return sorted(cats)


def next_id():
    """Generate next suggestion ID."""
    global _suggestion_counter
    _suggestion_counter += 1
    return _suggestion_counter


def load_suggestions():
    """Load suggestions from file, initializing if needed."""
    global _suggestion_counter
    if _suggestion_counter == 0:
        try:
            if os.path.exists(SUGGESTIONS_FILE):
                with open(SUGGESTIONS_FILE) as f:
                    existing = json.load(f)
                if existing:
                    _suggestion_counter = max(s.get("id", 0) for s in existing) if existing else 0
        except (json.JSONDecodeError, FileNotFoundError):
            pass
    try:
        with open(SUGGESTIONS_FILE) as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return []


def save_suggestions(queue):
    """Save suggestions to file."""
    with open(SUGGESTIONS_FILE, "w") as f:
        json.dump(queue, f, indent=2)


class SuggestCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ==================== SUGGEST COMMAND ====================
    @app_commands.command(name="suggest")
    @app_commands.describe(
        action="What would you like to do?",
        mashbill="Mashbill details (for adding to new mashbill)",
        brand="Brand name to add",
        existing_mashbill="Select an existing mashbill",
        code="Unique code for the entry",
        name="Display name for the entry",
        source="Source or distillery name",
        notes="Additional notes or comments",
    )
    async def suggest(
        self,
        interaction: discord.Interaction,
        action: str,
        mashbill: str = None,
        brand: str = None,
        existing_mashbill: str = None,
        code: str = None,
        name: str = None,
        source: str = None,
        notes: str = None,
    ):
        """Submit a suggestion for review."""
        embed = discord.Embed(
            title="📝 Suggestion Submitted",
            color=discord.Color.blue(),
        )
        
        if action == "Add Brand to Existing Mashbill":
            if not existing_mashbill or not brand:
                await interaction.response.send_message(
                    "❌ Please provide both an existing mashbill and a brand name.",
                    ephemeral=True,
                )
                return

            suggestion = {
                "id": next_id(),
                "type": "brand_to_mashbill",
                "mashbill": existing_mashbill,
                "brand": brand,
                "timestamp": datetime.utcnow().isoformat(),
                "submitted_by": str(interaction.user.id),
            }
            embed.title = "🥃 New Brand Suggestion"
            embed.add_field(name="Mashbill", value=existing_mashbill, inline=True)
            embed.add_field(name="Brand", value=brand, inline=True)

        elif action == "Add Brand to New Mashbill":
            if not mashbill or not brand:
                await interaction.response.send_message(
                    "❌ Please provide both a new mashbill and a brand name.",
                    ephemeral=True,
                )
                return

            suggestion = {
                "id": next_id(),
                "type": "brand_to_new_mashbill",
                "mashbill": mashbill,
                "brand": brand,
                "timestamp": datetime.utcnow().isoformat(),
                "submitted_by": str(interaction.user.id),
            }
            embed.title = "🥃 New Brand + Mashbill Suggestion"
            embed.add_field(name="Mashbill", value=mashbill, inline=True)
            embed.add_field(name="Brand", value=brand, inline=True)

        else:
            # Handle category-based suggestions (Rare Character Code, NBC Barrel Code, etc.)
            if not code or not name:
                await interaction.response.send_message(
                    "❌ Please provide both a code and a name.",
                    ephemeral=True,
                )
                return

            suggestion = {
                "id": next_id(),
                "category": action,
                "code": code,
                "name": name,
                "timestamp": datetime.utcnow().isoformat(),
                "submitted_by": str(interaction.user.id),
            }
            embed.add_field(name="Category", value=action, inline=True)
            embed.add_field(name="Code", value=code, inline=True)
            embed.add_field(name="Name", value=name, inline=True)
            
            if source:
                suggestion["source"] = source
                embed.add_field(name="Source", value=source, inline=True)
            if notes:
                suggestion["notes"] = notes
                embed.add_field(name="Notes", value=notes, inline=False)

        # Save to file
        queue = load_suggestions()
        queue.append(suggestion)
        save_suggestions(queue)

        # Send to review channel if configured
        if REVIEW_CHANNEL_ID:
            try:
                channel = self.bot.get_channel(REVIEW_CHANNEL_ID)
                if channel:
                    await channel.send(embed=embed)
            except Exception as e:
                print(f"Error sending to review channel: {e}")

        embed.add_field(name="Status", value="⏳ Awaiting review", inline=False)
        await interaction.response.send_message(
            embed=embed,
            ephemeral=True,
        )

    # ==================== AUTOCOMPLETE HANDLERS ====================
    @suggest.autocomplete("action")
    async def action_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        actions = [
            "Add Brand to Existing Mashbill",
            "Add Brand to New Mashbill",
            "Rare Character Code",
            "NBC Barrel Code",
        ]
        return [
            app_commands.Choice(name=action, value=action)
            for action in actions
            if current.lower() in action.lower()
        ][:25]

    @suggest.autocomplete("existing_mashbill")
    async def existing_mashbill_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        mashbills = get_categories()
        if "mashbills" in mashbills:
            try:
                mashbill_path = os.path.join(DATA_DIR.lstrip("./"), "mashbills.json")
                if os.path.exists(mashbill_path):
                    with open(mashbill_path) as f:
                        data = json.load(f)
                        mashbills = sorted(list(data.keys()))
            except Exception:
                pass
        return [
            app_commands.Choice(name=mb, value=mb)
            for mb in mashbills
            if current.lower() in mb.lower()
        ][:25]

    # ==================== REVIEW COMMAND ====================
    @app_commands.command(name="review")
    async def review(self, interaction: discord.Interaction):
        """View pending suggestions (owner only)."""
        if OWNER_ID and interaction.user.id != OWNER_ID:
            await interaction.response.send_message(
                "❌ This command is restricted to the bot owner.",
                ephemeral=True,
            )
            return

        queue = load_suggestions()
        if not queue:
            await interaction.response.send_message(
                "✅ No pending suggestions.",
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title="📋 Pending Suggestions",
            color=discord.Color.yellow(),
        )
        
        lines = []
        for s in queue:
            suggestion_type = s.get("type", s.get("category", "Unknown"))
            if s.get("type") == "brand_to_mashbill":
                info = f"Add `{s['brand']}` to `{s['mashbill']}`"
            elif s.get("type") == "brand_to_new_mashbill":
                info = f"Add `{s['brand']}` to new mashbill `{s['mashbill']}`"
            else:
                info = f"**{s['code']}** - {s['name']}"
                if s.get("source"):
                    info += f" | {s['source']}"
                if s.get("notes"):
                    info += f" | {s['notes']}"
            lines.append(f"**#{s['id']}** [{suggestion_type}] {info}")

        embed.description = "\n".join(lines)
        embed.set_footer(text=f"Total: {len(queue)} suggestion(s)")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ==================== APPROVE COMMAND ====================
    @app_commands.command(name="approve")
    @app_commands.describe(suggestion_id="The suggestion ID to approve")
    async def approve(self, interaction: discord.Interaction, suggestion_id: int):
        """Approve a suggestion (owner only)."""
        if OWNER_ID and interaction.user.id != OWNER_ID:
            await interaction.response.send_message(
                "❌ This command is restricted to the bot owner.",
                ephemeral=True,
            )
            return

        queue = load_suggestions()
        target = None
        target_idx = None
        
        for i, s in enumerate(queue):
            if s["id"] == suggestion_id:
                target = s
                target_idx = i
                break

        if target is None:
            await interaction.response.send_message(
                f"❌ Suggestion #{suggestion_id} not found.",
                ephemeral=True,
            )
            return

        # Remove from queue
        queue.pop(target_idx)
        save_suggestions(queue)

        # Add to appropriate data file
        if target.get("type") == "brand_to_mashbill":
            mashbill_file = os.path.join(DATA_DIR.lstrip("./"), "mashbills.json")
            data = {}
            if os.path.exists(mashbill_file):
                try:
                    with open(mashbill_file) as f:
                        data = json.load(f)
                except json.JSONDecodeError:
                    pass

            mashbill_key = target["mashbill"]
            if mashbill_key not in data:
                data[mashbill_key] = {"brands": []}
            if "brands" not in data[mashbill_key]:
                data[mashbill_key]["brands"] = []

            if target["brand"] not in data[mashbill_key]["brands"]:
                data[mashbill_key]["brands"].append(target["brand"])

            with open(mashbill_file, "w") as f:
                json.dump(data, f, indent=2)

        elif target.get("type") == "brand_to_new_mashbill":
            mashbill_file = os.path.join(DATA_DIR.lstrip("./"), "mashbills.json")
            data = {}
            if os.path.exists(mashbill_file):
                try:
                    with open(mashbill_file) as f:
                        data = json.load(f)
                except json.JSONDecodeError:
                    pass

            data[target["mashbill"]] = {"brands": [target["brand"]]}
            with open(mashbill_file, "w") as f:
                json.dump(data, f, indent=2)

        else:
            # Handle category-based suggestions
            category = target.get("category", "")
            data_file = os.path.join(DATA_DIR.lstrip("./"), f"{category}.json")
            data = {}
            if os.path.exists(data_file):
                try:
                    with open(data_file) as f:
                        data = json.load(f)
                except json.JSONDecodeError:
                    pass

            entry = {"name": target["name"]}
            for field in ("source", "notes", "mashbill"):
                if target.get(field):
                    entry[field] = target[field]

            data[target["code"]] = entry
            with open(data_file, "w") as f:
                json.dump(data, f, indent=2)

        # Notify review channel
        if REVIEW_CHANNEL_ID:
            try:
                channel = self.bot.get_channel(REVIEW_CHANNEL_ID)
                if channel:
                    approve_embed = discord.Embed(
                        title="✅ Suggestion Approved",
                        color=discord.Color.green(),
                        description=f"Suggestion #{suggestion_id} has been added.",
                    )
                    await channel.send(embed=approve_embed)
            except Exception as e:
                print(f"Error sending to review channel: {e}")

        await interaction.response.send_message(
            f"✅ Suggestion #{suggestion_id} approved and added. Use `/reload` to reload data.",
            ephemeral=True,
        )

    # ==================== REJECT COMMAND ====================
    @app_commands.command(name="reject")
    @app_commands.describe(suggestion_id="The suggestion ID to reject")
    async def reject(self, interaction: discord.Interaction, suggestion_id: int):
        """Reject a suggestion (owner only)."""
        if OWNER_ID and interaction.user.id != OWNER_ID:
            await interaction.response.send_message(
                "❌ This command is restricted to the bot owner.",
                ephemeral=True,
            )
            return

        queue = load_suggestions()
        target = None
        target_idx = None
        
        for i, s in enumerate(queue):
            if s["id"] == suggestion_id:
                target = s
                target_idx = i
                break

        if target is None:
            await interaction.response.send_message(
                f"❌ Suggestion #{suggestion_id} not found.",
                ephemeral=True,
            )
            return

        # Remove from queue
        queue.pop(target_idx)
        save_suggestions(queue)

        # Notify review channel
        if REVIEW_CHANNEL_ID:
            try:
                channel = self.bot.get_channel(REVIEW_CHANNEL_ID)
                if channel:
                    reject_embed = discord.Embed(
                        title="❌ Suggestion Rejected",
                        color=discord.Color.red(),
                        description=f"Suggestion #{suggestion_id} has been rejected.",
                    )
                    await channel.send(embed=reject_embed)
            except Exception as e:
                print(f"Error sending to review channel: {e}")

        await interaction.response.send_message(
            f"❌ Suggestion #{suggestion_id} rejected.",
            ephemeral=True,
        )

    # ==================== CLEAR COMMAND ====================
    @app_commands.command(name="clear")
    @app_commands.describe(suggestion_id="The suggestion ID to clear (optional, clears all if omitted)")
    async def clear(self, interaction: discord.Interaction, suggestion_id: int = None):
        """Clear suggestions (owner only)."""
        if OWNER_ID and interaction.user.id != OWNER_ID:
            await interaction.response.send_message(
                "❌ This command is restricted to the bot owner.",
                ephemeral=True,
            )
            return

        if suggestion_id is not None:
            # Clear specific suggestion
            queue = load_suggestions()
            target_idx = None
            
            for i, s in enumerate(queue):
                if s["id"] == suggestion_id:
                    target_idx = i
                    break

            if target_idx is None:
                await interaction.response.send_message(
                    f"❌ Suggestion #{suggestion_id} not found.",
                    ephemeral=True,
                )
                return

            queue.pop(target_idx)
            save_suggestions(queue)
            await interaction.response.send_message(
                f"🗑️ Suggestion #{suggestion_id} cleared.",
                ephemeral=True,
            )
        else:
            # Clear all
            save_suggestions([])
            await interaction.response.send_message(
                "🗑️ All suggestions cleared.",
                ephemeral=True,
            )


async def setup(bot):
    """Load the suggest cog."""
    await bot.add_cog(SuggestCog(bot))