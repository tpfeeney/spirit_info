import os
import json
import re
from datetime import datetime

import discord
from discord import app_commands
from discord.ext import commands
from discord.ui import Select, View, Modal, TextInput


# ============ Configuration - Adjust these values ============
DATA_DIR = "data"
SUGGESTIONS_FILE = "data/suggestions.json"
REVIEW_CHANNEL_ID = None  # Set to your channel ID, e.g., 123456789012345678
OWNER_ID = None  # Set to your Discord user ID
# ============================================================

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


def load_json_data(filename):
    """Load a JSON data file."""
    filepath = os.path.join(DATA_DIR.lstrip("./"), filename)
    try:
        if os.path.exists(filepath):
            with open(filepath) as f:
                return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        pass
    return {}


def validate_mashbill_format(mashbill):
    """Validate mashbill format like 51C/25R/24MB."""
    pattern = r'^\d+[A-Z]+(/\d+[A-Z]+)*$'
    return bool(re.match(pattern, mashbill.upper()))


def validate_nbc_code_format(code):
    """Validate NBC code format like 52xx or 10xxx."""
    pattern = r'^\d+x+$|^[A-Z]\d+$'
    return bool(re.match(pattern, code.upper()))


# ==================== MODALS ====================

class NewMashbillModal(Modal, title="Suggest New Mashbill"):
    mashbill = TextInput(
        label="Mashbill (e.g., 51C/25R/24MB)",
        placeholder="Format: 51C/25R/24MB",
        required=True,
        max_length=50
    )
    brand = TextInput(
        label="Brand/Product (Optional)",
        placeholder="Brand or product name",
        required=False,
        max_length=100
    )

    def __init__(self):
        super().__init__()

    async def on_submit(self, interaction: discord.Interaction):
        mashbill_value = self.mashbill.value.strip().upper()
        
        # Validate format
        if not validate_mashbill_format(mashbill_value):
            await interaction.response.send_message(
                "❌ Invalid mashbill format. Please use format like: 51C/25R/24MB",
                ephemeral=True
            )
            return
        
        # Check if mashbill already exists
        mashbills_data = load_json_data("mashbills.json")
        if mashbill_value in mashbills_data:
            await interaction.response.send_message(
                f"⚠️ Mashbill `{mashbill_value}` already exists!\n"
                f"Use the 'Brand' option if you want to add a brand to this mashbill.",
                ephemeral=True
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
            title="📝 New Mashbill Suggestion Submitted",
            color=discord.Color.blue(),
        )
        embed.add_field(name="Mashbill", value=mashbill_value, inline=True)
        embed.add_field(name="Suggestion ID", value=f"#{suggestion['id']}", inline=True)
        if self.brand.value:
            embed.add_field(name="Brand", value=self.brand.value, inline=False)
        embed.add_field(name="Status", value="⏳ Awaiting review", inline=False)
        
        # Send to review channel
        if REVIEW_CHANNEL_ID:
            try:
                channel = interaction.client.get_channel(REVIEW_CHANNEL_ID)
                if channel:
                    await channel.send(embed=embed)
            except Exception as e:
                print(f"Error sending to review channel: {e}")
        
        await interaction.response.send_message(embed=embed, ephemeral=True)


class BrandToMashbillModal(Modal, title="Add Brand to Mashbill"):
    brand = TextInput(
        label="Brand/Product Name",
        placeholder="Enter the brand name",
        required=True,
        max_length=100
    )

    def __init__(self, mashbill):
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
            title="🥃 Brand Suggestion Submitted",
            color=discord.Color.blue(),
        )
        embed.add_field(name="Mashbill", value=self.mashbill, inline=True)
        embed.add_field(name="Brand", value=brand_value, inline=True)
        embed.add_field(name="Suggestion ID", value=f"#{suggestion['id']}", inline=True)
        embed.add_field(name="Status", value="⏳ Awaiting review", inline=False)
        
        # Send to review channel
        if REVIEW_CHANNEL_ID:
            try:
                channel = interaction.client.get_channel(REVIEW_CHANNEL_ID)
                if channel:
                    await channel.send(embed=embed)
            except Exception as e:
                print(f"Error sending to review channel: {e}")
        
        await interaction.response.send_message(embed=embed, ephemeral=True)


class NewRCCodeModal(Modal, title="Suggest New RC Code"):
    code = TextInput(
        label="RC Code (e.g., HIC, KOA)",
        placeholder="Enter the code",
        required=True,
        max_length=20
    )
    type_field = TextInput(
        label="Type (Optional)",
        placeholder="e.g., Bourbon, Rye, etc.",
        required=False,
        max_length=50
    )
    mashbill = TextInput(
        label="Mashbill (Optional)",
        placeholder="e.g., 75/21/4",
        required=False,
        max_length=50
    )
    source = TextInput(
        label="Source (Optional)",
        placeholder="e.g., MGP, Barton, etc.",
        required=False,
        max_length=100
    )
    aging_location = TextInput(
        label="Aging Location (Optional)",
        placeholder="e.g., KY, IN, etc.",
        required=False,
        max_length=100
    )

    async def on_submit(self, interaction: discord.Interaction):
        code_value = self.code.value.strip().upper()
        
        # Check if code already exists
        rc_data = load_json_data("rc_codes.json")
        if code_value in rc_data:
            await interaction.response.send_message(
                f"⚠️ RC Code `{code_value}` already exists!\n"
                f"Use the 'Update RC Code' option to modify it.",
                ephemeral=True
            )
            return
        
        # Create suggestion
        suggestion = {
            "id": next_id(),
            "type": "new_rc_code",
            "code": code_value,
            "timestamp": datetime.utcnow().isoformat(),
            "submitted_by": str(interaction.user.id),
        }
        
        if self.type_field.value:
            suggestion["rc_type"] = self.type_field.value.strip()
        if self.mashbill.value:
            suggestion["mashbill"] = self.mashbill.value.strip()
        if self.source.value:
            suggestion["source"] = self.source.value.strip()
        if self.aging_location.value:
            suggestion["aging_location"] = self.aging_location.value.strip()
        
        # Show second modal for additional fields
        await interaction.response.send_modal(NewRCCodeModal2(suggestion))


class NewRCCodeModal2(Modal, title="RC Code Details (Part 2)"):
    color = TextInput(
        label="Color (Optional)",
        placeholder="e.g., Dark Red, Gold, etc.",
        required=False,
        max_length=50
    )
    note = TextInput(
        label="Note (Optional)",
        placeholder="Additional notes",
        required=False,
        max_length=500,
        style=discord.TextStyle.paragraph
    )
    confirmed = TextInput(
        label="Confirmed? (Optional)",
        placeholder="yes or no",
        required=False,
        max_length=3
    )

    def __init__(self, suggestion_data):
        super().__init__()
        self.suggestion_data = suggestion_data

    async def on_submit(self, interaction: discord.Interaction):
        if self.color.value:
            self.suggestion_data["color"] = self.color.value.strip()
        if self.note.value:
            self.suggestion_data["note"] = self.note.value.strip()
        if self.confirmed.value:
            confirmed_value = self.confirmed.value.strip().lower()
            if confirmed_value in ['yes', 'y', 'true']:
                self.suggestion_data["confirmed"] = True
            elif confirmed_value in ['no', 'n', 'false']:
                self.suggestion_data["confirmed"] = False
        
        # Save
        queue = load_suggestions()
        queue.append(self.suggestion_data)
        save_suggestions(queue)
        
        # Create embed
        embed = discord.Embed(
            title="🔤 New RC Code Suggestion Submitted",
            color=discord.Color.blue(),
        )
        embed.add_field(name="Code", value=self.suggestion_data["code"], inline=True)
        embed.add_field(name="Suggestion ID", value=f"#{self.suggestion_data['id']}", inline=True)
        
        for key in ["rc_type", "mashbill", "source", "aging_location", "color", "note", "confirmed"]:
            if key in self.suggestion_data:
                display_key = "Type" if key == "rc_type" else key.replace("_", " ").title()
                embed.add_field(name=display_key, value=str(self.suggestion_data[key]), inline=True)
        
        embed.add_field(name="Status", value="⏳ Awaiting review", inline=False)
        
        # Send to review channel
        if REVIEW_CHANNEL_ID:
            try:
                channel = interaction.client.get_channel(REVIEW_CHANNEL_ID)
                if channel:
                    await channel.send(embed=embed)
            except Exception as e:
                print(f"Error sending to review channel: {e}")
        
        await interaction.response.send_message(embed=embed, ephemeral=True)


class UpdateRCCodeModal(Modal, title="Update RC Code"):
    code = TextInput(
        label="RC Code to Update",
        placeholder="Enter the existing code",
        required=True,
        max_length=20
    )

    async def on_submit(self, interaction: discord.Interaction):
        code_value = self.code.value.strip().upper()
        
        # Check if code exists
        rc_data = load_json_data("rc_codes.json")
        if code_value not in rc_data:
            await interaction.response.send_message(
                f"❌ RC Code `{code_value}` does not exist!\n"
                f"Use the 'New RC Code' option to create it.",
                ephemeral=True
            )
            return
        
        # Show field selection view
        view = RCFieldSelectionView(code_value, rc_data[code_value])
        await interaction.response.send_message(
            f"Select which field to update for RC Code `{code_value}`:",
            view=view,
            ephemeral=True
        )


class RCFieldSelectionView(View):
    def __init__(self, code, current_data):
        super().__init__(timeout=180)
        self.code = code
        self.current_data = current_data
        
        # Create select menu
        options = [
            discord.SelectOption(label="Type", value="type", description=f"Current: {current_data.get('type', 'Not set')}"),
            discord.SelectOption(label="Mashbill", value="mashbill", description=f"Current: {current_data.get('mashbill', 'Not set')}"),
            discord.SelectOption(label="Source", value="source", description=f"Current: {current_data.get('source', 'Not set')}"),
            discord.SelectOption(label="Aging Location", value="aging_location", description=f"Current: {current_data.get('aging_location', 'Not set')}"),
            discord.SelectOption(label="Color", value="color", description=f"Current: {current_data.get('color', 'Not set')}"),
            discord.SelectOption(label="Note", value="note", description=f"Current: {current_data.get('note', 'Not set')[:50]}"),
            discord.SelectOption(label="Confirmed", value="confirmed", description=f"Current: {current_data.get('confirmed', 'Not set')}"),
        ]
        
        select = Select(
            placeholder="Choose a field to update...",
            options=options,
            custom_id="rc_field_select"
        )
        select.callback = self.select_callback
        self.add_item(select)
    
    async def select_callback(self, interaction: discord.Interaction):
        field = interaction.data["values"][0]
        
        # Show modal for the selected field
        modal = UpdateRCFieldModal(self.code, field, self.current_data.get(field, ""))
        await interaction.response.send_modal(modal)


class UpdateRCFieldModal(Modal):
    def __init__(self, code, field, current_value):
        super().__init__(title=f"Update RC Code: {code}")
        self.code = code
        self.field = field
        
        display_name = field.replace("_", " ").title()
        
        if field == "confirmed":
            self.value_input = TextInput(
                label=display_name,
                placeholder="yes or no",
                default=str(current_value) if current_value else "",
                required=True,
                max_length=10
            )
        elif field == "note":
            self.value_input = TextInput(
                label=display_name,
                placeholder=f"New {display_name}",
                default=str(current_value) if current_value else "",
                required=True,
                max_length=500,
                style=discord.TextStyle.paragraph
            )
        else:
            self.value_input = TextInput(
                label=display_name,
                placeholder=f"New {display_name}",
                default=str(current_value) if current_value else "",
                required=True,
                max_length=100
            )
        
        self.add_item(self.value_input)

    async def on_submit(self, interaction: discord.Interaction):
        new_value = self.value_input.value.strip()
        
        # Handle confirmed field specially
        if self.field == "confirmed":
            confirmed_value = new_value.lower()
            if confirmed_value in ['yes', 'y', 'true']:
                new_value = True
            elif confirmed_value in ['no', 'n', 'false']:
                new_value = False
            else:
                await interaction.response.send_message(
                    "❌ Invalid value for confirmed. Please use 'yes' or 'no'.",
                    ephemeral=True
                )
                return
        
        # Create suggestion
        suggestion = {
            "id": next_id(),
            "type": "update_rc_code",
            "code": self.code,
            "field": self.field,
            "value": new_value,
            "timestamp": datetime.utcnow().isoformat(),
            "submitted_by": str(interaction.user.id),
        }
        
        # Save
        queue = load_suggestions()
        queue.append(suggestion)
        save_suggestions(queue)
        
        # Create embed
        embed = discord.Embed(
            title="🔤 Update RC Code Suggestion Submitted",
            color=discord.Color.blue(),
        )
        embed.add_field(name="Code", value=self.code, inline=True)
        embed.add_field(name="Field", value=self.field.replace("_", " ").title(), inline=True)
        embed.add_field(name="New Value", value=str(new_value), inline=True)
        embed.add_field(name="Suggestion ID", value=f"#{suggestion['id']}", inline=True)
        embed.add_field(name="Status", value="⏳ Awaiting review", inline=False)
        
        # Send to review channel
        if REVIEW_CHANNEL_ID:
            try:
                channel = interaction.client.get_channel(REVIEW_CHANNEL_ID)
                if channel:
                    await channel.send(embed=embed)
            except Exception as e:
                print(f"Error sending to review channel: {e}")
        
        await interaction.response.send_message(embed=embed, ephemeral=True)


class NewNBCCodeModal(Modal, title="Suggest New NBC Code"):
    code = TextInput(
        label="NBC Code (e.g., 52xx, 10xxx)",
        placeholder="Format: 52xx or similar",
        required=True,
        max_length=20
    )
    source = TextInput(
        label="Source (Optional)",
        placeholder="e.g., MGP, Barton, etc.",
        required=False,
        max_length=100
    )
    mashbill = TextInput(
        label="Mashbill (Optional)",
        placeholder="e.g., 21% rye, 36% rye",
        required=False,
        max_length=50
    )
    barrel = TextInput(
        label="Barrel (Optional)",
        placeholder="e.g., Kelvin, ISC",
        required=False,
        max_length=100
    )

    async def on_submit(self, interaction: discord.Interaction):
        code_value = self.code.value.strip()
        
        # Validate format
        if not validate_nbc_code_format(code_value):
            await interaction.response.send_message(
                "❌ Invalid NBC code format. Please use format like: 52xx or 10xxx",
                ephemeral=True
            )
            return
        
        # Check if code already exists
        nbc_data = load_json_data("nbc_codes.json")
        if code_value in nbc_data:
            await interaction.response.send_message(
                f"⚠️ NBC Code `{code_value}` already exists!\n"
                f"Use the 'Update NBC Code' option to modify it.",
                ephemeral=True
            )
            return
        
        # Create suggestion
        suggestion = {
            "id": next_id(),
            "type": "new_nbc_code",
            "code": code_value,
            "timestamp": datetime.utcnow().isoformat(),
            "submitted_by": str(interaction.user.id),
        }
        
        if self.source.value:
            suggestion["source"] = self.source.value.strip()
        if self.mashbill.value:
            suggestion["mashbill"] = self.mashbill.value.strip()
        if self.barrel.value:
            suggestion["barrel"] = self.barrel.value.strip()
        
        # Show second modal for additional fields
        await interaction.response.send_modal(NewNBCCodeModal2(suggestion))


class NewNBCCodeModal2(Modal, title="NBC Code Details (Part 2)"):
    note = TextInput(
        label="Note (Optional)",
        placeholder="Additional notes",
        required=False,
        max_length=500,
        style=discord.TextStyle.paragraph
    )
    confirmed = TextInput(
        label="Confirmed? (Optional)",
        placeholder="yes or no",
        required=False,
        max_length=3
    )

    def __init__(self, suggestion_data):
        super().__init__()
        self.suggestion_data = suggestion_data

    async def on_submit(self, interaction: discord.Interaction):
        if self.note.value:
            self.suggestion_data["note"] = self.note.value.strip()
        if self.confirmed.value:
            confirmed_value = self.confirmed.value.strip().lower()
            if confirmed_value in ['yes', 'y', 'true']:
                self.suggestion_data["confirmed"] = True
            elif confirmed_value in ['no', 'n', 'false']:
                self.suggestion_data["confirmed"] = False
        
        # Save
        queue = load_suggestions()
        queue.append(self.suggestion_data)
        save_suggestions(queue)
        
        # Create embed
        embed = discord.Embed(
            title="📦 New NBC Code Suggestion Submitted",
            color=discord.Color.blue(),
        )
        embed.add_field(name="Code", value=self.suggestion_data["code"], inline=True)
        embed.add_field(name="Suggestion ID", value=f"#{self.suggestion_data['id']}", inline=True)
        
        for key in ["source", "mashbill", "barrel", "note", "confirmed"]:
            if key in self.suggestion_data:
                display_key = key.replace("_", " ").title()
                embed.add_field(name=display_key, value=str(self.suggestion_data[key]), inline=True)
        
        embed.add_field(name="Status", value="⏳ Awaiting review", inline=False)
        
        # Send to review channel
        if REVIEW_CHANNEL_ID:
            try:
                channel = interaction.client.get_channel(REVIEW_CHANNEL_ID)
                if channel:
                    await channel.send(embed=embed)
            except Exception as e:
                print(f"Error sending to review channel: {e}")
        
        await interaction.response.send_message(embed=embed, ephemeral=True)


class UpdateNBCCodeModal(Modal, title="Update NBC Code"):
    code = TextInput(
        label="NBC Code to Update",
        placeholder="e.g., 52xx, 10xxx",
        required=True,
        max_length=20
    )

    async def on_submit(self, interaction: discord.Interaction):
        code_value = self.code.value.strip()
        
        # Check if code exists
        nbc_data = load_json_data("nbc_codes.json")
        if code_value not in nbc_data:
            await interaction.response.send_message(
                f"❌ NBC Code `{code_value}` does not exist!\n"
                f"Use the 'New NBC Code' option to create it.",
                ephemeral=True
            )
            return
        
        # Show field selection view
        view = NBCFieldSelectionView(code_value, nbc_data[code_value])
        await interaction.response.send_message(
            f"Select which field to update for NBC Code `{code_value}`:",
            view=view,
            ephemeral=True
        )


class NBCFieldSelectionView(View):
    def __init__(self, code, current_data):
        super().__init__(timeout=180)
        self.code = code
        self.current_data = current_data
        
        # Create select menu
        options = [
            discord.SelectOption(label="Source", value="source", description=f"Current: {current_data.get('source', 'Not set')[:50]}"),
            discord.SelectOption(label="Mashbill", value="mashbill", description=f"Current: {current_data.get('mashbill', 'Not set')}"),
            discord.SelectOption(label="Barrel", value="barrel", description=f"Current: {current_data.get('barrel', 'Not set')[:50]}"),
            discord.SelectOption(label="Note", value="note", description=f"Current: {current_data.get('note', 'Not set')[:50]}"),
            discord.SelectOption(label="Confirmed", value="confirmed", description=f"Current: {current_data.get('confirmed', 'Not set')}"),
        ]
        
        select = Select(
            placeholder="Choose a field to update...",
            options=options,
            custom_id="nbc_field_select"
        )
        select.callback = self.select_callback
        self.add_item(select)
    
    async def select_callback(self, interaction: discord.Interaction):
        field = interaction.data["values"][0]
        
        # Show modal for the selected field
        modal = UpdateNBCFieldModal(self.code, field, self.current_data.get(field, ""))
        await interaction.response.send_modal(modal)


class UpdateNBCFieldModal(Modal):
    def __init__(self, code, field, current_value):
        super().__init__(title=f"Update NBC Code: {code}")
        self.code = code
        self.field = field
        
        display_name = field.replace("_", " ").title()
        
        if field == "confirmed":
            self.value_input = TextInput(
                label=display_name,
                placeholder="yes or no",
                default=str(current_value) if current_value else "",
                required=True,
                max_length=10
            )
        elif field == "note":
            self.value_input = TextInput(
                label=display_name,
                placeholder=f"New {display_name}",
                default=str(current_value) if current_value else "",
                required=True,
                max_length=500,
                style=discord.TextStyle.paragraph
            )
        else:
            self.value_input = TextInput(
                label=display_name,
                placeholder=f"New {display_name}",
                default=str(current_value) if current_value else "",
                required=True,
                max_length=100
            )
        
        self.add_item(self.value_input)

    async def on_submit(self, interaction: discord.Interaction):
        new_value = self.value_input.value.strip()
        
        # Handle confirmed field specially
        if self.field == "confirmed":
            confirmed_value = new_value.lower()
            if confirmed_value in ['yes', 'y', 'true']:
                new_value = True
            elif confirmed_value in ['no', 'n', 'false']:
                new_value = False
            else:
                await interaction.response.send_message(
                    "❌ Invalid value for confirmed. Please use 'yes' or 'no'.",
                    ephemeral=True
                )
                return
        
        # Create suggestion
        suggestion = {
            "id": next_id(),
            "type": "update_nbc_code",
            "code": self.code,
            "field": self.field,
            "value": new_value,
            "timestamp": datetime.utcnow().isoformat(),
            "submitted_by": str(interaction.user.id),
        }
        
        # Save
        queue = load_suggestions()
        queue.append(suggestion)
        save_suggestions(queue)
        
        # Create embed
        embed = discord.Embed(
            title="📦 Update NBC Code Suggestion Submitted",
            color=discord.Color.blue(),
        )
        embed.add_field(name="Code", value=self.code, inline=True)
        embed.add_field(name="Field", value=self.field.replace("_", " ").title(), inline=True)
        embed.add_field(name="New Value", value=str(new_value), inline=True)
        embed.add_field(name="Suggestion ID", value=f"#{suggestion['id']}", inline=True)
        embed.add_field(name="Status", value="⏳ Awaiting review", inline=False)
        
        # Send to review channel
        if REVIEW_CHANNEL_ID:
            try:
                channel = interaction.client.get_channel(REVIEW_CHANNEL_ID)
                if channel:
                    await channel.send(embed=embed)
            except Exception as e:
                print(f"Error sending to review channel: {e}")
        
        await interaction.response.send_message(embed=embed, ephemeral=True)


# ==================== VIEWS ====================

class CategorySelectionView(View):
    def __init__(self):
        super().__init__(timeout=180)
        
        # Create select menu
        options = [
            discord.SelectOption(label="Mashbill", value="mashbill", emoji="📋", description="Suggest a new mashbill"),
            discord.SelectOption(label="Brand", value="brand", emoji="🥃", description="Add a brand to an existing mashbill"),
            discord.SelectOption(label="RC (Rare Character)", value="rc", emoji="🔤", description="Suggest or update RC code"),
            discord.SelectOption(label="NBC (Barrel Code)", value="nbc", emoji="📦", description="Suggest or update NBC code"),
        ]
        
        select = Select(
            placeholder="Choose what to suggest...",
            options=options,
            custom_id="category_select"
        )
        select.callback = self.select_callback
        self.add_item(select)
    
    async def select_callback(self, interaction: discord.Interaction):
        category = interaction.data["values"][0]
        
        if category == "mashbill":
            modal = NewMashbillModal()
            await interaction.response.send_modal(modal)
        
        elif category == "brand":
            # Show mashbill selection
            view = MashbillSelectionView()
            await interaction.response.edit_message(
                content="Select a mashbill to add a brand to:",
                view=view
            )
        
        elif category == "rc":
            # Show RC action selection
            view = RCActionView()
            await interaction.response.edit_message(
                content="What would you like to do with RC codes?",
                view=view
            )
        
        elif category == "nbc":
            # Show NBC action selection
            view = NBCActionView()
            await interaction.response.edit_message(
                content="What would you like to do with NBC codes?",
                view=view
            )


class MashbillSelectionView(View):
    def __init__(self):
        super().__init__(timeout=180)
        
        # Load mashbills
        mashbills_data = load_json_data("mashbills.json")
        mashbills = sorted(list(mashbills_data.keys()))[:25]  # Discord limit
        
        if not mashbills:
            return
        
        options = [
            discord.SelectOption(label=mb, value=mb)
            for mb in mashbills
        ]
        
        select = Select(
            placeholder="Choose a mashbill...",
            options=options,
            custom_id="mashbill_select"
        )
        select.callback = self.select_callback
        self.add_item(select)
    
    async def select_callback(self, interaction: discord.Interaction):
        mashbill = interaction.data["values"][0]
        modal = BrandToMashbillModal(mashbill)
        await interaction.response.send_modal(modal)


class RCActionView(View):
    def __init__(self):
        super().__init__(timeout=180)
        
        options = [
            discord.SelectOption(label="New RC Code", value="new", emoji="➕", description="Suggest a new RC code"),
            discord.SelectOption(label="Update RC Code", value="update", emoji="✏️", description="Update an existing RC code"),
        ]
        
        select = Select(
            placeholder="Choose an action...",
            options=options,
            custom_id="rc_action_select"
        )
        select.callback = self.select_callback
        self.add_item(select)
    
    async def select_callback(self, interaction: discord.Interaction):
        action = interaction.data["values"][0]
        
        if action == "new":
            modal = NewRCCodeModal()
            await interaction.response.send_modal(modal)
        elif action == "update":
            modal = UpdateRCCodeModal()
            await interaction.response.send_modal(modal)


class NBCActionView(View):
    def __init__(self):
        super().__init__(timeout=180)
        
        options = [
            discord.SelectOption(label="New NBC Code", value="new", emoji="➕", description="Suggest a new NBC code"),
            discord.SelectOption(label="Update NBC Code", value="update", emoji="✏️", description="Update an existing NBC code"),
        ]
        
        select = Select(
            placeholder="Choose an action...",
            options=options,
            custom_id="nbc_action_select"
        )
        select.callback = self.select_callback
        self.add_item(select)
    
    async def select_callback(self, interaction: discord.Interaction):
        action = interaction.data["values"][0]
        
        if action == "new":
            modal = NewNBCCodeModal()
            await interaction.response.send_modal(modal)
        elif action == "update":
            modal = UpdateNBCCodeModal()
            await interaction.response.send_modal(modal)


# ==================== COG ====================

class SuggestCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ==================== SUGGEST COMMAND ====================
    @app_commands.command(name="suggest")
    async def suggest(self, interaction: discord.Interaction):
        """Submit a suggestion for review."""
        view = CategorySelectionView()
        await interaction.response.send_message(
            "What would you like to suggest?",
            view=view,
            ephemeral=True
        )

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
            suggestion_type = s.get("type", "Unknown")
            
            if suggestion_type == "brand_to_mashbill":
                info = f"**#{s['id']}** [Brand] Add `{s['brand']}` to `{s['mashbill']}`"
            elif suggestion_type == "new_mashbill":
                info = f"**#{s['id']}** [Mashbill] New mashbill `{s['mashbill']}`"
                if s.get('brand'):
                    info += f" with brand `{s['brand']}`"
            elif suggestion_type == "new_rc_code":
                info = f"**#{s['id']}** [RC] New code `{s['code']}`"
            elif suggestion_type == "update_rc_code":
                info = f"**#{s['id']}** [RC] Update `{s['code']}` - {s['field']}: `{s['value']}`"
            elif suggestion_type == "new_nbc_code":
                info = f"**#{s['id']}** [NBC] New code `{s['code']}`"
            elif suggestion_type == "update_nbc_code":
                info = f"**#{s['id']}** [NBC] Update `{s['code']}` - {s['field']}: `{s['value']}`"
            else:
                info = f"**#{s['id']}** [{suggestion_type}]"
            
            lines.append(info)
        
        # Split into chunks if too long
        description = "\n".join(lines)
        if len(description) > 4000:
            description = description[:4000] + "\n... (truncated)"
        
        embed.description = description
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
        suggestion_type = target.get("type")
        
        if suggestion_type == "brand_to_mashbill":
            mashbill_file = os.path.join(DATA_DIR.lstrip("./"), "mashbills.json")
            data = load_json_data("mashbills.json")

            mashbill_key = target["mashbill"]
            if mashbill_key not in data:
                data[mashbill_key] = {"name": mashbill_key, "brands": [], "grains": {}, "raw": mashbill_key.lower()}
            if "brands" not in data[mashbill_key]:
                data[mashbill_key]["brands"] = []

            if target["brand"] not in data[mashbill_key]["brands"]:
                data[mashbill_key]["brands"].append(target["brand"])

            with open(mashbill_file, "w") as f:
                json.dump(data, f, indent=2)

        elif suggestion_type == "new_mashbill":
            mashbill_file = os.path.join(DATA_DIR.lstrip("./"), "mashbills.json")
            data = load_json_data("mashbills.json")

            mashbill_key = target["mashbill"]
            data[mashbill_key] = {
                "name": mashbill_key,
                "brands": [target["brand"]] if target.get("brand") else [],
                "grains": {},
                "raw": mashbill_key.lower()
            }

            with open(mashbill_file, "w") as f:
                json.dump(data, f, indent=2)

        elif suggestion_type == "new_rc_code":
            rc_file = os.path.join(DATA_DIR.lstrip("./"), "rc_codes.json")
            data = load_json_data("rc_codes.json")

            entry = {"name": target["code"]}
            for field in ["rc_type", "mashbill", "source", "aging_location", "color", "note", "confirmed"]:
                if field in target:
                    key = "type" if field == "rc_type" else field
                    entry[key] = target[field]

            data[target["code"]] = entry

            with open(rc_file, "w") as f:
                json.dump(data, f, indent=2)

        elif suggestion_type == "update_rc_code":
            rc_file = os.path.join(DATA_DIR.lstrip("./"), "rc_codes.json")
            data = load_json_data("rc_codes.json")

            if target["code"] in data:
                data[target["code"]][target["field"]] = target["value"]

            with open(rc_file, "w") as f:
                json.dump(data, f, indent=2)

        elif suggestion_type == "new_nbc_code":
            nbc_file = os.path.join(DATA_DIR.lstrip("./"), "nbc_codes.json")
            data = load_json_data("nbc_codes.json")

            entry = {}
            for field in ["source", "mashbill", "barrel", "note", "confirmed"]:
                if field in target:
                    entry[field] = target[field]

            data[target["code"]] = entry

            with open(nbc_file, "w") as f:
                json.dump(data, f, indent=2)

        elif suggestion_type == "update_nbc_code":
            nbc_file = os.path.join(DATA_DIR.lstrip("./"), "nbc_codes.json")
            data = load_json_data("nbc_codes.json")

            if target["code"] in data:
                data[target["code"]][target["field"]] = target["value"]

            with open(nbc_file, "w") as f:
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
    @app_commands.describe(suggestion_id="The suggestion ID to clear (leave blank to clear all)")
    async def clear(self, interaction: discord.Interaction, suggestion_id: int = None):
        """Clear suggestion(s) from the queue (owner only)."""
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