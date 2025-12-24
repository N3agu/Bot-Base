import os
import logging
import json
import discord
from discord import app_commands
from discord.ext import commands
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
    """Recursively replace placeholders in strings within dictionaries and lists."""
    if isinstance(obj, str):
        return obj.replace("{user}", member.mention).replace("{username}", member.name)
    elif isinstance(obj, list):
        return [replace_placeholders(item, member) for item in obj]
    elif isinstance(obj, dict):
        return {k: replace_placeholders(v, member) for k, v in obj.items()}
    return obj

class MyBot(commands.Bot):
    async def setup_hook(self):
        await self.tree.sync()

bot = MyBot(command_prefix='!', intents=intents)

@bot.event
async def on_ready():
    logging.info(f'Logged in as {bot.user} (ID: {bot.user.id})')
    
    config = load_config()
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
                            logging.error(f"Failed to assign role to {member}: {e}")
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
                data = replace_placeholders(raw_data, member)
                
                content = data.get('content')
                embeds = []
                if 'embeds' in data:
                    embeds = [discord.Embed.from_dict(e) for e in data['embeds']]
                elif any(k in data for k in ('title', 'description', 'fields', 'color')):
                    embeds = [discord.Embed.from_dict(data)]
                
                await channel.send(content=content, embeds=embeds[:10])
            except Exception as e:
                logging.error(f"Failed to send welcome message: {e}")

@bot.tree.command(name="embed", description="Parse JSON and post message with embeds")
@app_commands.describe(embed_json="Raw JSON string for the message payload")
async def embed_command(interaction: discord.Interaction, embed_json: str):
    try:
        data = json.loads(embed_json)
        content = data.get('content')
        embeds = []
        if 'embeds' in data:
            embeds = [discord.Embed.from_dict(e) for e in data['embeds']]
        elif any(k in data for k in ('title', 'description', 'fields', 'color')):
            embeds = [discord.Embed.from_dict(data)]

        if not content and not embeds:
            await interaction.response.send_message("JSON must contain 'content' or 'embeds'.", ephemeral=True)
            return

        await interaction.response.send_message(content=content, embeds=embeds[:10])
    except json.JSONDecodeError:
        await interaction.response.send_message("Error: Invalid JSON format.", ephemeral=True)
    except Exception as e:
        logging.error(f"Embed error: {e}")
        await interaction.response.send_message(f"Error parsing data: {e}", ephemeral=True)

@bot.tree.command(name="welcome", description="Set welcome channel, message, and optional auto-role")
@app_commands.describe(
    channel="The channel to send welcome messages in",
    embed_json="Raw JSON for the welcome message",
    role="Optional role to give to new members"
)
async def welcome_command(interaction: discord.Interaction, channel: discord.TextChannel, embed_json: str, role: discord.Role = None):
    try:
        data = json.loads(embed_json)
        if not data.get('content') and not data.get('embeds') and not data.get('title'):
             await interaction.response.send_message("Invalid JSON: Must have content or embeds.", ephemeral=True)
             return

        config = load_config()
        guild_id = str(interaction.guild_id)
        
        config[guild_id] = {
            "channel_id": channel.id,
            "embed_data": data,
            "role_id": role.id if role else None
        }
        
        save_config(config)
        
        response = f"Welcome message set to {channel.mention}."
        if role:
            response += f" Auto-role set to {role.mention}."
            
        await interaction.response.send_message(response)
        
    except json.JSONDecodeError:
        await interaction.response.send_message("Error: Invalid JSON format.", ephemeral=True)
    except Exception as e:
        logging.error(f"Welcome config error: {e}")
        await interaction.response.send_message("An error occurred saving the configuration.", ephemeral=True)

if __name__ == '__main__':
    if not TOKEN:
        logging.error("DISCORD_TOKEN not found in .env file")
    else:
        bot.run(TOKEN)