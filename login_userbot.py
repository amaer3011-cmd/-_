import asyncio
import os
from dotenv import load_dotenv
from telethon import TelegramClient

load_dotenv()

API_ID = int(os.getenv("API_ID", "123456"))
API_HASH = os.getenv("API_HASH", "")

async def main():
    print("=" * 60)
    print("🤖 أداة تسجيل دخول حساب Userbot لسحب الأعضاء من القنوات المغلقة")
    print("=" * 60)
    
    if API_ID == 123456 or not API_HASH:
        print("❌ برجاء ضبط API_ID و API_HASH في ملف .env أولاً!")
        return

    session_path = os.path.join(os.path.dirname(__file__), "user_session")
    client = TelegramClient(session_path, API_ID, API_HASH)

    await client.start()
    me = await client.get_me()
    
    print("\n✅ تم تسجيل الدخول بنجاح للحساب:")
    print(f"👤 الاسم: {me.first_name} {me.last_name or ''}")
    print(f"🔹 اليوزر: @{me.username or 'لا يوجد'}")
    print(f"🆔 ID: {me.id}")
    print("\n🎉 تم إنشاء ملف الجلسة 'user_session.session' بنجاح!")
    print("الآن سيتسنى للبوت سحب كافة الأعضاء من أي قناة مغلقة دون الحاجة لـ أدمن!")
    
    await client.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
