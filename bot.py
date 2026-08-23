import os
import re
import asyncio
import glob
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

# --- FUNCIONES DE NORMALIZACIÓN Y BYPASS ---

def clean_url(url: str) -> str:
    """Limpia parámetros de tracking como ?igsh= o ?si= que provocan errores 403."""
    url = url.split("?")[0]
    return url

async def download_twitter_direct(url: str, user_id: int):
    """Extrae el video directo de Twitter/X usando la API de sindicación VxTwitter."""
    target_path = f"downloads/{user_id}_twitter.mp4"
    
    # Extraer ID del Tweet
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
    """Descarga estándar mediante yt-dlp con headers y fallback de cookies."""
    output_template = f"downloads/{user_id}_%(id)s.%(ext)s"
    
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
    
    # Si existe un archivo cookies.txt en el directorio, se usa automáticamente
    if os.path.exists("cookies.txt"):
        ydl_opts['cookiefile'] = 'cookies.txt'

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        return ydl.prepare_filename(info)

async def download_media_cascade(url: str, user_id: int):
    """Router inteligente que decide el mejor método según la plataforma."""
    url_cleaned = clean_url(url)
    
    # 1. Rutas específicas para Twitter / X
    if "twitter.com" in url.lower() or "x.com" in url.lower():
        try:
            return await download_twitter_direct(url, user_id)
        except Exception as e:
            print(f"Bypass Twitter falló: {e}, intentando con extractor general...")

    # 2. Descarga estándar / Instagram / TikTok / Sitios de terceros
    try:
        f = await asyncio.to_thread(download_with_ytdlp, url_cleaned, user_id)
        if f and os.path.exists(f):
            return f
    except Exception as e:
        print(f"Descarga yt-dlp limpia falló: {e}, intentando con URL original...")

    # 3. Reintento con URL original completa
    try:
        f = await asyncio.to_thread(download_with_ytdlp, url, user_id)
        if f and os.path.exists(f):
            return f
    except Exception as e:
        print(f"Reintento falló: {e}")

    # Chequeo final de archivos generados
    matches = glob.glob(f"downloads/{user_id}_*")
    if matches:
        return matches[0]

    raise Exception("Todos los métodos de descarga fallaron.")

# --- MANEJADORES ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.reply(
        "👋 **¡Bienvenido al Descargador Pro!**\n\n"
        "Puedo descargar fotos y videos de:\n"
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

    # Enviar Log al Admin
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
