import asyncio
import logging
import os
import random
import re
from datetime import datetime
from typing import List, Dict, Optional, Set, Union

# قراءة ملف .env يدويًا أو عبر dotenv لمنع الخطأ في المنصات المستضيفة
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    env_file = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(env_file):
        with open(env_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, val = line.split("=", 1)
                    os.environ.setdefault(key.strip(), val.strip().strip("'\""))

from telethon import TelegramClient, events, Button
from telethon.tl.functions.channels import InviteToChannelRequest, GetParticipantRequest
from telethon.tl.types import Channel, Chat, User
from telethon.errors import (
    UserPrivacyRestrictedError,
    FloodWaitError,
    UserAlreadyParticipantError,
    UserNotMutualContactError,
    UserChannelsTooMuchError,
    ChannelInvalidError,
    ChannelPrivateError
)

from database import Database


# إعداد logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# قراءة المتغيرات من .env
API_ID = int(os.getenv("API_ID", "123456"))
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

# تحويل القناة وحساب الأدمن لمجموعات
RAW_CHANNEL_ID = os.getenv("CHANNEL_ID", "0")
DEFAULT_CHANNEL_ID = int(RAW_CHANNEL_ID) if RAW_CHANNEL_ID.replace("-", "").isdigit() else RAW_CHANNEL_ID

RAW_ADMIN_IDS = os.getenv("ADMIN_IDS", "")
ADMIN_IDS: Set[int] = {int(x.strip()) for x in RAW_ADMIN_IDS.split(",") if x.strip().isdigit()}

# إعداد قاعدة البيانات
db = Database()

# تهيئة القناة الافتراضية إذا كانت محددة
if DEFAULT_CHANNEL_ID and DEFAULT_CHANNEL_ID != 0:
    db.save_channel(channel_id=DEFAULT_CHANNEL_ID, title="القناة الافتراضية", set_active=True)


class ForceSubscriptionBot:
    def __init__(self):
        # عميل البوت للتفاعل والواجهات
        self.bot = TelegramClient('bot_session', API_ID, API_HASH)
        # حالات المستخدمين المؤقتة
        self.user_states: Dict[int, dict] = {}
        # تتبع العمليات الجماعية النشطة لإتاحة الإيقاف الفوري
        self.active_bulk_tasks: Set[int] = set()

    def is_admin(self, user_id: int) -> bool:
        """فحص ما إذا كان المستخدم مسؤولاً"""
        if not ADMIN_IDS:
            return True  # إذا لم تكن هناك قائمة محددة يتاح للجميع
        return user_id in ADMIN_IDS

    async def start(self):
        """بدء تشغيل البوت"""
        if not BOT_TOKEN or BOT_TOKEN == 'your_bot_token':
            logger.error("❌ برجاء ضبط BOT_TOKEN و API_ID و API_HASH في ملف .env أولاً!")
            print("⚠️ برجاء تعديل ملف .env وكتابة بيانات البوت والتليجرام الخاصة بك.")
            return

        await self.bot.start(bot_token=BOT_TOKEN)
        bot_me = await self.bot.get_me()
        logger.info(f"✅ تم تشغيل البوت بنجاح: @{bot_me.username}")

        self.register_handlers()
        await self.bot.run_until_disconnected()

    def get_main_keyboard(self):
        """إنشاء لوحة التحكم الرئيسية بأزرار شفافة"""
        return [
            [Button.inline("👤 إضافة عضو فردي", b"cmd_add_user"), Button.inline("👥 إضافة جماعية", b"cmd_bulk_add")],
            [Button.inline("📊 الإحصائيات", b"cmd_stats"), Button.inline("📢 إدارة القناة", b"cmd_channel")],
            [Button.inline("📥 تصدير السجل", b"cmd_export"), Button.inline("❓ المساعدة", b"cmd_help")]
        ]

    def get_cancel_keyboard(self):
        """زر الإلغاء الشفاف"""
        return [[Button.inline("❌ إلغاء العملية", b"cmd_cancel")]]

    def register_handlers(self):
        """تسجيل جميع الأحداث والـ Handlers"""

        @self.bot.on(events.ChatAction)
        async def auto_delete_service_messages(event):
            """حذف رسائل النظام الإجبارية تلقائياً من الجروب عند إضافة أي عضو لإخفاء هوية المُضيف"""
            if event.user_added or event.user_joined:
                try:
                    await event.delete()
                    logger.info(f"🧹 تم حذف رسالة إشعار الإضافة التلقائية لـ {event.user_id} لضمان الخصوصية.")
                except Exception as e:
                    logger.warning(f"⚠️ تعذر حذف رسالة الإشعار الخدمية: {e}")

        @self.bot.on(events.NewMessage(pattern=r'^/start$'))
        async def start_handler(event):
            sender_id = event.sender_id
            if not self.is_admin(sender_id):
                await event.reply("⛔ **عذراً، هذا البوت مخصص للمسؤولين المعتمدين فقط.**")
                return

            active_chan = db.get_active_channel()
            chan_name = active_chan['title'] if active_chan else "غير محددة"
            chan_id = active_chan['channel_id'] if active_chan else "لا يوجد"

            msg_text = (
                "👋 **مرحباً بك في بوت الإضافة والإشتراك الإجباري المطور**\n\n"
                f"📢 **القناة النشطة حالياً:** {chan_name} (`{chan_id}`)\n"
                "🔒 **الخصوصية:** تتم الإضافة دون إظهار أي بيانات للمُضيف.\n\n"
                "اختر الخيار المطلوب من الأزرار التالية:"
            )
            await event.reply(msg_text, buttons=self.get_main_keyboard())

        @self.bot.on(events.NewMessage(pattern=r'^/help$'))
        async def help_cmd(event):
            await self.send_help(event)

        @self.bot.on(events.NewMessage(pattern=r'^/stats$'))
        async def stats_cmd(event):
            await self.send_stats(event)

        @self.bot.on(events.NewMessage(pattern=r'^/add_user$'))
        async def add_user_cmd(event):
            await self.prompt_add_user(event)

        @self.bot.on(events.NewMessage(pattern=r'^/bulk_add$'))
        async def bulk_add_cmd(event):
            await self.prompt_bulk_add(event)

        @self.bot.on(events.NewMessage(pattern=r'^/export$'))
        async def export_cmd(event):
            await self.export_logs(event)

        @self.bot.on(events.NewMessage(pattern=r'^/channel'))
        async def channel_cmd(event):
            await self.manage_channels(event)

        @self.bot.on(events.CallbackQuery)
        async def callback_handler(event):
            sender_id = event.sender_id
            if not self.is_admin(sender_id):
                await event.answer("⛔ غير مسموح لك باستخدام هذا البوت.", alert=True)
                return

            data = event.data

            if data == b"cmd_main":
                active_chan = db.get_active_channel()
                chan_name = active_chan['title'] if active_chan else "غير محددة"
                chan_id = active_chan['channel_id'] if active_chan else "لا يوجد"
                msg_text = (
                    "👋 **لوحة التحكم الرئيسية**\n\n"
                    f"📢 **القناة النشطة:** {chan_name} (`{chan_id}`)\n\n"
                    "اختر الخيار المطلوب:"
                )
                await event.edit(msg_text, buttons=self.get_main_keyboard())

            elif data == b"cmd_add_user":
                await event.answer()
                await self.prompt_add_user(event)

            elif data == b"cmd_bulk_add":
                await event.answer()
                await self.prompt_bulk_add(event)

            elif data == b"cmd_stats":
                await event.answer()
                await self.send_stats(event, edit=True)

            elif data == b"cmd_channel":
                await event.answer()
                await self.manage_channels(event, edit=True)

            elif data == b"cmd_export":
                await event.answer()
                await self.export_logs(event)

            elif data == b"cmd_help":
                await event.answer()
                await self.send_help(event, edit=True)

            elif data == b"cmd_cancel":
                if sender_id in self.user_states:
                    del self.user_states[sender_id]
                await event.edit("✅ **تم إلغاء العملية الجارية.**", buttons=[[Button.inline("🔙 القائمة الرئيسية", b"cmd_main")]])

            elif data == b"stop_bulk":
                if sender_id in self.active_bulk_tasks:
                    self.active_bulk_tasks.remove(sender_id)
                    await event.answer("🛑 جاري إيقاف عملية الإضافة الجماعية...", alert=True)
                else:
                    await event.answer("⚠️ لا توجد عملية إضافة جماعية نشطة حالياً.", alert=True)

            elif data.startswith(b"confirm_add:"):
                user_key = data.decode().split(":")[1]
                await self.execute_single_add(event, user_key)

            elif data.startswith(b"set_chan:"):
                chan_id = int(data.decode().split(":")[1])
                db.save_channel(channel_id=chan_id, title=f"القناة {chan_id}", set_active=True)
                await event.answer("✅ تم تعيين القناة النشطة بنجاح!", alert=True)
                await self.manage_channels(event, edit=True)

        @self.bot.on(events.NewMessage)
        async def message_input_handler(event):
            sender_id = event.sender_id
            if event.text.startswith('/'):
                return  # تجاهل الأوامر
            if not self.is_admin(sender_id):
                return

            if sender_id in self.user_states:
                state_data = self.user_states[sender_id]
                step = state_data.get('step')

                if step == 'awaiting_single_user':
                    await self.process_single_user_input(event)

                elif step == 'awaiting_bulk_users':
                    await self.process_bulk_users_input(event)

                elif step == 'awaiting_channel_id':
                    await self.process_new_channel_input(event)

    async def prompt_add_user(self, event):
        sender_id = event.sender_id
        self.user_states[sender_id] = {'step': 'awaiting_single_user'}
        text = (
            "👤 **إضافة عضو فردي**\n\n"
            "يرجى إرسال إحدى البيانات التالية للعضو:\n"
            "1️⃣ **اسم المستخدم:** `@username`\n"
            "2️⃣ **معرف الحساب (ID):** `123456789`\n"
            "3️⃣ **تحويل رسالة:** تحويل أي رسالة من العضو إلي هنا مباشرة."
        )
        if isinstance(event, events.CallbackQuery.Event):
            await event.edit(text, buttons=self.get_cancel_keyboard())
        else:
            await event.reply(text, buttons=self.get_cancel_keyboard())

    async def prompt_bulk_add(self, event):
        sender_id = event.sender_id
        self.user_states[sender_id] = {'step': 'awaiting_bulk_users'}
        text = (
            "👥 **إضافة مجموعة أعضاء (Bulk Add)**\n\n"
            "أرسل قائمة الأعضاء بـ إحدى الطريقتين:\n"
            "1️⃣ **رسالة نصية:** أرسل اليوزرات أو المعرفات كل يوزر في سطر مستقل.\n"
            "2️⃣ **ملف نصي (.txt):** قم برفع ملف نصي يحتوي على يوزرات أو IDs الأعضاء.\n\n"
            "⏱️ *سيتم إضافة الأعضاء مع فواصل زمنية آمنة لحماية البوت من الحظر.*"
        )
        if isinstance(event, events.CallbackQuery.Event):
            await event.edit(text, buttons=self.get_cancel_keyboard())
        else:
            await event.reply(text, buttons=self.get_cancel_keyboard())

    async def send_help(self, event, edit=False):
        text = (
            "🆘 **دليل وتوجيهات الاستخدام**\n\n"
            "1️⃣ **تحديد القناة:** أضف البوت كـ أدمن مع صلاحية `إضافة أعضاء (Add Members)` في القناة.\n"
            "2️⃣ **الإضافة الفردية:** أرسل /add_user ثم أرسل اليوزر أو تحويل رسالة.\n"
            "3️⃣ **الإضافة الجماعية:** أرسل /bulk_add مع قائمة اليوزرات أو ملف `.txt`.\n"
            "4️⃣ **الحماية والتأخير:** يقوم البوت بعمل فواصل عشوائية بين الطلبات لمنع حظر الحسابات.\n"
            "5️⃣ **سجل السجلات:** يمكنك تصدير ملف السجلات في أي وقت عن طريق /export."
        )
        buttons = [[Button.inline("🔙 القائمة الرئيسية", b"cmd_main")]]
        if edit and isinstance(event, events.CallbackQuery.Event):
            await event.edit(text, buttons=buttons)
        else:
            await event.reply(text, buttons=buttons)

    async def send_stats(self, event, edit=False):
        stats = db.get_stats()
        active_chan = db.get_active_channel()
        chan_title = active_chan['title'] if active_chan else "غير محددة"

        text = (
            "📊 **إحصائيات البوت والعمليات**\n\n"
            f"📢 **القناة النشطة:** {chan_title}\n"
            f"📥 **إجمالي المحاولات:** `{stats['total']}`\n"
            f"✅ **العمليات الناجحة:** `{stats['success']}`\n"
            f"❌ **العمليات الفاشلة:** `{stats['failed']}`\n"
            f"📅 **إضافات اليوم:** `{stats['today']}`\n"
            f"🔒 **قيود الخصوصية (Privacy Restricted):** `{stats['privacy_errors']}`\n"
        )
        buttons = [[Button.inline("🔄 تحديث", b"cmd_stats"), Button.inline("🔙 القائمة الرئيسية", b"cmd_main")]]
        if edit and isinstance(event, events.CallbackQuery.Event):
            await event.edit(text, buttons=buttons)
        else:
            await event.reply(text, buttons=buttons)

    async def export_logs(self, event):
        logs_text = db.export_logs_text()
        file_path = os.path.join(os.path.dirname(__file__), "add_logs.txt")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(logs_text)

        await self.bot.send_file(
            event.chat_id,
            file_path,
            caption="📥 **تقرير السجلات وإحصائيات الإضافة الكلية**",
            buttons=[[Button.inline("🔙 القائمة الرئيسية", b"cmd_main")]]
        )
        if os.path.exists(file_path):
            os.remove(file_path)

    async def manage_channels(self, event, edit=False):
        active_chan = db.get_active_channel()
        all_chans = db.get_all_channels()

        text = "📢 **إدارة القنوات المستهدفة**\n\n"
        if active_chan:
            text += f"🟢 **القناة النشطة حالياً:** {active_chan['title']} (`{active_chan['channel_id']}`)\n\n"
        else:
            text += "🔴 **لم يتم تحديد قناة نشطة بعد.**\n\n"

        buttons = []
        if all_chans:
            text += "📋 **القنوات المسجلة لديك:**\n"
            for ch in all_chans:
                status_icon = "✅" if active_chan and ch['channel_id'] == active_chan['channel_id'] else "⚪"
                text += f"{status_icon} {ch['title']} (`{ch['channel_id']}`)\n"
                if not (active_chan and ch['channel_id'] == active_chan['channel_id']):
                    buttons.append([Button.inline(f"تفعيل {ch['title']}", f"set_chan:{ch['channel_id']}".encode())])

        text += "\nلإضافة قناة جديدة، قم بكتابة أمر: `/channel <CHANNEL_ID_OR_USERNAME>`"

        buttons.append([Button.inline("🔙 القائمة الرئيسية", b"cmd_main")])

        if edit and isinstance(event, events.CallbackQuery.Event):
            await event.edit(text, buttons=buttons)
        else:
            await event.reply(text, buttons=buttons)

    async def process_new_channel_input(self, event):
        msg = event.text.strip()
        sender_id = event.sender_id

        try:
            entity = await self.bot.get_entity(int(msg) if msg.replace("-", "").isdigit() else msg)
            title = getattr(entity, 'title', str(entity.id))
            db.save_channel(entity.id, title, getattr(entity, 'username', ''), set_active=True)
            del self.user_states[sender_id]
            await event.reply(f"✅ **تمت إضافة وتفعيل القناة:** {title} (`{entity.id}`)", buttons=[[Button.inline("🔙 القائمة الرئيسية", b"cmd_main")]])
        except Exception as e:
            await event.reply(f"❌ **تعذر التعرف على القناة:** {str(e)}\nتأكد من معرف القناة وأن البوت أدمن فيها.")

    async def process_single_user_input(self, event):
        sender_id = event.sender_id
        message = event.text.strip() if event.text else ""

        # محاولة استخراج المستخدم من التوجيه أو النص
        user_entity = None
        if event.message.fwd_from and event.message.fwd_from.from_id:
            try:
                user_entity = await self.bot.get_entity(event.message.fwd_from.from_id)
            except Exception as e:
                logger.warning(f"Failed to fetch forwarded user: {e}")

        if not user_entity and message:
            try:
                target = int(message) if message.isdigit() else message
                user_entity = await self.bot.get_entity(target)
            except Exception as e:
                logger.warning(f"Failed to fetch user by message: {e}")

        if not user_entity or not isinstance(user_entity, User):
            await event.reply(
                "❌ **لم أتمكن من التعرف على العضو.**\n"
                "تأكد من كتابة اليوزر بشكل صحيح مثل `@username` أو معرف رقمي صحيح أو تحويل رسالة منه.",
                buttons=self.get_cancel_keyboard()
            )
            return

        user_id = user_entity.id
        username = user_entity.username or ""
        first_name = user_entity.first_name or ""
        last_name = user_entity.last_name or ""
        full_name = f"{first_name} {last_name}".strip()

        # حفظ الجلسة المؤقتة
        user_key = str(user_id)
        self.user_states[sender_id] = {
            'step': 'confirm_single_add',
            'user_info': {
                'id': user_id,
                'username': username,
                'name': full_name,
                'entity': user_entity
            }
        }

        active_chan = db.get_active_channel()
        chan_title = active_chan['title'] if active_chan else "القناة الحالية"

        text = (
            "🔍 **تفاصيل العضو للـإضافة:**\n\n"
            f"👤 **الاسم:** {full_name}\n"
            f"🔹 **اليوزر:** @{username if username else 'لا يوجد'}\n"
            f"🆔 **ID:** `{user_id}`\n"
            f"📢 **المستهدف:** {chan_title}\n\n"
            "هل ترغب في إضافة هذا العضو الآن؟"
        )

        buttons = [
            [Button.inline("✅ تأكيد الإضافة", f"confirm_add:{user_key}".encode()), Button.inline("❌ إلغاء", b"cmd_cancel")]
        ]
        await event.reply(text, buttons=buttons)

    async def execute_single_add(self, event, user_key: str):
        sender_id = event.sender_id
        state = self.user_states.get(sender_id, {})
        user_info = state.get('user_info')

        if not user_info:
            await event.edit("❌ **انتهت صلاحية هذه العملية.**", buttons=[[Button.inline("🔙 القائمة الرئيسية", b"cmd_main")]])
            return

        active_chan = db.get_active_channel()
        if not active_chan:
            await event.edit("❌ **لا توجد قناة نشطة مسجلة حالياً!** برجاء تحديد قناة من الإعدادات.", buttons=[[Button.inline("📢 إدارة القنوات", b"cmd_channel")]])
            return

        target_channel = active_chan['channel_id']

        try:
            await self.bot(InviteToChannelRequest(target_channel, [user_info['entity']]))
            db.log_add(user_info['id'], user_info['username'], user_info['name'], sender_id, "success", "", target_channel)

            await event.edit(
                "✅ **تمت إضافة العضو بنجاح!**\n\n"
                f"👤 **الاسم:** {user_info['name']}\n"
                f"🆔 **ID:** `{user_info['id']}`\n"
                "🔒 **ملاحظة:** تمت الإضافة بشرط الخصوصية الكامل دون ظهور اسم المضيف.",
                buttons=[[Button.inline("➕ إضافة عضو آخر", b"cmd_add_user"), Button.inline("🔙 الرئيسية", b"cmd_main")]]
            )

        except UserPrivacyRestrictedError:
            db.log_add(user_info['id'], user_info['username'], user_info['name'], sender_id, "privacy_restricted", "إعدادات الخصوصية تمنع الإضافة", target_channel)
            await event.edit(
                "❌ **تعذرت الإضافة - خطأ في الخصوصية:**\n"
                "إعدادات حساب العضو تمنع إضافته للمجموعات/القنوات تلقائياً.",
                buttons=[[Button.inline("🔙 القائمة الرئيسية", b"cmd_main")]]
            )
        except UserAlreadyParticipantError:
            db.log_add(user_info['id'], user_info['username'], user_info['name'], sender_id, "already_participant", "العضو موجود بالفعل في القناة", target_channel)
            await event.edit("⚠️ **العضو مشترك بالفعل في القناة!**", buttons=[[Button.inline("🔙 القائمة الرئيسية", b"cmd_main")]])
        except FloodWaitError as e:
            db.log_add(user_info['id'], user_info['username'], user_info['name'], sender_id, "flood_wait", f"FloodWait {e.seconds}s", target_channel)
            await event.edit(f"⏳ **تنبيه حماية تليجرام (Flood Wait):**\nيرجى الانتظار لمدة {e.seconds} ثانية قبل إعادة المحاولة.", buttons=[[Button.inline("🔙 القائمة الرئيسية", b"cmd_main")]])
        except Exception as e:
            db.log_add(user_info['id'], user_info['username'], user_info['name'], sender_id, "failed", str(e), target_channel)
            await event.edit(f"❌ **حدث خطأ أثناء الإضافة:** {str(e)}", buttons=[[Button.inline("🔙 القائمة الرئيسية", b"cmd_main")]])

        finally:
            if sender_id in self.user_states:
                del self.user_states[sender_id]

    async def process_bulk_users_input(self, event):
        sender_id = event.sender_id
        text_content = ""

        # فحص إذا تم إرسال ملف نصي
        if event.message.file and event.message.file.name and event.message.file.name.endswith('.txt'):
            file_bytes = await event.message.download_media(bytes)
            text_content = file_bytes.decode('utf-8', errors='ignore')
        elif event.text:
            text_content = event.text

        # استخراج كافة اليوزرات والـ IDs وإزالة التكرار فورا بالذاكرة
        lines = [line.strip() for line in text_content.splitlines() if line.strip()]
        targets = []
        seen = set()
        for line in lines:
            cleaned = line.replace("https://t.me/", "").replace("@", "").strip()
            if cleaned and cleaned not in seen:
                seen.add(cleaned)
                targets.append(cleaned)

        if not targets:
            await event.reply("❌ **لم يتم العثور على أية يوزرات أو معرفات صالحة في القائمة!**", buttons=self.get_cancel_keyboard())
            return

        active_chan = db.get_active_channel()
        if not active_chan:
            await event.reply("❌ **برجاء تحديد القناة النشطة أولاً.**", buttons=[[Button.inline("📢 إدارة القنوات", b"cmd_channel")]])
            return

        target_channel = active_chan['channel_id']
        del self.user_states[sender_id]

        # تفعيل تتبع العملية الجماعية لإمكانية الإيقاف
        self.active_bulk_tasks.add(sender_id)

        stop_button = [[Button.inline("🛑 إيقاف الإضافة الجماعية", b"stop_bulk")]]
        status_msg = await event.reply(
            f"🚀 **بدء عملية الإضافة الجماعية ({len(targets)} عضو فريد)...**\n\n"
            "⏳ جاري معالجة الأعضاء مع تطبيق الفواصل الزمنية الآمنة...",
            buttons=stop_button
        )

        success_count = 0
        failed_count = 0
        privacy_count = 0

        delay_min = int(os.getenv("DEFAULT_DELAY_MIN", "3"))
        delay_max = int(os.getenv("DEFAULT_DELAY_MAX", "7"))

        for idx, item in enumerate(targets, start=1):
            # فحص خيار الإيقاف السريع
            if sender_id not in self.active_bulk_tasks:
                await status_msg.edit(
                    f"⏹️ **تم إيقاف عملية الإضافة الجماعية يدوياً.**\n\n"
                    f"📊 تم إكمال `{idx-1}` من أصل `{len(targets)}` عضو.\n"
                    f"✅ ناجحة: `{success_count}` | ❌ فاشلة: `{failed_count}`",
                    buttons=[[Button.inline("🔙 الرئيسية", b"cmd_main")]]
                )
                return

            try:
                # التعرف على الكيان
                target_obj = int(item) if item.isdigit() else item
                entity = await self.bot.get_entity(target_obj)

                if isinstance(entity, User):
                    await self.bot(InviteToChannelRequest(target_channel, [entity]))
                    success_count += 1
                    db.log_add(entity.id, entity.username, f"{entity.first_name or ''} {entity.last_name or ''}".strip(), sender_id, "success", "", target_channel)
                else:
                    failed_count += 1
                    db.log_add(None, str(item), "", sender_id, "failed", "ليس حساب مستخدم", target_channel)

            except UserPrivacyRestrictedError:
                privacy_count += 1
                failed_count += 1
                db.log_add(None, str(item), "", sender_id, "privacy_restricted", "إعدادات الخصوصية تمنع الإضافة", target_channel)
            except UserAlreadyParticipantError:
                success_count += 1
                db.log_add(None, str(item), "", sender_id, "already_participant", "موجود مسبقاً", target_channel)
            except FloodWaitError as e:
                db.log_add(None, str(item), "", sender_id, "flood_wait", f"انتظار {e.seconds}s", target_channel)
                await status_msg.edit(f"⏳ **انتظار حماية التليجرام (FloodWait):** انتظر {e.seconds} ثانية...", buttons=stop_button)
                await asyncio.sleep(e.seconds)
            except Exception as e:
                failed_count += 1
                db.log_add(None, str(item), "", sender_id, "failed", str(e), target_channel)

            # تحديث شريط التقدم كل 3 أعضاء أو في النهاية
            if idx % 3 == 0 or idx == len(targets):
                try:
                    await status_msg.edit(
                        f"🔄 **تقدم عملية الإضافة الجماعية ({idx}/{len(targets)}):**\n\n"
                        f"✅ ناجحة: `{success_count}`\n"
                        f"❌ فاشلة: `{failed_count}` (منها `{privacy_count}` بسبب الخصوصية)\n"
                        f"⏳ جاري الانتقال للعضو التالي...",
                        buttons=stop_button
                    )
                except Exception:
                    pass

            # فاصل زمني عشوائي آمن بين الإضافات
            if idx < len(targets) and sender_id in self.active_bulk_tasks:
                sleep_time = random.randint(delay_min, delay_max)
                await asyncio.sleep(sleep_time)

        if sender_id in self.active_bulk_tasks:
            self.active_bulk_tasks.remove(sender_id)

        await status_msg.edit(
            f"🎉 **التقرير النهائي لعملية الإضافة الجماعية:**\n\n"
            f"📊 **إجمالي الأعضاء:** `{len(targets)}`\n"
            f"✅ **تمت الإضافة بنجاح:** `{success_count}`\n"
            f"❌ **تعذرت إضافتهم:** `{failed_count}`\n"
            f"🔒 **بسبب قيود الخصوصية:** `{privacy_count}`",
            buttons=[[Button.inline("📥 تصدير التقرير", b"cmd_export"), Button.inline("🔙 الرئيسية", b"cmd_main")]]
        )


async def main():
    bot_app = ForceSubscriptionBot()
    await bot_app.start()

if __name__ == "__main__":
    asyncio.run(main())
