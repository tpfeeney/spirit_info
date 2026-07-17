import os
import json
import discord
from discord import app_commands, ui
from discord.ext import commands
from typing import Optional, Literal

# ==================== CONFIG ====================
DATA_DIR = "./data"
SUGGESTIONS_FILE = os.path.join(DATA_DIR, "suggestions.json")

# Handle environment variables safely
review_channel_env = os.getenv("REVIEW_CHANNEL_ID", "0")
REVIEW_CHANNEL_ID = int(review_channel_env) if review_channel_env and review_channel_env.strip() else 0

owner_id_env = os.getenv("OWNER_ID", "0")
OWNER_ID = int(owner_id_env) if owner_id_env and owner_id_env.strip() else 0

# ==================== HELPER FUNCTIONS ====================
def get_categories():
    """Return list of available categories from JSON files."""
    categories = []
    for filename in ["rc_codes.json", "nbc_codes.json", "mashbills.json"]:
        filepath = os.path.join(DATA_DIR, filename)
        if os.path.exists(filepath):
            categories.append(filename.replace(".json", ""))
    return categories

def next_id():
    """Generate next suggestion ID."""
    queue = load_suggestions()
    if not queue:
        return 1
    return max(s["id"] for s in queue) + 1

def load_suggestions():
    """Load suggestions queue from file."""
    if not os.path.exists(SUGGESTIONS_FILE):
        return []
    try:
        with open(SUGGESTIONS_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return []

def save_suggestions(queue):
    """Save suggestions queue to file."""
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(SUGGESTIONS_FILE, "w") as f:
        json.dump(queue, f, indent=2)

async def notify_owner(bot_or_client, suggestion: dict, desc: str, submitter: discord.User):
    """DM the owner about a new suggestion."""
    if not OWNER_ID:
        return
    try:
        owner = await bot_or_client.fetch_user(OWNER_ID)
        embed = discord.Embed(
            title="🔔 New Suggestion Submitted",
            color=discord.Color.gold(),
            description=f"{desc}\n\n**Submitted by:** {submitter.mention} ({submitter})"
        )
        embed.set_footer(text=f"Suggestion ID: {suggestion['id']}")
        await owner.send(embed=embed)
    except discord.Forbidden:
        print("⚠️ Could not DM owner — they may have DMs disabled.")
    except Exception as e:
        print(f"Error DMing owner: {e}")

# ==================== MODAL CLASSES ====================
class NewMashbillModal(ui.Modal, title="Add New Mashbill"):
    mashbill = ui.TextInput(
        label="Mashbill",
        placeholder="e.g., 51C/25R/24MB",
        required=True,
        max_length=50
    )
    brand_name = ui.TextInput(
        label="Brand Name (Optional)",
        placeholder="Enter brand/product name",
        required=False,
        max_length=100
    )
    
    async def on_submit(self, interaction: discord.Interaction):
        # Check for duplicate
        mashbills_file = os.path.join(DATA_DIR, "mashbills.json")
        if os.path.exists(mashbills_file):
            with open(mashbills_file, "r") as f:
                existing = json.load(f)
                if self.mashbill.value in existing:
                    await interaction.response.send_message(
                        f"❌ Mashbill `{self.mashbill.value}` already exists!",
                        ephemeral=True
                    )
                    return
        
        suggestion = {
            "id": next_id(),
            "type": "new_mashbill" if not self.brand_name.value else "brand_to_new_mashbill",
            "user": str(interaction.user),
            "user_id": interaction.user.id,
            "mashbill": self.mashbill.value,
        }
        
        if self.brand_name.value:
            suggestion["brand"] = self.brand_name.value
        
        queue = load_suggestions()
        queue.append(suggestion)
        save_suggestions(queue)
        
        desc = f"**Type:** New Mashbill\n**Mashbill:** {self.mashbill.value}"
        if self.brand_name.value:
            desc += f"\n**Brand:** {self.brand_name.value}"
        
        embed = discord.Embed(
            title="📝 Suggestion Submitted",
            color=discord.Color.blue(),
            description=desc
        )
        embed.set_footer(text=f"Suggestion ID: {suggestion['id']}")
        await interaction.response.send_message(embed=embed, ephemeral=True)
        
        if REVIEW_CHANNEL_ID:
            try:
                channel = interaction.client.get_channel(REVIEW_CHANNEL_ID)
                if channel:
                    review_embed = discord.Embed(
                        title="🔔 New Suggestion",
                        color=discord.Color.gold(),
                        description=f"**ID:** {suggestion['id']}\n{desc}\n**User:** {interaction.user.mention}"
                    )
                    await channel.send(embed=review_embed)
            except Exception as e:
                print(f"Error sending to review channel: {e}")

        await notify_owner(interaction.client, suggestion, desc, interaction.user)

class NewRCCodeModal(ui.Modal, title="Add New RC Code"):
    code = ui.TextInput(
        label="Code",
        placeholder="e.g., RIO",
        required=True,
        max_length=20
    )
    rc_type = ui.TextInput(
        label="Type (Optional)",
        placeholder="e.g., Bourbon, Rye",
        required=False,
        max_length=50
    )
    mashbill = ui.TextInput(
        label="Mashbill (Optional)",
        placeholder="e.g., 75/21/4",
        required=False,
        max_length=50
    )
    source = ui.TextInput(
        label="Source (Optional)",
        placeholder="e.g., MGP, Barton",
        required=False,
        max_length=100
    )
    aging_location = ui.TextInput(
        label="Aging Location (Optional)",
        placeholder="e.g., KY, IN, TN",
        required=False,
        max_length=100
    )
    
    async def on_submit(self, interaction: discord.Interaction):
        suggestion = {
            "id": next_id(),
            "type": "new_rc_code",
            "category": "rc_codes",
            "user": str(interaction.user),
            "user_id": interaction.user.id,
            "code": self.code.value,
        }
        
        if self.rc_type.value:
            suggestion["rc_type"] = self.rc_type.value
        if self.mashbill.value:
            suggestion["mashbill"] = self.mashbill.value
        if self.source.value:
            suggestion["source"] = self.source.value
        if self.aging_location.value:
            suggestion["aging_location"] = self.aging_location.value
        
        queue = load_suggestions()
        queue.append(suggestion)
        save_suggestions(queue)
        
        desc = f"**Type:** New RC Code\n**Code:** {self.code.value}"
        if self.rc_type.value:
            desc += f"\n**Type:** {self.rc_type.value}"
        if self.mashbill.value:
            desc += f"\n**Mashbill:** {self.mashbill.value}"
        if self.source.value:
            desc += f"\n**Source:** {self.source.value}"
        if self.aging_location.value:
            desc += f"\n**Aging Location:** {self.aging_location.value}"
        
        embed = discord.Embed(
            title="📝 Suggestion Submitted",
            color=discord.Color.blue(),
            description=desc
        )
        embed.set_footer(text=f"Suggestion ID: {suggestion['id']}")
        await interaction.response.send_message(embed=embed, ephemeral=True)
        
        if REVIEW_CHANNEL_ID:
            try:
                channel = interaction.client.get_channel(REVIEW_CHANNEL_ID)
                if channel:
                    review_embed = discord.Embed(
                        title="🔔 New Suggestion",
                        color=discord.Color.gold(),
                        description=f"**ID:** {suggestion['id']}\n{desc}\n**User:** {interaction.user.mention}"
                    )
                    await channel.send(embed=review_embed)
            except Exception as e:
                print(f"Error sending to review channel: {e}")

        await notify_owner(interaction.client, suggestion, desc, interaction.user)

class NewNBCCodeModal(ui.Modal, title="Add New NBC Code"):
    code = ui.TextInput(
        label="Code",
        placeholder="e.g., 52xx format",
        required=True,
        max_length=20
    )
    source = ui.TextInput(
        label="Source (Optional)",
        placeholder="e.g., MGP, Barton",
        required=False,
        max_length=100
    )
    mashbill = ui.TextInput(
        label="Mashbill (Optional)",
        placeholder="e.g., 75/21/4",
        required=False,
        max_length=50
    )
    barrel = ui.TextInput(
        label="Barrel (Optional)",
        placeholder="e.g., Kelvin, ISC",
        required=False,
        max_length=100
    )
    note = ui.TextInput(
        label="Note (Optional)",
        placeholder="Additional notes",
        required=False,
        max_length=200,
        style=discord.TextStyle.paragraph
    )
    
    async def on_submit(self, interaction: discord.Interaction):
        suggestion = {
            "id": next_id(),
            "type": "new_nbc_code",
            "category": "nbc_codes",
            "user": str(interaction.user),
            "user_id": interaction.user.id,
            "code": self.code.value,
        }
        
        if self.source.value:
            suggestion["source"] = self.source.value
        if self.mashbill.value:
            suggestion["mashbill"] = self.mashbill.value
        if self.barrel.value:
            suggestion["barrel"] = self.barrel.value
        if self.note.value:
            suggestion["note"] = self.note.value
        
        queue = load_suggestions()
        queue.append(suggestion)
        save_suggestions(queue)
        
        desc = f"**Type:** New NBC Code\n**Code:** {self.code.value}"
        if self.source.value:
            desc += f"\n**Source:** {self.source.value}"
        if self.mashbill.value:
            desc += f"\n**Mashbill:** {self.mashbill.value}"
        if self.barrel.value:
            desc += f"\n**Barrel:** {self.barrel.value}"
        if self.note.value:
            desc += f"\n**Note:** {self.note.value}"
        
        embed = discord.Embed(
            title="📝 Suggestion Submitted",
            color=discord.Color.blue(),
            description=desc
        )
        embed.set_footer(text=f"Suggestion ID: {suggestion['id']}")
        await interaction.response.send_message(embed=embed, ephemeral=True)
        
        if REVIEW_CHANNEL_ID:
            try:
                channel = interaction.client.get_channel(REVIEW_CHANNEL_ID)
                if channel:
                    review_embed = discord.Embed(
                        title="🔔 New Suggestion",
                        color=discord.Color.gold(),
                        description=f"**ID:** {suggestion['id']}\n{desc}\n**User:** {interaction.user.mention}"
                    )
                    await channel.send(embed=review_embed)
            except Exception as e:
                print(f"Error sending to review channel: {e}")

        await notify_owner(interaction.client, suggestion, desc, interaction.user)

class UpdateRCCodeModal(ui.Modal, title="Update RC Code"):
    code = ui.TextInput(
        label="Code to Update",
        placeholder="e.g., RIO",
        required=True,
        max_length=20
    )
    field = ui.TextInput(
        label="Field to Update",
        placeholder="e.g., type, mashbill, source, aging_location",
        required=True,
        max_length=50
    )
    value = ui.TextInput(
        label="New Value",
        placeholder="Enter new value",
        required=True,
        max_length=200
    )
    
    async def on_submit(self, interaction: discord.Interaction):
        suggestion = {
            "id": next_id(),
            "type": "update_rc_code",
            "category": "rc_codes",
            "user": str(interaction.user),
            "user_id": interaction.user.id,
            "code": self.code.value,
            "field": self.field.value,
            "value": self.value.value,
        }
        
        queue = load_suggestions()
        queue.append(suggestion)
        save_suggestions(queue)
        
        embed = discord.Embed(
            title="📝 Suggestion Submitted",
            color=discord.Color.blue(),
            description=f"**Type:** Update RC Code\n**Code:** {self.code.value}\n**Field:** {self.field.value}\n**New Value:** {self.value.value}"
        )
        embed.set_footer(text=f"Suggestion ID: {suggestion['id']}")
        await interaction.response.send_message(embed=embed, ephemeral=True)
        
        if REVIEW_CHANNEL_ID:
            try:
                channel = interaction.client.get_channel(REVIEW_CHANNEL_ID)
                if channel:
                    review_embed = discord.Embed(
                        title="🔔 New Suggestion",
                        color=discord.Color.gold(),
                        description=f"**ID:** {suggestion['id']}\n**Type:** Update RC Code\n**Code:** {self.code.value}\n**Field:** {self.field.value}\n**New Value:** {self.value.value}\n**User:** {interaction.user.mention}"
                    )
                    await channel.send(embed=review_embed)
            except Exception as e:
                print(f"Error sending to review channel: {e}")

        inline_desc = f"**Type:** Update RC Code\n**Code:** {self.code.value}\n**Field:** {self.field.value}\n**New Value:** {self.value.value}"
        await notify_owner(interaction.client, suggestion, inline_desc, interaction.user)

class UpdateNBCCodeModal(ui.Modal, title="Update NBC Code"):
    code = ui.TextInput(
        label="Code to Update",
        placeholder="e.g., 52xx",
        required=True,
        max_length=20
    )
    field = ui.TextInput(
        label="Field to Update",
        placeholder="e.g., source, mashbill, barrel, note",
        required=True,
        max_length=50
    )
    value = ui.TextInput(
        label="New Value",
        placeholder="Enter new value",
        required=True,
        max_length=200
    )
    
    async def on_submit(self, interaction: discord.Interaction):
        suggestion = {
            "id": next_id(),
            "type": "update_nbc_code",
            "category": "nbc_codes",
            "user": str(interaction.user),
            "user_id": interaction.user.id,
            "code": self.code.value,
            "field": self.field.value,
            "value": self.value.value,
        }
        
        queue = load_suggestions()
        queue.append(suggestion)
        save_suggestions(queue)
        
        embed = discord.Embed(
            title="📝 Suggestion Submitted",
            color=discord.Color.blue(),
            description=f"**Type:** Update NBC Code\n**Code:** {self.code.value}\n**Field:** {self.field.value}\n**New Value:** {self.value.value}"
        )
        embed.set_footer(text=f"Suggestion ID: {suggestion['id']}")
        await interaction.response.send_message(embed=embed, ephemeral=True)
        
        if REVIEW_CHANNEL_ID:
            try:
                channel = interaction.client.get_channel(REVIEW_CHANNEL_ID)
                if channel:
                    review_embed = discord.Embed(
                        title="🔔 New Suggestion",
                        color=discord.Color.gold(),
                        description=f"**ID:** {suggestion['id']}\n**Type:** Update NBC Code\n**Code:** {self.code.value}\n**Field:** {self.field.value}\n**New Value:** {self.value.value}\n**User:** {interaction.user.mention}"
                    )
                    await channel.send(embed=review_embed)
            except Exception as e:
                print(f"Error sending to review channel: {e}")

        inline_desc = f"**Type:** Update NBC Code\n**Code:** {self.code.value}\n**Field:** {self.field.value}\n**New Value:** {self.value.value}"
        await notify_owner(interaction.client, suggestion, inline_desc, interaction.user)

class NewBangCommandModal(ui.Modal, title="Suggest a ! Command"):
    suggestion = ui.TextInput(
        label="Command Suggestion",
        placeholder="e.g., !barrelproof - look up barrel proof for a given code",
        required=True,
        max_length=1000,
        style=discord.TextStyle.paragraph
    )

    async def on_submit(self, interaction: discord.Interaction):
        suggestion_entry = {
            "id": next_id(),
            "type": "new_bang_command",
            "user": str(interaction.user),
            "user_id": interaction.user.id,
            "suggestion": self.suggestion.value,
        }

        queue = load_suggestions()
        queue.append(suggestion_entry)
        save_suggestions(queue)

        desc = f"**Type:** New ! Command\n**Suggestion:** {self.suggestion.value}"

        embed = discord.Embed(
            title="📝 Suggestion Submitted",
            color=discord.Color.blue(),
            description=desc
        )
        embed.set_footer(text=f"Suggestion ID: {suggestion_entry['id']}")
        await interaction.response.send_message(embed=embed, ephemeral=True)

        if REVIEW_CHANNEL_ID:
            try:
                channel = interaction.client.get_channel(REVIEW_CHANNEL_ID)
                if channel:
                    review_embed = discord.Embed(
                        title="🔔 New Suggestion",
                        color=discord.Color.gold(),
                        description=f"**ID:** {suggestion_entry['id']}\n{desc}\n**User:** {interaction.user.mention}"
                    )
                    await channel.send(embed=review_embed)
            except Exception as e:
                print(f"Error sending to review channel: {e}")

        await notify_owner(interaction.client, suggestion_entry, desc, interaction.user)

class BrandToMashbillWithSearchModal(ui.Modal, title="Add Brand to Mashbill"):
    mashbill = ui.TextInput(
        label="Mashbill",
        placeholder="e.g., 75C/21R/4MB",
        required=True,
        max_length=50
    )
    brand_name = ui.TextInput(
        label="Brand Name",
        placeholder="Enter brand/product name",
        required=True,
        max_length=100
    )
    
    async def on_submit(self, interaction: discord.Interaction):
        # Verify mashbill exists
        mashbills_file = os.path.join(DATA_DIR, "mashbills.json")
        if os.path.exists(mashbills_file):
            with open(mashbills_file, "r") as f:
                existing = json.load(f)
                if self.mashbill.value not in existing:
                    await interaction.response.send_message(
                        f"❌ Mashbill `{self.mashbill.value}` not found. Please check the spelling.",
                        ephemeral=True
                    )
                    return
        
        suggestion = {
            "id": next_id(),
            "type": "brand_to_mashbill",
            "user": str(interaction.user),
            "user_id": interaction.user.id,
            "mashbill": self.mashbill.value,
            "brand": self.brand_name.value,
        }
        
        queue = load_suggestions()
        queue.append(suggestion)
        save_suggestions(queue)
        
        embed = discord.Embed(
            title="📝 Suggestion Submitted",
            color=discord.Color.blue(),
            description=f"**Type:** Brand to Existing Mashbill\n**Mashbill:** {self.mashbill.value}\n**Brand:** {self.brand_name.value}"
        )
        embed.set_footer(text=f"Suggestion ID: {suggestion['id']}")
        await interaction.response.send_message(embed=embed, ephemeral=True)
        
        if REVIEW_CHANNEL_ID:
            try:
                channel = interaction.client.get_channel(REVIEW_CHANNEL_ID)
                if channel:
                    review_embed = discord.Embed(
                        title="🔔 New Suggestion",
                        color=discord.Color.gold(),
                        description=f"**ID:** {suggestion['id']}\n**Type:** Brand to Existing Mashbill\n**User:** {interaction.user.mention}\n**Mashbill:** {self.mashbill.value}\n**Brand:** {self.brand_name.value}"
                    )
                    await channel.send(embed=review_embed)
            except Exception as e:
                print(f"Error sending to review channel: {e}")

        inline_desc = f"**Type:** Brand to Existing Mashbill\n**Mashbill:** {self.mashbill.value}\n**Brand:** {self.brand_name.value}"
        await notify_owner(interaction.client, suggestion, inline_desc, interaction.user)

# ==================== COG ====================
class SuggestCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ==================== SUGGEST COMMAND ====================
    @app_commands.command(name="suggest")
    @app_commands.describe(action="What would you like to do?")
    @app_commands.choices(action=[
        app_commands.Choice(name="Brand to Existing Mashbill", value="brand_to_mashbill"),
        app_commands.Choice(name="New Mashbill", value="new_mashbill"),
        app_commands.Choice(name="New RC Code", value="new_rc_code"),
        app_commands.Choice(name="Update RC Code", value="update_rc_code"),
        app_commands.Choice(name="New NBC Code", value="new_nbc_code"),
        app_commands.Choice(name="Update NBC Code", value="update_nbc_code"),
        app_commands.Choice(name="Add ! Command", value="new_bang_command"),
    ])
    async def suggest(
        self,
        interaction: discord.Interaction,
        action: str
    ):
        """Submit a suggestion for review."""
        
        if action == "brand_to_mashbill":
            modal = BrandToMashbillWithSearchModal()
            await interaction.response.send_modal(modal)
        
        elif action == "new_mashbill":
            modal = NewMashbillModal()
            await interaction.response.send_modal(modal)
        
        elif action == "new_rc_code":
            modal = NewRCCodeModal()
            await interaction.response.send_modal(modal)
        
        elif action == "update_rc_code":
            modal = UpdateRCCodeModal()
            await interaction.response.send_modal(modal)
        
        elif action == "new_nbc_code":
            modal = NewNBCCodeModal()
            await interaction.response.send_modal(modal)
        
        elif action == "update_nbc_code":
            modal = UpdateNBCCodeModal()
            await interaction.response.send_modal(modal)

        elif action == "new_bang_command":
            modal = NewBangCommandModal()
            await interaction.response.send_modal(modal)

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
            color=discord.Color.blue(),
        )
        
        for s in queue[:10]:
            suggestion_type = s.get("type", "unknown")
            suggestion_id = s.get("id", "N/A")
            user = s.get("user", "Unknown")
            
            fields = []
            if suggestion_type == "brand_to_mashbill":
                fields.append(f"**Type:** Brand to Existing Mashbill")
                fields.append(f"**Mashbill:** {s.get('mashbill', 'N/A')}")
                fields.append(f"**Brand:** {s.get('brand', 'N/A')}")
            elif suggestion_type == "brand_to_new_mashbill":
                fields.append(f"**Type:** Brand to New Mashbill")
                fields.append(f"**Mashbill:** {s.get('mashbill', 'N/A')}")
                fields.append(f"**Brand:** {s.get('brand', 'N/A')}")
            elif suggestion_type == "new_mashbill":
                fields.append(f"**Type:** New Mashbill")
                fields.append(f"**Mashbill:** {s.get('mashbill', 'N/A')}")
            elif suggestion_type in ["new_rc_code", "update_rc_code"]:
                fields.append(f"**Type:** {'New' if suggestion_type == 'new_rc_code' else 'Update'} RC Code")
                fields.append(f"**Code:** {s.get('code', 'N/A')}")
                if suggestion_type == "update_rc_code":
                    fields.append(f"**Field:** {s.get('field', 'N/A')}")
                    fields.append(f"**Value:** {s.get('value', 'N/A')}")
            elif suggestion_type in ["new_nbc_code", "update_nbc_code"]:
                fields.append(f"**Type:** {'New' if suggestion_type == 'new_nbc_code' else 'Update'} NBC Code")
                fields.append(f"**Code:** {s.get('code', 'N/A')}")
                if suggestion_type == "update_nbc_code":
                    fields.append(f"**Field:** {s.get('field', 'N/A')}")
                    fields.append(f"**Value:** {s.get('value', 'N/A')}")
            elif suggestion_type == "new_bang_command":
                fields.append(f"**Type:** New ! Command")
                fields.append(f"**Suggestion:** {s.get('suggestion', 'N/A')}")
            
            embed.add_field(
                name=f"ID: {suggestion_id} — {user}",
                value="\n".join(fields),
                inline=False
            )
        
        if len(queue) > 10:
            embed.set_footer(text=f"Showing 10 of {len(queue)} suggestions")
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ==================== APPROVE COMMAND ====================
    @app_commands.command(name="approve")
    @app_commands.describe(suggestion_id="The ID of the suggestion to approve")
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

        suggestion_type = target.get("type", "")
        
        # Handle different suggestion types
        if suggestion_type == "brand_to_mashbill":
            # Add brand to existing mashbill
            mashbills_file = os.path.join(DATA_DIR, "mashbills.json")
            try:
                with open(mashbills_file, "r") as f:
                    data = json.load(f)
                
                mashbill = target.get("mashbill")
                brand = target.get("brand")
                
                if mashbill in data:
                    if "brands" not in data[mashbill]:
                        data[mashbill]["brands"] = []
                    if brand not in data[mashbill]["brands"]:
                        data[mashbill]["brands"].append(brand)
                    
                    with open(mashbills_file, "w") as f:
                        json.dump(data, f, indent=2)
                    
                    result_msg = f"✅ Brand '{brand}' added to mashbill '{mashbill}'."
                else:
                    result_msg = f"❌ Mashbill '{mashbill}' not found."
            except Exception as e:
                result_msg = f"❌ Error: {e}"
        
        elif suggestion_type == "brand_to_new_mashbill":
            # Create new mashbill with brand
            mashbills_file = os.path.join(DATA_DIR, "mashbills.json")
            try:
                with open(mashbills_file, "r") as f:
                    data = json.load(f)
                
                mashbill = target.get("mashbill")
                brand = target.get("brand")
                
                if mashbill not in data:
                    data[mashbill] = {
                        "name": mashbill,
                        "grains": {},
                        "raw": mashbill.lower(),
                        "brands": [brand] if brand else []
                    }
                    
                    with open(mashbills_file, "w") as f:
                        json.dump(data, f, indent=2)
                    
                    result_msg = f"✅ New mashbill '{mashbill}' created with brand '{brand}'."
                else:
                    result_msg = f"❌ Mashbill '{mashbill}' already exists."
            except Exception as e:
                result_msg = f"❌ Error: {e}"
        
        elif suggestion_type == "new_mashbill":
            # Create new mashbill without brand
            mashbills_file = os.path.join(DATA_DIR, "mashbills.json")
            try:
                with open(mashbills_file, "r") as f:
                    data = json.load(f)
                
                mashbill = target.get("mashbill")
                
                if mashbill not in data:
                    data[mashbill] = {
                        "name": mashbill,
                        "grains": {},
                        "raw": mashbill.lower(),
                        "brands": []
                    }
                    
                    with open(mashbills_file, "w") as f:
                        json.dump(data, f, indent=2)
                    
                    result_msg = f"✅ New mashbill '{mashbill}' created."
                else:
                    result_msg = f"❌ Mashbill '{mashbill}' already exists."
            except Exception as e:
                result_msg = f"❌ Error: {e}"
        
        elif suggestion_type in ["new_rc_code", "new_nbc_code"]:
            # Add new code to RC or NBC codes file
            category = target.get("category", "")
            file_path = os.path.join(DATA_DIR, f"{category}.json")
            
            try:
                with open(file_path, "r") as f:
                    data = json.load(f)
                
                code = target.get("code")
                
                if code not in data:
                    new_entry = {"name": code}
                    
                    # Add all provided fields
                    for key in ["rc_type", "type", "mashbill", "source", "aging_location", "barrel", "note", "confirmed"]:
                        if key in target and target[key]:
                            new_entry[key] = target[key]
                    
                    data[code] = new_entry
                    
                    with open(file_path, "w") as f:
                        json.dump(data, f, indent=2)
                    
                    result_msg = f"✅ New code '{code}' added to {category}."
                else:
                    result_msg = f"❌ Code '{code}' already exists in {category}."
            except Exception as e:
                result_msg = f"❌ Error: {e}"
        
        elif suggestion_type in ["update_rc_code", "update_nbc_code"]:
            # Update existing code in RC or NBC codes file
            category = target.get("category", "")
            file_path = os.path.join(DATA_DIR, f"{category}.json")
            
            try:
                with open(file_path, "r") as f:
                    data = json.load(f)
                
                code = target.get("code")
                field = target.get("field")
                value = target.get("value")
                
                if code in data:
                    data[code][field] = value
                    
                    with open(file_path, "w") as f:
                        json.dump(data, f, indent=2)
                    
                    result_msg = f"✅ Code '{code}' updated: {field} = {value}"
                else:
                    result_msg = f"❌ Code '{code}' not found in {category}."
            except Exception as e:
                result_msg = f"❌ Error: {e}"
        
        elif suggestion_type == "new_bang_command":
            # Freeform suggestion - nothing to write, just acknowledge for manual implementation
            result_msg = f"✅ Noted. Suggested command:\n> {target.get('suggestion', 'N/A')}"

        else:
            result_msg = f"❌ Unknown suggestion type: {suggestion_type}"

        # Remove from queue
        queue.pop(target_idx)
        save_suggestions(queue)

        # Notify review channel
        if REVIEW_CHANNEL_ID:
            try:
                channel = self.bot.get_channel(REVIEW_CHANNEL_ID)
                if channel:
                    approve_embed = discord.Embed(
                        title="✅ Suggestion Approved",
                        color=discord.Color.green(),
                        description=f"Suggestion #{suggestion_id} has been approved.\n\n{result_msg}"
                    )
                    await channel.send(embed=approve_embed)
            except Exception as e:
                print(f"Error sending to review channel: {e}")

        await interaction.response.send_message(
            f"✅ Suggestion #{suggestion_id} approved.\n\n{result_msg}",
            ephemeral=True,
        )

    # ==================== REJECT COMMAND ====================
    @app_commands.command(name="reject")
    @app_commands.describe(suggestion_id="The ID of the suggestion to reject")
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
                        description=f"Suggestion #{suggestion_id} has been rejected."
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
    @app_commands.describe(suggestion_id="The ID of the suggestion to clear (leave empty to clear all)")
    async def clear(self, interaction: discord.Interaction, suggestion_id: Optional[int] = None):
        """Clear suggestion(s) from queue (owner only)."""
        if OWNER_ID and interaction.user.id != OWNER_ID:
            await interaction.response.send_message(
                "❌ This command is restricted to the bot owner.",
                ephemeral=True,
            )
            return

        queue = load_suggestions()
        
        if suggestion_id is not None:
            # Clear specific suggestion
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