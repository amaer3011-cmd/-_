import sqlite3
from datetime import datetime
import os
from typing import List, Dict, Any, Optional

DB_FILE = os.path.join(os.path.dirname(__file__), "bot_data.db")

class Database:
    def __init__(self, db_path: str = DB_FILE):
        self.db_path = db_path
        self.init_db()

    def get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self):
        """إنشاء الجداول في حالة عدم وجودها"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # جدول سجلات الإضافة
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS add_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    target_user_id INTEGER,
                    target_username TEXT,
                    target_name TEXT,
                    added_by INTEGER,
                    status TEXT,
                    error_message TEXT,
                    channel_id INTEGER,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # جدول القنوات المدارة
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS channels (
                    channel_id INTEGER PRIMARY KEY,
                    title TEXT,
                    username TEXT,
                    is_active INTEGER DEFAULT 0,
                    added_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # جدول الإعدادات العامة
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """)

            # الفهارس لسرعة الأداء واقتناص الإحصائيات الفورية
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_status ON add_logs(status)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_timestamp ON add_logs(timestamp)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_target_user ON add_logs(target_user_id)")

            conn.commit()

    def log_add(self, user_id: Optional[int], username: Optional[str], name: Optional[str], 
                added_by: int, status: str, error_message: str = "", channel_id: Optional[int] = None):
        """تسجيل عملية إضافة جديدة"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO add_logs (target_user_id, target_username, target_name, added_by, status, error_message, channel_id, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (user_id, username, name, added_by, status, error_message, channel_id, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
            conn.commit()

    def get_stats(self) -> Dict[str, Any]:
        """استخراج إحصائيات شامِلة"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("SELECT COUNT(*) FROM add_logs")
            total = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM add_logs WHERE status = 'success'")
            success = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM add_logs WHERE status != 'success'")
            failed = cursor.fetchone()[0]

            today_str = datetime.now().strftime("%Y-%m-%d")
            cursor.execute("SELECT COUNT(*) FROM add_logs WHERE timestamp LIKE ?", (f"{today_str}%",))
            today_count = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM add_logs WHERE status = 'privacy_restricted'")
            privacy_errors = cursor.fetchone()[0]

            return {
                "total": total,
                "success": success,
                "failed": failed,
                "today": today_count,
                "privacy_errors": privacy_errors
            }

    def save_channel(self, channel_id: int, title: str, username: str = "", set_active: bool = True):
        """إضافة أو تحديث قناة في الداتابيز"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if set_active:
                cursor.execute("UPDATE channels SET is_active = 0")

            cursor.execute("""
                INSERT INTO channels (channel_id, title, username, is_active)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(channel_id) DO UPDATE SET
                    title=excluded.title,
                    username=excluded.username,
                    is_active=excluded.is_active
            """, (channel_id, title, username, 1 if set_active else 0))
            conn.commit()

    def get_active_channel() -> Optional[Dict[str, Any]]:
        """جلب القناة النشطة حالياً"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM channels WHERE is_active = 1 LIMIT 1")
            row = cursor.fetchone()
            if row:
                return dict(row)
            # إذا لم توجد قناة نشطة، هات القناة الأولى
            cursor.execute("SELECT * FROM channels LIMIT 1")
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_all_channels(self) -> List[Dict[str, Any]]:
        """جلب جميع القنوات المسجلة"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM channels ORDER BY added_at DESC")
            rows = cursor.fetchall()
            return [dict(r) for r in rows]

    def set_setting(self, key: str, value: str):
        """حفظ إعداد"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO settings (key, value)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value
            """, (key, str(value)))
            conn.commit()

    def get_setting(self, key: str, default: str = "") -> str:
        """جلب إعداد"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
            row = cursor.fetchone()
            return row[0] if row else default

    def export_logs_text(self) -> str:
        """تصدير سجلات الإضافة في صيغة نصية"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM add_logs ORDER BY timestamp DESC LIMIT 1000")
            rows = cursor.fetchall()

            output = ["ID | Target | Status | Error | Added By | Timestamp"]
            output.append("-" * 65)
            for r in rows:
                target = r['target_username'] or str(r['target_user_id']) or r['target_name'] or "N/A"
                output.append(f"{r['id']} | {target} | {r['status']} | {r['error_message']} | {r['added_by']} | {r['timestamp']}")
            
            return "\n".join(output)
