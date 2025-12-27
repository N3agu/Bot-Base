import os
import logging
import json
import discord
import datetime
import traceback
from discord import app_commands
from discord.ext import commands
from discord import ui
from dotenv import load_dotenv

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("bot_errors.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)

load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
CONFIG_FILE = 'config.json'
INVITES_FILE = 'invites_data.json'

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.reactions = True
intents.invites = True

def load_json(filename):
    """Safely loads JSON, returning empty dict on failure."""
    if not os.path.exists(filename):
        return {}
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logging.error(f"Error loading {filename}: {e}. Returning empty dict.")
        return {}

def save_json(filename, data):
    """Safely saves JSON with error handling."""
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4)
    except OSError as e:
        logging.error(f"Error saving {filename}: {e}")

def replace_placeholders(obj, member):
    """Recursively replaces placeholders safely."""
    if not member: 
        return obj
    try:
        if isinstance(obj, str):
            u_mention = member.mention if hasattr(member, 'mention') else "Unknown"
            u_name = member.name if hasattr(member, 'name') else "Unknown"
            return obj.replace("{user}", u_mention).replace("{username}", u_name)
        elif isinstance(obj, list):
            return [replace_placeholders(item, member) for item in obj]
        elif isinstance(obj, dict):
            return {k: replace_placeholders(v, member) for k, v in obj.items()}
    except Exception as e:
        logging.error(f"Placeholder error: {e}")
    return obj

def apply_theme(data, guild_id):
    """Injects theme safely."""
    try:
        config = load_json(CONFIG_FILE)
        if guild_id not in config or 'theme' not in config[guild_id]:
            return data

        primary_color = config[guild_id]['theme'].get('primary')
        if not primary_color:
            return data

        def set_color(embed_dict):
            if isinstance(embed_dict, dict) and 'color' not in embed_dict:
                embed_dict['color'] = primary_color
            return embed_dict

        if 'embeds' in data and isinstance(data['embeds'], list):
            data['embeds'] = [set_color(e) for e in data['embeds']]
        elif any(k in data for k in ('title', 'description', 'fields')):
            data = set_color(data)
    except Exception as e:
        logging.error(f"Theme application error: {e}")
        
    return data

def is_staff(interaction: discord.Interaction):
    """Checks staff permissions safely."""
    if not interaction.guild:
        return False
        
    if interaction.user.guild_permissions.administrator:
        return True
    
    try:
        config = load_json(CONFIG_FILE)
        guild_id = str(interaction.guild_id)
        if guild_id in config and 'ticket_staff' in config[guild_id]:
            staff_roles = config[guild_id]['ticket_staff']
            user_role_ids = [r.id for r in interaction.user.roles]
            if any(sid in user_role_ids for sid in staff_roles):
                return True
    except Exception as e:
        logging.error(f"Staff check error: {e}")
        
    return False

def get_owner_id(channel):
    """Safely extracts owner ID."""
    if hasattr(channel, 'topic') and channel.topic and channel.topic.startswith("Ticket Owner:"):
        try:
            return int(channel.topic.split(":")[1].strip())
        except (ValueError, IndexError):
            return None
    return None

def calculate_invites(guild, inviter_id, invites_data):
    """Calculates invites without crashing on bad data."""
    guild_id = str(guild.id)
    if guild_id not in invites_data:
        return 0, 0, 0
        
    real_count = 0
    fake_count = 0
    left_count = 0
    
    try:
        inviter_records = [
            (uid, data) for uid, data in invites_data[guild_id].items()
            if data.get('inviter_id') == inviter_id
        ]
        
        for uid_str, data in inviter_records:
            if data.get('is_fake'):
                fake_count += 1
                continue
            
            try:
                mem = guild.get_member(int(uid_str))
                if mem:
                    real_count += 1
                else:
                    left_count += 1
            except ValueError:
                continue # skip malformed ids
                
    except Exception as e:
        logging.error(f"Calculation error: {e}")
            
    return real_count, fake_count, left_count

class TicketClosedView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label="Reopen", style=discord.ButtonStyle.green, custom_id="ticket_reopen", emoji="🔓")
    async def reopen(self, interaction: discord.Interaction, button: ui.Button):
        try:
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
                    try:
                        await interaction.channel.set_permissions(member, send_messages=True, read_messages=True)
                    except discord.Forbidden:
                        await interaction.followup.send("Warning: I lack permissions to modify channel settings.", ephemeral=True)

            await interaction.channel.send("Ticket reopened.", view=TicketControlsView())
            
            try:
                await interaction.message.delete()
            except discord.NotFound:
                pass
                
        except Exception as e:
            logging.error(f"Reopen error: {e}")
            await interaction.followup.send("An error occurred reopening the ticket.", ephemeral=True)

    @ui.button(label="Delete", style=discord.ButtonStyle.red, custom_id="ticket_delete", emoji="⛔")
    async def delete(self, interaction: discord.Interaction, button: ui.Button):
        try:
            if not is_staff(interaction):
                await interaction.response.send_message("Only Ticket Staff can delete tickets.", ephemeral=True)
                return

            await interaction.response.send_message("Deleting ticket in 3 seconds...", ephemeral=True)
            await interaction.channel.delete()
        except discord.Forbidden:
            await interaction.response.send_message("Error: I do not have permission to delete this channel.", ephemeral=True)
        except Exception as e:
            logging.error(f"Delete error: {e}")

class TicketControlsView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label="Close", style=discord.ButtonStyle.red, custom_id="ticket_close", emoji="🔒")
    async def close(self, interaction: discord.Interaction, button: ui.Button):
        try:
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
                    try:
                        await interaction.channel.set_permissions(member, send_messages=False, read_messages=True)
                    except discord.Forbidden:
                        pass

            await interaction.channel.send("Ticket Closed. Choose an action:", view=TicketClosedView())
        except Exception as e:
            logging.error(f"Close error: {e}")
            await interaction.followup.send("An error occurred closing the ticket.", ephemeral=True)

class TicketView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label="Open Ticket", style=discord.ButtonStyle.secondary, custom_id="create_ticket", emoji="📩")
    async def create_ticket(self, interaction: discord.Interaction, button: ui.Button):
        try:
            await interaction.response.defer(ephemeral=True)
            
            config = load_json(CONFIG_FILE)
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

            channel_name = f"ticket-{interaction.user.name}"
            
            channel_name = "".join(c for c in channel_name if c.isalnum() or c in "-_")

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
        
        except discord.Forbidden:
            await interaction.followup.send("Error: I do not have permission to create channels.", ephemeral=True)
        except discord.HTTPException as e:
             await interaction.followup.send(f"Error creating ticket (Discord Limit/Error): {e}", ephemeral=True)
        except Exception as e:
            logging.error(f"Ticket creation error: {e}")
            await interaction.followup.send("An unexpected error occurred.", ephemeral=True)

class MyBot(commands.Bot):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.invite_cache = {}

    async def setup_hook(self):
        self.tree.on_error = self.on_tree_error
        self.add_view(TicketView())
        self.add_view(TicketControlsView())
        self.add_view(TicketClosedView())
        await self.tree.sync()

    async def on_tree_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        try:
            if isinstance(error, app_commands.MissingPermissions):
                await interaction.response.send_message("You need Administrator permissions to use this command.", ephemeral=True)
            elif isinstance(error, app_commands.NoPrivateMessage):
                await interaction.response.send_message("This command cannot be used in DMs.", ephemeral=True)
            else:
                logging.error(f"Interaction error: {error}")
                if not interaction.response.is_done():
                    await interaction.response.send_message(f"An internal error occurred: {str(error)}", ephemeral=True)
        except Exception as e:
            logging.error(f"Failed to handle tree error: {e}")

    async def on_error(self, event_method, *args, **kwargs):
        logging.error(f"Error in event {event_method}: {traceback.format_exc()}")
    
    async def cache_invites(self):
        for guild in self.guilds:
            try:
                invites = await guild.invites()
                self.invite_cache[guild.id] = {invite.code: invite.uses for invite in invites}
            except discord.Forbidden:
                logging.warning(f"Missing permissions to fetch invites for {guild.name}")
                self.invite_cache[guild.id] = {}
            except Exception as e:
                logging.error(f"Error caching invites for {guild.name}: {e}")

bot = MyBot(command_prefix='!', intents=intents)

@bot.event
async def on_ready():
    logging.info(f'Logged in as {bot.user} (ID: {bot.user.id})')
    
    try:
        config = load_json(CONFIG_FILE)
        
        if 'bot_status' in config:
            status_data = config['bot_status']
            activity_type = getattr(discord.ActivityType, status_data.get('type', 'playing'), discord.ActivityType.playing)
            await bot.change_presence(activity=discord.Activity(type=activity_type, name=status_data.get('text', 'Online')))
            logging.info("Restored bot status.")
        
        await bot.cache_invites()
        
        for guild in bot.guilds:
            guild_id = str(guild.id)
            if guild_id in config and config[guild_id].get('role_id'):
                role_id = config[guild_id]['role_id']
                role = guild.get_role(role_id)
                
                if role:
                    for member in guild.members:
                        if not member.bot and role not in member.roles:
                            try:
                                await member.add_roles(role)
                            except (discord.Forbidden, discord.HTTPException):
                                continue
    except Exception as e:
        logging.error(f"Startup error: {e}")

@bot.event
async def on_invite_create(invite):
    try:
        if invite.guild.id not in bot.invite_cache:
            bot.invite_cache[invite.guild.id] = {}
        bot.invite_cache[invite.guild.id][invite.code] = invite.uses
    except Exception as e:
        logging.error(f"on_invite_create error: {e}")

@bot.event
async def on_invite_delete(invite):
    try:
        if invite.guild.id in bot.invite_cache:
            bot.invite_cache[invite.guild.id].pop(invite.code, None)
    except Exception as e:
        logging.error(f"on_invite_delete error: {e}")

@bot.event
async def on_member_join(member):
    try:
        config = load_json(CONFIG_FILE)
        invites_data = load_json(INVITES_FILE)
        guild_id = str(member.guild.id)
        
        if guild_id in config:
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

        track_channel_id = config.get(guild_id, {}).get('invite_log_channel')
        inviter = None
        
        if track_channel_id:
            try:
                current_invites = await member.guild.invites()
                cached_invites = bot.invite_cache.get(member.guild.id, {})
                
                used_invite = None
                for invite in current_invites:
                    old_uses = cached_invites.get(invite.code, 0)
                    if invite.uses > old_uses:
                        used_invite = invite
                        break
                
                bot.invite_cache[member.guild.id] = {inv.code: inv.uses for inv in current_invites}
                
                if used_invite:
                    inviter = used_invite.inviter
                    
                    now = datetime.datetime.now(datetime.timezone.utc)
                    account_age = now - member.created_at
                    is_fake = account_age.total_seconds() < 86400
                    
                    if guild_id not in invites_data:
                        invites_data[guild_id] = {}
                    
                    invites_data[guild_id][str(member.id)] = {
                        "inviter_id": inviter.id,
                        "is_fake": is_fake
                    }
                    save_json(INVITES_FILE, invites_data)
                    
                    real, fake, left = calculate_invites(member.guild, inviter.id, invites_data)

                    channel = member.guild.get_channel(track_channel_id)
                    if channel:
                        embed_data = {
                            "title": f"Welcome {member.name}",
                            "description": f"Invited by {inviter.mention}",
                            "thumbnail": {"url": member.avatar.url if member.avatar else member.default_avatar.url},
                            "fields": [
                                {"name": "Real", "value": str(real), "inline": True},
                                {"name": "Fake", "value": str(fake), "inline": True},
                                {"name": "Left", "value": str(left), "inline": True}
                            ],
                            "footer": {"text": f"Account Created: {member.created_at.strftime('%Y-%m-%d %H:%M:%S')}"}
                        }
                        embed_data = apply_theme(embed_data, guild_id)
                        await channel.send(embed=discord.Embed.from_dict(embed_data))
                        
            except discord.Forbidden:
                logging.error("Permission denied for invite tracking.")
            except Exception as e:
                logging.error(f"Invite tracking calculation error: {e}")
    except Exception as e:
        logging.error(f"on_member_join critical error: {e}")

@bot.event
async def on_member_remove(member):
    try:
        config = load_json(CONFIG_FILE)
        invites_data = load_json(INVITES_FILE)
        guild_id = str(member.guild.id)
        
        track_channel_id = config.get(guild_id, {}).get('invite_log_channel')
        
        if track_channel_id and guild_id in invites_data:
            member_id = str(member.id)
            if member_id in invites_data[guild_id]:
                record = invites_data[guild_id][member_id]
                inviter_id = record.get('inviter_id')
                
                if inviter_id:
                    real, fake, left = calculate_invites(member.guild, inviter_id, invites_data)
                    
                    inviter = member.guild.get_member(inviter_id)
                    inviter_mention = inviter.mention if inviter else "Unknown User"

                    channel = member.guild.get_channel(track_channel_id)
                    if channel:
                        embed_data = {
                            "title": f"{member.name} Left",
                            "description": f"Was invited by {inviter_mention}",
                            "thumbnail": {"url": member.avatar.url if member.avatar else member.default_avatar.url},
                            "fields": [
                                {"name": "Real", "value": str(real), "inline": True},
                                {"name": "Fake", "value": str(fake), "inline": True},
                                {"name": "Left", "value": str(left), "inline": True}
                            ]
                        }
                        embed_data = apply_theme(embed_data, guild_id)
                        await channel.send(embed=discord.Embed.from_dict(embed_data))
    except Exception as e:
        logging.error(f"on_member_remove error: {e}")

@bot.event
async def on_raw_reaction_add(payload):
    if payload.member and payload.member.bot:
        return

    try:
        config = load_json(CONFIG_FILE)
        message_id = str(payload.message_id)
        
        if 'reaction_roles' in config and message_id in config['reaction_roles']:
            role_map = config['reaction_roles'][message_id]
            emoji_key = str(payload.emoji)
            
            if emoji_key in role_map:
                role_id = role_map[emoji_key]
                guild = bot.get_guild(payload.guild_id)
                if guild:
                    role = guild.get_role(role_id)
                    if role:
                        try:
                            member = guild.get_member(payload.user_id)
                            if member:
                                await member.add_roles(role)
                        except discord.Forbidden:
                            logging.error(f"Missing permissions to add role {role.name}")
    except Exception as e:
        logging.error(f"Reaction add error: {e}")

@bot.event
async def on_raw_reaction_remove(payload):
    try:
        config = load_json(CONFIG_FILE)
        message_id = str(payload.message_id)
        
        if 'reaction_roles' in config and message_id in config['reaction_roles']:
            role_map = config['reaction_roles'][message_id]
            emoji_key = str(payload.emoji)
            
            if emoji_key in role_map:
                role_id = role_map[emoji_key]
                guild = bot.get_guild(payload.guild_id)
                if guild:
                    member = guild.get_member(payload.user_id)
                    if member and not member.bot:
                        role = guild.get_role(role_id)
                        if role:
                            try:
                                await member.remove_roles(role)
                            except discord.Forbidden:
                                logging.error(f"Missing permissions to remove role {role.name}")
    except Exception as e:
        logging.error(f"Reaction remove error: {e}")

@bot.tree.command(name="theme", description="Set default colors for server embeds")
@app_commands.describe(primary="Hex code for primary color", secondary="Hex code for secondary color")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.guild_only()
async def theme_command(interaction: discord.Interaction, primary: str, secondary: str = None):
    try:
        p_int = int(primary.strip('#'), 16)
        s_int = int(secondary.strip('#'), 16) if secondary else None
        
        config = load_json(CONFIG_FILE)
        guild_id = str(interaction.guild_id)
        
        if guild_id not in config:
            config[guild_id] = {}
        
        if 'theme' not in config[guild_id]:
             config[guild_id]['theme'] = {}

        config[guild_id]['theme'] = {'primary': p_int, 'secondary': s_int}
        save_json(CONFIG_FILE, config)
        
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
@app_commands.guild_only()
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
@app_commands.guild_only()
async def welcome_command(interaction: discord.Interaction, channel: discord.TextChannel, embed_json: str, role: discord.Role = None):
    try:
        data = json.loads(embed_json)
        if not data.get('content') and not data.get('embeds') and not data.get('title'):
             await interaction.response.send_message("Invalid JSON.", ephemeral=True)
             return

        config = load_json(CONFIG_FILE)
        guild_id = str(interaction.guild_id)
        
        if guild_id not in config:
            config[guild_id] = {}
            
        config[guild_id].update({
            "channel_id": channel.id,
            "embed_data": data,
            "role_id": role.id if role else None
        })
        
        save_json(CONFIG_FILE, config)
        await interaction.response.send_message(f"Welcome message set to {channel.mention}.")
    except json.JSONDecodeError:
        await interaction.response.send_message("Error: Invalid JSON format.", ephemeral=True)

@bot.tree.command(name="poll", description="Create a poll with options separated by |")
@app_commands.describe(question="The poll question", options="Options separated by |", use_numbers="Use numbers 1-10 instead of letters")
@app_commands.guild_only()
async def poll_command(interaction: discord.Interaction, question: str, options: str, use_numbers: bool = False):
    try:
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
    except Exception as e:
        logging.error(f"Poll error: {e}")
        if not interaction.response.is_done():
            await interaction.response.send_message("An error occurred creating the poll.", ephemeral=True)

@bot.tree.command(name="imagepoll", description="Create an image-based poll (images separated by |)")
@app_commands.describe(question="The poll question", urls="Image URLs separated by |", use_numbers="Use numbers 1-10 instead of letters")
@app_commands.guild_only()
async def imagepoll_command(interaction: discord.Interaction, question: str, urls: str, use_numbers: bool = False):
    try:
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
    except Exception as e:
        logging.error(f"Image poll error: {e}")

@bot.tree.command(name="status", description="Set the bot's activity status")
@app_commands.describe(activity="Type of activity", text="Status text")
@app_commands.choices(activity=[
    app_commands.Choice(name="Playing", value="playing"),
    app_commands.Choice(name="Watching", value="watching"),
    app_commands.Choice(name="Listening", value="listening"),
    app_commands.Choice(name="Competing", value="competing")
])
@app_commands.checks.has_permissions(administrator=True)
@app_commands.guild_only()
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
        
        config = load_json(CONFIG_FILE)
        config['bot_status'] = {'type': activity.value, 'text': text}
        save_json(CONFIG_FILE, config)
        
        await interaction.response.send_message(f"Status updated to: {activity.name} {text}", ephemeral=True)
    except Exception as e:
        logging.error(f"Status update error: {e}")
        await interaction.response.send_message("Failed to update status.", ephemeral=True)

@bot.tree.command(name="ticketpanel", description="Create a ticket panel in a specific channel")
@app_commands.describe(channel="Channel to post the panel", category_id="ID of the category for new tickets", embed_json="JSON for the panel embed", button_color="Color of the Open Ticket button")
@app_commands.choices(button_color=[
    app_commands.Choice(name="Gray (Default)", value="gray"),
    app_commands.Choice(name="Blue", value="blue"),
    app_commands.Choice(name="Green", value="green"),
    app_commands.Choice(name="Red", value="red")
])
@app_commands.checks.has_permissions(administrator=True)
@app_commands.guild_only()
async def ticketpanel_command(interaction: discord.Interaction, channel: discord.TextChannel, category_id: str, embed_json: str, button_color: app_commands.Choice[str] = None):
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

        view = TicketView()
        color_map = {
            "gray": discord.ButtonStyle.secondary,
            "blue": discord.ButtonStyle.primary,
            "green": discord.ButtonStyle.success,
            "red": discord.ButtonStyle.danger
        }
        
        target_style = discord.ButtonStyle.secondary
        if button_color:
            target_style = color_map.get(button_color.value, discord.ButtonStyle.secondary)
            
        if view.children:
            view.children[0].style = target_style

        message = await channel.send(content=content, embeds=embeds[:10], view=view)
        
        config = load_json(CONFIG_FILE)
        if 'tickets' not in config:
            config['tickets'] = {}
        
        config['tickets'][str(message.id)] = cat_id_int
        save_json(CONFIG_FILE, config)

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
@app_commands.guild_only()
async def ticketstaff_command(interaction: discord.Interaction, action: app_commands.Choice[str], role: discord.Role):
    try:
        config = load_json(CONFIG_FILE)
        guild_id = str(interaction.guild_id)
        
        if guild_id not in config:
            config[guild_id] = {}
            
        if 'ticket_staff' not in config[guild_id]:
            config[guild_id]['ticket_staff'] = []
            
        staff_list = config[guild_id]['ticket_staff']
        
        if action.value == "add":
            if role.id not in staff_list:
                staff_list.append(role.id)
                save_json(CONFIG_FILE, config)
                await interaction.response.send_message(f"Role {role.mention} added to Ticket Staff.", ephemeral=True)
            else:
                await interaction.response.send_message(f"Role {role.mention} is already Ticket Staff.", ephemeral=True)
                
        elif action.value == "remove":
            if role.id in staff_list:
                staff_list.remove(role.id)
                save_json(CONFIG_FILE, config)
                await interaction.response.send_message(f"Role {role.mention} removed from Ticket Staff.", ephemeral=True)
            else:
                await interaction.response.send_message(f"Role {role.mention} is not in Ticket Staff list.", ephemeral=True)
    except Exception as e:
        logging.error(f"Ticket staff error: {e}")
        await interaction.response.send_message("Failed to update staff config.", ephemeral=True)

@bot.tree.command(name="reactionrole", description="Create a reaction role message")
@app_commands.describe(question="The question/title for the reaction role", options="Options separated by |")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.guild_only()
async def reactionrole_command(interaction: discord.Interaction, question: str, options: str):
    await interaction.response.defer()
    try:
        option_list = [opt.strip() for opt in options.split('|') if opt.strip()]
        if len(option_list) > 20:
            await interaction.followup.send("Too many options (max 20).", ephemeral=True)
            return
            
        emojis = [chr(0x1f1e6 + i) for i in range(len(option_list))]
        
        description_lines = []
        role_map = {}
        
        for i, option_name in enumerate(option_list):
            emoji = emojis[i]
            role = discord.utils.get(interaction.guild.roles, name=option_name)
            if not role:
                try:
                    role = await interaction.guild.create_role(name=option_name, reason="Reaction Role Creation")
                except discord.Forbidden:
                    await interaction.followup.send("Error: Bot missing permissions to create roles.", ephemeral=True)
                    return
            
            role_map[emoji] = role.id
            description_lines.append(f"{emoji} : {role.mention}")
            
        embed_data = {
            "title": question,
            "description": "\n\n".join(description_lines)
        }
        embed_data = apply_theme(embed_data, str(interaction.guild_id))
        embed = discord.Embed.from_dict(embed_data)
        
        message = await interaction.channel.send(embed=embed)
        
        for emoji in emojis:
            await message.add_reaction(emoji)
            
        config = load_json(CONFIG_FILE)
        if 'reaction_roles' not in config:
            config['reaction_roles'] = {}
            
        config['reaction_roles'][str(message.id)] = role_map
        save_json(CONFIG_FILE, config)
        
        await interaction.followup.send("Reaction role created!", ephemeral=True)
    except Exception as e:
        logging.error(f"Reaction role error: {e}")
        await interaction.followup.send("An error occurred creating the reaction role.", ephemeral=True)

@bot.tree.command(name="trackinvites", description="Set channel for invite tracking logs")
@app_commands.describe(channel="Channel to post invite logs")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.guild_only()
async def trackinvites_command(interaction: discord.Interaction, channel: discord.TextChannel):
    try:
        config = load_json(CONFIG_FILE)
        guild_id = str(interaction.guild_id)
        
        if guild_id not in config:
            config[guild_id] = {}
            
        config[guild_id]['invite_log_channel'] = channel.id
        save_json(CONFIG_FILE, config)
        
        await interaction.response.send_message(f"Invite tracking logs will be posted in {channel.mention}.")
    except Exception as e:
        logging.error(f"Track invites error: {e}")
        await interaction.response.send_message("Failed to save tracking channel.", ephemeral=True)

@bot.tree.command(name="invites", description="Check invite statistics")
@app_commands.describe(user="The user to check (defaults to yourself)")
@app_commands.guild_only()
async def invites_command(interaction: discord.Interaction, user: discord.Member = None):
    try:
        if user is None:
            user = interaction.user
            
        invites_data = load_json(INVITES_FILE)
        guild_id = str(interaction.guild_id)
        
        real, fake, left = calculate_invites(interaction.guild, user.id, invites_data)

        embed_data = {
            "title": f"{user.name}'s Invites",
            "thumbnail": {"url": user.avatar.url if user.avatar else user.default_avatar.url},
            "fields": [
                {"name": "Real", "value": str(real), "inline": True},
                {"name": "Fake", "value": str(fake), "inline": True},
                {"name": "Left", "value": str(left), "inline": True}
            ],
            "footer": {"text": f"Account Created: {user.created_at.strftime('%Y-%m-%d %H:%M:%S')}"}
        }
        
        embed_data = apply_theme(embed_data, guild_id)
        await interaction.response.send_message(embed=discord.Embed.from_dict(embed_data))
    except Exception as e:
        logging.error(f"Invites check error: {e}")
        await interaction.response.send_message("An error occurred fetching invite stats.", ephemeral=True)

if __name__ == '__main__':
    if not TOKEN:
        logging.error("DISCORD_TOKEN not found in .env file")
    else:
        try:
            bot.run(TOKEN)
        except Exception as e:
            logging.critical(f"Bot execution failed: {e}")