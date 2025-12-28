<div align=center>
  <h1>Bot Base</h1>
<img src="https://raw.githubusercontent.com/N3agu/Bot-Base/refs/heads/main/Images/logo.png" width="220">
</div>

## Summary
A robust, feature-rich Discord bot base built with `discord.py`. This includes advanced systems for ticketing, invite tracking, polling, reaction roles, and server management, all configurable via Slash Commands.

## Features

* **Ticket System**: Persistent ticket panels with Open/Close/Reopen/Delete workflows. Supports staff role configuration and chat locking.
* **Invite Tracking**: Tracks real, fake (accounts <24h old), and left invites. Logs joins and leaves with statistics.
* **Advanced Polls**:
    * **Text Polls**: Standard polls with dynamic emoji reactions.
    * **Image Polls**: Visual polls displaying images from URLs with voting buttons.
* **Welcome System**: customizable welcome messages (JSON embed support) and auto-role assignment.
* **Reaction Roles**: Auto-creates roles and assigns them via emoji reactions.
* **Theming**: Set a server-wide primary color that automatically applies to all bot embeds.
* **Embed Builder**: Parse raw JSON to send complex embeds via command.
* **Fail-Safe Architecture**: Robust error handling, logging to file, and persistent configuration.

## Setup & Installation

1.  **Clone the repository**:
    ```bash
    git clone https://github.com/N3agu/Bot-Base.git
    cd Bot-Base
    ```

2.  **Install Dependencies**:
    ```bash
    pip install discord.py python-dotenv
    ```

3.  **Configure Environment**:
    Create a file named `.env` in the root directory and add your bot token:
    ```text
    DISCORD_TOKEN=your_bot_token_here
    ```

4.  **Run the Bot**:
    ```bash
    python main.py
    ```
    *Note: `config.json` and `invites_data.json` will be created automatically upon the first run/command usage.*

## Commands

### Administrator Commands
*These commands require the `Administrator` permission.*

| Command | Parameters | Description |
| :--- | :--- | :--- |
| `/ticketpanel` | `channel`, `category_id`, `embed_json`, `[button_color]` | Creates a persistent ticket panel. `category_id` is where new tickets open. |
| `/ticketstaff` | `action`, `role` | Add/Remove roles that can manage tickets (view, close, delete). |
| `/trackinvites`| `channel` | Sets the channel where Join/Leave logs (with invite stats) are posted. |
| `/welcome` | `channel`, `embed_json`, `[role]` | Sets the welcome channel, message, and optional auto-role for new members. |
| `/reactionrole`| `question`, `options` | Creates a reaction role message. Options separated by `\|` (e.g., `Red\|Blue`). |
| `/embed` | `embed_json` | Posts a custom embed message parsed from JSON. |
| `/theme` | `primary`, `[secondary]` | Sets the default hex color (e.g., `#FF5733`) for bot embeds. |
| `/status` | `activity`, `text` | Sets the bot's presence (e.g., "Playing Minecraft"). |

### Public Commands
*These commands can be used by anyone.*

| Command | Parameters | Description |
| :--- | :--- | :--- |
| `/poll` | `question`, `options`, `[use_numbers]` | Creates a standard poll. Options separated by `\|`. |
| `/imagepoll` | `question`, `urls`, `[use_numbers]` | Creates a poll with images. URLs separated by `\|`. |
| `/invites` | `[user]` | Checks a user's invite statistics (Real, Fake, Left). |

## JSON Embeds

Commands like `/embed`, `/welcome`, and `/ticketpanel` accept a **JSON string**. You can generate these using online tools like [DiscoHook](https://discohook.com/) / [MessageStyle](https://message.style/app/editor), or you can write them manually.

**Supported Placeholders:**
* `{user}` -> Mentions the user (e.g., @N3agu).
* `{username}` -> Displays the username (e.g., N3agu).

**Example JSON Payload:**
```json
{
  "title": "Welcome to the Server!",
  "description": "Hello {user}, please read the rules.",
  "color": 3447003,
  "fields": [
    {
      "name": "Get Started",
      "value": "Check out #general"
    }
  ]
}
```

## Configuration Files
- `config.json`: Stores server settings, ticket configs, roles, and themes. Do not edit manually unless necessary; the bot handles this.
- `invites_data.json`: Stores the history of who invited whom. Used to calculate "Left" and "Fake" statistics accurately.
- `bot_errors.log`: If the bot encounters an issue, details are logged here instead of crashing the console.
