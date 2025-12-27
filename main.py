import os
import logging
import json
import discord
from discord import app_commands
from discord.ext import commands
from discord import ui
from dotenv import load_dotenv

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
CONFIG_FILE = 'config.json'

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

def load_config():
    if not os.path.exists(CONFIG_FILE):
        return {}
    with open(CONFIG_FILE, 'r') as f:
        return json.load(f)

def save_config(data):
    with open(CONFIG_FILE, 'w') as f:
        json.dump(data, f, indent=4)

def replace_placeholders(obj, member):
    if isinstance(obj, str):
        return obj.replace("{user}", member.mention).replace("{username}", member.name)
    elif isinstance(obj, list):
        return [replace_placeholders(item, member) for item in obj]
    elif isinstance(obj, dict):
        return {k: replace_placeholders(v, member) for k, v in obj.items()}
    return obj

def apply_theme(data, guild_id):
    config = load_config()
    if guild_id not in config or 'theme' not in config[guild_id]:
        return data

    primary_color = config[guild_id]['theme'].get('primary')
    if not primary_color:
        return data

    def set_color(embed_dict):
        if 'color' not in embed_dict:
            embed_dict['color'] = primary_color
        return embed_dict

    if 'embeds' in data:
        data['embeds'] = [set_color(e) for e in data['embeds']]
    elif any(k in data for k in ('title', 'description', 'fields')):
        data = set_color(data)
        
    return data

def is_staff(interaction: discord.Interaction):
    """Checks if the user is Admin or has a Ticket Staff role."""
    if interaction.user.guild_permissions.administrator:
        return True
    
    config = load_config()
    guild_id = str(interaction.guild_id)
    if guild_id in config and 'ticket_staff' in config[guild_id]:
        staff_roles = config[guild_id]['ticket_staff']
        user_role_ids = [r.id for r in interaction.user.roles]

        if any(sid in user_role_ids for sid in staff_roles):
            return True
            
    return False

def get_owner_id(channel):
    """Extracts owner ID from channel topic."""
    if channel.topic and channel.topic.startswith("Ticket Owner:"):
        try:
            return int(channel.topic.split(":")[1].strip())
        except:
            return None
    return None

class TicketClosedView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label="Reopen", style=discord.ButtonStyle.green, custom_id="ticket_reopen", emoji="🔓")
    async def reopen(self, interaction: discord.Interaction, button: ui.Button):
        owner_id = get_owner_id(interaction.channel)
        is_owner = owner_id == interaction.user.id
        is_authorized = is_staff(interaction)

        if not (is_authorized or is_owner):
            await interaction.response.send_message("You do not have permission to reopen this ticket.", ephemeral=True)
            return

        await interaction.response.defer()

        if owner_id:
            member = interaction.guild.get_member(owner_id)
            if member:
                await interaction.channel.set_permissions(member, send_messages=True, read_messages=True)

        await interaction.channel.send("Ticket reopened.", view=TicketControlsView())
        
        try:
            await interaction.message.delete()
        except:
            pass

    @ui.button(label="Delete", style=discord.ButtonStyle.red, custom_id="ticket_delete", emoji="⛔")
    async def delete(self, interaction: discord.Interaction, button: ui.Button):
        if not is_staff(interaction):
            await interaction.response.send_message("Only Ticket Staff can delete tickets.", ephemeral=True)
            return

        await interaction.response.send_message("Deleting ticket in 3 seconds...", ephemeral=True)
        await interaction.channel.delete()

class TicketControlsView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label="Close", style=discord.ButtonStyle.red, custom_id="ticket_close", emoji="🔒")
    async def close(self, interaction: discord.Interaction, button: ui.Button):
        owner_id = get_owner_id(interaction.channel)
        is_owner = owner_id == interaction.user.id
        is_authorized = is_staff(interaction)

        if not (is_authorized or is_owner):
            await interaction.response.send_message("You do not have permission to close this ticket.", ephemeral=True)
            return

        await interaction.response.defer()

        if owner_id:
            member = interaction.guild.get_member(owner_id)
            if member:
                await interaction.channel.set_permissions(member, send_messages=False, read_messages=True)

        await interaction.channel.send("Ticket Closed. Choose an action:", view=TicketClosedView())

class TicketView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label="Open Ticket", style=discord.ButtonStyle.green, custom_id="create_ticket", emoji="📩")
    async def create_ticket(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer(ephemeral=True)
        
        config = load_config()
        message_id = str(interaction.message.id)
        guild_id = str(interaction.guild_id)
        
        tickets_config = config.get('tickets', {})
        category_id = tickets_config.get(message_id)
        
        if not category_id:
            await interaction.followup.send("Error: Ticket configuration not found for this panel.", ephemeral=True)
            return

        category = interaction.guild.get_channel(category_id)
        if not category:
            await interaction.followup.send("Error: Ticket category no longer exists.", ephemeral=True)
            return

        overrides = {
            interaction.guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }

        if guild_id in config and 'ticket_staff' in config[guild_id]:
            for role_id in config[guild_id]['ticket_staff']:
                role = interaction.guild.get_role(role_id)
                if role:
                    overrides[role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

        try:
            channel_name = f"ticket-{interaction.user.name}"
            ticket_channel = await interaction.guild.create_text_channel(
                name=channel_name, 
                category=category, 
                overwrites=overrides,
                topic=f"Ticket Owner: {interaction.user.id}"
            )
            
            await interaction.followup.send(f"Ticket created: {ticket_channel.mention}", ephemeral=True)
            
            await ticket_channel.send(
                f"{interaction.user.mention} Welcome to your ticket! Staff will answer as soon as possible.",
                view=TicketControlsView()
            )
            
        except Exception as e:
            logging.error(f"Ticket creation error: {e}")
            await interaction.followup.send("Failed to create ticket channel. Check bot permissions.", ephemeral=True)

class MyBot(commands.Bot):
    async def setup_hook(self):
        self.tree.on_error = self.on_tree_error
        self.add_view(TicketView())
        self.add_view(TicketControlsView())
        self.add_view(TicketClosedView())
        await self.tree.sync()

    async def on_tree_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("You need Administrator permissions to use this command.", ephemeral=True)
        else:
            logging.error(f"Interaction error: {error}")
            if not interaction.response.is_done():
                await interaction.response.send_message("An internal error occurred.", ephemeral=True)

bot = MyBot(command_prefix='!', intents=intents)

@bot.event
async def on_ready():
    logging.info(f'Logged in as {bot.user} (ID: {bot.user.id})')
    
    config = load_config()
    
    if 'bot_status' in config:
        status_data = config['bot_status']
        activity_type = getattr(discord.ActivityType, status_data['type'], discord.ActivityType.playing)
        await bot.change_presence(activity=discord.Activity(type=activity_type, name=status_data['text']))
        logging.info("Restored bot status.")

    for guild in bot.guilds:
        guild_id = str(guild.id)
        if guild_id in config and config[guild_id].get('role_id'):
            role_id = config[guild_id]['role_id']
            role = guild.get_role(role_id)
            
            if role:
                logging.info(f"Checking roles for {guild.name}...")
                count = 0
                for member in guild.members:
                    if not member.bot and role not in member.roles:
                        try:
                            await member.add_roles(role)
                            count += 1
                        except discord.Forbidden:
                            logging.error(f"Missing permissions to assign role in {guild.name}")
                            break
                        except Exception as e:
                            logging.error(f"Failed to assign role: {e}")
                if count > 0:
                    logging.info(f"Backfilled role to {count} members in {guild.name}")

@bot.event
async def on_member_join(member):
    config = load_config()
    guild_id = str(member.guild.id)
    
    if guild_id not in config:
        return

    settings = config[guild_id]
    
    if settings.get('role_id'):
        role = member.guild.get_role(settings['role_id'])
        if role:
            try:
                await member.add_roles(role)
            except discord.Forbidden:
                logging.error(f"Cannot assign welcome role in {member.guild.id}")

    if settings.get('channel_id') and settings.get('embed_data'):
        channel = member.guild.get_channel(settings['channel_id'])
        if channel:
            try:
                raw_data = settings['embed_data']
                data = apply_theme(raw_data, guild_id)
                data = replace_placeholders(data, member)
                
                content = data.get('content')
                embeds = []
                if 'embeds' in data:
                    embeds = [discord.Embed.from_dict(e) for e in data['embeds']]
                elif any(k in data for k in ('title', 'description', 'fields', 'color')):
                    embeds = [discord.Embed.from_dict(data)]
                
                await channel.send(content=content, embeds=embeds[:10])
            except Exception as e:
                logging.error(f"Failed to send welcome message: {e}")

@bot.tree.command(name="theme", description="Set default colors for server embeds")
@app_commands.describe(primary="Hex code for primary color", secondary="Hex code for secondary color")
@app_commands.checks.has_permissions(administrator=True)
async def theme_command(interaction: discord.Interaction, primary: str, secondary: str = None):
    try:
        p_int = int(primary.strip('#'), 16)
        s_int = int(secondary.strip('#'), 16) if secondary else None
        
        config = load_config()
        guild_id = str(interaction.guild_id)
        
        if guild_id not in config:
            config[guild_id] = {}
        
        if 'theme' not in config[guild_id]:
             config[guild_id]['theme'] = {}

        config[guild_id]['theme'] = {'primary': p_int, 'secondary': s_int}
        save_config(config)
        
        embed = discord.Embed(title="Theme Updated", description=f"Primary set to {primary}", color=p_int)
        if s_int: embed.add_field(name="Secondary", value=secondary)
        await interaction.response.send_message(embed=embed)
    except ValueError:
        await interaction.response.send_message("Invalid hex color format.", ephemeral=True)
    except Exception as e:
        logging.error(f"Theme error: {e}")
        await interaction.response.send_message("Failed to save theme.", ephemeral=True)

@bot.tree.command(name="embed", description="Parse JSON and post message with embeds")
@app_commands.describe(embed_json="Raw JSON string for the message payload")
@app_commands.checks.has_permissions(administrator=True)
async def embed_command(interaction: discord.Interaction, embed_json: str):
    try:
        data = json.loads(embed_json)
        data = apply_theme(data, str(interaction.guild_id))

        content = data.get('content')
        embeds = []
        if 'embeds' in data:
            embeds = [discord.Embed.from_dict(e) for e in data['embeds']]
        elif any(k in data for k in ('title', 'description', 'fields', 'color')):
            embeds = [discord.Embed.from_dict(data)]

        if not content and not embeds:
            await interaction.response.send_message("JSON must contain 'content' or 'embeds'.", ephemeral=True)
            return

        await interaction.response.send_message("Embed posted successfully.", ephemeral=True)
        await interaction.channel.send(content=content, embeds=embeds[:10])
    except json.JSONDecodeError:
        await interaction.response.send_message("Error: Invalid JSON format.", ephemeral=True)
    except Exception as e:
        logging.error(f"Embed error: {e}")
        await interaction.response.send_message(f"Error parsing data: {e}", ephemeral=True)

@bot.tree.command(name="welcome", description="Set welcome channel, message, and optional auto-role")
@app_commands.describe(channel="Channel", embed_json="JSON", role="Optional Role")
@app_commands.checks.has_permissions(administrator=True)
async def welcome_command(interaction: discord.Interaction, channel: discord.TextChannel, embed_json: str, role: discord.Role = None):
    try:
        data = json.loads(embed_json)
        if not data.get('content') and not data.get('embeds') and not data.get('title'):
             await interaction.response.send_message("Invalid JSON.", ephemeral=True)
             return

        config = load_config()
        guild_id = str(interaction.guild_id)
        
        if guild_id not in config:
            config[guild_id] = {}
            
        config[guild_id].update({
            "channel_id": channel.id,
            "embed_data": data,
            "role_id": role.id if role else None
        })
        
        save_config(config)
        await interaction.response.send_message(f"Welcome message set to {channel.mention}.")
    except json.JSONDecodeError:
        await interaction.response.send_message("Error: Invalid JSON format.", ephemeral=True)

@bot.tree.command(name="poll", description="Create a poll with options separated by |")
@app_commands.describe(question="The poll question", options="Options separated by |", use_numbers="Use numbers 1-10 instead of letters")
async def poll_command(interaction: discord.Interaction, question: str, options: str, use_numbers: bool = False):
    option_list = [opt.strip() for opt in options.split('|') if opt.strip()]
    
    if len(option_list) < 2:
        await interaction.response.send_message("You need at least 2 options for a poll.", ephemeral=True)
        return
    
    max_options = 10 if use_numbers else 20
    if len(option_list) > max_options:
        await interaction.response.send_message(f"Maximum options supported: {max_options}", ephemeral=True)
        return

    emojis = []
    if use_numbers:
        emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
    else:
        emojis = [chr(0x1f1e6 + i) for i in range(20)]

    description_lines = []
    for i, option in enumerate(option_list):
        description_lines.append(f"{emojis[i]} {option}")

    embed_data = {
        "title": question,
        "description": "\n\n".join(description_lines)
    }
    
    embed_data = apply_theme(embed_data, str(interaction.guild_id))
    embed = discord.Embed.from_dict(embed_data)

    await interaction.response.send_message("Poll created!", ephemeral=True)
    message = await interaction.channel.send(embed=embed)

    for i in range(len(option_list)):
        await message.add_reaction(emojis[i])

@bot.tree.command(name="imagepoll", description="Create an image-based poll (images separated by |)")
@app_commands.describe(question="The poll question", urls="Image URLs separated by |", use_numbers="Use numbers 1-10 instead of letters")
async def imagepoll_command(interaction: discord.Interaction, question: str, urls: str, use_numbers: bool = False):
    url_list = [u.strip() for u in urls.split('|') if u.strip()]
    
    if len(url_list) < 2:
        await interaction.response.send_message("You need at least 2 image URLs for a poll.", ephemeral=True)
        return
        
    max_options = 10 if use_numbers else 20
    if len(url_list) > max_options:
        await interaction.response.send_message(f"Maximum options supported: {max_options}", ephemeral=True)
        return

    emojis = []
    if use_numbers:
        emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
    else:
        emojis = [chr(0x1f1e6 + i) for i in range(20)]

    await interaction.response.send_message("Creating image poll...", ephemeral=True)

    question_data = {"title": question}
    question_data = apply_theme(question_data, str(interaction.guild_id))
    await interaction.channel.send(embed=discord.Embed.from_dict(question_data))

    for i, url in enumerate(url_list):
        embed_data = {
            "description": f"Option {emojis[i]}",
            "image": {"url": url}
        }
        embed_data = apply_theme(embed_data, str(interaction.guild_id))
        
        msg = await interaction.channel.send(embed=discord.Embed.from_dict(embed_data))
        await msg.add_reaction(emojis[i])

@bot.tree.command(name="status", description="Set the bot's activity status")
@app_commands.describe(activity="Type of activity", text="Status text")
@app_commands.choices(activity=[
    app_commands.Choice(name="Playing", value="playing"),
    app_commands.Choice(name="Watching", value="watching"),
    app_commands.Choice(name="Listening", value="listening"),
    app_commands.Choice(name="Competing", value="competing")
])
@app_commands.checks.has_permissions(administrator=True)
async def status_command(interaction: discord.Interaction, activity: app_commands.Choice[str], text: str):
    try:
        type_map = {
            "playing": discord.ActivityType.playing,
            "watching": discord.ActivityType.watching,
            "listening": discord.ActivityType.listening,
            "competing": discord.ActivityType.competing
        }
        
        act_type = type_map.get(activity.value, discord.ActivityType.playing)
        await bot.change_presence(activity=discord.Activity(type=act_type, name=text))
        
        config = load_config()
        config['bot_status'] = {'type': activity.value, 'text': text}
        save_config(config)
        
        await interaction.response.send_message(f"Status updated to: {activity.name} {text}", ephemeral=True)
    except Exception as e:
        logging.error(f"Status update error: {e}")
        await interaction.response.send_message("Failed to update status.", ephemeral=True)

@bot.tree.command(name="ticketpanel", description="Create a ticket panel in a specific channel")
@app_commands.describe(channel="Channel to post the panel", category_id="ID of the category for new tickets", embed_json="JSON for the panel embed")
@app_commands.checks.has_permissions(administrator=True)
async def ticketpanel_command(interaction: discord.Interaction, channel: discord.TextChannel, category_id: str, embed_json: str):
    try:
        try:
            cat_id_int = int(category_id)
            category = interaction.guild.get_channel(cat_id_int)
            if not category or not isinstance(category, discord.CategoryChannel):
                 await interaction.response.send_message("Invalid Category ID provided.", ephemeral=True)
                 return
        except ValueError:
            await interaction.response.send_message("Category ID must be a number.", ephemeral=True)
            return

        data = json.loads(embed_json)
        data = apply_theme(data, str(interaction.guild_id))
        
        embeds = []
        if 'embeds' in data:
            embeds = [discord.Embed.from_dict(e) for e in data['embeds']]
        elif any(k in data for k in ('title', 'description', 'fields', 'color')):
            embeds = [discord.Embed.from_dict(data)]
            
        content = data.get('content')

        if not content and not embeds:
            await interaction.response.send_message("JSON must contain 'content' or 'embeds'.", ephemeral=True)
            return

        message = await channel.send(content=content, embeds=embeds[:10], view=TicketView())
        
        config = load_config()
        if 'tickets' not in config:
            config['tickets'] = {}
        
        config['tickets'][str(message.id)] = cat_id_int
        save_config(config)

        await interaction.response.send_message(f"Ticket panel created in {channel.mention}", ephemeral=True)

    except json.JSONDecodeError:
        await interaction.response.send_message("Error: Invalid JSON format.", ephemeral=True)
    except Exception as e:
        logging.error(f"Ticket panel error: {e}")
        await interaction.response.send_message(f"Error creating panel: {e}", ephemeral=True)

@bot.tree.command(name="ticketstaff", description="Add or remove roles that can manage tickets")
@app_commands.describe(action="Add or Remove a role", role="The role to configure")
@app_commands.choices(action=[
    app_commands.Choice(name="Add", value="add"),
    app_commands.Choice(name="Remove", value="remove")
])
@app_commands.checks.has_permissions(administrator=True)
async def ticketstaff_command(interaction: discord.Interaction, action: app_commands.Choice[str], role: discord.Role):
    config = load_config()
    guild_id = str(interaction.guild_id)
    
    if guild_id not in config:
        config[guild_id] = {}
        
    if 'ticket_staff' not in config[guild_id]:
        config[guild_id]['ticket_staff'] = []
        
    staff_list = config[guild_id]['ticket_staff']
    
    if action.value == "add":
        if role.id not in staff_list:
            staff_list.append(role.id)
            save_config(config)
            await interaction.response.send_message(f"Role {role.mention} added to Ticket Staff.", ephemeral=True)
        else:
            await interaction.response.send_message(f"Role {role.mention} is already Ticket Staff.", ephemeral=True)
            
    elif action.value == "remove":
        if role.id in staff_list:
            staff_list.remove(role.id)
            save_config(config)
            await interaction.response.send_message(f"Role {role.mention} removed from Ticket Staff.", ephemeral=True)
        else:
            await interaction.response.send_message(f"Role {role.mention} is not in Ticket Staff list.", ephemeral=True)

if __name__ == '__main__':
    if not TOKEN:
        logging.error("DISCORD_TOKEN not found in .env file")
    else:
        bot.run(TOKEN)