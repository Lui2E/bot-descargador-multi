import os
import re
import asyncio
import glob
import yt_dlp
import httpx
from bs4 import BeautifulSoup
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup
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

def get_cookie_file():
    paths = ["/etc/secrets/cookies.txt", "cookies.txt"]
    for path in paths:
        if os.path.exists(path) and os.path.getsize(path) > 0:
            return path
    return None

# --- MOTORES DE EXTRACCIÓN ---

def extract_direct_stream_url(url: str):
    """Extrae el enlace directo al archivo de video (.mp4) sin descargarlo al servidor."""
    cookie_file = get_cookie_file()
    ydl_opts = {
        'format': 'best/bestvideo+bestaudio',
        'quiet': True,
        'no_warnings': True,
        'nocheckcertificate': True,
        'age_limit': 0,
        'geo_bypass': True,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        }
    }
    if cookie_file:
        ydl_opts['cookiefile'] = cookie_file

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        if 'url' in info:
            return info['url'], info.get('title', 'Video')
        if 'entries' in info and len(info['entries']) > 0:
            return info['entries'][0]['url'], info['entries'][0].get('title', 'Video')
    return None, None

def download_media_locally(url: str, user_id: int):
    """Intenta descargar el archivo al servidor si es pequeño."""
    output_template = f"downloads/{user_id}_%(autonumber)s_%(id)s.%(ext)s"
    cookie_file = get_cookie_file()
    
    ydl_opts = {
        'format': 'best[ext=mp4]/best',
        'outtmpl': output_template,
        'quiet': True,
        'no_warnings': True,
        'nocheckcertificate': True,
        'max_filesize': 48 * 1024 * 1024, # Máximo 48 MB para Telegram
    }
    if cookie_file:
        ydl_opts['cookiefile'] = cookie_file

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])
    
    downloaded = glob.glob(f"downloads/{user_id}_*")
    return [f for f in downloaded if not f.endswith(('.part', '.ytdl')) and os.path.getsize(f) > 0]

# --- MANEJADORES ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.reply(
        "👋 **¡Bienvenido al Descargador Pro!**\n\n"
        "Puedo obtener fotos y videos de:\n"
        "✅ TikTok\n"
        "✅ Instagram\n"
        "✅ Facebook\n"
        "✅ X (Twitter)\n"
        "✅ LinkedIn\n\n"
        "Solo **envíame el enlace** de la publicación o video."
    )

@dp.message(F.text.contains("http"))
async def handle_link(message: types.Message):
    url = message.text.strip()
    user = message.from_user
    user_id = user.id
    username = f"@{user.username}" if user.username else "Sin username"
    full_name = user.full_name

    if ADMIN_ID != 0:
        log_text = (
            f"📊 LOG DE ACTIVIDAD\n\n"
            f"👤 Usuario: {full_name}\n"
            f"🆔 ID: {user_id}\n"
            f"🏷 Username: {username}\n"
            f"🔗 Enlace: {url}"
        )
        try:
            await bot.send_message(chat_id=ADMIN_ID, text=log_text, disable_web_page_preview=True)
        except Exception as e:
            print(f"Error log admin: {e}")

    status_msg = await message.reply("🔎 **Procesando enlace...**", parse_mode="Markdown")
    
    # 1. Intentar descargar localmente para enviar por Telegram
    try:
        files = await asyncio.to_thread(download_media_locally, url, user_id)
        if files:
            for file_path in files:
                ext = file_path.lower()
                if ext.endswith(('.mp4', '.mkv', '.mov', '.webm', '.ts')):
                    await message.reply_video(video=FSInputFile(file_path), caption="✅ **Video descargado con éxito.**")
                elif ext.endswith(('.jpg', '.jpeg', '.png', '.webp')):
                    await message.reply_photo(photo=FSInputFile(file_path), caption="✅ **Foto descargada con éxito.**")
                else:
                    await message.reply_document(document=FSInputFile(file_path), caption="✅ **Archivo listo.**")
            await status_msg.delete()
            return
    except Exception as e:
        print(f"Descarga local no completada ({e}), extrayendo enlace directo...")

    # 2. Si pesa más de 50MB o falla en Render, extraer el stream directo
    try:
        direct_url, title = await asyncio.to_thread(extract_direct_stream_url, url)
        if direct_url:
            kb = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="⬇️ Descargar / Ver Video", url=direct_url)
            ]])
            await message.reply(
                f"🎬 **{title}**\n\n"
                "El video está listo para descarga directa en alta calidad:",
                reply_markup=kb,
                parse_mode="Markdown"
            )
            await status_msg.delete()
            return
    except Exception as e:
        print(f"Extracción directa falló: {e}")

    await message.reply("❌ No se pudo procesar el enlace. Verifica que el video exista y esté disponible.")
    if status_msg:
        try:
            await status_msg.delete()
        except Exception:
            pass
            
    # Limpieza
    for f in glob.glob(f"downloads/{user_id}_*"):
        try:
            os.remove(f)
        except Exception:
            pass

async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    print("🚀 Bot iniciado correctamente...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    Thread(target=run_web, daemon=True).start()
    asyncio.run(main())
