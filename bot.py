import os
import threading
import asyncio
from datetime import datetime, timedelta
import json

import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv

from flask import Flask

from PIL import Image, ImageDraw, ImageFont
import requests
from io import BytesIO


# =============== FLASK WEB SERVER (FOR RENDER) ===============

app = Flask(__name__)

@app.route("/")
def home():
    return "Bot is running!"


def run_flask():
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)


# =============== DISCORD BOT SETUP ===============

load_dotenv()
TOKEN = os.getenv("TOKEN")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)


# =============== EVENT STORAGE ===============

EVENTS_FILE = "events.json"

def load_events():
    """Load events from JSON file"""
    if os.path.exists(EVENTS_FILE):
        with open(EVENTS_FILE, "r") as f:
            return json.load(f)
    return []

def save_events(events):
    """Save events to JSON file"""
    with open(EVENTS_FILE, "w") as f:
        json.dump(events, f, indent=2)

events = load_events()


# =============== EVENT CHECKER TASK ===============

@tasks.loop(minutes=1)
async def check_events():
    """Check every minute if any events need to be triggered"""
    global events
    now = datetime.now()
    
    for event in events[:]:  # Copy list to avoid modification issues
        event_time = datetime.fromisoformat(event["time"])
        reminder_time = event_time - timedelta(minutes=10)
        
        # Check if it's time for the 10-minute reminder
        if not event.get("reminder_sent", False) and now >= reminder_time and now < event_time:
            channel = bot.get_channel(event["channel_id"])
            if channel:
                mention = event["mention"]
                await channel.send(f"⏰ **Reminder:** {mention} - Event '{event['name']}' starts in 10 minutes!")
                event["reminder_sent"] = True
                save_events(events)
        
        # Check if it's time for the actual event
        if now >= event_time and not event.get("event_triggered", False):
            channel = bot.get_channel(event["channel_id"])
            if channel:
                mention = event["mention"]
                await channel.send(f"🔔 **EVENT NOW:** {mention} - '{event['name']}' is starting!")
                event["event_triggered"] = True
                
                # Handle repeating events
                if event.get("repeat_days"):
                    # Schedule next occurrence
                    next_time = event_time + timedelta(days=event["repeat_days"])
                    new_event = event.copy()
                    new_event["time"] = next_time.isoformat()
                    new_event["reminder_sent"] = False
                    new_event["event_triggered"] = False
                    events.append(new_event)
                    await channel.send(f"📅 Next occurrence scheduled for: {next_time.strftime('%Y-%m-%d %H:%M')}")
                
                save_events(events)
        
        # Clean up old one-time events (24 hours after they've triggered)
        if event.get("event_triggered", False) and not event.get("repeat_days"):
            if now > event_time + timedelta(hours=24):
                events.remove(event)
                save_events(events)


@check_events.before_loop
async def before_check_events():
    await bot.wait_until_ready()


# =============== ORIGINAL WELCOME FEATURE ===============

@bot.event
async def on_ready():
    print(f"Bot is online as {bot.user}")
    check_events.start()  # Start the event checker


@bot.event
async def on_member_join(member):
    template = Image.open("image.png").convert("RGBA")
    avatar_url = member.display_avatar.url
    avatar_bytes = requests.get(avatar_url).content
    avatar = Image.open(BytesIO(avatar_bytes)).convert("RGBA")
    avatar = avatar.resize((140, 140))
    template.paste(avatar, (390, 28), avatar)
    draw = ImageDraw.Draw(template)
    font = ImageFont.truetype("pokemon-gb.ttf", 38)
    username = member.name
    draw.text((190, 469), username, font=font, fill=(0, 0, 0))
    output_path = "welcome.png"
    template.save(output_path)
    channel = member.guild.system_channel
    if channel:
        await channel.send(file=discord.File(output_path))


# =============== EVENT COMMANDS ===============

@bot.command(name="addevent")
async def add_event(ctx, event_name: str, date: str, time: str, mention: str, repeat_days: int = 0):
    """
    Add a new event with optional repeating
    
    Usage: !addevent "Event Name" YYYY-MM-DD HH:MM @role 2
    
    Examples:
    !addevent "Raid Night" 2026-01-29 20:00 @everyone 0
    !addevent "Daily Standup" 2026-01-29 09:00 @team 1
    !addevent "Weekly Meeting" 2026-01-30 15:00 @staff 7
    """
    try:
        # Parse the datetime
        event_datetime = datetime.strptime(f"{date} {time}", "%Y-%m-%d %H:%M")
        
        # Check if the event is in the future
        if event_datetime <= datetime.now():
            await ctx.send("❌ Event time must be in the future!")
            return
        
        # Create event object
        event = {
            "name": event_name,
            "time": event_datetime.isoformat(),
            "channel_id": ctx.channel.id,
            "mention": mention,
            "repeat_days": repeat_days if repeat_days > 0 else None,
            "reminder_sent": False,
            "event_triggered": False,
            "created_by": str(ctx.author)
        }
        
        events.append(event)
        save_events(events)
        
        repeat_info = f" (repeats every {repeat_days} days)" if repeat_days > 0 else ""
        await ctx.send(
            f"✅ Event added successfully!\n"
            f"**Event:** {event_name}\n"
            f"**Time:** {event_datetime.strftime('%Y-%m-%d %H:%M')}\n"
            f"**Mention:** {mention}\n"
            f"**Reminder:** 10 minutes before{repeat_info}"
        )
        
    except ValueError:
        await ctx.send("❌ Invalid date/time format! Use: YYYY-MM-DD HH:MM (24-hour format)")
    except Exception as e:
        await ctx.send(f"❌ Error creating event: {str(e)}")


@bot.command(name="listevents")
async def list_events(ctx):
    """List all upcoming events"""
    if not events:
        await ctx.send("📅 No events scheduled.")
        return
    
    now = datetime.now()
    upcoming = [e for e in events if datetime.fromisoformat(e["time"]) > now]
    
    if not upcoming:
        await ctx.send("📅 No upcoming events.")
        return
    
    # Sort by time
    upcoming.sort(key=lambda x: x["time"])
    
    embed = discord.Embed(title="📅 Upcoming Events", color=discord.Color.blue())
    
    for i, event in enumerate(upcoming[:10], 1):  # Show max 10 events
        event_time = datetime.fromisoformat(event["time"])
        time_until = event_time - now
        
        repeat_info = f"\n🔁 Repeats every {event['repeat_days']} days" if event.get("repeat_days") else ""
        
        embed.add_field(
            name=f"{i}. {event['name']}",
            value=f"⏰ {event_time.strftime('%Y-%m-%d %H:%M')}\n"
                  f"👥 {event['mention']}\n"
                  f"⏳ In {time_until.days}d {time_until.seconds//3600}h {(time_until.seconds//60)%60}m"
                  f"{repeat_info}",
            inline=False
        )
    
    await ctx.send(embed=embed)


@bot.command(name="deleteevent")
async def delete_event(ctx, event_index: int):
    """
    Delete an event by its index from the list
    
    Usage: !deleteevent 1
    (Use !listevents to see event numbers)
    """
    now = datetime.now()
    upcoming = [e for e in events if datetime.fromisoformat(e["time"]) > now]
    upcoming.sort(key=lambda x: x["time"])
    
    if event_index < 1 or event_index > len(upcoming):
        await ctx.send(f"❌ Invalid event number! Use !listevents to see available events.")
        return
    
    event_to_delete = upcoming[event_index - 1]
    events.remove(event_to_delete)
    save_events(events)
    
    await ctx.send(f"✅ Deleted event: '{event_to_delete['name']}'")


@bot.command(name="eventhelp")
async def event_help(ctx):
    """Show help for event commands"""
    embed = discord.Embed(
        title="🎯 Event System Help",
        description="Manage events and reminders with these commands:",
        color=discord.Color.green()
    )
    
    embed.add_field(
        name="!addevent",
        value='**Create a new event**\n'
              'Usage: `!addevent "Name" YYYY-MM-DD HH:MM @mention [repeat_days]`\n'
              'Examples:\n'
              '• `!addevent "Raid" 2026-01-29 20:00 @everyone 0`\n'
              '• `!addevent "Daily" 2026-01-29 09:00 @team 1` (repeats daily)\n'
              '• `!addevent "Weekly" 2026-01-30 15:00 @staff 7` (repeats weekly)',
        inline=False
    )
    
    embed.add_field(
        name="!listevents",
        value="**View all upcoming events**\nShows next 10 events with countdown timers",
        inline=False
    )
    
    embed.add_field(
        name="!deleteevent",
        value="**Delete an event**\nUsage: `!deleteevent 1`\n(Use !listevents to see event numbers)",
        inline=False
    )
    
    embed.add_field(
        name="⏰ Reminders",
        value="• You'll get a reminder **10 minutes before** each event\n"
              "• The event notification is sent at the scheduled time\n"
              "• Repeating events automatically schedule the next occurrence",
        inline=False
    )
    
    await ctx.send(embed=embed)


# =============== START FLASK + BOT TOGETHER ===============

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    bot.run(TOKEN)