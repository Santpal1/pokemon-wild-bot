import discord
from discord.ext import commands
from dotenv import load_dotenv
import os

# Load the .env file
load_dotenv()
TOKEN = os.getenv("TOKEN")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True   # needed for on_member_join

bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    print(f"Bot is online as {bot.user}")


@bot.event
async def on_member_join(member):
    from PIL import Image, ImageDraw, ImageFont
    import requests
    from io import BytesIO

    # Load template
    template = Image.open("image.png").convert("RGBA")

    # Fetch avatar from Discord
    avatar_url = member.display_avatar.url
    avatar_bytes = requests.get(avatar_url).content
    avatar = Image.open(BytesIO(avatar_bytes)).convert("RGBA")

    # Resize avatar
    avatar = avatar.resize((140, 140))

    # Place avatar (your perfect coordinates)
    template.paste(avatar, (390, 28), avatar)

    # Draw username using Pokémon font
    draw = ImageDraw.Draw(template)
    font = ImageFont.truetype("pokemon-gb.ttf", 38)

    username = member.name  # auto insert their Discord username

    # Draw only the username between "Wild" and "appeared!"
    draw.text((190, 469), username, font=font, fill=(0, 0, 0))

    # Save output
    output_path = "welcome.png"
    template.save(output_path)

    # Send in system channel
    channel = member.guild.system_channel
    if channel:
        await channel.send(file=discord.File(output_path))


bot.run(TOKEN)
