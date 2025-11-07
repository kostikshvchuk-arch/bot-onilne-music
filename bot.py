import discord
from discord.ext import commands, tasks
import yt_dlp
import asyncio
import os

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
intents.members = True
intents.guilds = True

bot = commands.Bot(command_prefix="/", intents=intents)
queues = {}

# ========== ОБНОВЛЕНИЕ СТАТУСА ==========
@bot.event
async def on_ready():
    print(f"✅ Бот запущен как {bot.user}")
    update_voice_status.start()

@tasks.loop(seconds=30)
async def update_voice_status():
    """Считает людей в войсах и обновляет статус"""
    total = 0
    for guild in bot.guilds:
        for vc in guild.voice_channels:
            total += len([m for m in vc.members if not m.bot])

    if total > 0:
        status_text = f"🎙 Онлайн в войсах: {total}"
    else:
        status_text = "🎙 Никого нет в войсах"

    await bot.change_presence(
        activity=discord.Activity(type=discord.ActivityType.listening, name=status_text)
    )

# ========== МУЗЫКА ==========
async def play_next(ctx):
    guild_id = ctx.guild.id
    if guild_id in queues and queues[guild_id]:
        url, title = queues[guild_id].pop(0)
        vc = ctx.voice_client
        vc.play(
            discord.FFmpegPCMAudio(url, before_options="-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"),
            after=lambda e: asyncio.run_coroutine_threadsafe(play_next(ctx), bot.loop)
        )
        await ctx.send(f"▶️ Сейчас играет: **{title}**")
    else:
        await ctx.send("🎵 Очередь пуста — отключаюсь.")
        await ctx.voice_client.disconnect()

@bot.command()
async def play(ctx, url: str):
    """Проиграть трек по ссылке"""
    if not ctx.author.voice:
        return await ctx.send("❌ Ты не в голосовом канале!")
    if not ctx.voice_client:
        await ctx.author.voice.channel.connect()
    vc = ctx.voice_client

    ydl_opts = {"format": "bestaudio/best", "quiet": True}
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        if "entries" in info:
            info = info["entries"][0]
        stream_url = info["url"]
        title = info.get("title", "Неизвестный трек")

    guild_id = ctx.guild.id
    if guild_id not in queues:
        queues[guild_id] = []

    if vc.is_playing() or vc.is_paused():
        queues[guild_id].append((stream_url, title))
        await ctx.send(f"➕ Добавлено в очередь: **{title}**")
    else:
        vc.play(
            discord.FFmpegPCMAudio(stream_url, before_options="-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"),
            after=lambda e: asyncio.run_coroutine_threadsafe(play_next(ctx), bot.loop)
        )
        await ctx.send(f"▶️ Сейчас играет: **{title}**")

@bot.command()
async def pause(ctx):
    vc = ctx.voice_client
    if vc and vc.is_playing():
        vc.pause()
        await ctx.send("⏸ Музыка на паузе.")
    else:
        await ctx.send("❌ Нечего ставить на паузу.")

@bot.command()
async def resume(ctx):
    vc = ctx.voice_client
    if vc and vc.is_paused():
        vc.resume()
        await ctx.send("▶️ Продолжаем воспроизведение.")
    else:
        await ctx.send("❌ Музыка не на паузе.")

@bot.command()
async def stop(ctx):
    vc = ctx.voice_client
    if vc:
        queues[ctx.guild.id] = []
        vc.stop()
        await vc.disconnect()
        await ctx.send("🛑 Музыка остановлена и бот отключился.")
    else:
        await ctx.send("❌ Я не в голосовом канале.")

@bot.command()
async def queue(ctx):
    guild_id = ctx.guild.id
    if guild_id not in queues or not queues[guild_id]:
        return await ctx.send("📭 Очередь пуста.")
    text = "\n".join([f"{i+1}. {t[1]}" for i, t in enumerate(queues[guild_id])])
    await ctx.send(f"📜 **Очередь треков:**\n{text}")

bot.run(os.getenv("TOKEN_БОТА"))
