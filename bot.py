import os
import asyncio
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
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))

bot = Bot(token=TOKEN)
dp = Dispatcher()

if not os.path.exists("downloads"):
    os.makedirs("downloads")

# --- FUNCIONES DE APOYO ---

def download_media(url, user_id):
    output_template = f"downloads/{user_id}_%(title).15s.%(ext)s"
    ydl_opts = {
        'format': 'best',
        'outtmpl': output_template,
        'quiet': True,
        'no_warnings': True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        return ydl.prepare_filename(info)

# --- MANEJADORES ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.reply(
        "👋 **¡Bienvenido al Descargador Pro!**\n\n"
        "Puedo bajar contenido de:\n"
        "✅ TikTok\n✅ Instagram\n✅ Facebook\n✅ X (Twitter)\n✅ LinkedIn\n\n"
        "Solo **envíame el enlace** de la publicación."
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
            f"🔗 **Enlace enviado:** {url}"
        )
        try:
            await bot.send_message(chat_id=ADMIN_ID, text=log_text, parse_mode="Markdown", disable_web_page_preview=True)
        except Exception as e:
            print(f"Error enviando log al admin: {e}")

    # Mensaje de estado simple sin botones de anuncios
    status_msg = await message.reply("🔎 **Procesando...**", parse_mode="Markdown")
    file_path = None

    try:
        file_path = await asyncio.to_thread(download_media, url, user_id)

        if not file_path or not os.path.exists(file_path):
            raise Exception("Archivo no encontrado")

        ext = file_path.lower()
        if ext.endswith(('.mp4', '.mkv', '.mov', '.webm')):
            await message.reply_video(video=FSInputFile(file_path), caption="✅ **Video descargado con éxito.**")
        elif ext.endswith(('.jpg', '.jpeg', '.png', '.webp')):
            await message.reply_photo(photo=FSInputFile(file_path), caption="✅ **Imagen descargada con éxito.**")
        else:
            await message.reply_document(document=FSInputFile(file_path), caption="✅ **Archivo listo.**")

    except Exception as e:
        print(f"Error procesando {url}: {e}")
        await message.reply("❌ Error al procesar el enlace. Verifica que la publicación sea pública.")
    finally:
        # Elimina el archivo local descargado y borra el mensaje "Procesando..."
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
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
