"""
Suggestion system for adding brands, mashbills, RC codes, and NBC codes.
"""

import discord
from discord import app_commands
from discord.ext import commands
import json
import os
from datetime import datetime
from typing import Optional

# Configuration
DATA_DIR = "./data"
SUGGESTIONS_FILE = os.path.join(DATA_DIR, "suggestions.json")
OWNER_ID = None  # Set this to your Discord user ID
REVIEW_CHANNEL_ID = None  # Set this to review channel ID if you want notifications

# Ensure data directory exists
os.makedirs(DATA_DIR, exist_ok=True)


def load_suggestions():
    """Load suggestions from file."""
    if not os.path.exists(SUGGESTIONS_FILE):
        return []
    try:
        with open(SUGGESTIONS_FILE, "r") as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading suggestions: {e}")
        return []


def save_suggestions(queue):
    """Save suggestions to file."""
    try:
        with open(SUGGESTIONS_FILE, "w") as f:
            json.dump(queue, f, indent=2)
    except Exception as e:
        print(f"Error saving suggestions: {e}")


def next_id():
    """Generate next suggestion ID."""
    queue = load_suggestions()
    if not queue:
        return 1
    return max(s["id"] for s in queue) + 1


def get_mashbills():
    """Load existing mashbills."""
    mashbill_path = os.path.join(DATA_DIR, "mashbills.json")
    if not os.path.exists(mashbill_path):
        return []
    try:
        with open(mashbill_path, "r") as f:
            data = json.load(f)
            return sorted(list(data.keys()))
    except Exception:
        return []


def validate_mashbill_format(mashbill: str) -> bool:
    """Validate mashbill format like 51C/25R/24MB."""
    import re
    pattern = r"^\d+(\.\d+)?[A-Z]+(/\d+(\.\d+)?[A-Z]+)*$"
    return bool(re.match(pattern, mashbill.upper()))


# ==================== MODAL CLASSES ====================

class NewMashbillModal(discord.ui.Modal, title="New Mashbill"):
    mashbill = discord.ui.TextInput(
        label="Mashbill",
        placeholder="e.g., 51C/25R/24MB",
        required=True,
        max_length=100,
    )
    brand = discord.ui.TextInput(
        label="Brand/Product (optional)",
        placeholder="e.g., Maker's Mark",
        required=False,
        max_length=200,
    )

    async def on_submit(self, interaction: discord.Interaction):
        mashbill_value = self.mashbill.value.strip()
        
        # Validate format
        if not validate_mashbill_format(mashbill_value):
            await interaction.response.send_message(
                "❌ Invalid mashbill format. Use format like: 51C/25R/24MB",
                ephemeral=True,
            )
            return
        
        # Check if exists
        existing = get_mashbills()
        if mashbill_value.upper() in [m.upper() for m in existing]:
            await interaction.response.send_message(
                f"⚠️ Mashbill `{mashbill_value}` already exists!",
                ephemeral=True,
            )
            return
        
        # Create suggestion
        suggestion = {
            "id": next_id(),
            "type": "new_mashbill",
            "mashbill": mashbill_value,
            "timestamp": datetime.utcnow().isoformat(),
            "submitted_by": str(interaction.user.id),
        }
        
        if self.brand.value:
            suggestion["brand"] = self.brand.value.strip()
        
        # Save
        queue = load_suggestions()
        queue.append(suggestion)
        save_suggestions(queue)
        
        # Create embed
        embed = discord.Embed(
            title="✅ New Mashbill Suggestion Submitted",
            color=discord.Color.green(),
        )
        embed.add_field(name="Mashbill", value=mashbill_value, inline=False)
        if self.brand.value:
            embed.add_field(name="Brand", value=self.brand.value.strip(), inline=False)
        embed.set_footer(text=f"ID: #{suggestion['id']}")
        
        # Send to review channel
        if REVIEW_CHANNEL_ID:
            try:
                channel = interaction.client.get_channel(REVIEW_CHANNEL_ID)
                if channel:
                    await channel.send(embed=embed)
            except Exception as e:
                print(f"Error sending to review channel: {e}")
        
        await interaction.response.send_message(embed=embed, ephemeral=True)


class BrandToMashbillModal(discord.ui.Modal, title="Add Brand to Mashbill"):
    brand = discord.ui.TextInput(
        label="Brand/Product Name",
        placeholder="e.g., Maker's Mark",
        required=True,
        max_length=200,
    )

    def __init__(self, mashbill: str):
        super().__init__()
        self.mashbill = mashbill

    async def on_submit(self, interaction: discord.Interaction):
        brand_value = self.brand.value.strip()
        
        # Create suggestion
        suggestion = {
            "id": next_id(),
            "type": "brand_to_mashbill",
            "mashbill": self.mashbill,
            "brand": brand_value,
            "timestamp": datetime.utcnow().isoformat(),
            "submitted_by": str(interaction.user.id),
        }
        
        # Save
        queue = load_suggestions()
        queue.append(suggestion)
        save_suggestions(queue)
        
        # Create embed
        embed = discord.Embed(
            title="✅ Brand Suggestion Submitted",
            color=discord.Color.green(),
        )
        embed.add_field(name="Brand", value=brand_value, inline=False)
        embed.add_field(name="Mashbill", value=self.mashbill, inline=False)
        embed.set_footer(text=f"ID: #{suggestion['id']}")
        
        # Send to review channel
        if REVIEW_CHANNEL_ID:
            try:
                channel = interaction.client.get_channel(REVIEW_CHANNEL_ID)
                if channel:
                    await channel.send(embed=embed)
            except Exception as e:
                print(f"Error sending to review channel: {e}")
        
        await interaction.response.send_message(embed=embed, ephemeral=True)


class NewRCCodeModal(discord.ui.Modal, title="New RC Code - Part 1"):
    code = discord.ui.TextInput(
        label="RC Code",
        placeholder="e.g., KEL",
        required=True,
        max_length=20,
    )
    name = discord.ui.TextInput(
        label="Name",
        placeholder="e.g., Kelvin Barrel",
        required=True,
        max_length=100,
    )
    type_field = discord.ui.TextInput(
        label="Type (optional)",
        placeholder="e.g., Bourbon, Rye",
        required=False,
        max_length=50,
    )
    mashbill = discord.ui.TextInput(
        label="Mashbill (optional)",
        placeholder="e.g., 75/21/4",
        required=False,
        max_length=100,
    )

    async def on_submit(self, interaction: discord.Interaction):
        # Store data for part 2
        self.code_value = self.code.value.strip()
        self.name_value = self.name.value.strip()
        self.type_value = self.type_field.value.strip() if self.type_field.value else None
        self.mashbill_value = self.mashbill.value.strip() if self.mashbill.value else None
        
        # Show part 2
        modal2 = NewRCCodeModal2(
            self.code_value,
            self.name_value,
            self.type_value,
            self.mashbill_value,
        )
        await interaction.response.send_modal(modal2)


class NewRCCodeModal2(discord.ui.Modal, title="New RC Code - Part 2"):
    source = discord.ui.TextInput(
        label="Source (optional)",
        placeholder="e.g., MGP, Barton",
        required=False,
        max_length=100,
    )
    aging_location = discord.ui.TextInput(
        label="Aging Location (optional)",
        placeholder="e.g., KY, IN",
        required=False,
        max_length=50,
    )
    color = discord.ui.TextInput(
        label="Color (optional)",
        placeholder="e.g., Red, Blue",
        required=False,
        max_length=50,
    )
    note = discord.ui.TextInput(
        label="Note (optional)",
        placeholder="Additional information",
        required=False,
        max_length=500,
        style=discord.TextStyle.paragraph,
    )

    def __init__(self, code: str, name: str, type_val: Optional[str], mashbill: Optional[str]):
        super().__init__()
        self.code = code
        self.name = name
        self.type_val = type_val
        self.mashbill = mashbill

    async def on_submit(self, interaction: discord.Interaction):
        # Create suggestion
        suggestion = {
            "id": next_id(),
            "type": "new_rc_code",
            "code": self.code,
            "name": self.name,
            "timestamp": datetime.utcnow().isoformat(),
            "submitted_by": str(interaction.user.id),
        }
        
        # Add optional fields
        if self.type_val:
            suggestion["whiskey_type"] = self.type_val
        if self.mashbill:
            suggestion["mashbill"] = self.mashbill
        if self.source.value:
            suggestion["source"] = self.source.value.strip()
        if self.aging_location.value:
            suggestion["aging_location"] = self.aging_location.value.strip()
        if self.color.value:
            suggestion["color"] = self.color.value.strip()
        if self.note.value:
            suggestion["note"] = self.note.value.strip()
        
        # Save
        queue = load_suggestions()
        queue.append(suggestion)
        save_suggestions(queue)
        
        # Create embed
        embed = discord.Embed(
            title="✅ New RC Code Suggestion Submitted",
            color=discord.Color.green(),
        )
        embed.add_field(name="Code", value=self.code, inline=True)
        embed.add_field(name="Name", value=self.name, inline=True)
        if self.type_val:
            embed.add_field(name="Type", value=self.type_val, inline=True)
        if self.mashbill:
            embed.add_field(name="Mashbill", value=self.mashbill, inline=True)
        if self.source.value:
            embed.add_field(name="Source", value=self.source.value.strip(), inline=True)
        if self.aging_location.value:
            embed.add_field(name="Aging Location", value=self.aging_location.value.strip(), inline=True)
        if self.color.value:
            embed.add_field(name="Color", value=self.color.value.strip(), inline=True)
        if self.note.value:
            embed.add_field(name="Note", value=self.note.value.strip(), inline=False)
        embed.set_footer(text=f"ID: #{suggestion['id']}")
        
        # Send to review channel
        if REVIEW_CHANNEL_ID:
            try:
                channel = interaction.client.get_channel(REVIEW_CHANNEL_ID)
                if channel:
                    await channel.send(embed=embed)
            except Exception as e:
                print(f"Error sending to review channel: {e}")
        
        await interaction.response.send_message(embed=embed, ephemeral=True)


class UpdateRCCodeModal(discord.ui.Modal, title="Update RC Code"):
    code = discord.ui.TextInput(
        label="RC Code",
        placeholder="e.g., KEL",
        required=True,
        max_length=20,
    )

    async def on_submit(self, interaction: discord.Interaction):
        code_value = self.code.value.strip()
        
        # Show field selection
        view = RCFieldSelectionView(code_value)
        await interaction.response.send_message(
            f"Select which field to update for RC code `{code_value}`:",
            view=view,
            ephemeral=True,
        )


class UpdateRCCodeFieldModal(discord.ui.Modal, title="Update RC Code Field"):
    value = discord.ui.TextInput(
        label="New Value",
        required=True,
        max_length=500,
        style=discord.TextStyle.paragraph,
    )

    def __init__(self, code: str, field: str):
        super().__init__()
        self.code = code
        self.field = field
        self.value.label = f"New {field.replace('_', ' ').title()}"

    async def on_submit(self, interaction: discord.Interaction):
        # Create suggestion
        suggestion = {
            "id": next_id(),
            "type": "update_rc_code",
            "code": self.code,
            "field": self.field,
            "value": self.value.value.strip(),
            "timestamp": datetime.utcnow().isoformat(),
            "submitted_by": str(interaction.user.id),
        }
        
        # Save
        queue = load_suggestions()
        queue.append(suggestion)
        save_suggestions(queue)
        
        # Create embed
        embed = discord.Embed(
            title="✅ RC Code Update Suggestion Submitted",
            color=discord.Color.green(),
        )
        embed.add_field(name="Code", value=self.code, inline=True)
        embed.add_field(name="Field", value=self.field.replace("_", " ").title(), inline=True)
        embed.add_field(name="New Value", value=self.value.value.strip(), inline=False)
        embed.set_footer(text=f"ID: #{suggestion['id']}")
        
        # Send to review channel
        if REVIEW_CHANNEL_ID:
            try:
                channel = interaction.client.get_channel(REVIEW_CHANNEL_ID)
                if channel:
                    await channel.send(embed=embed)
            except Exception as e:
                print(f"Error sending to review channel: {e}")
        
        await interaction.response.send_message(embed=embed, ephemeral=True)


class NewNBCCodeModal(discord.ui.Modal, title="New NBC Code"):
    code = discord.ui.TextInput(
        label="NBC Code (format: 52xx)",
        placeholder="e.g., 5201",
        required=True,
        max_length=20,
    )
    source = discord.ui.TextInput(
        label="Source (optional)",
        placeholder="e.g., MGP, Barton",
        required=False,
        max_length=100,
    )
    mashbill = discord.ui.TextInput(
        label="Mashbill (optional)",
        placeholder="e.g., 75/21/4",
        required=False,
        max_length=100,
    )
    barrel = discord.ui.TextInput(
        label="Barrel (optional)",
        placeholder="e.g., Kelvin",
        required=False,
        max_length=100,
    )

    async def on_submit(self, interaction: discord.Interaction):
        code_value = self.code.value.strip()
        
        # Validate format
        if not code_value.lower().endswith("xx") and not code_value.lower().endswith("xxx"):
            await interaction.response.send_message(
                "⚠️ NBC codes typically end with 'xx' or 'xxx' (e.g., 52xx, 10xxx)",
                ephemeral=True,
            )
            # Continue anyway, just warn
        
        # Store for part 2
        self.code_value = code_value
        self.source_value = self.source.value.strip() if self.source.value else None
        self.mashbill_value = self.mashbill.value.strip() if self.mashbill.value else None
        self.barrel_value = self.barrel.value.strip() if self.barrel.value else None
        
        # Show part 2
        modal2 = NewNBCCodeModal2(
            self.code_value,
            self.source_value,
            self.mashbill_value,
            self.barrel_value,
        )
        await interaction.response.send_modal(modal2)


class NewNBCCodeModal2(discord.ui.Modal, title="New NBC Code - Part 2"):
    note = discord.ui.TextInput(
        label="Note (optional)",
        placeholder="Additional information",
        required=False,
        max_length=500,
        style=discord.TextStyle.paragraph,
    )
    confirmed = discord.ui.TextInput(
        label="Confirmed? (optional)",
        placeholder="yes/no or true/false",
        required=False,
        max_length=10,
    )

    def __init__(self, code: str, source: Optional[str], mashbill: Optional[str], barrel: Optional[str]):
        super().__init__()
        self.code = code
        self.source = source
        self.mashbill = mashbill
        self.barrel = barrel

    async def on_submit(self, interaction: discord.Interaction):
        # Create suggestion
        suggestion = {
            "id": next_id(),
            "type": "new_nbc_code",
            "code": self.code,
            "timestamp": datetime.utcnow().isoformat(),
            "submitted_by": str(interaction.user.id),
        }
        
        # Add optional fields
        if self.source:
            suggestion["source"] = self.source
        if self.mashbill:
            suggestion["mashbill"] = self.mashbill
        if self.barrel:
            suggestion["barrel"] = self.barrel
        if self.note.value:
            suggestion["note"] = self.note.value.strip()
        if self.confirmed.value:
            conf_val = self.confirmed.value.strip().lower()
            if conf_val in ["yes", "true", "1"]:
                suggestion["confirmed"] = True
            elif conf_val in ["no", "false", "0"]:
                suggestion["confirmed"] = False
        
        # Save
        queue = load_suggestions()
        queue.append(suggestion)
        save_suggestions(queue)
        
        # Create embed
        embed = discord.Embed(
            title="✅ New NBC Code Suggestion Submitted",
            color=discord.Color.green(),
        )
        embed.add_field(name="Code", value=self.code, inline=True)
        if self.source:
            embed.add_field(name="Source", value=self.source, inline=True)
        if self.mashbill:
            embed.add_field(name="Mashbill", value=self.mashbill, inline=True)
        if self.barrel:
            embed.add_field(name="Barrel", value=self.barrel, inline=True)
        if self.note.value:
            embed.add_field(name="Note", value=self.note.value.strip(), inline=False)
        if self.confirmed.value:
            embed.add_field(name="Confirmed", value=self.confirmed.value.strip(), inline=True)
        embed.set_footer(text=f"ID: #{suggestion['id']}")
        
        # Send to review channel
        if REVIEW_CHANNEL_ID:
            try:
                channel = interaction.client.get_channel(REVIEW_CHANNEL_ID)
                if channel:
                    await channel.send(embed=embed)
            except Exception as e:
                print(f"Error sending to review channel: {e}")
        
        await interaction.response.send_message(embed=embed, ephemeral=True)


class UpdateNBCCodeModal(discord.ui.Modal, title="Update NBC Code"):
    code = discord.ui.TextInput(
        label="NBC Code (format: 52xx)",
        placeholder="e.g., 5201",
        required=True,
        max_length=20,
    )

    async def on_submit(self, interaction: discord.Interaction):
        code_value = self.code.value.strip()
        
        # Show field selection
        view = NBCFieldSelectionView(code_value)
        await interaction.response.send_message(
            f"Select which field to update for NBC code `{code_value}`:",
            view=view,
            ephemeral=True,
        )


class UpdateNBCCodeFieldModal(discord.ui.Modal, title="Update NBC Code Field"):
    value = discord.ui.TextInput(
        label="New Value",
        required=True,
        max_length=500,
        style=discord.TextStyle.paragraph,
    )

    def __init__(self, code: str, field: str):
        super().__init__()
        self.code = code
        self.field = field
        self.value.label = f"New {field.replace('_', ' ').title()}"

    async def on_submit(self, interaction: discord.Interaction):
        # Create suggestion
        suggestion = {
            "id": next_id(),
            "type": "update_nbc_code",
            "code": self.code,
            "field": self.field,
            "value": self.value.value.strip(),
            "timestamp": datetime.utcnow().isoformat(),
            "submitted_by": str(interaction.user.id),
        }
        
        # Save
        queue = load_suggestions()
        queue.append(suggestion)
        save_suggestions(queue)
        
        # Create embed
        embed = discord.Embed(
            title="✅ NBC Code Update Suggestion Submitted",
            color=discord.Color.green(),
        )
        embed.add_field(name="Code", value=self.code, inline=True)
        embed.add_field(name="Field", value=self.field.replace("_", " ").title(), inline=True)
        embed.add_field(name="New Value", value=self.value.value.strip(), inline=False)
        embed.set_footer(text=f"ID: #{suggestion['id']}")
        
        # Send to review channel
        if REVIEW_CHANNEL_ID:
            try:
                channel = interaction.client.get_channel(REVIEW_CHANNEL_ID)
                if channel:
                    await channel.send(embed=embed)
            except Exception as e:
                print(f"Error sending to review channel: {e}")
        
        await interaction.response.send_message(embed=embed, ephemeral=True)


# ==================== VIEW CLASSES ====================

class CategorySelectionView(discord.ui.View):
    """Main selection menu for suggestion type."""
    
    @discord.ui.select(
        placeholder="Choose what to suggest...",
        options=[
            discord.SelectOption(label="New Mashbill", value="new_mashbill", emoji="📝"),
            discord.SelectOption(label="Brand to Existing Mashbill", value="brand_to_mashbill", emoji="🏷️"),
            discord.SelectOption(label="New RC Code", value="new_rc_code", emoji="🆕"),
            discord.SelectOption(label="Update RC Code", value="update_rc_code", emoji="✏️"),
            discord.SelectOption(label="New NBC Code", value="new_nbc_code", emoji="🆕"),
            discord.SelectOption(label="Update NBC Code", value="update_nbc_code", emoji="✏️"),
        ],
    )
    async def select_callback(self, interaction: discord.Interaction, select: discord.ui.Select):
        selection = select.values[0]
        
        if selection == "new_mashbill":
            modal = NewMashbillModal()
            await interaction.response.send_modal(modal)
        
        elif selection == "brand_to_mashbill":
            mashbills = get_mashbills()
            if not mashbills:
                await interaction.response.send_message(
                    "❌ No mashbills found. Please add a mashbill first.",
                    ephemeral=True,
                )
                return
            view = MashbillSelectionView(mashbills)
            await interaction.response.send_message(
                "Select a mashbill:",
                view=view,
                ephemeral=True,
            )
        
        elif selection == "new_rc_code":
            modal = NewRCCodeModal()
            await interaction.response.send_modal(modal)
        
        elif selection == "update_rc_code":
            modal = UpdateRCCodeModal()
            await interaction.response.send_modal(modal)
        
        elif selection == "new_nbc_code":
            modal = NewNBCCodeModal()
            await interaction.response.send_modal(modal)
        
        elif selection == "update_nbc_code":
            modal = UpdateNBCCodeModal()
            await interaction.response.send_modal(modal)


class MashbillSelectionView(discord.ui.View):
    """Select existing mashbill for brand addition."""
    
    def __init__(self, mashbills: list):
        super().__init__()
        
        # Split into chunks of 25 for select menu limit
        for i in range(0, len(mashbills), 25):
            chunk = mashbills[i:i+25]
            options = [discord.SelectOption(label=mb, value=mb) for mb in chunk]
            select = discord.ui.Select(
                placeholder=f"Select mashbill ({i+1}-{i+len(chunk)})...",
                options=options,
            )
            select.callback = self.make_callback()
            self.add_item(select)
    
    def make_callback(self):
        async def callback(interaction: discord.Interaction):
            mashbill = interaction.data["values"][0]
            modal = BrandToMashbillModal(mashbill)
            await interaction.response.send_modal(modal)
        return callback


class RCFieldSelectionView(discord.ui.View):
    """Select which field to update for RC code."""
    
    def __init__(self, code: str):
        super().__init__()
        self.code = code
    
    @discord.ui.select(
        placeholder="Choose field to update...",
        options=[
            discord.SelectOption(label="Name", value="name"),
            discord.SelectOption(label="Type", value="type"),
            discord.SelectOption(label="Mashbill", value="mashbill"),
            discord.SelectOption(label="Source", value="source"),
            discord.SelectOption(label="Aging Location", value="aging_location"),
            discord.SelectOption(label="Color", value="color"),
            discord.SelectOption(label="Note", value="note"),
            discord.SelectOption(label="Confirmed", value="confirmed"),
        ],
    )
    async def select_callback(self, interaction: discord.Interaction, select: discord.ui.Select):
        field = select.values[0]
        modal = UpdateRCCodeFieldModal(self.code, field)
        await interaction.response.send_modal(modal)


class NBCFieldSelectionView(discord.ui.View):
    """Select which field to update for NBC code."""
    
    def __init__(self, code: str):
        super().__init__()
        self.code = code
    
    @discord.ui.select(
        placeholder="Choose field to update...",
        options=[
            discord.SelectOption(label="Source", value="source"),
            discord.SelectOption(label="Mashbill", value="mashbill"),
            discord.SelectOption(label="Barrel", value="barrel"),
            discord.SelectOption(label="Note", value="note"),
            discord.SelectOption(label="Confirmed", value="confirmed"),
        ],
    )
    async def select_callback(self, interaction: discord.Interaction, select: discord.ui.Select):
        field = select.values[0]
        modal = UpdateNBCCodeFieldModal(self.code, field)
        await interaction.response.send_modal(modal)


# ==================== COG CLASS ====================

class SuggestionCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="suggest")
    async def suggest(self, interaction: discord.Interaction):
        """Submit a suggestion for mashbills, brands, RC codes, or NBC codes."""
        view = CategorySelectionView()
        await interaction.response.send_message(
            "What would you like to suggest?",
            view=view,
            ephemeral=True,
        )

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
            suggestion_type = s.get("type", "Unknown")
            
            if suggestion_type == "new_mashbill":
                info = f"New mashbill: `{s['mashbill']}`"
                if s.get("brand"):
                    info += f" (with brand: {s['brand']})"
            
            elif suggestion_type == "brand_to_mashbill":
                info = f"Add `{s['brand']}` to `{s['mashbill']}`"
            
            elif suggestion_type == "new_rc_code":
                info = f"New RC: **{s['code']}** - {s['name']}"
                if s.get("source"):
                    info += f" | {s['source']}"
            
            elif suggestion_type == "update_rc_code":
                info = f"Update RC **{s['code']}**: {s['field']} = {s['value']}"
            
            elif suggestion_type == "new_nbc_code":
                info = f"New NBC: **{s['code']}**"
                if s.get("source"):
                    info += f" | {s['source']}"
            
            elif suggestion_type == "update_nbc_code":
                info = f"Update NBC **{s['code']}**: {s['field']} = {s['value']}"
            
            else:
                info = f"Unknown type: {suggestion_type}"
            
            lines.append(f"**#{s['id']}** [{suggestion_type}] {info}")

        embed.description = "\n".join(lines)
        embed.set_footer(text=f"Total: {len(queue)} suggestion(s)")
        await interaction.response.send_message(embed=embed, ephemeral=True)

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

        suggestion_type = target.get("type", "Unknown")
        
        # Process based on type
        if suggestion_type in ["new_mashbill", "brand_to_mashbill", "new_rc_code", "update_rc_code", "new_nbc_code", "update_nbc_code"]:
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
                            description=f"Suggestion #{suggestion_id} ({suggestion_type}) has been approved.",
                        )
                        await channel.send(embed=approve_embed)
                except Exception as e:
                    print(f"Error sending to review channel: {e}")
            
            await interaction.response.send_message(
                f"✅ Suggestion #{suggestion_id} approved. Please manually add to data files.",
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                f"❌ Unknown suggestion type: {suggestion_type}",
                ephemeral=True,
            )

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

    @app_commands.command(name="clear_suggestions")
    async def clear_suggestions(self, interaction: discord.Interaction):
        """Clear all pending suggestions (owner only)."""
        if OWNER_ID and interaction.user.id != OWNER_ID:
            await interaction.response.send_message(
                "❌ This command is restricted to the bot owner.",
                ephemeral=True,
            )
            return

        save_suggestions([])
        await interaction.response.send_message(
            "✅ All suggestions cleared.",
            ephemeral=True,
        )


async def setup(bot):
    await bot.add_cog(SuggestionCog(bot))