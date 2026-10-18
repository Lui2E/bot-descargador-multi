import os
import re
import asyncio
import glob
import sqlite3
from datetime import datetime, timedelta
import yt_dlp
import httpx
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import FSInputFile
from flask import Flask
from threading import Thread

# --- CONFIGURACIÓN DE FLASK (KEEP-ALIVE) ---
app = Flask('')

@app.route('/')
def home():
    return "Bot is alive!"

def run_web():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# --- CONFIGURACIÓN DEL BOT ---
TOKEN = os.getenv("TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

bot = Bot(token=TOKEN)
dp = Dispatcher()

if not os.path.exists("downloads"):
    os.makedirs("downloads")

# --- BASE DE DATOS (LÍMITES, USUARIOS Y BANEOS) ---
DB_NAME = "/data/bot_database.db" if os.path.exists("/data") else "bot_database.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # Registro de usuarios activos del bot (para broadcasts)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS bot_users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_seen TIMESTAMP
        )
    ''')
    
    # Registro de descargas
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_downloads (
            user_id INTEGER,
            download_time TIMESTAMP
        )
    ''')
    
    # Usuarios Baneados
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS banned_users (
            user_id INTEGER PRIMARY KEY,
            ban_time TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# --- FUNCIONES AUXILIARES BD ---

def register_user(user_id: int, username: str):
    """Guarda o actualiza a los usuarios para el envío masivo de mensajes."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO bot_users (user_id, username, first_seen)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET username=excluded.username
    ''', (user_id, username, datetime.now()))
    conn.commit()
    conn.close()

def get_all_users() -> list[int]:
    """Obtiene la lista de IDs de todos los usuarios registrados."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT user_id FROM bot_users')
    rows = cursor.fetchall()
    conn.close()
    return [r[0] for r in rows]

def is_banned(user_id: int) -> bool:
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT user_id FROM banned_users WHERE user_id = ?', (user_id,))
    res = cursor.fetchone()
    conn.close()
    return res is not None

def ban_user(user_id: int):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('INSERT OR REPLACE INTO banned_users (user_id, ban_time) VALUES (?, ?)',
                   (user_id, datetime.now()))
    conn.commit()
    conn.close()

def unban_user(user_id: int):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('DELETE FROM banned_users WHERE user_id = ?', (user_id,))
    conn.commit()
    conn.close()

def check_and_register_limit(user_id: int, max_downloads: int = 3, hours_window: int = 24) -> tuple[bool, int]:
    if user_id == ADMIN_ID:
        return True, 0
        
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    time_threshold = datetime.now() - timedelta(hours=hours_window)
    
    cursor.execute('DELETE FROM user_downloads WHERE download_time < ?', (time_threshold,))
    cursor.execute('SELECT COUNT(*) FROM user_downloads WHERE user_id = ? AND download_time >= ?', (user_id, time_threshold))
    count = cursor.fetchone()[0]
    
    if count >= max_downloads:
        conn.commit()
        conn.close()
        return False, count
    
    cursor.execute('INSERT INTO user_downloads (user_id, download_time) VALUES (?, ?)', (user_id, datetime.now()))
    conn.commit()
    conn.close()
    return True, count + 1

# --- FUNCIONES DE DESCARGA ---

def clean_url(url: str) -> str:
    return url.split("?")[0]

async def download_twitter_direct(url: str, user_id: int):
    target_path = f"downloads/{user_id}_twitter.mp4"
    match = re.search(r'status/(\d+)', url)
    if not match:
        raise Exception("No es un enlace de Tweet válido.")
    
    tweet_id = match.group(1)
    api_url = f"https://api.vxtwitter.com/Twitter/status/{tweet_id}"
    
    async with httpx.AsyncClient(timeout=15.0) as client:
        res = await client.get(api_url)
        if res.status_code == 200:
            data = res.json()
            media_urls = data.get("mediaURLs", [])
            video_url = data.get("video_url") or (media_urls[0] if media_urls else None)
            
            if video_url:
                async with client.stream("GET", video_url) as r:
                    with open(target_path, "wb") as f:
                        async for chunk in r.aiter_bytes():
                            f.write(chunk)
                if os.path.exists(target_path) and os.path.getsize(target_path) > 0:
                    return target_path

    raise Exception("No se pudo extraer el video mediante la API de Twitter.")

def download_with_ytdlp(url: str, user_id: int):
    output_template = f"downloads/{user_id}_%(id)s.%(ext)s"
    cookie_path = "/etc/secrets/cookies.txt" if os.path.exists("/etc/secrets/cookies.txt") else "cookies.txt"
    
    ydl_opts = {
        'format': 'bestvideo+bestaudio/best[ext=mp4]/best',
        'outtmpl': output_template,
        'quiet': True,
        'no_warnings': True,
        'nocheckcertificate': True,
        'age_limit': 0,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'es-ES,es;q=0.9,en;q=0.8',
        }
    }
    
    if os.path.exists(cookie_path):
        ydl_opts['cookiefile'] = cookie_path

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        return ydl.prepare_filename(info)

async def download_media_cascade(url: str, user_id: int):
    url_cleaned = clean_url(url)
    
    if "twitter.com" in url.lower() or "x.com" in url.lower():
        try:
            return await download_twitter_direct(url, user_id)
        except Exception as e:
            print(f"Bypass Twitter falló: {e}, intentando con extractor general...")

    try:
        f = await asyncio.to_thread(download_with_ytdlp, url_cleaned, user_id)
        if f and os.path.exists(f):
            return f
    except Exception as e:
        print(f"Descarga yt-dlp limpia falló: {e}, intentando con URL original...")

    try:
        f = await asyncio.to_thread(download_with_ytdlp, url, user_id)
        if f and os.path.exists(f):
            return f
    except Exception as e:
        print(f"Reintento falló: {e}")

    matches = glob.glob(f"downloads/{user_id}_*")
    if matches:
        return matches[0]

    raise Exception("Todos los métodos de descarga fallaron.")

# --- MANEJADORES ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    username = message.from_user.username or "Sin username"
    register_user(user_id, username)

    if is_banned(user_id):
        await message.reply("⛔ **Tu acceso a este bot ha sido bloqueado.**")
        return

    await message.reply(
        "👋 **¡Bienvenido al Descargador Pro!**\n\n"
        "Puedo descargar fotos y videos de:\n"
        "✅ TikTok\n"
        "✅ Instagram\n"
        "✅ Facebook\n"
        "✅ X (Twitter)\n"
        "✅ LinkedIn\n\n"
        "📌 **Límite diario:** Tienes un máximo de **3 descargas cada 24 horas**.\n\n"
        "Solo **envíame el enlace** de la publicación o video que deseas obtener."
    )

# --- COMANDOS DE ADMINISTRACIÓN (BAN, UNBAN Y BROADCAST) ---

@dp.message(Command("ban"))
async def cmd_ban(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
        
    args = message.text.split()
    if len(args) < 2:
        await message.reply("⚠️ Uso correcto: `/ban <ID_USUARIO>`")
        return
        
    try:
        target_id = int(args[1])
        ban_user(target_id)
        await message.reply(f"🚫 El usuario con ID `{target_id}` ha sido **bloqueado**.")
    except ValueError:
        await message.reply("❌ ID no válido.")

@dp.message(Command("unban"))
async def cmd_unban(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
        
    args = message.text.split()
    if len(args) < 2:
        await message.reply("⚠️ Uso correcto: `/unban <ID_USUARIO>`")
        return
        
    try:
        target_id = int(args[1])
        unban_user(target_id)
        await message.reply(f"✅ El usuario con ID `{target_id}` ha sido **desbloqueado**.")
    except ValueError:
        await message.reply("❌ ID no válido.")

@dp.message(Command("broadcast"))
async def cmd_broadcast(message: types.Message):
    """Permite al admin enviar un comunicado masivo de ética, concientización, etc."""
    if message.from_user.id != ADMIN_ID:
        return

    text_to_send = message.text.replace("/broadcast", "").strip()
    if not text_to_send:
        await message.reply(
            "⚠️ **Uso del comando:**\n\n"
            "`/broadcast <mensaje>`\n\n"
            "Ejemplo:\n"
            "`/broadcast 📢 Recordatorio: Por favor, hagamos un uso ético del bot y respetemos los derechos de autor.`"
        )
        return

    users = get_all_users()
    success = 0
    failed = 0

    status = await message.reply(f"⏳ **Enviando mensaje masivo a {len(users)} usuarios...**")

    for u_id in users:
        try:
            await bot.send_message(chat_id=u_id, text=text_to_send, parse_mode="Markdown")
            success += 1
            await asyncio.sleep(0.05)  # Pausa breve para prevenir límites de rate de Telegram
        except Exception:
            failed += 1

    await status.edit_text(
        f"✅ **Difusión completada:**\n\n"
        f"📤 Mensajes enviados: `{success}`\n"
        f"❌ Fallidos/Bloqueados: `{failed}`"
    )

# --- MANEJADOR DE ENLACES DE DESCARGA ---

@dp.message(F.text.contains("http"))
async def handle_link(message: types.Message):
    user_id = message.from_user.id
    username = f"@{message.from_user.username}" if message.from_user.username else "Sin username"
    full_name = message.from_user.full_name
    
    register_user(user_id, message.from_user.username or "Sin username")

    if is_banned(user_id):
        await message.reply("⛔ **Tu acceso a este bot ha sido bloqueado.**")
        return

    url = message.text.strip()

    # Control del límite de 3 descargas por 24 horas
    can_download, count = check_and_register_limit(user_id, max_downloads=3, hours_window=24)
    if not can_download:
        await message.reply(
            "⚠️ **Límite de descargas alcanzado**\n\n"
            "Has alcanzado tus **3 descargas permitidas en 24 horas**.\n"
            "Vuelve a intentarlo mañana cuando se cumpla tu ciclo."
        )
        return

    # Log al Admin
    if ADMIN_ID != 0:
        log_text = (
            "📊 **LOG DE ACTIVIDAD**\n\n"
            f"👤 **Usuario:** {full_name}\n"
            f"🆔 **ID:** `{user_id}`\n"
            f"🏷 **Username:** {username}\n"
            f"🔗 **Enlace:** {url}"
        )
        try:
            await bot.send_message(chat_id=ADMIN_ID, text=log_text, parse_mode="Markdown", disable_web_page_preview=True)
        except Exception as e:
            print(f"Error log admin: {e}")

    status_msg = await message.reply("🔎 **Procesando descarga...**", parse_mode="Markdown")
    file_path = None

    try:
        file_path = await download_media_cascade(url, user_id)

        if not file_path or not os.path.exists(file_path):
            raise Exception("Archivo no generado.")

        ext = file_path.lower()
        if ext.endswith(('.mp4', '.mkv', '.mov', '.webm', '.ts')):
            await message.reply_video(video=FSInputFile(file_path), caption="✅ **Video descargado con éxito.**")
        elif ext.endswith(('.jpg', '.jpeg', '.png', '.webp')):
            await message.reply_photo(photo=FSInputFile(file_path), caption="✅ **Foto descargada con éxito.**")
        else:
            await message.reply_document(document=FSInputFile(file_path), caption="✅ **Archivo listo.**")

    except Exception as e:
        print(f"Error final con {url}: {e}")
        await message.reply("❌ No se pudo descargar el contenido. Verifica que no sea privado.")
    finally:
        for f in glob.glob(f"downloads/{user_id}_*"):
            try:
                os.remove(f)
            except Exception:
                pass

        if status_msg:
            try:
                await status_msg.delete()
            except Exception:
                pass

async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    print("🚀 Bot iniciado correctamente...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    Thread(target=run_web, daemon=True).start()
    asyncio.run(main())
