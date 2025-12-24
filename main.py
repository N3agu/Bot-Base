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
    if isinstance(obj, str):
        return obj.replace("{user}", member.mention).replace("{username}", member.name)
    elif isinstance(obj, list):
        return [replace_placeholders(item, member) for item in obj]
    elif isinstance(obj, dict):
        return {k: replace_placeholders(v, member) for k, v in obj.items()}
    return obj

def apply_theme(data, guild_id):
    """Injects primary theme color if the embed has no color set."""
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

class MyBot(commands.Bot):
    async def setup_hook(self):
        self.tree.on_error = self.on_tree_error
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
@app_commands.describe(
    primary="Hex code for primary color (e.g. #FF5733)",
    secondary="Hex code for secondary color"
)
@app_commands.checks.has_permissions(administrator=True)
async def theme_command(interaction: discord.Interaction, primary: str, secondary: str = None):
    try:
        p_int = int(primary.strip('#'), 16)
        s_int = int(secondary.strip('#'), 16) if secondary else None
        
        config = load_config()
        guild_id = str(interaction.guild_id)
        
        if guild_id not in config:
            config[guild_id] = {}
        
        config[guild_id]['theme'] = {
            'primary': p_int,
            'secondary': s_int
        }
        
        save_config(config)
        
        embed = discord.Embed(
            title="Theme Updated", 
            description=f"Primary color set to {primary}",
            color=p_int
        )
        if s_int:
            embed.add_field(name="Secondary", value=secondary)
            
        await interaction.response.send_message(embed=embed)
        
    except ValueError:
        await interaction.response.send_message("Invalid hex color format. Use format like #FF5733.", ephemeral=True)
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

if __name__ == '__main__':
    if not TOKEN:
        logging.error("DISCORD_TOKEN not found in .env file")
    else:
        bot.run(TOKEN)