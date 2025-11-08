import discord
from discord.ext import commands, tasks
import yt_dlp
import asyncio
import os
import re
from discord import ui 

# ИНТЕНТЫ
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
intents.members = True
intents.guilds = True

# СОЗДАНИЕ БОТА
bot = commands.Bot(command_prefix="!", intents=intents)
queues = {}
NOW_PLAYING_MESSAGE = {} # Словарь для хранения сообщений с кнопками

# ========== ПУТЬ К COOKIE-ФАЙЛУ ==========
# !!! ВАЖНО: СОЗДАЙ ФАЙЛ 'youtube_cookies.txt' РЯДОМ С bot.py !!!
COOKIE_FILE_PATH = "youtube_cookies.txt"

# ========== КЛАСС КНОПОК ДЛЯ УПРАВЛЕНИЯ ПЛЕЕРОМ ==========
class PlayerControls(ui.View):
    def __init__(self, bot_instance):
        super().__init__(timeout=None)
        self.bot = bot_instance

    # Кнопка ПАУЗА/ВОЗОБНОВИТЬ
    @ui.button(label="⏸️ Пауза / ▶️ Играть", style=discord.ButtonStyle.blurple, custom_id="persistent_pause_resume")
    async def pause_resume(self, interaction: discord.Interaction, button: ui.Button):
        vc = interaction.guild.voice_client
        if not vc:
            return await interaction.response.send_message("❌ Бот не в голосовом канале.", ephemeral=True)

        if vc.is_playing():
            vc.pause()
            await interaction.response.edit_message(content="⏸️ Музыка на паузе.", view=self)
        elif vc.is_paused():
            vc.resume()
            await interaction.response.edit_message(content="▶️ Продолжаем воспроизведение.", view=self)
        else:
            await interaction.response.send_message("❌ Нечего ставить на паузу.", ephemeral=True)

    # Кнопка СТОП (Остановить и отключить)
    @ui.button(label="🛑 Стоп", style=discord.ButtonStyle.red, custom_id="persistent_stop")
    async def stop_button(self, interaction: discord.Interaction, button: ui.Button):
        vc = interaction.guild.voice_client
        if vc:
            queues[interaction.guild.id] = []
            vc.stop()
            await vc.disconnect()
            await interaction.response.edit_message(content="🛑 Музыка остановлена и бот отключился.", view=None)
        else:
            await interaction.response.send_message("❌ Я не в голосовом канале.", ephemeral=True)

    # Кнопка ПРОПУСТИТЬ ТРЕК (Skip)
    @ui.button(label="⏭️ Пропустить", style=discord.ButtonStyle.green, custom_id="persistent_skip")
    async def skip_button(self, interaction: discord.Interaction, button: ui.Button):
        vc = interaction.guild.voice_client
        if vc and vc.is_playing():
            vc.stop() # stop() вызывает play_next через after=lambda
            await interaction.response.send_message("⏭️ Пропускаю текущий трек.", ephemeral=True)
            # Обновим сообщение с кнопками (удаляем старое, чтобы избежать спама)
            guild_id = interaction.guild.id
            if guild_id in NOW_PLAYING_MESSAGE:
                try:
                    await NOW_PLAYING_MESSAGE[guild_id].delete()
                    del NOW_PLAYING_MESSAGE[guild_id]
                except:
                    pass
        else:
            await interaction.response.send_message("❌ Нечего пропускать.", ephemeral=True)

    # Кнопка ОЧЕРЕДЬ
    @ui.button(label="📜 Очередь", style=discord.ButtonStyle.grey, custom_id="persistent_queue")
    async def queue_button(self, interaction: discord.Interaction, button: ui.Button):
        guild_id = interaction.guild.id
        if guild_id not in queues or not queues[guild_id]:
            return await interaction.response.send_message("📭 Очередь пуста.", ephemeral=True)
        text = "\n".join([f"{i+1}. {t[1]}" for i, t in enumerate(queues[guild_id])])
        await interaction.response.send_message(f"📜 **Очередь треков:**\n{text}", ephemeral=True)


# ========== ОБНОВЛЕНИЕ СТАТУСА И СИНХРОНИЗАЦИЯ КОМАНД ==========
@bot.event
async def on_ready():
    print(f"✅ Бот запущен как {bot.user}")
    
    try:
        synced = await bot.tree.sync()
        print(f"📝 Синхронизировано {len(synced)} слэш-команд.")
    except Exception as e:
        print(f"❌ Не удалось синхронизировать слэш-команды: {e}")
        
    update_voice_status.start()
    # ДОБАВЛЯЕМ ПЕРСИСТЕНТНОСТЬ КНОПОК
    bot.add_view(PlayerControls(bot)) 

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

# ========== МУЗЫКАЛЬНЫЕ КОМАНДЫ (Обновлено) ==========

# Вспомогательная функция (С ЗАДЕРЖКОЙ ОТКЛЮЧЕНИЯ И КНОПКАМИ)
async def play_next(interaction: discord.Interaction):
    guild_id = interaction.guild.id
    vc = interaction.guild.voice_client

    # Удаляем предыдущее сообщение с кнопками
    if guild_id in NOW_PLAYING_MESSAGE:
        try:
            await NOW_PLAYING_MESSAGE[guild_id].delete()
            del NOW_PLAYING_MESSAGE[guild_id]
        except Exception:
            pass # Игнорируем, если сообщение уже удалено

    if guild_id in queues and queues[guild_id]:
        url, title = queues[guild_id].pop(0)
        
        vc.play(
            discord.FFmpegPCMAudio(url, before_options="-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"),
            after=lambda e: asyncio.run_coroutine_threadsafe(play_next(interaction), bot.loop)
        )
        # Отправляем новое сообщение с кнопками
        view = PlayerControls(bot)
        msg = await interaction.channel.send(f"▶️ Сейчас играет: **{title}**", view=view)
        NOW_PLAYING_MESSAGE[guild_id] = msg
    
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
    
    # 3. УЛУЧШЕНИЕ: Очистка URL от лишних параметров
    if re.match(r'https?://(?:www\.)?youtube\.com/watch\?v=', query) or re.match(r'https?://youtu\.be/', query):
        query = re.sub(r'(\?|&)(list|start_radio|index)=.*$', '', query)
        query = query.split('&')[0]

    # 4. Поиск и извлечение информации (ДОБАВЛЕНО: cookiefile)
    ydl_opts = {
        "format": "bestaudio/best", 
        "quiet": True, 
        "default_search": "auto",
        "cookiefile": COOKIE_FILE_PATH # <-- ИСПРАВЛЕНИЕ ОШИБКИ 429
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = await asyncio.to_thread(ydl.extract_info, query, download=False)
            
            if "entries" in info:
                info = info["entries"][0]
            
            stream_url = info["url"]
            title = info.get("title", "Неизвестный трек")
    except Exception as e:
        print(f"Ошибка YT-DLP: {e}")
        return await interaction.followup.send("❌ Не удалось найти или загрузить трек. Проверь файл `youtube_cookies.txt`.")

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
        # Отправляем сообщение с кнопками
        view = PlayerControls(bot)
        msg = await interaction.followup.send(f"▶️ Сейчас играет: **{title}**", view=view)
        NOW_PLAYING_MESSAGE[guild_id] = msg


# КОМАНДА /play
@bot.tree.command(name="play", description="Проиграть трек по ссылке (YouTube, SoundCloud) или названию.")
@discord.app_commands.describe(query="Ссылка на трек или поисковый запрос")
async def play_slash(interaction: discord.Interaction, query: str):
    await interaction.response.defer(thinking=True) 
    bot.loop.create_task(_play_worker(interaction, query))


# ========== КОМАНДА /search (С ВЫБОРОМ) ==========

class SearchSelect(ui.Select):
    def __init__(self, options, bot_instance, original_interaction):
        super().__init__(placeholder="Выбери трек для воспроизведения...", options=options, custom_id="music_search_select")
        self.bot = bot_instance
        self.original_interaction = original_interaction

    async def callback(self, interaction: discord.Interaction):
        # Получаем выбранное название трека
        selected_title = self.values[0]
        
        # Удаляем все кнопки после выбора
        await interaction.message.delete()
        
        # Передаем выбранный трек в _play_worker
        await interaction.response.defer(thinking=True)
        bot.loop.create_task(_play_worker(interaction, selected_title))


@bot.tree.command(name="search", description="Найти трек на YouTube и выбрать из списка.")
@discord.app_commands.describe(query="Поисковый запрос (название трека)")
async def search_slash(interaction: discord.Interaction, query: str):
    if not interaction.user.voice:
        return await interaction.response.send_message("❌ Ты не в голосовом канале!")
    
    await interaction.response.defer(thinking=True)

    # ДОБАВЛЕНО: cookiefile для поиска
    ydl_opts = {
        "format": "bestaudio/best",
        "quiet": True,
        "default_search": "ytsearch5",
        "extract_flat": "in_playlist",
        "cookiefile": COOKIE_FILE_PATH # <-- ИСПРАВЛЕНИЕ ОШИБКИ 429
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = await asyncio.to_thread(ydl.extract_info, query, download=False)
            
        options = []
        if "entries" in info:
            for i, entry in enumerate(info["entries"]):
                if i >= 5: 
                    break 
                
                title = entry.get("title", "Неизвестный трек")
                options.append(discord.SelectOption(label=title[:100], value=title))
        
        if not options:
             return await interaction.followup.send("❌ Ничего не найдено по твоему запросу.")

        # Создаем Select Menu и View
        select = SearchSelect(options, bot, interaction)
        view = ui.View(timeout=60)
        view.add_item(select)

        await interaction.followup.send(f"🔍 **Результаты поиска по запросу '{query}'**:", view=view)

    except Exception as e:
        print(f"Ошибка YT-DLP при поиске: {e}")
        await interaction.followup.send("❌ Произошла ошибка при поиске треков.")

# Запуск бота с переменной окружения
bot.run(os.getenv("TOKEN_BOT"))
