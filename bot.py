import os
import asyncio
import glob
import yt_dlp
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

# --- MOTOR DE DESCARGA MULTI-MÉTODO (3 MÉTODOS EN CASCADA) ---

def download_method_1(url, base_template):
    """Método 1: Extracción directa de mejor calidad (Video / Foto)."""
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
    """Método 2: Bypass para redes sociales, Twitter/Instagram y restricciones."""
    ydl_opts = {
        'format': 'best[ext=mp4]/best',
        'outtmpl': base_template,
        'quiet': True,
        'no_warnings': True,
        'nocheckcertificate': True,
        'age_limit': 0,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1',
            'Accept-Language': 'es-ES,es;q=0.9,en;q=0.8',
            'Sec-Fetch-Mode': 'navigate',
        },
        'extract_flat': False,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        return ydl.prepare_filename(info)

def download_method_3(url, base_template):
    """Método 3: Extractor genérico y sitios externos complejos."""
    ydl_opts = {
        'format': 'b/bv*+ba/best',
        'outtmpl': base_template,
        'quiet': True,
        'no_warnings': True,
        'nocheckcertificate': True,
        'ignoreerrors': True,
        'geo_bypass': True,
        'socket_timeout': 20,
        'extractor_args': {
            'generic': ['impersonate'],
            'twitter': {'api': ['syndication']}
        }
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        if info:
            return ydl.prepare_filename(info)
        raise Exception("Extractor genérico no pudo procesar la URL.")

def download_media_cascade(url, user_id):
    """Prueba progresivamente los 3 métodos hasta completar la descarga."""
    output_template = f"downloads/{user_id}_%(id)s.%(ext)s"
    methods = [download_method_1, download_method_2, download_method_3]
    last_error = None

    for i, method in enumerate(methods, 1):
        try:
            print(f"🔄 Intentando descarga con Método {i} para: {url}")
            filepath = method(url, output_template)
            
            if filepath and os.path.exists(filepath):
                return filepath
                
            # Búsqueda por coincidencia de archivos generados
            matches = glob.glob(f"downloads/{user_id}_*")
            if matches:
                return matches[0]
                
        except Exception as e:
            print(f"⚠️ Método {i} falló: {e}")
            last_error = e
            continue

    raise Exception(f"Los 3 métodos fallaron. Último error: {last_error}")

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

    # Notificación privada al Administrador
    if ADMIN_ID != 0:
        log_text = (
            "📊 **LOG DE ACTIVIDAD**\n\n"
            f"👤 **Usuario:** {full_name}\n"
            f"🆔 **ID:** `{user_id}`\n"
            f"🏷 **Username:** {username}\n"
            f"🔗 **Enlace enviado:** {url}"
        )
        try:
            await bot.send_message(chat_id=ADMIN_ID, text=log_text, parse_mode="Markdown", disable_web_page_preview=True)
        except Exception as e:
            print(f"Error enviando log al admin: {e}")

    status_msg = await message.reply("🔎 **Procesando descarga...**", parse_mode="Markdown")
    file_path = None

    try:
        file_path = await asyncio.to_thread(download_media_cascade, url, user_id)

        if not file_path or not os.path.exists(file_path):
            raise Exception("Archivo no encontrado en el servidor.")

        ext = file_path.lower()
        if ext.endswith(('.mp4', '.mkv', '.mov', '.webm', '.ts')):
            await message.reply_video(video=FSInputFile(file_path), caption="✅ **Video descargado con éxito.**")
        elif ext.endswith(('.jpg', '.jpeg', '.png', '.webp')):
            await message.reply_photo(photo=FSInputFile(file_path), caption="✅ **Foto descargada con éxito.**")
        else:
            await message.reply_document(document=FSInputFile(file_path), caption="✅ **Archivo listo.**")

    except Exception as e:
        print(f"Error final procesando {url}: {e}")
        await message.reply("❌ No se pudo descargar el enlace. Verifica que la publicación sea pública.")
    finally:
        # Limpieza de archivos temporales del disco
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
