import os
import asyncio
import yt_dlp
import httpx
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup
from flask import Flask, request
from threading import Thread

# --- CONFIGURACIÓN DE FLASK (KEEP-ALIVE + WEBHOOK DE RECOMPENSA) ---
app = Flask('')

# Guardamos aquí el event loop principal del bot para poder
# enviar mensajes desde el hilo de Flask (que es distinto al del bot)
main_loop = None

@app.route('/')
def home():
    return "Bot is alive!"

@app.route('/reward')
def reward():
    """
    AdsGram llamará a esta ruta cuando un usuario complete un anuncio.
    Ejemplo de llamada real: https://tu-app.onrender.com/reward?userid=123456789
    """
    user_id = request.args.get('userid')
    if user_id and main_loop:
        async def send_reward():
            try:
                await bot.send_message(
                    chat_id=int(user_id),
                    text="🎉 **¡Gracias por ver el anuncio!** Tu recompensa fue registrada.",
                    parse_mode="Markdown"
                )
            except Exception as e:
                print(f"Error enviando recompensa a {user_id}: {e}")

        asyncio.run_coroutine_threadsafe(send_reward(), main_loop)
        print(f"✅ Recompensa procesada para userid={user_id}")
    else:
        print(f"⚠️ Petición a /reward sin userid válido o loop no listo: {user_id}")
    return "OK", 200

def run_web():
    # Render asigna un puerto dinámico en la variable de entorno PORT
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# --- CONFIGURACIÓN DEL BOT ---
TOKEN = os.getenv("TOKEN")
ADSGRAM_BLOCK_ID = os.getenv("ADSGRAM_BLOCK_ID")  # solo el número, sin el prefijo "bot-"
ADSGRAM_TOKEN = os.getenv("ADSGRAM_TOKEN")        # token de tu cuenta AdsGram
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))

bot = Bot(token=TOKEN)
dp = Dispatcher()

if not os.path.exists("downloads"):
    os.makedirs("downloads")

# --- FUNCIONES DE APOYO ---
async def get_ad_data(user_id):
    try:
        url = (
            f"https://api.adsgram.ai/advbot"
            f"?tgid={user_id}&blockid={ADSGRAM_BLOCK_ID}&language=es&token={ADSGRAM_TOKEN}"
        )
        async with httpx.AsyncClient() as client:
            response = await client.get(url, timeout=5)
            if response.status_code == 200:
                data = response.json()
                click_url = data.get('click_url')
                button_name = data.get('button_name', '🎁 Oferta Especial')
                if click_url:
                    return click_url, button_name
            else:
                print(f"AdsGram status {response.status_code}: {response.text}")
    except Exception as e:
        print(f"Error AdsGram: {e}")
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
    username = user.username if user.username else "Sin username"
    full_name = user.full_name
    log_text = (
        "📊 **LOG DE ACTIVIDAD**\n\n"
        f"👤 **Usuario:** {full_name}\n"
        f"🆔 **ID:** `{user_id}`\n"
        f"🏷 **Username:** {username}\n"
        f"🔗 **Enlace enviado:** {url}"
    )

    try:
        if ADMIN_ID != 0:
            await bot.send_message(chat_id=ADMIN_ID, text=log_text, parse_mode="Markdown", disable_web_page_preview=True)
    except Exception as e:
        print(f"Error enviando log al admin: {e}")

    ad_link, ad_text = await get_ad_data(user_id)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=ad_text, url=ad_link)]])

    status_msg = await message.reply("🔎 **Procesando...**", reply_markup=kb, parse_mode="Markdown")
    try:
        file_path = await asyncio.to_thread(download_media, url, user_id)

        if not os.path.exists(file_path):
            raise Exception("Archivo no encontrado")
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
        await message.reply("❌ Error al procesar el enlace.")
        if status_msg:
            await status_msg.delete()

async def main():
    global main_loop
    main_loop = asyncio.get_running_loop()  # guardamos el loop para usarlo desde Flask
    await bot.delete_webhook(drop_pending_updates=True)
    print("🚀 Bot iniciado con Flask (Keep-Alive) activo...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    Thread(target=run_web).start()
    asyncio.run(main())
