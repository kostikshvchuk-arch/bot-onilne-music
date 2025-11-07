import discord
from discord.ext import commands, tasks
import yt_dlp
import asyncio
import os

# ИНТЕНТЫ
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
intents.members = True
intents.guilds = True

# СОЗДАНИЕ БОТА: Смена префикса на '!' (чтобы / не конфликтовал с slash-командами)
bot = commands.Bot(command_prefix="!", intents=intents)
queues = {}

# ========== ОБНОВЛЕНИЕ СТАТУСА И СИНХРОНИЗАЦИЯ КОМАНД ==========
@bot.event
async def on_ready():
    print(f"✅ Бот запущен как {bot.user}")
    
    # !!! КЛЮЧЕВОЙ КОД ДЛЯ СИНХРОНИЗАЦИИ СЛЭШ-КОМАНД !!!
    try:
        # Синхронизация команд с Discord API
        synced = await bot.tree.sync()
        print(f"📝 Синхронизировано {len(synced)} слэш-команд.")
    except Exception as e:
        print(f"❌ Не удалось синхронизировать слэш-команды: {e}")
        
    update_voice_status.start()

@tasks.loop(seconds=30)
async def update_voice_status():
    """Считает людей в войсах и обновляет статус"""
    total = 0
    for guild in bot.guilds:
        if guild.unavailable:
            continue
            
        for vc in guild.voice_channels:
            if vc.permissions_for(guild.me).connect:
                total += len([m for m in vc.members if not m.bot])

    if total > 0:
        status_text = f"🎙 Онлайн в войсах: {total}"
    else:
        status_text = "🎙 Никого нет в войсах"

    await bot.change_presence(
        activity=discord.Activity(type=discord.ActivityType.listening, name=status_text)
    )

# ========== МУЗЫКАЛЬНЫЕ СЛЭШ-КОМАНДЫ (COMMAND TREE) ==========

# Вспомогательная функция (адаптирована для слэш-команд)
async def play_next(interaction: discord.Interaction):
    guild_id = interaction.guild.id
    vc = interaction.guild.voice_client

    if guild_id in queues and queues[guild_id]:
        url, title = queues[guild_id].pop(0)
        
        vc.play(
            discord.FFmpegPCMAudio(url, before_options="-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"),
            after=lambda e: asyncio.run_coroutine_threadsafe(play_next(interaction), bot.loop)
        )
        await interaction.channel.send(f"▶️ Сейчас играет: **{title}**")
    else:
        await interaction.channel.send("🎵 Очередь пуста — отключаюсь.")
        await vc.disconnect()


# КОМАНДА /play
@bot.tree.command(name="play", description="Проиграть трек по ссылке или названию.")
@discord.app_commands.describe(query="Ссылка на YouTube/другой сайт или поисковый запрос")
async def play_slash(interaction: discord.Interaction, query: str):
    await interaction.response.defer() # Откладываем ответ
    
    if not interaction.user.voice:
        return await interaction.followup.send("❌ Ты не в голосовом канале!")
    
    # Подключение к каналу
    if not interaction.guild.voice_client:
        await interaction.user.voice.channel.connect()
    vc = interaction.guild.voice_client

    # Поиск и извлечение информации
    ydl_opts = {"format": "bestaudio/best", "quiet": True, "default_search": "auto"}
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(query, download=False)
            if "entries" in info:
                info = info["entries"][0]
            stream_url = info["url"]
            title = info.get("title", "Неизвестный трек")
    except Exception as e:
        print(f"Ошибка YT-DLP: {e}")
        return await interaction.followup.send("❌ Не удалось найти или загрузить трек.")

    # Добавление в очередь и воспроизведение
    guild_id = interaction.guild.id
    if guild_id not in queues:
        queues[guild_id] = []

    if vc.is_playing() or vc.is_paused():
        queues[guild_id].append((stream_url, title))
        await interaction.followup.send(f"➕ Добавлено в очередь: **{title}**")
    else:
        vc.play(
            discord.FFmpegPCMAudio(stream_url, before_options="-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"),
            after=lambda e: asyncio.run_coroutine_threadsafe(play_next(interaction), bot.loop)
        )
        await interaction.followup.send(f"▶️ Сейчас играет: **{title}**")


# КОМАНДА /pause
@bot.tree.command(name="pause", description="Поставить музыку на паузу.")
async def pause_slash(interaction: discord.Interaction):
    vc = interaction.guild.voice_client
    if vc and vc.is_playing():
        vc.pause()
        await interaction.response.send_message("⏸ Музыка на паузе.")
    else:
        await interaction.response.send_message("❌ Нечего ставить на паузу.")

# КОМАНДА /resume
@bot.tree.command(name="resume", description="Продолжить воспроизведение.")
async def resume_slash(interaction: discord.Interaction):
    vc = interaction.guild.voice_client
    if vc and vc.is_paused():
        vc.resume()
        await interaction.response.send_message("▶️ Продолжаем воспроизведение.")
    else:
        await interaction.response.send_message("❌ Музыка не на паузе.")

# КОМАНДА /stop
@bot.tree.command(name="stop", description="Остановить музыку и отключить бота.")
async def stop_slash(interaction: discord.Interaction):
    vc = interaction.guild.voice_client
    if vc:
        queues[interaction.guild.id] = []
        vc.stop()
        await vc.disconnect()
        await interaction.response.send_message("🛑 Музыка остановлена и бот отключился.")
    else:
        await interaction.response.send_message("❌ Я не в голосовом канале.")

# КОМАНДА /queue
@bot.tree.command(name="queue", description="Показать текущую очередь треков.")
async def queue_slash(interaction: discord.Interaction):
    guild_id = interaction.guild.id
    if guild_id not in queues or not queues[guild_id]:
        return await interaction.response.send_message("📭 Очередь пуста.")
    text = "\n".join([f"{i+1}. {t[1]}" for i, t in enumerate(queues[guild_id])])
    await interaction.response.send_message(f"📜 **Очередь треков:**\n{text}")

# Запуск бота с переменной окружения
bot.run(os.getenv("TOKEN_BOT"))
