import os
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

# --- MOTOR DE DESCARGA MULTI-MÉTODO ---

def download_method_1(url, base_template):
    """Método 1: yt-dlp estándar optimizado."""
    ydl_opts = {
        'format': 'bestvideo+bestaudio/best',
        'outtmpl': base_template,
        'quiet': True,
        'no_warnings': True,
        'nocheckcertificate': True,
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        return ydl.prepare_filename(info)

def download_method_2(url, base_template):
    """Método 2: yt-dlp con headers móviles de Instagram/Twitter."""
    ydl_opts = {
        'format': 'best[ext=mp4]/best',
        'outtmpl': base_template,
        'quiet': True,
        'no_warnings': True,
        'nocheckcertificate': True,
        'age_limit': 0,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 Instagram 324.0.0.0',
            'Accept': '*/*',
        },
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        return ydl.prepare_filename(info)

def download_method_cobalt(url, user_id):
    """Método 3: Bypass mediante API pública externa (Cobalt) para contenido restringido."""
    target_path = f"downloads/{user_id}_cobalt.mp4"
    cobalt_instances = [
        "https://api.cobalt.tools/api/json",
        "https://cobalt-api.kwiatekm.pl/api/json"
    ]
    
    for endpoint in cobalt_instances:
        try:
            with httpx.Client(timeout=20.0) as client:
                res = client.post(
                    endpoint,
                    headers={"Accept": "application/json", "Content-Type": "application/json"},
                    json={"url": url, "vQuality": "720"}
                )
                if res.status_code == 200:
                    data = res.json()
                    download_url = data.get("url")
                    if download_url:
                        # Descargar el stream directo del archivo
                        with client.stream("GET", download_url) as r:
                            with open(target_path, "wb") as f:
                                for chunk in r.iter_bytes(chunk_size=8192):
                                    f.write(chunk)
                        if os.path.exists(target_path) and os.path.getsize(target_path) > 0:
                            return target_path
        except Exception as err:
            print(f"Instancia {endpoint} falló: {err}")
            continue

    raise Exception("Bypass externo no pudo extraer el video.")

def download_media_cascade(url, user_id):
    """Ejecuta los 3 métodos en orden."""
    output_template = f"downloads/{user_id}_%(id)s.%(ext)s"

    # Intento 1
    try:
        f = download_method_1(url, output_template)
        if f and os.path.exists(f): return f
    except Exception as e:
        print(f"Método 1 falló: {e}")

    # Intento 2
    try:
        f = download_method_2(url, output_template)
        if f and os.path.exists(f): return f
    except Exception as e:
        print(f"Método 2 falló: {e}")

    # Intento 3 (API externa de bypass para restricciones de Instagram/TikTok)
    try:
        f = download_method_cobalt(url, user_id)
        if f and os.path.exists(f): return f
    except Exception as e:
        print(f"Método 3 (Cobalt) falló: {e}")

    # Chequeo final de archivos descargados
    matches = glob.glob(f"downloads/{user_id}_*")
    if matches:
        return matches[0]

    raise Exception("No fue posible descargar el video tras probar todos los métodos.")

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
        file_path = await asyncio.to_thread(download_media_cascade, url, user_id)

        if not file_path or not os.path.exists(file_path):
            raise Exception("Archivo no encontrado tras la descarga.")

        ext = file_path.lower()
        if ext.endswith(('.mp4', '.mkv', '.mov', '.webm', '.ts')):
            await message.reply_video(video=FSInputFile(file_path), caption="✅ **Video descargado con éxito.**")
        elif ext.endswith(('.jpg', '.jpeg', '.png', '.webp')):
            await message.reply_photo(photo=FSInputFile(file_path), caption="✅ **Foto descargada con éxito.**")
        else:
            await message.reply_document(document=FSInputFile(file_path), caption="✅ **Archivo listo.**")

    except Exception as e:
        print(f"Error procesando {url}: {e}")
        await message.reply("❌ No se pudo descargar el enlace. Verifica que la publicación sea pública.")
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
