import discord
from discord.ext import commands, tasks
import yt_dlp
import asyncio
import os
import re # Импортируем для очистки URL

# ИНТЕНТЫ
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
intents.members = True
intents.guilds = True

# СОЗДАНИЕ БОТА: Префикс '!'
bot = commands.Bot(command_prefix="!", intents=intents)
queues = {}

# ========== ОБНОВЛЕНИЕ СТАТУСА И СИНХРОНИЗАЦИЯ КОМАНД ==========
@bot.event
async def on_ready():
    print(f"✅ Бот запущен как {bot.user}")
    
    # КЛЮЧЕВОЙ КОД ДЛЯ СИНХРОНИЗАЦИИ СЛЭШ-КОМАНД
    try:
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

# ========== МУЗЫКАЛЬНЫЕ КОМАНДЫ ==========

# Вспомогательная функция (С ЗАДЕРЖКОЙ ОТКЛЮЧЕНИЯ)
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
    
    # Исправление мгновенного отключения
    elif vc and not vc.is_playing() and not vc.is_paused():
        
        await interaction.channel.send("💡 Очередь пуста. Отключусь через 60 секунд, если ничего не добавить.")
        
        await asyncio.sleep(60)
        
        # Повторная проверка: если все еще не играет, то отключаемся
        if vc and not vc.is_playing() and not vc.is_paused():
            await interaction.channel.send("🎵 Очередь пуста — отключаюсь.")
            await vc.disconnect()

# ФОНОВАЯ ЗАДАЧА: Выполняет медленную работу (поиск, подключение)
async def _play_worker(interaction: discord.Interaction, query: str):
    
    # 1. Проверки
    if not interaction.user.voice:
        return await interaction.followup.send("❌ Ты не в голосовом канале!")
    
    # 2. Подключение к каналу
    if not interaction.guild.voice_client:
        try:
            await interaction.user.voice.channel.connect()
        except asyncio.TimeoutError:
             return await interaction.followup.send("❌ Не удалось подключиться к голосовому каналу (Таймаут).")
        except Exception as e:
             return await interaction.followup.send(f"❌ Не удалось подключиться: {e}")

    vc = interaction.guild.voice_client
    
    # 3. УЛУЧШЕНИЕ: Очистка URL от лишних параметров, таких как &list= или &start_radio=
    if re.match(r'https?://(?:www\.)?youtube\.com/watch\?v=', query) or re.match(r'https?://youtu\.be/', query):
        # Удаляем все, что идет после v=... или youtu.be/... до & (включая &)
        query = re.sub(r'(\?|&)(list|start_radio|index)=.*$', '', query)
        query = query.split('&')[0] # Очищаем все остальные параметры

    # 4. Поиск и извлечение информации
    ydl_opts = {"format": "bestaudio/best", "quiet": True, "default_search": "auto"}
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # ydl.extract_info - самая долгая операция!
            info = await asyncio.to_thread(ydl.extract_info, query, download=False)
            
            # Если это плейлист (Mix или длинная ссылка), берем первый трек
            if "entries" in info:
                # Ограничиваемся первым треком из-за потенциально очень больших плейлистов
                info = info["entries"][0]
            
            stream_url = info["url"]
            title = info.get("title", "Неизвестный трек")
    except Exception as e:
        print(f"Ошибка YT-DLP: {e}")
        return await interaction.followup.send("❌ Не удалось найти или загрузить трек. Попробуйте другую ссылку.")

    # 5. Добавление в очередь и воспроизведение
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


# КОМАНДА /play (ТОЛЬКО ДЛЯ НЕМЕДЛЕННОГО ОТВЕТА)
@bot.tree.command(name="play", description="Проиграть трек по ссылке или названию.")
@discord.app_commands.describe(query="Ссылка на YouTube/другой сайт или поисковый запрос")
async def play_slash(interaction: discord.Interaction, query: str):
    # 1. НЕМЕДЛЕННО ОТВЕЧАЕМ DISCORD'У, ЧТО НАЧАЛИ ДУМАТЬ
    await interaction.response.defer(thinking=True) 
    
    # 2. ПЕРЕДАЕМ ВСЮ МЕДЛЕННУЮ РАБОТУ В ФОНОВЫЙ ПОТОК
    bot.loop.create_task(_play_worker(interaction, query))


# КОМАНДЫ /pause, /resume, /stop, /queue (без изменений)

@bot.tree.command(name="pause", description="Поставить музыку на паузу.")
async def pause_slash(interaction: discord.Interaction):
    vc = interaction.guild.voice_client
    if vc and vc.is_playing():
        vc.pause()
        await interaction.response.send_message("⏸ Музыка на паузе.")
    else:
        await interaction.response.send_message("❌ Нечего ставить на паузу.")

@bot.tree.command(name="resume", description="Продолжить воспроизведение.")
async def resume_slash(interaction: discord.Interaction):
    vc = interaction.guild.voice_client
    if vc and vc.is_paused():
        vc.resume()
        await interaction.response.send_message("▶️ Продолжаем воспроизведение.")
    else:
        await interaction.response.send_message("❌ Музыка не на паузе.")

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

@bot.tree.command(name="queue", description="Показать текущую очередь треков.")
async def queue_slash(interaction: discord.Interaction):
    guild_id = interaction.guild.id
    if guild_id not in queues or not queues[guild_id]:
        return await interaction.response.send_message("📭 Очередь пуста.")
    text = "\n".join([f"{i+1}. {t[1]}" for i, t in enumerate(queues[guild_id])])
    await interaction.response.send_message(f"📜 **Очередь треков:**\n{text}")

# Запуск бота с переменной окружения
bot.run(os.getenv("TOKEN_BOT"))
