import os
import asyncio
import yt_dlp
import httpx
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup
from flask import Flask
from threading import Thread

# --- CONFIGURACIÓN DE FLASK (KEEP-ALIVE PARA RENDER) ---
app = Flask('')

@app.route('/')
def home():
    return "Bot is alive!"

def run_web():
    # Render usa el puerto 10000 por defecto para Web Services
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# --- CONFIGURACIÓN DEL BOT ---
TOKEN = os.getenv("TOKEN")
ADSGRAM_BLOCK_ID = os.getenv("ADSGRAM_BLOCK_ID")
ADMIN_ID = int(os.getenv("ADMIN_ID", 0)) 

bot = Bot(token=TOKEN)
dp = Dispatcher()

if not os.path.exists("downloads"):
    os.makedirs("downloads")

# --- FUNCIONES DE APOYO ---

async def get_ad_data(user_id):
    try:
        url = f"https://api.adsgram.ai/adv?blockId={ADSGRAM_BLOCK_ID}&chatId={user_id}"
        async with httpx.AsyncClient() as client:
            response = await client.get(url, timeout=5)
            if response.status_code == 200:
                data = response.json()
                return data.get('link'), data.get('banner_text', '🎁 Oferta Especial')
    except:
        pass
    return "https://t.me/Adsgramoficial", "🎁 Patrocinado"

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
        "✅ TikTok, Instagram, Facebook, X y LinkedIn.\n\n"
        "Solo **envíame el enlace** de la publicación."
    )

@dp.message(F.text.contains("http"))
async def handle_link(message: types.Message):
    url = message.text
    user = message.from_user
    user_id = user.id
    username = f"@{user.username}" if user.username else "Sin username"
    full_name = user.full_name

    if ADMIN_ID != 0:
        log_text = (
            "📊 **LOG DE ACTIVIDAD**\n\n"
            f"👤 **Usuario:** {full_name}\n"
            f"🆔 **ID:** `{user_id}`\n"
            f"🔗 **Enlace:** {url}"
        )
        try:
            await bot.send_message(chat_id=ADMIN_ID, text=log_text, parse_mode="Markdown", disable_web_page_preview=True)
        except Exception as e:
            print(f"Error log admin: {e}")

    ad_link, ad_text = await get_ad_data(user_id)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=ad_text, url=ad_link)]])
    
    status_msg = await message.reply("🔎 **Procesando...**", reply_markup=kb, parse_mode="Markdown")

    try:
        file_path = await asyncio.to_thread(download_media, url, user_id)
        
        if not os.path.exists(file_path):
            raise Exception("Archivo no encontrado")

        file_input = FSInputFile(file_path)
        if file_path.lower().endswith(('.mp4', '.mkv', '.mov', '.webm')):
            await message.reply_video(video=file_input, caption="✅ **Video descargado.**")
        elif file_path.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')):
            await message.reply_photo(photo=file_input, caption="✅ **Imagen descargada.**")
        else:
            await message.reply_document(document=file_input, caption="✅ **Archivo listo.**")
        
        if os.path.exists(file_path):
            os.remove(file_path)
        await status_msg.delete()

    except Exception as e:
        await message.reply(f"❌ Error al procesar el enlace.")
        if status_msg:
            await status_msg.delete()

async def main():
    # Limpiamos webhooks para asegurar que el polling funcione bien en Render
    await bot.delete_webhook(drop_pending_updates=True)
    print("🚀 Bot iniciado en Render con Flask Keep-Alive...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    # 1. Lanzamos el servidor Flask en un hilo secundario
    Thread(target=run_web).start()
    # 2. Lanzamos el bot de Telegram en el bucle principal
    asyncio.run(main())
