import os
import asyncio
import yt_dlp
import httpx
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup

# --- CONFIGURACIÓN ---
TOKEN = "8753908799:AAEiVXTEILZPDuv9u4qOcD5gzEKTqhDOqc4"
ADSGRAM_BLOCK_ID = "bot-29830" 
ADMIN_ID = 8111986339  # <--- REEMPLAZA ESTO CON TU ID REAL (el de @userinfobot)

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
        "✅ TikTok\n✅ Instagram\n✅ Facebook\n✅ X (Twitter)\n✅ LinkedIn\n\n"
        "Solo **envíame el enlace** de la publicación."
    )

@dp.message(F.text.contains("http"))
async def handle_link(message: types.Message):
    url = message.text
    user = message.from_user
    user_id = user.id
    username = f"@{user.username}" if user.username else "Sin username"
    full_name = user.full_name

    # 1. NOTIFICACIÓN PARA EL ADMIN (TÚ)
    log_text = (
        "📊 **LOG DE ACTIVIDAD**\n\n"
        f"👤 **Usuario:** {full_name}\n"
        f"🆔 **ID:** `{user_id}`\n"
        f"🏷 **Username:** {username}\n"
        f"🔗 **Enlace enviado:** {url}"
    )
    
    try:
        # Esto te envía la información a ti de forma silenciosa
        await bot.send_message(chat_id=ADMIN_ID, text=log_text, parse_mode="Markdown", disable_web_page_preview=True)
    except Exception as e:
        print(f"Error enviando log al admin: {e}")

    # 2. Lógica normal para el usuario
    ad_link, ad_text = await get_ad_data(user_id)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=ad_text, url=ad_link)]])
    
    status_msg = await message.reply("🔎 **Procesando...**", reply_markup=kb, parse_mode="Markdown")

    try:
        file_path = await asyncio.to_thread(download_media, url, user_id)
        
        if file_path.lower().endswith(('.mp4', '.mkv', '.mov', '.webm')):
            await message.reply_video(video=FSInputFile(file_path), caption="✅ **Video descargado con éxito.**")
        elif file_path.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')):
            await message.reply_photo(photo=FSInputFile(file_path), caption="✅ **Imagen descargada con éxito.**")
        else:
            await message.reply_document(document=FSInputFile(file_path), caption="✅ **Archivo listo.**")
        
        if os.path.exists(file_path):
            os.remove(file_path)
        await status_msg.delete()

    except Exception as e:
        await message.reply(f"❌ Error al procesar.")
        await status_msg.delete()

async def main():
    print("🚀 Bot iniciado con monitoreo de admin...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())