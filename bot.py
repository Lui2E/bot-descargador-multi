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

# --- MOTORES DE DESCARGA ---

async def download_instagram_photos_direct(url: str, user_id: int):
    """Extrae fotos de publicaciones y carruseles de Instagram usando la API Graph pública."""
    shortcode_match = re.search(r'/(?:p|reel)/([A-Za-z0-9_-]+)', url)
    if not shortcode_match:
        raise Exception("No se encontró shortcode de Instagram.")
    
    shortcode = shortcode_match.group(1)
    api_url = f"https://www.instagram.com/p/{shortcode}/?__a=1&__d=dis"
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 Instagram 324.0.0.0',
        'Accept': '*/*',
        'Accept-Language': 'es-ES,es;q=0.9,en;q=0.8',
    }
    
    async with httpx.AsyncClient(headers=headers, follow_redirects=True, timeout=15.0) as client:
        res = await client.get(api_url)
        if res.status_code == 200:
            data = res.json()
            items = data.get('items', [])
            if not items:
                raise Exception("Sin items en respuesta Instagram.")
            
            item = items[0]
            downloaded = []
            
            # Caso 1: Carrusel de imágenes
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

            # Caso 2: Imagen individual
            image_candidates = item.get('image_versions2', {}).get('candidates', [])
            if image_candidates:
                img_url = image_candidates[0]['url']
                path = f"downloads/{user_id}_single.jpg"
                r = await client.get(img_url)
                with open(path, 'wb') as f:
                    f.write(r.content)
                return [path]

    raise Exception("API directa de Instagram no respondió con imágenes válidas.")

def download_ytdlp_engine(url: str, user_id: int):
    """Motor robusto de yt-dlp con soporte estricto para sitios de streaming y adultos."""
    output_template = f"downloads/{user_id}_%(autonumber)s_%(id)s.%(ext)s"
    
    ydl_opts = {
        # Fuerza descarga del flujo de video real
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'outtmpl': output_template,
        'quiet': True,
        'no_warnings': True,
        'nocheckcertificate': True,
        'age_limit': 0,
        'geo_bypass': True,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Sec-Fetch-Mode': 'navigate',
        }
    }
    
    if os.path.exists("cookies.txt"):
        ydl_opts['cookiefile'] = 'cookies.txt'

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])
    
    downloaded = glob.glob(f"downloads/{user_id}_*")
    valid_files = [f for f in downloaded if not f.endswith(('.part', '.ytdl')) and os.path.getsize(f) > 0]
    
    if not valid_files:
        raise Exception("yt-dlp no completó la descarga.")
        
    return valid_files

async def download_media_cascade(url: str, user_id: int):
    # 1. Si es publicación de Instagram de fotos o post tradicional (/p/)
    if "instagram.com/p/" in url:
        try:
            return await download_instagram_photos_direct(url, user_id)
        except Exception as e:
            print(f"Instagram Direct API falló: {e}, probando yt-dlp...")

    # 2. Descarga por yt-dlp estándar
    try:
        return await asyncio.to_thread(download_ytdlp_engine, url, user_id)
    except Exception as e:
        print(f"yt-dlp falló: {e}")

    # 3. Fallback de imágenes generales
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

    # Log seguro al Admin
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
            raise Exception("No se obtuvieron archivos válidos.")

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
