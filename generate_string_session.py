import asyncio
import os
from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.sessions import StringSession

load_dotenv()

API_ID = int(os.getenv("API_ID", "123456"))
API_HASH = os.getenv("API_HASH", "")

async def main():
    print("=" * 70)
    print("🔑 مولّد كود الجلسة النصية (String Session Generator) للسيرفرات")
    print("=" * 70)
    
    if API_ID == 123456 or not API_HASH:
        print("❌ برجاء ضبط API_ID و API_HASH في ملف .env أولاً!")
        return

    print("جاري الاتصال بسيرفرات تليجرام لتوليد الكود...")
    client = TelegramClient(StringSession(), API_ID, API_HASH)
    await client.start()

    session_string = client.session.save()
    me = await client.get_me()

    print("\n✅ تم تسجيل الدخول بنجاح وتوليد كود الجلسة!")
    print(f"👤 الحساب: {me.first_name} (@{me.username or 'بدون يوزر'})")
    print("\n" + "=" * 70)
    print("📋 كود الجلسة (USERBOT_STRING_SESSION):")
    print(session_string)
    print("=" * 70)

    # حفظ الكود في ملف .env تلقائياً
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(env_path):
        with open(env_path, "a", encoding="utf-8") as f:
            f.write(f"\nUSERBOT_STRING_SESSION={session_string}\n")
        print("\n✅ تم حفظ الكود تلقائياً داخل ملف .env المحلي!")
        print("💡 لسيرفر الاستضافة (Docker/Render/Heroku): انسخ كود USERBOT_STRING_SESSION وأضفه في متغيرات بيئة السيرفر (Environment Variables).")

    await client.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
