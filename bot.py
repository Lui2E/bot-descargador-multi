import os
import re
import asyncio
import glob
import yt_dlp
import httpx
from bs4 import BeautifulSoup
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

# --- DETECCIÓN DE COOKIES EN RENDER ---
def get_cookie_file():
    """Detecta la ruta real donde Render monta el archivo secreto."""
    paths = ["/etc/secrets/cookies.txt", "cookies.txt"]
    for path in paths:
        if os.path.exists(path) and os.path.getsize(path) > 0:
            return path
    return None

# --- MOTORES DE DESCARGA ---

async def download_instagram_photos_direct(url: str, user_id: int):
    """Extrae imágenes/carruseles de Instagram."""
    shortcode_match = re.search(r'/(?:p|reel)/([A-Za-z0-9_-]+)', url)
    if not shortcode_match:
        raise Exception("Sin shortcode válido.")
    
    shortcode = shortcode_match.group(1)
    api_url = f"https://www.instagram.com/p/{shortcode}/?__a=1&__d=dis"
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 Instagram 324.0.0.0',
        'Accept': '*/*',
    }
    
    async with httpx.AsyncClient(headers=headers, follow_redirects=True, timeout=15.0) as client:
        res = await client.get(api_url)
        if res.status_code == 200:
            data = res.json()
            items = data.get('items', [])
            if items:
                item = items[0]
                downloaded = []
                
                # Carrusel
                if 'carousel_media' in item:
                    for idx, media in enumerate(item['carousel_media']):
                        candidates = media.get('image_versions2', {}).get('candidates', [])
                        if candidates:
                            img_url = candidates[0]['url']
                            path = f"downloads/{user_id}_{idx}.jpg"
                            r = await client.get(img_url)
                            with open(path, 'wb') as f:
                                f.write(r.content)
                            downloaded.append(path)
                    if downloaded:
                        return downloaded

                # Imagen única
                candidates = item.get('image_versions2', {}).get('candidates', [])
                if candidates:
                    img_url = candidates[0]['url']
                    path = f"downloads/{user_id}_single.jpg"
                    r = await client.get(img_url)
                    with open(path, 'wb') as f:
                        f.write(r.content)
                    return [path]

    raise Exception("API Instagram sin resultados.")

def download_ytdlp_engine(url: str, user_id: int):
    """Motor de descarga universal con soporte de cookies montadas en Render."""
    output_template = f"downloads/{user_id}_%(autonumber)s_%(id)s.%(ext)s"
    cookie_file = get_cookie_file()
    
    ydl_opts = {
        'format': 'best/bestvideo+bestaudio',
        'outtmpl': output_template,
        'quiet': True,
        'no_warnings': True,
        'nocheckcertificate': True,
        'age_limit': 0,
        'geo_bypass': True,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'es-ES,es;q=0.9,en;q=0.8',
            'Sec-Fetch-Mode': 'navigate',
        }
    }
    
    if cookie_file:
        print(f"✅ Usando archivo de cookies desde: {cookie_file}")
        ydl_opts['cookiefile'] = cookie_file
    else:
        print("⚠️ No se detectó archivo cookies.txt en el sistema.")

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])
    
    downloaded = glob.glob(f"downloads/{user_id}_*")
    valid_files = [f for f in downloaded if not f.endswith(('.part', '.ytdl')) and os.path.getsize(f) > 0]
    
    if not valid_files:
        raise Exception("yt-dlp no generó archivos válidos.")
        
    return valid_files

async def download_media_cascade(url: str, user_id: int):
    # 1. Instagram Fotos
    if "instagram.com/p/" in url:
        try:
            return await download_instagram_photos_direct(url, user_id)
        except Exception as e:
            print(f"Instagram Direct API falló: {e}")

    # 2. Motor principal yt-dlp (con cookies cargadas)
    try:
        return await asyncio.to_thread(download_ytdlp_engine, url, user_id)
    except Exception as e:
        print(f"yt-dlp falló: {e}")

    # 3. Fallback OpenGraph para fotos de Facebook/Webs
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        async with httpx.AsyncClient(headers=headers, follow_redirects=True, timeout=10.0) as client:
            res = await client.get(url)
            if res.status_code == 200:
                soup = BeautifulSoup(res.text, 'html.parser')
                meta_img = soup.find('meta', property='og:image')
                if meta_img and meta_img.get('content'):
                    img_res = await client.get(meta_img['content'])
                    target = f"downloads/{user_id}_meta.jpg"
                    with open(target, 'wb') as f:
                        f.write(img_res.content)
                    if os.path.exists(target) and os.path.getsize(target) > 0:
                        return [target]
    except Exception as e:
        print(f"Fallback meta image falló: {e}")

    raise Exception("Todos los métodos fallaron.")

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
        "Solo **envíame el enlace** de la publicación o video que deseas obtener."
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

    status_msg = await message.reply("🔎 **Procesando descarga...**", parse_mode="Markdown")
    downloaded_files = []

    try:
        downloaded_files = await download_media_cascade(url, user_id)

        if not downloaded_files:
            raise Exception("No se obtuvieron archivos.")

        for file_path in downloaded_files:
            ext = file_path.lower()
            if ext.endswith(('.mp4', '.mkv', '.mov', '.webm', '.ts', '.avi')):
                await message.reply_video(video=FSInputFile(file_path), caption="✅ **Video descargado con éxito.**")
            elif ext.endswith(('.jpg', '.jpeg', '.png', '.webp', '.heic')):
                await message.reply_photo(photo=FSInputFile(file_path), caption="✅ **Foto descargada con éxito.**")
            else:
                await message.reply_document(document=FSInputFile(file_path), caption="✅ **Archivo listo.**")

    except Exception as e:
        print(f"Error final procesando {url}: {e}")
        await message.reply("❌ No se pudo descargar el enlace. Verifica que la publicación exista y sea accesible.")
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
