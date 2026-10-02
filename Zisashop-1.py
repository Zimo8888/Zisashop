import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
import sqlite3
import random
import string
import os
import requests 
import time
from urllib.parse import quote, unquote
from datetime import datetime

# ==========================================
# 🔐 تنظیمات محرمانه از Railway Variables / Environment
# مقادیر واقعی را داخل GitHub ننویسید.
# Railway Variables:
# BOT_TOKEN
# PANEL_URL
# VPN_USERNAME
# VPN_PASSWORD
# ==========================================
API_TOKEN = os.getenv("BOT_TOKEN", "").strip()
PANEL_URL = os.getenv("PANEL_URL", "").strip().rstrip("/")
VPN_USERNAME = os.getenv("VPN_USERNAME", "").strip()
VPN_PASSWORD = os.getenv("VPN_PASSWORD", "").strip()
VPN_GROUP_ID = 1  # آیدی عددی گروه

if not API_TOKEN:
    raise RuntimeError("BOT_TOKEN در Railway Variables تنظیم نشده است.")
if not PANEL_URL:
    raise RuntimeError("PANEL_URL در Railway Variables تنظیم نشده است.")
if not VPN_USERNAME:
    raise RuntimeError("VPN_USERNAME در Railway Variables تنظیم نشده است.")
if not VPN_PASSWORD:
    raise RuntimeError("VPN_PASSWORD در Railway Variables تنظیم نشده است.")

bot = telebot.TeleBot(API_TOKEN)

OWNER_ID = 7105951313
REPORTS_CHANNEL = -1003927917163

BOT_USERNAME = ""
try: BOT_USERNAME = bot.get_me().username
except: pass

user_steps = {}
temp_data = {}
user_nav = {}

# ==========================================
# 🗄️ مسیر دیتابیس برای Railway Volume
# اگر Volume روی /data متصل باشد، دیتابیس و بکاپ‌ها آنجا ذخیره می‌شوند.
# در اجرای لوکال، از پوشه data کنار فایل ربات استفاده می‌شود.
# ==========================================
if os.path.isdir("/data") and os.access("/data", os.W_OK):
    DATA_DIR = "/data"
else:
    DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "shop.db")
BACKUP_DIR = os.path.join(DATA_DIR, "backups")
os.makedirs(BACKUP_DIR, exist_ok=True)

# ==========================================
# توابع اصلی ارتباط با API پاسارگارد/مرزبان
# ==========================================

def get_panel_token():
    session = requests.Session()
    login_url = f"{PANEL_URL}/api/admin/token"
    login_data = {"username": VPN_USERNAME, "password": VPN_PASSWORD, "grant_type": "password"}
    try:
        req = session.post(login_url, data=login_data, timeout=10)
        if req.status_code == 200:
            return req.json().get("access_token")
    except: pass
    return None

def create_pasarguard_user(username, data_limit, expire_time=0, note="ساخته شده توسط Zisa"):
    token = get_panel_token()
    if not token: raise Exception("توکن ورود دریافت نشد. مشخصات ورود را بررسی کنید.")

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }

    payload = {
        "username": username,
        "proxies": {"vless": {}},
        "data_limit": data_limit,
        "data_limit_reset_strategy": "no_reset",
        "status": "active",
        "note": note,
        "group_ids": [VPN_GROUP_ID],
        "hwids": []
    }

    if expire_time != 0:
        payload["expire"] = expire_time

    create_req = requests.post(f"{PANEL_URL}/api/user", headers=headers, json=payload, timeout=20)
    
    if create_req.status_code not in (200, 201):
        try: error = create_req.json()
        except: error = create_req.text[:200]
        raise Exception(f"ساخت کاربر ناموفق بود (کد {create_req.status_code}): {error}")

    user_data = create_req.json()
    subscription_url = user_data.get("subscription_url")
    if not subscription_url:
        links = user_data.get("links", [])
        if links: subscription_url = links[0]
        else: raise Exception("لینک کانفیگ در خروجی پنل یافت نشد.")

    return subscription_url

def get_vpn_usage(username):
    token = get_panel_token()
    if not token: return None
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    try:
        req = requests.get(f"{PANEL_URL}/api/user/{username}", headers=headers, timeout=10)
        if req.status_code == 200:
            return req.json()
    except: pass
    return None

def delete_vpn_user(username):
    token = get_panel_token()
    if not token: return False
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    try:
        req = requests.delete(f"{PANEL_URL}/api/user/{username}", headers=headers, timeout=10)
        return req.status_code in [200, 204, 404, 422]
    except: pass
    return False

def get_username_by_sublink(sub_link):
    token = get_panel_token()
    if not token: return None
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    try:
        req = requests.get(f"{PANEL_URL}/api/users", headers=headers, timeout=15)
        if req.status_code == 200:
            data = req.json()
            users_list = data if isinstance(data, list) else data.get("users", [])
            for u in users_list:
                if u.get("subscription_url") == sub_link: return u.get("username")
                if sub_link in u.get("links", []): return u.get("username")
    except: pass
    return None

# ==========================================
# 💾 بکاپ و ریستور دیتابیس
# ==========================================

def create_database_backup():
    """ساخت بکاپ سالم و سازگار از دیتابیس فعلی."""
    if not os.path.exists(DB_PATH):
        init_db()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = os.path.join(BACKUP_DIR, f"shop_backup_{timestamp}.db")
    source = sqlite3.connect(DB_PATH)
    destination = sqlite3.connect(backup_path)
    try:
        source.backup(destination)
    finally:
        destination.close()
        source.close()
    return backup_path

def validate_sqlite_database(db_path):
    """بررسی می‌کند فایل ارسالی واقعاً یک دیتابیس SQLite سالم باشد."""
    if not os.path.isfile(db_path) or os.path.getsize(db_path) == 0:
        return False
    conn = None
    try:
        conn = sqlite3.connect(db_path)
        result = conn.execute("PRAGMA integrity_check").fetchone()
        return bool(result and result[0] == "ok")
    except Exception:
        return False
    finally:
        if conn:
            conn.close()

def restore_database_from_file(uploaded_path):
    """ریستور امن دیتابیس با بکاپ اضطراری و جایگزینی اتمیک."""
    if not validate_sqlite_database(uploaded_path):
        raise ValueError("فایل ارسالی یک دیتابیس SQLite سالم نیست.")
    emergency_backup = create_database_backup()
    restore_temp = os.path.join(DATA_DIR, f".shop_restore_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.db")
    try:
        source = sqlite3.connect(uploaded_path)
        destination = sqlite3.connect(restore_temp)
        try:
            source.backup(destination)
        finally:
            destination.close()
            source.close()
        if not validate_sqlite_database(restore_temp):
            raise ValueError("اعتبارسنجی دیتابیس ریستور شده ناموفق بود.")
        os.replace(restore_temp, DB_PATH)
        init_db()
        return emergency_backup
    except Exception:
        if os.path.exists(restore_temp):
            try: os.remove(restore_temp)
            except Exception: pass
        raise

# ==========================================

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (user_id INTEGER PRIMARY KEY, first_name TEXT, username TEXT, 
                  balance INTEGER DEFAULT 0, total_orders INTEGER DEFAULT 0,
                  is_admin INTEGER DEFAULT 0, is_banned INTEGER DEFAULT 0, ban_reason TEXT,
                  kyc_status INTEGER DEFAULT 0, card_info TEXT)''')
                  
    c.execute('''CREATE TABLE IF NOT EXISTS sub_categories
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, parent_cat TEXT, name TEXT, is_locked INTEGER DEFAULT 0)''')
                 
    c.execute('''CREATE TABLE IF NOT EXISTS products
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, subcat_id INTEGER, name TEXT, price INTEGER,
                  min_order INTEGER, max_order INTEGER, sample_link TEXT, description TEXT, is_locked INTEGER DEFAULT 0)''')
                  
    c.execute('''CREATE TABLE IF NOT EXISTS orders
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, prod_id INTEGER, prod_name TEXT, 
                  qty INTEGER, order_link TEXT, total_price INTEGER, status TEXT, track_code TEXT, date TEXT)''')

    c.execute('''CREATE TABLE IF NOT EXISTS vpn_orders
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, plan_id TEXT, name TEXT, 
                  price INTEGER, config_link TEXT, track_code TEXT, date TEXT, 
                  vol_total TEXT, vol_used TEXT, expire TEXT)''')
                  
    c.execute('''CREATE TABLE IF NOT EXISTS receipts
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, amount INTEGER, status INTEGER DEFAULT 0)''')
                 
    c.execute('''CREATE TABLE IF NOT EXISTS support_tickets
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, status INTEGER DEFAULT 0)''')
                  
    c.execute('''CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS channels (channel_id TEXT PRIMARY KEY)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS discount_codes
                 (code TEXT PRIMARY KEY, percent INTEGER, global_limit INTEGER, user_limit INTEGER, category TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS user_discounts
                 (user_id INTEGER, code TEXT, remaining_uses INTEGER)''')
                 
    try: c.execute("ALTER TABLE orders ADD COLUMN discount_code TEXT DEFAULT ''")
    except: pass
    try: c.execute("ALTER TABLE vpn_orders ADD COLUMN discount_code TEXT DEFAULT ''")
    except: pass
    try: c.execute("ALTER TABLE vpn_orders ADD COLUMN panel_username TEXT DEFAULT ''")
    except: pass
    try: c.execute("ALTER TABLE users ADD COLUMN referrer_id INTEGER DEFAULT 0")
    except: pass
    
    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('card_number', 'تنظیم نشده')")
    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('card_name', 'تنظیم نشده')")
    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('tutorial_link', 'تنظیم نشده')")
    
    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('vpn_price_base', '3500')")
    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('vpn_price_15', '50000')")
    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('vpn_price_25', '85000')")
    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('vpn_price_35', '120000')")
    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('vpn_price_50', '175000')")
    
    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('vpn_price_100_1', '250000')")
    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('vpn_price_100_2', '275000')")
    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('vpn_price_100_3', '300000')")
    
    conn.commit()
    conn.close()

init_db()

def get_all_admins():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_id FROM users WHERE is_admin=1")
    admins = [row[0] for row in c.fetchall()]
    conn.close()
    if OWNER_ID not in admins:
        admins.append(OWNER_ID)
    return admins

def is_admin(user_id):
    if user_id == OWNER_ID: return True
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT is_admin FROM users WHERE user_id=?", (user_id,))
    res = c.fetchone()
    conn.close()
    return True if (res and res[0] == 1) else False

def check_banned(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT is_banned, ban_reason FROM users WHERE user_id=?", (user_id,))
    res = c.fetchone()
    conn.close()
    if res and res[0] == 1:
        return res[1] if res[1] else "توسط مدیریت بن شده‌اید."
    return False

def check_join(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT channel_id FROM channels")
    channels = [row[0] for row in c.fetchall()]
    conn.close()
    if not channels: return True
    for channel in channels:
        try:
            status = bot.get_chat_member(channel, user_id).status
            if status in ['left', 'kicked']: return False
        except: return False
    return True

def generate_track_code():
    return "TRC-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=6))

def format_account_text(user):
    kyc_stat = "❌ تایید نشده"
    if user[8] == 1: kyc_stat = "⏳ در حال بررسی"
    elif user[8] == 2: kyc_stat = "✅ تایید شده"
    
    txt = f"""👤 **اطلاعات حساب کاربری شما**
━━━━ ❖ ━━━━
📛 **نام اکانت:** {user[1]}
🆔 **آیدی عددی:** `{user[0]}`
🌐 **یوزرنیم:** @{user[2] if user[2] else 'ندارد'}
💰 **موجودی:** {user[3]:,} تومان
🛍 **تعداد خرید:** {user[4]}
━━━━ ❖ ━━━━
🔐 **وضعیت احراز هویت:** {kyc_stat}"""
    if user[8] == 2: txt += f"\n💳 **اطلاعات کارت:**\n`{user[9]}`"
    return txt

def send_channel_report(text):
    markup = InlineKeyboardMarkup().add(InlineKeyboardButton("🛒 ورود به ربات فروشگاه", url=f"https://t.me/{BOT_USERNAME}", style="primary"))
    try: bot.send_message(REPORTS_CHANNEL, text, reply_markup=markup)
    except: pass

def send_main_menu(chat_id):
    user_nav[chat_id] = {'level': 'main'}
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    
    markup.add(
        KeyboardButton("🛒 خدمات تلگرام", style="primary"),
        KeyboardButton("📸 خدمات اینستا", style="danger") 
    )
    markup.add(
        KeyboardButton("🎵 خدمات تیک تاک", style="primary"),
        KeyboardButton("▶️ خدمات یوتیوب", style="danger") 
    )
    markup.add(
        KeyboardButton("🟣 خدمات روبیکا", style="primary"),
        KeyboardButton("🌐 خرید VPN", style="primary")
    )
    markup.add(
        KeyboardButton("🛍 سرویس های من", style="primary"),
        KeyboardButton("👤 حساب کاربری", style="success")
    )
    markup.add(
        KeyboardButton("💳 کیف پول", style="primary"),
        KeyboardButton("🏷 ثبت کد تخفیف", style="success")
    )
    markup.add(
        KeyboardButton("🤝 زیرمجموعه گیری", style="success"),
        KeyboardButton("🎧 پشتیبانی", style="danger")
    )
    
    if is_admin(chat_id):
        markup.add(KeyboardButton("⚙️ پنل مدیریت کل", style="danger"))

    bot.send_message(chat_id, "💠 **به منوی اصلی خوش آمدید!**\nلطفا یک گزینه را انتخاب کنید 👇", reply_markup=markup, parse_mode="Markdown")

def send_cat_menu(chat_id, cat_id, cat_name):
    user_nav[chat_id] = {'level': 'cat', 'current_cat': cat_id, 'cat_name': cat_name}
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT name, is_locked FROM sub_categories WHERE parent_cat=?", (cat_id,))
    subcats = c.fetchall()
    conn.close()
    
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    colors = ["primary", "success", "danger"]
    
    for index, sc in enumerate(subcats):
        btn_name = f"🔒 {sc[0]}" if sc[1] == 1 else sc[0]
        markup.add(KeyboardButton(btn_name, style=colors[index % len(colors)]))
        
    if is_admin(chat_id): markup.add(KeyboardButton(f"⚙️ مدیریت دسته‌های {cat_name}", style="primary"))
    markup.add(KeyboardButton("🔙 برگشت به منوی اصلی", style="danger"))
    bot.send_message(chat_id, f"📂 شما وارد بخش **{cat_name}** شدید.\nیک دسته‌بندی را انتخاب کنید:", reply_markup=markup, parse_mode="Markdown")

def send_subcat_menu(chat_id, subcat_id, subcat_name):
    cat_id = user_nav.get(chat_id, {}).get('current_cat', 'telegram')
    cat_name = user_nav.get(chat_id, {}).get('cat_name', 'خدمات')
    user_nav[chat_id] = {'level': 'subcat', 'current_cat': cat_id, 'cat_name': cat_name, 'current_subcat': subcat_id, 'subcat_name': subcat_name}
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT name, is_locked FROM products WHERE subcat_id=?", (subcat_id,))
    products = c.fetchall()
    conn.close()
    
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    colors = ["primary", "success", "danger"]
    
    for index, p in enumerate(products):
        btn_name = f"🔒 {p[0]}" if p[1] == 1 else p[0]
        markup.add(KeyboardButton(btn_name, style=colors[index % len(colors)]))
        
    if is_admin(chat_id): markup.add(KeyboardButton(f"⚙️ مدیریت محصولات ({subcat_name})", style="primary"))
    markup.add(KeyboardButton("🔙 برگشت به دسته‌بندی‌ها", style="danger"))
    bot.send_message(chat_id, f"📦 شما وارد بخش **{subcat_name}** شدید.\nمحصول را انتخاب کنید:", reply_markup=markup, parse_mode="Markdown")

@bot.message_handler(commands=['testpanel'])
def test_vpn_panel(message):
    chat_id = message.chat.id
    if not is_admin(chat_id): return
    bot.send_message(chat_id, "⏳ در حال ارسال درخواست ۱۰۰ مگابایتی به پاسارگارد...\n(لطفاً چند ثانیه صبر کنید)")
    data_limit = 100 * 1048576 
    username = f"zisa_vpn_{random.randint(10000, 99999)}"
    try:
        sub_link = create_pasarguard_user(username, data_limit, 0)
        msg = f"✅ **ارتباط با پنل موفقیت‌آمیز بود!**\n\n📌 **یوزرنیم ساخته شده:** `{username}`\n🔗 **لینک ساب:**\n`{sub_link}`"
        bot.send_message(chat_id, msg, parse_mode="Markdown")
    except Exception as e:
        bot.send_message(chat_id, f"❌ **خطا در اتصال به پنل!**\n\nارور:\n`{str(e)}`", parse_mode="Markdown")

@bot.message_handler(commands=['start'])
def start_command(message):
    user_id = message.from_user.id
    fname = message.from_user.first_name
    uname = message.from_user.username
    user_steps.pop(user_id, None) 
    
    ban_reason = check_banned(user_id)
    if ban_reason:
        bot.send_message(user_id, f"🚫 **حساب شما مسدود است.**\nدلیل: {ban_reason}", parse_mode="Markdown")
        return

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
    exists = c.fetchone()
    
    if not exists:
        referrer_id = 0
        args = message.text.split()
        if len(args) > 1 and args[1].isdigit():
            ref = int(args[1])
            if ref != user_id:
                referrer_id = ref
        c.execute("INSERT INTO users (user_id, first_name, username, referrer_id) VALUES (?, ?, ?, ?)", (user_id, fname, uname, referrer_id))
    else:
        c.execute("UPDATE users SET first_name=?, username=? WHERE user_id=?", (fname, uname, user_id))
    
    conn.commit()
    conn.close()

    if not check_join(user_id):
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT channel_id FROM channels")
        channels = [row[0] for row in c.fetchall()]
        conn.close()
        markup = InlineKeyboardMarkup(row_width=1)
        for ch in channels: markup.add(InlineKeyboardButton(f"عضویت در {ch}", url=f"https://t.me/{ch.replace('@','')}", style="primary"))
        markup.add(InlineKeyboardButton("✅ تایید عضویت", callback_data="check_join", style="success"))
        bot.send_message(message.chat.id, "⚠️ **برای استفاده از ربات ابتدا در کانال‌های زیر عضو شوید:**", reply_markup=markup, parse_mode="Markdown")
        return

    send_main_menu(message.chat.id)

# ==========================================
# 💾 مدیریت بکاپ / ریستور دیتابیس
# ==========================================

@bot.message_handler(commands=['backup'])
def backup_database_command(message):
    chat_id = message.chat.id
    if not is_admin(chat_id): return
    status_msg = bot.send_message(chat_id, "⏳ در حال ساخت بکاپ دیتابیس...")
    try:
        backup_path = create_database_backup()
        with open(backup_path, "rb") as backup_file:
            bot.send_document(chat_id, backup_file, caption="✅ **بکاپ دیتابیس با موفقیت ساخته شد.**\n\nاین فایل را در جای امن نگه دارید.", parse_mode="Markdown")
        try: bot.delete_message(chat_id, status_msg.message_id)
        except Exception: pass
    except Exception as e:
        try: bot.edit_message_text(f"❌ **ساخت بکاپ ناموفق بود.**\n\n`{str(e)}`", chat_id, status_msg.message_id, parse_mode="Markdown")
        except Exception: bot.send_message(chat_id, f"❌ خطا در ساخت بکاپ:\n`{str(e)}`", parse_mode="Markdown")

@bot.message_handler(commands=['restore'])
def restore_database_command(message):
    chat_id = message.chat.id
    if not is_admin(chat_id): return
    user_steps[chat_id] = "awaiting_database_restore"
    bot.send_message(chat_id, "📥 **ریستور دیتابیس**\n\nفایل بکاپ `.db` را به صورت **Document** ارسال کنید.\nقبل از جایگزینی، از دیتابیس فعلی یک بکاپ اضطراری گرفته می‌شود.\n\nبرای لغو، `/cancel` را بفرستید.", parse_mode="Markdown")

@bot.message_handler(commands=['cancel'])
def cancel_database_restore(message):
    chat_id = message.chat.id
    if user_steps.get(chat_id) == "awaiting_database_restore":
        user_steps.pop(chat_id, None)
        bot.send_message(chat_id, "❌ عملیات ریستور لغو شد.")

@bot.message_handler(content_types=['document'], func=lambda message: user_steps.get(message.chat.id) == 'awaiting_database_restore')
def restore_database_document(message):
    chat_id = message.chat.id
    if not is_admin(chat_id): return
    if user_steps.get(chat_id) != "awaiting_database_restore": return
    user_steps.pop(chat_id, None)
    temp_upload = os.path.join(DATA_DIR, f".restore_upload_{chat_id}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.db")
    try:
        file_info = bot.get_file(message.document.file_id)
        file_data = bot.download_file(file_info.file_path)
        with open(temp_upload, "wb") as f: f.write(file_data)
        if not validate_sqlite_database(temp_upload):
            bot.send_message(chat_id, "❌ فایل ارسالی دیتابیس SQLite سالم و قابل استفاده نیست.")
            return
        bot.send_message(chat_id, "⏳ فایل سالم است؛ در حال ریستور دیتابیس...")
        emergency_backup = restore_database_from_file(temp_upload)
        bot.send_message(chat_id, "✅ **ریستور با موفقیت انجام شد.**\n\n" + f"🛡 بکاپ اضطراری دیتابیس قبلی:\n`{os.path.basename(emergency_backup)}`\n\n🔄 دیتابیس جدید فعال شد.", parse_mode="Markdown")
    except Exception as e:
        bot.send_message(chat_id, f"❌ **ریستور انجام نشد و دیتابیس فعلی حفظ شد.**\n\n`{str(e)}`", parse_mode="Markdown")
    finally:
        if os.path.exists(temp_upload):
            try: os.remove(temp_upload)
            except Exception: pass

@bot.message_handler(content_types=['text', 'photo', 'video', 'document', 'audio', 'voice', 'animation'])
def handle_all_messages(message):
    chat_id = message.chat.id
    
    ban_reason = check_banned(chat_id)
    if ban_reason: return

    if not check_join(chat_id):
        start_command(message)
        return

    # ====================================================
    # 📢 بخش ارسال پیام‌های چندرسانه‌ای/فوروارد (همگانی و ناشناس)
    # ====================================================
    if chat_id in user_steps:
        step = user_steps[chat_id]
        is_forward = getattr(message, 'forward_date', None) is not None
        
        if step == 'ask_broadcast':
            bot.send_message(chat_id, "⏳ در حال ارسال، لطفا صبر کنید...")
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("SELECT user_id FROM users")
            users = c.fetchall()
            conn.close()
            success = 0
            for u in users:
                try:
                    if is_forward:
                        bot.forward_message(u[0], chat_id, message.message_id)
                    else:
                        bot.copy_message(u[0], chat_id, message.message_id)
                    success += 1
                except: pass
            bot.send_message(chat_id, f"✅ پیام همگانی با موفقیت به {success} نفر ارسال شد.")
            user_steps.pop(chat_id, None)
            return
            
        elif step == 'ask_anon_msg_text':
            target = temp_data[chat_id]['target']
            try:
                if is_forward:
                    bot.forward_message(target, chat_id, message.message_id)
                else:
                    bot.copy_message(target, chat_id, message.message_id)
                bot.send_message(chat_id, "✅ پیام ناشناس شما با موفقیت به کاربر ارسال شد.")
            except: 
                bot.send_message(chat_id, "❌ خطا در ارسال (احتمالاً کاربر ربات را بلاک کرده است).")
            user_steps.pop(chat_id, None)
            return
    # ====================================================

    if message.content_type == 'photo':
        if chat_id in user_steps:
            step = user_steps[chat_id]
            if step == 'ask_kyc_photo':
                caption = message.caption if message.caption else "بدون کپشن"
                bot.send_message(chat_id, "✅ اطلاعات احراز هویت با موفقیت برای مدیریت ارسال شد.")
                conn = sqlite3.connect(DB_PATH)
                c = conn.cursor()
                c.execute("UPDATE users SET kyc_status=1, card_info=? WHERE user_id=?", (caption, chat_id))
                conn.commit()
                conn.close()
                markup = InlineKeyboardMarkup()
                markup.add(InlineKeyboardButton("✅ تایید", callback_data=f"kyc_accept_{chat_id}", style="success"),
                           InlineKeyboardButton("❌ رد", callback_data=f"kyc_reject_{chat_id}", style="danger"))
                admins = get_all_admins()
                for admin in admins:
                    try:
                        bot.forward_message(admin, chat_id, message.message_id)
                        bot.send_message(admin, f"🛡 **درخواست احراز هویت جدید:**\n🆔 آیدی: `{chat_id}`\n📝 کپشن: {caption}", reply_markup=markup, parse_mode="Markdown")
                    except: pass
                user_steps.pop(chat_id, None)
                
            elif step == 'ask_receipt_photo':
                amount = temp_data[chat_id]['charge_amount']
                conn = sqlite3.connect(DB_PATH)
                c = conn.cursor()
                c.execute("INSERT INTO receipts (user_id, amount) VALUES (?, ?)", (chat_id, amount))
                receipt_id = c.lastrowid
                conn.commit()
                conn.close()
                bot.send_message(chat_id, "✅ رسید پرداخت ارسال شد. پس از تایید مدیریت، موجودی شما افزوده خواهد شد.")
                markup = InlineKeyboardMarkup(row_width=2)
                markup.add(InlineKeyboardButton("ℹ️ اطلاعات فرستنده", callback_data=f"supinfo_{chat_id}", style="primary"))
                markup.add(InlineKeyboardButton("✅ تایید و افزایش", callback_data=f"rec_acc_{receipt_id}", style="success"),
                           InlineKeyboardButton("❌ رد رسید", callback_data=f"rec_rej_{receipt_id}", style="danger"))
                admins = get_all_admins()
                for admin in admins:
                    try:
                        bot.forward_message(admin, chat_id, message.message_id)
                        bot.send_message(admin, f"🧾 **رسید شارژ کیف پول**\n🆔 آیدی: `{chat_id}`\n💰 مبلغ درخواستی: {amount:,} تومان", reply_markup=markup, parse_mode="Markdown")
                    except: pass
                user_steps.pop(chat_id, None)
        return

    text = message.text
    if not text: return
    
    translation_table = str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩', '01234567890123456789')
    text = text.translate(translation_table)

    if text == "🔙 برگشت به منوی اصلی":
        user_steps.pop(chat_id, None)
        send_main_menu(chat_id)
        return
    elif text == "🔙 برگشت به دسته‌بندی‌ها":
        user_steps.pop(chat_id, None)
        nav = user_nav.get(chat_id, {})
        if 'current_cat' in nav: send_cat_menu(chat_id, nav['current_cat'], nav['cat_name'])
        else: send_main_menu(chat_id)
        return

    if text == "👤 حساب کاربری":
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE user_id=?", (chat_id,))
        user = c.fetchone()
        conn.close()
        markup = InlineKeyboardMarkup()
        if user[8] == 0: markup.add(InlineKeyboardButton("🔐 ثبت احراز هویت", callback_data="start_kyc", style="primary"))
        elif user[8] == 2: markup.add(InlineKeyboardButton("🗑 حذف احراز هویت", callback_data="delete_kyc", style="danger"))
        bot.send_message(chat_id, format_account_text(user), reply_markup=markup, parse_mode="Markdown")
        return
        
    elif text == "💳 کیف پول":
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT balance, kyc_status FROM users WHERE user_id=?", (chat_id,))
        user = c.fetchone()
        conn.close()
        markup = InlineKeyboardMarkup().add(InlineKeyboardButton("💵 شارژ موجودی", callback_data="charge_wallet", style="success"))
        bot.send_message(chat_id, f"💰 **موجودی فعلی کیف پول شما:**\n{user[0]:,} تومان", reply_markup=markup, parse_mode="Markdown")
        return

    elif text == "🤝 زیرمجموعه گیری":
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        try: c.execute("SELECT COUNT(*) FROM users WHERE referrer_id=?", (chat_id,))
        except: c.execute("SELECT 0") # در صورت آپدیت نشدن دیتابیس
        ref_count = c.fetchone()[0]
        conn.close()
        
        link = f"https://t.me/{BOT_USERNAME}?start={chat_id}"
        msg = f"""🤝 **بخش زیرمجموعه‌گیری (کسب درآمد)**
━━━━ ❖ ━━━━
با دعوت از دوستان خود به ربات، **10 درصد** از مبلغ تمام خریدهای آنها (چه خدمات مجازی و چه VPN) را به صورت خودکار به عنوان پورسانت در کیف پول خود دریافت کنید!

👥 **تعداد زیرمجموعه‌های شما:** {ref_count} نفر

🔗 **لینک اختصاصی دعوت شما:**
`{link}`

*(کافیست این لینک را برای دوستان خود یا در گروه‌ها ارسال کنید)*"""
        bot.send_message(chat_id, msg, parse_mode="Markdown")
        return

    elif text == "🏷 ثبت کد تخفیف":
        user_steps[chat_id] = "ask_user_disc"
        bot.send_message(chat_id, "🏷 **کد تخفیف خود را ارسال کنید:**", parse_mode="Markdown")
        return
        
    elif text == "🛍 سرویس های من":
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(InlineKeyboardButton("🛒 خدمات مجازی", callback_data="myservices_virtual", style="primary"),
                   InlineKeyboardButton("🌐 سرویس های VPN", callback_data="myservices_vpn", style="primary"))
        bot.send_message(chat_id, "📂 **بخش مورد نظر را جهت مشاهده تاریخچه انتخاب کنید:**", reply_markup=markup, parse_mode="Markdown")
        return

    elif text == "🎧 پشتیبانی":
        user_steps[chat_id] = "ask_support"
        bot.send_message(chat_id, "💬 **لطفا پیام، پیشنهاد یا مشکل خود را در یک پیام برای مدیریت بنویسید:**", parse_mode="Markdown")
        return

    elif text == "🌐 خرید VPN":
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT value FROM settings WHERE key='lock_vpn'")
        r = c.fetchone()
        
        c.execute('''SELECT d.code, d.percent FROM user_discounts u JOIN discount_codes d ON u.code = d.code WHERE u.user_id=? AND u.remaining_uses > 0 AND (d.category='vpn' OR d.category='all') ORDER BY d.percent DESC LIMIT 1''', (chat_id,))
        disc = c.fetchone()
        
        c.execute("SELECT key, value FROM settings WHERE key LIKE 'vpn_price_%'")
        vpn_prices = {row[0]: int(row[1]) for row in c.fetchall()}
        conn.close()
        
        if r and r[0] == '1':
            bot.send_message(chat_id, "🔒 **بخش فروش VPN موقتاً توسط مدیریت متوقف شده است. لطفاً بعداً تلاش کنید.**", parse_mode="Markdown")
            return

        disc_msg = f"\n🎁 **شما یک تخفیف {disc[1]} درصدی فعال برای این بخش دارید! (در فاکتور نهایی اعمال می‌شود)**\n" if disc else ""

        msg = f"""🌐 **به بخش Zisa VPN خوش آمدید**
━━━━ ❖ ━━━━
💎 بهترین کیفیت، سرعت و پایداری
💳 تعرفه پایه: هر گیگابایت {vpn_prices.get('vpn_price_base', 3500):,} تومان

🔸 **پلن 15 گیگ** (نامحدود) ➖ {vpn_prices.get('vpn_price_15', 50000):,} تومان
🔸 **پلن 25 گیگ** (نامحدود) ➖ {vpn_prices.get('vpn_price_25', 85000):,} تومان
🔸 **پلن 35 گیگ** (نامحدود) ➖ {vpn_prices.get('vpn_price_35', 120000):,} تومان
🔸 **پلن 50 گیگ** (نامحدود) ➖ {vpn_prices.get('vpn_price_50', 175000):,} تومان

🔥 **پلن‌های ویژه 100 گیگ (دو ماهه):**
🔹 **تک کاربره** ➖ {vpn_prices.get('vpn_price_100_1', 250000):,} تومان
🔹 **دو کاربره** ➖ {vpn_prices.get('vpn_price_100_2', 275000):,} تومان
🔹 **سه کاربره** ➖ {vpn_prices.get('vpn_price_100_3', 300000):,} تومان

🎁 **تست 50 مگابایت** (رایگان یکبار مصرف)
━━━━ ❖ ━━━━{disc_msg}
👇 جهت خرید، یکی از پلن‌های زیر را انتخاب کنید:"""
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(InlineKeyboardButton("15 گیگ", callback_data="buyvpn_15", style="primary"), InlineKeyboardButton("25 گیگ", callback_data="buyvpn_25", style="primary"))
        markup.add(InlineKeyboardButton("35 گیگ", callback_data="buyvpn_35", style="primary"), InlineKeyboardButton("50 گیگ", callback_data="buyvpn_50", style="primary"))
        markup.add(InlineKeyboardButton("100 گیگ (تک کاربره)", callback_data="buyvpn_100_1", style="primary"))
        markup.add(InlineKeyboardButton("100 گیگ (دو کاربره)", callback_data="buyvpn_100_2", style="primary"), InlineKeyboardButton("100 گیگ (سه کاربره)", callback_data="buyvpn_100_3", style="primary"))
        markup.add(InlineKeyboardButton("🎁 دریافت تست رایگان", callback_data="buyvpn_test", style="success"))
        bot.send_message(chat_id, msg, reply_markup=markup, parse_mode="Markdown")
        return

    if chat_id in user_steps:
        step = user_steps[chat_id]
        
        if step == 'ask_user_disc':
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("SELECT * FROM discount_codes WHERE code=? AND global_limit > 0", (text,))
            code_data = c.fetchone()
            if not code_data:
                bot.send_message(chat_id, "❌ کد تخفیف نامعتبر است یا ظرفیت استفاده از آن پر شده است.")
            else:
                c.execute("SELECT * FROM user_discounts WHERE user_id=? AND code=?", (chat_id, text))
                if c.fetchone():
                    bot.send_message(chat_id, "❌ شما قبلاً این کد تخفیف را ثبت کرده‌اید.")
                else:
                    c.execute("UPDATE discount_codes SET global_limit = global_limit - 1 WHERE code=?", (text,))
                    c.execute("INSERT INTO user_discounts (user_id, code, remaining_uses) VALUES (?, ?, ?)", (chat_id, text, code_data[3]))
                    conn.commit()
                    cat_map_fa = {'telegram': 'خدمات تلگرام', 'insta': 'خدمات اینستاگرام', 'tiktok': 'خدمات تیک‌تاک', 'youtube': 'خدمات یوتیوب', 'rubika': 'خدمات روبیکا', 'vpn': 'خرید VPN', 'all': 'همه بخش‌ها'}
                    bot.send_message(chat_id, f"✅ **کد تخفیف اعمال شد!**\nشما {code_data[1]}% تخفیف برای **{cat_map_fa.get(code_data[4], code_data[4])}** دریافت کردید و می‌توانید در {code_data[3]} خرید خود از آن استفاده کنید.", parse_mode="Markdown")
            conn.close()
            user_steps.pop(chat_id, None)
            return

        if step == 'ask_support':
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("INSERT INTO support_tickets (user_id) VALUES (?)", (chat_id,))
            ticket_id = c.lastrowid
            conn.commit()
            conn.close()
            
            markup = InlineKeyboardMarkup()
            markup.add(InlineKeyboardButton("ℹ️ اطلاعات فرستنده", callback_data=f"supinfo_{chat_id}", style="primary"))
            markup.add(InlineKeyboardButton("✍️ پاسخ", callback_data=f"suprep_{ticket_id}", style="primary"),
                       InlineKeyboardButton("👁 دیده شد", callback_data=f"supseen_{ticket_id}", style="success"))
            admins = get_all_admins()
            for admin in admins:
                try:
                    fwd = bot.forward_message(admin, chat_id, message.message_id)
                    bot.send_message(admin, f"📩 **پیام جدید از بخش پشتیبانی (کد #{ticket_id}):**", reply_markup=markup, reply_to_message_id=fwd.message_id, parse_mode="Markdown")
                except: pass
            bot.send_message(chat_id, "✅ پیام شما با موفقیت به تیم پشتیبانی ارسال شد.")
            user_steps.pop(chat_id, None)
            return

        elif step == 'ask_charge_amount':
            if not text.isdigit() or int(text) < 10000:
                return bot.send_message(chat_id, "❌ **خطا:** حداقل مبلغ قابل شارژ 10,000 تومان می‌باشد.", parse_mode="Markdown")
            
            amount_toman = int(text)
            
            if amount_toman > 400000:
                conn = sqlite3.connect(DB_PATH)
                c = conn.cursor()
                c.execute("SELECT kyc_status FROM users WHERE user_id=?", (chat_id,))
                k_stat = c.fetchone()[0]
                conn.close()
                if k_stat != 2:
                    user_steps.pop(chat_id, None)
                    return bot.send_message(chat_id, "❌ **کاربر گرامی، برای شارژ مبالغ بیشتر از 400,000 تومان، ابتدا باید از بخش 👤 حساب کاربری، احراز هویت خود را تکمیل کنید.**", parse_mode="Markdown")
            
            amount_rial = amount_toman * 10
            
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("SELECT value FROM settings WHERE key='card_number'")
            card_num = c.fetchone()[0]
            c.execute("SELECT value FROM settings WHERE key='card_name'")
            card_name = c.fetchone()[0]
            conn.close()
            
            temp_data[chat_id] = {'charge_amount': amount_toman}
            user_steps[chat_id] = 'ask_receipt_photo'
            
            msg = f"""💳 **درخواست شارژ کیف پول**
━━━━ ❖ ━━━━
💰 **مبلغ واریزی به تومان:** {amount_toman:,}
💵 **مبلغ واریزی به ریال:** {amount_rial:,}

💳 **شماره کارت جهت واریز (با یک لمس کپی می‌شود):**
`{card_num}`
👤 **به نام:** {card_name}

⚠️ **نکات مهم:**
۱. حتماً با همان کارتی که در ربات احراز هویت کرده‌اید واریز کنید.
۲. با لمس شماره کارت یا مبالغ بالا، متن کپی می‌شود یا از دکمه‌های زیر استفاده کنید.
━━━━ ❖ ━━━━
📸 **لطفاً عکس فیش/رسید پرداخت خود را ارسال کنید:**"""
            markup = InlineKeyboardMarkup(row_width=1)
            markup.add(InlineKeyboardButton("📋 کپی شماره کارت", callback_data="copy_cardnum", style="primary"))
            markup.add(InlineKeyboardButton("📋 کپی مبلغ به ریال", callback_data=f"copy_rial_{amount_rial}", style="primary"))
            bot.send_message(chat_id, msg, reply_markup=markup, parse_mode="Markdown")
            return
            
        elif step == 'ask_order_qty':
            if not text.isdigit(): return bot.send_message(chat_id, "❌ فقط عدد وارد کنید!")
            qty = int(text)
            d = temp_data[chat_id]
            if qty < d['min'] or qty > d['max']: return bot.send_message(chat_id, f"❌ تعداد باید بین {d['min']} و {d['max']} باشد.")
            temp_data[chat_id]['qty'] = qty
            user_steps[chat_id] = 'ask_order_link'
            bot.send_message(chat_id, f"🔗 **لطفا لینک سفارش خود را ارسال کنید:**\nنمونه: `{d['sample']}`", parse_mode="Markdown")
            return
            
        elif step == 'ask_order_link':
            temp_data[chat_id]['link'] = text
            d = temp_data[chat_id]
            total_price = d['qty'] * d['price']
            
            price_txt = f"{total_price:,} تومان"
            if 'discount_percent' in d:
                new_total = int(total_price * (100 - d['discount_percent']) / 100)
                price_txt = f"❌ اصلی: {total_price:,} تومان\n🎁 **با تخفیف ({d['discount_percent']}%):** ✅ {new_total:,} تومان"
                total_price = new_total
                
            temp_data[chat_id]['total_price'] = total_price
            info = f"""🛍 **پیش‌فاکتور سفارش شما**
━━━━ ❖ ━━━━
📌 **محصول:** {d['name']}
🔢 **تعداد درخواستی:** {d['qty']}
🔗 **لینک ثبت شده:** {d['link']}
💰 **مبلغ پرداخت:**
{price_txt}
━━━━ ❖ ━━━━
⚠️ **آیا از ثبت این سفارش با اطلاعات فوق اطمینان دارید؟**
(مسئولیت اشتباه بودن لینک بر عهده شماست)"""
            markup = InlineKeyboardMarkup().add(InlineKeyboardButton("✅ تایید و پرداخت", callback_data="conf_order", style="success"), InlineKeyboardButton("❌ لغو", callback_data="cancel_order", style="danger"))
            bot.send_message(chat_id, info, reply_markup=markup, parse_mode="Markdown")
            user_steps.pop(chat_id, None)
            return

        if is_admin(chat_id):
            if step.startswith('ask_edit_prprice_'):
                pr_id = step.split("_")[3]
                if not text.isdigit(): return bot.send_message(chat_id, "❌ فقط عدد ارسال کنید!")
                conn = sqlite3.connect(DB_PATH)
                c = conn.cursor()
                c.execute("UPDATE products SET price=? WHERE id=?", (int(text), pr_id))
                conn.commit()
                conn.close()
                bot.send_message(chat_id, "✅ قیمت محصول با موفقیت آپدیت شد.")
                user_steps.pop(chat_id, None)
                return

            if step.startswith('ask_edit_vpn_'):
                plan = step.replace("ask_edit_vpn_", "")
                if not text.isdigit(): return bot.send_message(chat_id, "❌ فقط عدد بفرستید!")
                conn = sqlite3.connect(DB_PATH)
                c = conn.cursor()
                c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (f"vpn_price_{plan}", text))
                conn.commit()
                conn.close()
                bot.send_message(chat_id, f"✅ قیمت پلن {plan} با موفقیت به {int(text):,} تومان تغییر یافت.")
                user_steps.pop(chat_id, None)
                return

            if step == 'ask_tutorial_link':
                conn = sqlite3.connect(DB_PATH)
                c = conn.cursor()
                c.execute("UPDATE settings SET value=? WHERE key='tutorial_link'", (text,))
                conn.commit()
                conn.close()
                bot.send_message(chat_id, "✅ لینک کانال آموزش اتصال با موفقیت ذخیره شد.")
                user_steps.pop(chat_id, None)
                return
            if step == 'ask_reset_test_id':
                conn = sqlite3.connect(DB_PATH)
                c = conn.cursor()
                c.execute("DELETE FROM vpn_orders WHERE user_id=? AND plan_id='test'", (text,))
                conn.commit()
                conn.close()
                bot.send_message(chat_id, f"✅ تست VPN برای کاربر `{text}` ریست شد و می‌تواند دوباره تست بگیرد.", parse_mode="Markdown")
                user_steps.pop(chat_id, None)
                return
            if step == 'ask_disc_code':
                temp_data[chat_id] = {'disc_code': text.strip()}
                user_steps[chat_id] = 'ask_disc_percent'
                bot.send_message(chat_id, "🔢 **درصد تخفیف** را وارد کنید (مثلاً برای 20 درصد بنویسید 20):", parse_mode="Markdown")
                return
            elif step == 'ask_disc_percent':
                if not text.isdigit(): return bot.send_message(chat_id, "❌ فقط عدد ارسال کنید.")
                temp_data[chat_id]['disc_percent'] = int(text)
                user_steps[chat_id] = 'ask_disc_global'
                bot.send_message(chat_id, "👥 **چند نفر مجموعاً** مجاز به ثبت و استفاده از این کد هستند؟ (مثلاً 50):", parse_mode="Markdown")
                return
            elif step == 'ask_disc_global':
                if not text.isdigit(): return bot.send_message(chat_id, "❌ فقط عدد ارسال کنید.")
                temp_data[chat_id]['disc_global'] = int(text)
                user_steps[chat_id] = 'ask_disc_user'
                bot.send_message(chat_id, "🛍 **هر کاربری که کد را ثبت می‌کند، تا چند خرید** می‌تواند از این تخفیف بهره‌مند شود؟ (مثلاً 1 یا 5):", parse_mode="Markdown")
                return
            elif step == 'ask_disc_user':
                if not text.isdigit(): return bot.send_message(chat_id, "❌ فقط عدد ارسال کنید.")
                temp_data[chat_id]['disc_user'] = int(text)
                
                markup = InlineKeyboardMarkup(row_width=2)
                markup.add(InlineKeyboardButton("همه موارد", callback_data="set_disc_cat_all", style="success"))
                markup.add(InlineKeyboardButton("تلگرام", callback_data="set_disc_cat_telegram", style="primary"), InlineKeyboardButton("اینستاگرام", callback_data="set_disc_cat_insta", style="primary"))
                markup.add(InlineKeyboardButton("تیک‌تاک", callback_data="set_disc_cat_tiktok", style="primary"), InlineKeyboardButton("یوتیوب", callback_data="set_disc_cat_youtube", style="primary"))
                markup.add(InlineKeyboardButton("روبیکا", callback_data="set_disc_cat_rubika", style="primary"), InlineKeyboardButton("خرید VPN", callback_data="set_disc_cat_vpn", style="primary"))
                
                bot.send_message(chat_id, "📂 **این کد تخفیف برای کدام بخش قابل استفاده باشد؟**", reply_markup=markup, parse_mode="Markdown")
                user_steps.pop(chat_id, None)
                return

            if step.startswith('reply_sup_'):
                parts = step.split('_')
                ticket_id = parts[2]
                uid = parts[3]
                
                conn = sqlite3.connect(DB_PATH)
                c = conn.cursor()
                c.execute("SELECT status FROM support_tickets WHERE id=?", (ticket_id,))
                t_stat = c.fetchone()[0]
                if t_stat != 0:
                    bot.send_message(chat_id, "⚠️ این پیام در این فاصله توسط ادمین دیگری پاسخ داده شد.")
                    user_steps.pop(chat_id, None)
                    conn.close()
                    return
                c.execute("UPDATE support_tickets SET status=1 WHERE id=?", (ticket_id,))
                conn.commit()
                conn.close()
                
                try:
                    bot.send_message(uid, f"🔔 **پاسخ مدیریت به پیام شما:**\n━━━━ ❖ ━━━━\n{text}", parse_mode="Markdown")
                    bot.send_message(chat_id, "✅ پاسخ با موفقیت ارسال و تیکت بسته شد.")
                except: bot.send_message(chat_id, "❌ خطا در ارسال (شاید کاربر ربات را بلاک کرده باشد).")
                user_steps.pop(chat_id, None)
                return
            elif step == 'ask_admin_id':
                conn = sqlite3.connect(DB_PATH)
                c = conn.cursor()
                c.execute("INSERT OR IGNORE INTO users (user_id, is_admin) VALUES (?, 1)", (text,))
                c.execute("UPDATE users SET is_admin=1 WHERE user_id=?", (text,))
                conn.commit()
                conn.close()
                bot.send_message(chat_id, f"✅ کاربر ادمین شد.")
                user_steps.pop(chat_id, None)
                return
            elif step == 'ask_search_order':
                track_code = text.strip()
                conn = sqlite3.connect(DB_PATH)
                c = conn.cursor()
                c.execute("SELECT * FROM orders WHERE track_code=?", (track_code,))
                ord_data = c.fetchone()
                if ord_data:
                    msg = f"🛒 **نتیجه جستجوی سفارش:**\n━━━━ ❖ ━━━━\n📌 **محصول:** {ord_data[3]}\n🔢 **تعداد:** {ord_data[4]}\n🔗 **لینک:** `{ord_data[5]}`\n💰 **مبلغ:** {ord_data[6]:,} تومان\n📊 **وضعیت:** {ord_data[7]}\n📅 **تاریخ:** {ord_data[9]}\n🔑 **کد پیگیری:** `{ord_data[8]}`\n🆔 **آیدی کاربر:** `{ord_data[1]}`"
                    markup = InlineKeyboardMarkup(row_width=2)
                    markup.add(InlineKeyboardButton("ℹ️ اطلاعات خریدار", callback_data=f"ordinfo_{ord_data[1]}", style="primary"))
                    if ord_data[7] == 'در حال انجام':
                        markup.add(InlineKeyboardButton("✅ تایید", callback_data=f"ordacc_{ord_data[0]}", style="success"), 
                                   InlineKeyboardButton("❌ لغو", callback_data=f"ordrej_{ord_data[0]}", style="danger"))
                    bot.send_message(chat_id, msg, reply_markup=markup, parse_mode="Markdown")
                else:
                    c.execute("SELECT * FROM vpn_orders WHERE track_code=?", (track_code,))
                    v_data = c.fetchone()
                    if v_data:
                        msg = f"🌐 **نتیجه جستجوی سرویس VPN:**\n━━━━ ❖ ━━━━\n📌 **پلن:** {v_data[3]}\n💰 **ارزش:** {v_data[4]:,} تومان\n📅 **تاریخ:** {v_data[7]}\n🔑 **کد پیگیری:** `{v_data[6]}`\n📊 **حجم کل:** {v_data[8]}\n⏳ **انقضا:** {v_data[10]}\n🆔 **آیدی کاربر:** `{v_data[1]}`\n\n🔗 **لینک کانفیگ:**\n`{v_data[5]}`"
                        markup = InlineKeyboardMarkup().add(InlineKeyboardButton("ℹ️ اطلاعات خریدار", callback_data=f"ordinfo_{v_data[1]}", style="primary"))
                        bot.send_message(chat_id, msg, reply_markup=markup, parse_mode="Markdown")
                    else:
                        bot.send_message(chat_id, "❌ سفارشی با این کد پیگیری در سیستم یافت نشد.")
                conn.close()
                user_steps.pop(chat_id, None)
                return
            elif step == 'ask_ban_id':
                temp_data[chat_id] = {'target': text}
                user_steps[chat_id] = 'ask_ban_reason'
                bot.send_message(chat_id, "💬 دلیل بن شدن را بنویسید:")
                return
            elif step == 'ask_ban_reason':
                target = temp_data[chat_id]['target']
                conn = sqlite3.connect(DB_PATH)
                c = conn.cursor()
                c.execute("UPDATE users SET is_banned=1, ban_reason=? WHERE user_id=?", (text, target))
                conn.commit()
                conn.close()
                try: bot.send_message(target, f"🚫 **حساب شما مسدود شد.**\nدلیل: {text}", parse_mode="Markdown")
                except: pass
                bot.send_message(chat_id, "✅ کاربر بن شد.")
                user_steps.pop(chat_id, None)
                return
            elif step == 'ask_unban_id':
                conn = sqlite3.connect(DB_PATH)
                c = conn.cursor()
                c.execute("UPDATE users SET is_banned=0, ban_reason='' WHERE user_id=?", (text,))
                conn.commit()
                conn.close()
                bot.send_message(chat_id, "✅ کاربر رفع بن شد.")
                user_steps.pop(chat_id, None)
                return
            elif step == 'ask_add_bal_id':
                temp_data[chat_id] = {'target': text}
                user_steps[chat_id] = 'ask_add_bal_amount'
                bot.send_message(chat_id, "مبلغ افزایش (تومان):")
                return
            elif step == 'ask_add_bal_amount':
                target = temp_data[chat_id]['target']
                conn = sqlite3.connect(DB_PATH)
                c = conn.cursor()
                c.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (int(text), target))
                conn.commit()
                conn.close()
                bot.send_message(chat_id, "✅ موجودی افزایش یافت.")
                try: bot.send_message(target, f"🎁 مبلغ {int(text):,} تومان توسط مدیریت به کیف پول شما افزوده شد.")
                except: pass
                user_steps.pop(chat_id, None)
                return
            elif step == 'ask_deduct_bal_id':
                temp_data[chat_id] = {'target': text}
                user_steps[chat_id] = 'ask_deduct_bal_amount'
                bot.send_message(chat_id, "مبلغ کسر (تومان):")
                return
            elif step == 'ask_deduct_bal_amount':
                target = temp_data[chat_id]['target']
                conn = sqlite3.connect(DB_PATH)
                c = conn.cursor()
                c.execute("UPDATE users SET balance = balance - ? WHERE user_id=?", (int(text), target))
                conn.commit()
                conn.close()
                bot.send_message(chat_id, "✅ موجودی کسر شد.")
                user_steps.pop(chat_id, None)
                return
            elif step == 'ask_card_number':
                conn = sqlite3.connect(DB_PATH)
                c = conn.cursor()
                c.execute("UPDATE settings SET value=? WHERE key='card_number'", (text,))
                conn.commit()
                conn.close()
                user_steps[chat_id] = 'ask_card_name'
                bot.send_message(chat_id, "👤 حالا نام و نام خانوادگی مالک کارت را بفرستید:")
                return
            elif step == 'ask_card_name':
                conn = sqlite3.connect(DB_PATH)
                c = conn.cursor()
                c.execute("UPDATE settings SET value=? WHERE key='card_name'", (text,))
                conn.commit()
                conn.close()
                bot.send_message(chat_id, "✅ اطلاعات کارت جدید شما با موفقیت در دیتابیس ثبت شد.")
                user_steps.pop(chat_id, None)
                return
            elif step == 'ask_add_channel':
                conn = sqlite3.connect(DB_PATH)
                c = conn.cursor()
                c.execute("INSERT OR IGNORE INTO channels (channel_id) VALUES (?)", (text,))
                conn.commit()
                conn.close()
                bot.send_message(chat_id, "✅ کانال اضافه شد.")
                user_steps.pop(chat_id, None)
                return

            elif step == 'ask_subcat_name':
                parent_cat = temp_data[chat_id]['parent_cat']
                conn = sqlite3.connect(DB_PATH)
                c = conn.cursor()
                c.execute("INSERT INTO sub_categories (parent_cat, name) VALUES (?, ?)", (parent_cat, text))
                conn.commit()
                conn.close()
                bot.send_message(chat_id, f"✅ پوشه «{text}» با موفقیت ساخته شد.")
                user_steps.pop(chat_id, None)
                send_cat_menu(chat_id, parent_cat, temp_data[chat_id]['cat_name'])
                return
            elif step == 'ask_prod_name':
                temp_data[chat_id]['name'] = text
                user_steps[chat_id] = 'ask_prod_price'
                bot.send_message(chat_id, "💰 قیمت محصول (به ازای هر عدد):")
                return
            elif step == 'ask_prod_price':
                temp_data[chat_id]['price'] = int(text)
                user_steps[chat_id] = 'ask_prod_min'
                bot.send_message(chat_id, "📉 حداقل مقدار سفارش:")
                return
            elif step == 'ask_prod_min':
                temp_data[chat_id]['min_order'] = int(text)
                user_steps[chat_id] = 'ask_prod_max'
                bot.send_message(chat_id, "📈 حداکثر مقدار سفارش:")
                return
            elif step == 'ask_prod_max':
                temp_data[chat_id]['max_order'] = int(text)
                user_steps[chat_id] = 'ask_prod_link'
                bot.send_message(chat_id, "🔗 یک لینک نمونه وارد کنید:")
                return
            elif step == 'ask_prod_link':
                temp_data[chat_id]['sample_link'] = text
                user_steps[chat_id] = 'ask_prod_desc'
                bot.send_message(chat_id, "💬 توضیحات محصول را وارد کنید:")
                return
            elif step == 'ask_prod_desc':
                d = temp_data[chat_id]
                conn = sqlite3.connect(DB_PATH)
                c = conn.cursor()
                c.execute('''INSERT INTO products (subcat_id, name, price, min_order, max_order, sample_link, description)
                             VALUES (?, ?, ?, ?, ?, ?, ?)''', (d['subcat_id'], d['name'], d['price'], d['min_order'], d['max_order'], d['sample_link'], text))
                conn.commit()
                conn.close()
                bot.send_message(chat_id, f"✅ محصول ساخته شد!")
                user_steps.pop(chat_id, None)
                send_subcat_menu(chat_id, d['subcat_id'], d['subcat_name'])
                return

    category_map = {"🛒 خدمات تلگرام": "telegram", "📸 خدمات اینستا": "insta", "🎵 خدمات تیک تاک": "tiktok", "▶️ خدمات یوتیوب": "youtube", "🟣 خدمات روبیکا": "rubika"}
    if text in category_map:
        cat_id = category_map[text]
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT value FROM settings WHERE key=?", (f"lock_{cat_id}",))
        res = c.fetchone()
        conn.close()
        
        if res and res[0] == '1':
            bot.send_message(chat_id, "🔒 **این بخش موقتاً توسط مدیریت غیرفعال شده است.**", parse_mode="Markdown")
            return
            
        send_cat_menu(chat_id, cat_id, text)
        return

    nav = user_nav.get(chat_id, {})
    
    if nav.get('level') == 'cat':
        clean_text = text.replace("🔒 ", "")
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT id, is_locked FROM sub_categories WHERE parent_cat=? AND name=?", (nav['current_cat'], clean_text))
        sc = c.fetchone()
        conn.close()
        if sc:
            if sc[1] == 1: bot.send_message(chat_id, "🔒 این دکمه قفل می‌باشد.")
            else: send_subcat_menu(chat_id, sc[0], clean_text)
            return

    if nav.get('level') == 'subcat':
        clean_text = text.replace("🔒 ", "")
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT * FROM products WHERE subcat_id=? AND name=?", (nav['current_subcat'], clean_text))
        prod = c.fetchone()
        
        if prod:
            if prod[8] == 1:
                bot.send_message(chat_id, "🔒 این دکمه قفل می‌باشد.")
                conn.close()
                return
                
            cat_id = nav['current_cat']
            c.execute('''SELECT d.code, d.percent FROM user_discounts u JOIN discount_codes d ON u.code = d.code WHERE u.user_id=? AND u.remaining_uses > 0 AND (d.category=? OR d.category='all') ORDER BY d.percent DESC LIMIT 1''', (chat_id, cat_id))
            disc = c.fetchone()
            conn.close()
            
            price_txt = f"💰 **قیمت (هر عدد):** {prod[3]:,} تومان"
            if disc:
                new_p = int(prod[3] * (100 - disc[1]) / 100)
                price_txt = f"💰 **قیمت اصلی:** ❌ {prod[3]:,} تومان\n🎁 **با تخفیف ({disc[1]}%):** ✅ {new_p:,} تومان"
            
            info = f"""📌 **نام سرویس:** {prod[2]}
{price_txt}
📉 **حداقل سفارش:** {prod[4]}
📈 **حداکثر سفارش:** {prod[5]}
🔗 **نمونه:** `{prod[6]}`

📝 **توضیحات:**
{prod[7]}"""
            
            user_steps[chat_id] = 'ask_order_qty'
            temp_data[chat_id] = {'type': 'virtual', 'prod_id': prod[0], 'name': prod[2], 'price': prod[3], 'min': prod[4], 'max': prod[5], 'sample': prod[6]}
            if disc:
                temp_data[chat_id]['discount_code'] = disc[0]
                temp_data[chat_id]['discount_percent'] = disc[1]
                
            markup = InlineKeyboardMarkup().add(InlineKeyboardButton("🛒 ثبت سفارش", callback_data=f"buyprod_{prod[0]}", style="success"))
            bot.send_message(chat_id, info, reply_markup=markup, parse_mode="Markdown")
            return

    if text == "⚙️ پنل مدیریت کل" and is_admin(chat_id):
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(InlineKeyboardButton("🔒 قفل دکمه‌های اصلی", callback_data="admin_lock_main", style="primary"),
                   InlineKeyboardButton("🌐 قیمت‌های VPN", callback_data="admin_vpn_prices", style="primary"))
        markup.add(InlineKeyboardButton("🏷 تنظیم کد تخفیف", callback_data="admin_add_discount", style="success"))
        markup.add(InlineKeyboardButton("👥 اطلاعات کاربران", callback_data="admin_export_users", style="primary"),
                   InlineKeyboardButton("🔍 پیگیری سفارش", callback_data="admin_search_order", style="primary"))
        markup.add(InlineKeyboardButton("👮‍♂️ تنظیم ادمین", callback_data="admin_set_admin", style="success"),
                   InlineKeyboardButton("❌ عزل ادمین", callback_data="admin_del_admin", style="danger"))
        markup.add(InlineKeyboardButton("🚫 بن کردن", callback_data="admin_ban", style="danger"),
                   InlineKeyboardButton("✅ رفع بن", callback_data="admin_unban", style="success"))
        markup.add(InlineKeyboardButton("💰 افزایش موجودی", callback_data="admin_add_bal", style="success"),
                   InlineKeyboardButton("💸 کسر موجودی", callback_data="admin_deduct_bal", style="danger"))
        markup.add(InlineKeyboardButton("💳 تنظیم شماره کارت", callback_data="admin_set_card", style="primary"),
                   InlineKeyboardButton("📢 پیام همگانی", callback_data="admin_broadcast", style="primary"))
        markup.add(InlineKeyboardButton("✉️ پیام ناشناس", callback_data="admin_anon_msg", style="primary"),
                   InlineKeyboardButton("📺 چنل‌های اجباری", callback_data="admin_channels", style="primary"))
        markup.add(InlineKeyboardButton("📚 تنظیم لینک آموزش", callback_data="admin_set_tutorial", style="primary"),
                   InlineKeyboardButton("♻️ ریست تست VPN", callback_data="admin_reset_test", style="success"))
        bot.send_message(chat_id, "⚙️ **پنل مدیریت کل ربات:**", reply_markup=markup, parse_mode="Markdown")
        return

    if text.startswith("⚙️ مدیریت دسته‌های") and is_admin(chat_id):
        cat_id = user_nav.get(chat_id, {}).get('current_cat')
        if not cat_id: return
        markup = InlineKeyboardMarkup(row_width=1)
        markup.add(InlineKeyboardButton("➕ ساخت دکمه (پوشه جدید)", callback_data=f"create_subcat_{cat_id}", style="success"))
        markup.add(InlineKeyboardButton("⚙ مدیریت پوشه‌های فعلی (حذف/قفل)", callback_data=f"managelist_sc_{cat_id}", style="primary"))
        bot.send_message(chat_id, "⚙️ **منوی مدیریت پوشه‌ها:**", reply_markup=markup, parse_mode="Markdown")
        return
        
    if text.startswith("⚙️ مدیریت محصولات") and is_admin(chat_id):
        subcat_id = user_nav.get(chat_id, {}).get('current_subcat')
        if not subcat_id: return
        markup = InlineKeyboardMarkup(row_width=1)
        markup.add(InlineKeyboardButton("➕ ساخت محصول نهایی", callback_data=f"create_prod_{subcat_id}", style="success"))
        markup.add(InlineKeyboardButton("⚙️ مدیریت محصولات فعلی (ویرایش/حذف/قفل)", callback_data=f"managelist_pr_{subcat_id}", style="primary"))
        bot.send_message(chat_id, "⚙️ **منوی مدیریت محصولات:**", reply_markup=markup, parse_mode="Markdown")
        return

@bot.callback_query_handler(func=lambda call: True)
def handle_query(call):
    chat_id = call.message.chat.id
    msg_id = call.message.message_id
    data = call.data
    
    ban_reason = check_banned(chat_id)
    if ban_reason:
        bot.answer_callback_query(call.id, f"🚫 حساب شما مسدود است.", show_alert=True)
        return

    if data == "ignore":
        bot.answer_callback_query(call.id, "این دکمه فقط جهت نمایش آمار است.", show_alert=False)
        return

    if data == "notut":
        bot.answer_callback_query(call.id, "لینک آموزش هنوز توسط مدیریت ثبت نشده است.", show_alert=True)
        return

    if data == "check_join":
        if check_join(chat_id):
            bot.delete_message(chat_id, msg_id)
            bot.answer_callback_query(call.id, "عضویت شما تایید شد!", show_alert=True)
            send_main_menu(chat_id)
        else:
            bot.answer_callback_query(call.id, "هنوز در کانال‌ها عضو نشده‌اید!", show_alert=True)

    # ==========================
    # اضافه شدن کال‌بک شارژ کیف پول
    # ==========================
    elif data == "charge_wallet":
        user_steps[chat_id] = 'ask_charge_amount'
        bot.send_message(chat_id, "💰 **لطفاً مبلغ مورد نظر برای شارژ کیف پول را به تومان وارد کنید:**\n(حداقل 10,000 تومان)", parse_mode="Markdown")

    elif data == "copy_cardnum":
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT value FROM settings WHERE key='card_number'")
        card_num = c.fetchone()[0]
        conn.close()
        bot.send_message(chat_id, f"`{card_num}`", parse_mode="Markdown")
        bot.answer_callback_query(call.id, "شماره کارت برای کپی ارسال شد.", show_alert=False)
        
    elif data.startswith("copy_rial_"):
        rial_amount = data.split("_")[2]
        bot.send_message(chat_id, f"`{rial_amount}`", parse_mode="Markdown")
        bot.answer_callback_query(call.id, "مبلغ ریالی برای کپی ارسال شد.", show_alert=False)

    elif data == "admin_add_discount" and is_admin(chat_id):
        user_steps[chat_id] = "ask_disc_code"
        bot.send_message(chat_id, "🏷 **کلمه کد تخفیف** را به زبان انگلیسی وارد کنید (مثلاً Zimo):", parse_mode="Markdown")
        
    elif data.startswith("set_disc_cat_") and is_admin(chat_id):
        cat = data.split("_")[3]
        d = temp_data[chat_id]
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("INSERT OR REPLACE INTO discount_codes (code, percent, global_limit, user_limit, category) VALUES (?, ?, ?, ?, ?)",
                  (d['disc_code'], d['disc_percent'], d['disc_global'], d['disc_user'], cat))
        conn.commit()
        conn.close()
        bot.edit_message_text(f"✅ کد تخفیف `{d['disc_code']}` با موفقیت برای بخش `{cat}` با ظرفیت {d['disc_global']} نفر ثبت شد.", chat_id, msg_id, parse_mode="Markdown")
        user_steps.pop(chat_id, None)

    elif data == "admin_vpn_prices" and is_admin(chat_id):
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(InlineKeyboardButton("تعرفه پایه", callback_data="edit_vpn_base", style="primary"))
        markup.add(InlineKeyboardButton("15 گیگ", callback_data="edit_vpn_15", style="primary"), InlineKeyboardButton("25 گیگ", callback_data="edit_vpn_25", style="primary"))
        markup.add(InlineKeyboardButton("35 گیگ", callback_data="edit_vpn_35", style="primary"), InlineKeyboardButton("50 گیگ", callback_data="edit_vpn_50", style="primary"))
        markup.add(InlineKeyboardButton("100 گیگ (تک کاربره)", callback_data="edit_vpn_100_1", style="primary"))
        markup.add(InlineKeyboardButton("100 گیگ (دو کاربره)", callback_data="edit_vpn_100_2", style="primary"), InlineKeyboardButton("100 گیگ (سه کاربره)", callback_data="edit_vpn_100_3", style="primary"))
        bot.edit_message_text("یک پلن را برای تغییر قیمت انتخاب کنید:", chat_id, msg_id, reply_markup=markup)

    elif data.startswith("edit_vpn_") and is_admin(chat_id):
        plan = data.replace("edit_vpn_", "")
        user_steps[chat_id] = f"ask_edit_vpn_{plan}"
        bot.send_message(chat_id, f"💰 لطفا قیمت جدید برای این پلن را به تومان وارد کنید (فقط عدد):", parse_mode="Markdown")

    elif data == "myservices_virtual":
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT id, prod_name, track_code, status FROM orders WHERE user_id=? ORDER BY id DESC LIMIT 20", (chat_id,))
        orders = c.fetchall()
        conn.close()
        markup = InlineKeyboardMarkup(row_width=1)
        if not orders:
            markup.add(InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_services", style="danger"))
            if call.message.content_type == 'photo':
                bot.delete_message(chat_id, msg_id)
                bot.send_message(chat_id, "شما هنوز هیچ سفارش مجازی ثبت نکرده‌اید.", reply_markup=markup)
            else:
                bot.edit_message_text("شما هنوز هیچ سفارش مجازی ثبت نکرده‌اید.", chat_id, msg_id, reply_markup=markup)
            return
        for ord in orders:
            status_emoji = "⏳" if ord[3] == "در حال انجام" else "✅" if ord[3] == "تکمیل شده" else "❌"
            markup.add(InlineKeyboardButton(f"{status_emoji} {ord[1]} ({ord[2]})", callback_data=f"myord_{ord[0]}", style="primary"))
        markup.add(InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_services", style="danger"))
        if call.message.content_type == 'photo':
            bot.delete_message(chat_id, msg_id)
            bot.send_message(chat_id, "📂 **لیست سفارشات مجازی شما:**\n(برای دیدن جزئیات کلیک کنید)", reply_markup=markup, parse_mode="Markdown")
        else:
            bot.edit_message_text("📂 **لیست سفارشات مجازی شما:**\n(برای دیدن جزئیات کلیک کنید)", chat_id, msg_id, reply_markup=markup, parse_mode="Markdown")

    elif data == "myservices_vpn":
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT id, name, track_code FROM vpn_orders WHERE user_id=? ORDER BY id DESC LIMIT 20", (chat_id,))
        vpns = c.fetchall()
        conn.close()
        markup = InlineKeyboardMarkup(row_width=1)
        if not vpns:
            markup.add(InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_services", style="danger"))
            if call.message.content_type == 'photo':
                bot.delete_message(chat_id, msg_id)
                bot.send_message(chat_id, "شما هنوز هیچ سرویس VPN خریداری نکرده‌‌اید.", reply_markup=markup)
            else:
                bot.edit_message_text("شما هنوز هیچ سرویس VPN خریداری نکرده‌اید.", chat_id, msg_id, reply_markup=markup)
            return
        for v in vpns:
            markup.add(InlineKeyboardButton(f"🌐 {v[1]} ({v[2]})", callback_data=f"myvpn_{v[0]}", style="primary"))
        markup.add(InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_services", style="danger"))
        if call.message.content_type == 'photo':
            bot.delete_message(chat_id, msg_id)
            bot.send_message(chat_id, "🌐 **لیست سرویس‌های VPN شما:**", reply_markup=markup, parse_mode="Markdown")
        else:
            bot.edit_message_text("🌐 **لیست سرویس‌های VPN شما:**", chat_id, msg_id, reply_markup=markup, parse_mode="Markdown")
        
    elif data == "back_to_services":
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(InlineKeyboardButton("🛒 خدمات مجازی", callback_data="myservices_virtual", style="primary"),
                   InlineKeyboardButton("🌐 سرویس های VPN", callback_data="myservices_vpn", style="primary"))
        if call.message.content_type == 'photo':
            bot.delete_message(chat_id, msg_id)
            bot.send_message(chat_id, "📂 **بخش مورد نظر را انتخاب کنید:**", reply_markup=markup, parse_mode="Markdown")
        else:
            bot.edit_message_text("📂 **بخش مورد نظر را انتخاب کنید:**", chat_id, msg_id, reply_markup=markup, parse_mode="Markdown")
        
    elif data.startswith("myord_"):
        ord_id = data.split("_")[1]
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT * FROM orders WHERE id=? AND user_id=?", (ord_id, chat_id))
        ord_data = c.fetchone()
        conn.close()
        if not ord_data: return bot.answer_callback_query(call.id, "سفارش یافت نشد.", show_alert=True)
        msg = f"""🧾 **جزئیات سفارش**
━━━━ ❖ ━━━━
📌 **محصول:** {ord_data[3]}
🔢 **تعداد:** {ord_data[4]}
🔗 **لینک:** `{ord_data[5]}`
💰 **هزینه:** {ord_data[6]:,} تومان
━━━━ ❖ ━━━━
📊 **وضعیت:** {ord_data[7]}
📅 **تاریخ:** {ord_data[9]}
🔑 **کد پیگیری:** `{ord_data[8]}`"""
        markup = InlineKeyboardMarkup().add(InlineKeyboardButton("🔙 بازگشت به لیست", callback_data="myservices_virtual", style="danger"))
        if call.message.content_type == 'photo':
            bot.delete_message(chat_id, msg_id)
            bot.send_message(chat_id, msg, reply_markup=markup, parse_mode="Markdown")
        else:
            bot.edit_message_text(msg, chat_id, msg_id, reply_markup=markup, parse_mode="Markdown")

    elif data.startswith("myvpn_"):
        vpn_id = data.split("_")[1]
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT * FROM vpn_orders WHERE id=? AND user_id=?", (vpn_id, chat_id))
        v_data = c.fetchone()
        
        try:
            c.execute("SELECT value FROM settings WHERE key='tutorial_link'")
            tut_res = c.fetchone()
            tut_link = tut_res[0] if tut_res else 'تنظیم نشده'
        except:
            tut_link = 'تنظیم نشده'
            
        if not v_data: 
            conn.close()
            return bot.answer_callback_query(call.id, "سرویس یافت نشد.", show_alert=True)
            
        config_link = v_data[5]
        
        panel_username = ""
        try:
            c.execute("SELECT panel_username FROM vpn_orders WHERE id=?", (vpn_id,))
            p_res = c.fetchone()
            if p_res and p_res[0]: panel_username = p_res[0]
        except: pass
        
        if not panel_username:
            if "#" in config_link:
                panel_username = unquote(config_link.split("#")[-1]).strip()
            
            if not panel_username:
                panel_username = get_username_by_sublink(config_link)
                
            if panel_username:
                try:
                    c.execute("UPDATE vpn_orders SET panel_username=? WHERE id=?", (panel_username, vpn_id))
                    conn.commit()
                except: pass
                
        conn.close()
        
        used_str = "نا مشخص"
        time_str = "نا مشخص"
        
        if panel_username:
            panel_info = get_vpn_usage(panel_username)
            if panel_info:
                try:
                    d_val = panel_info.get("data_limit")
                    u_val = panel_info.get("used_traffic")
                    
                    data_limit = int(float(d_val)) if d_val else 0
                    used_traffic = int(float(u_val)) if u_val else 0
                    
                    def fmt_size(b):
                        if not b or b == 0: return "0 MB"
                        gb = round(b / 1073741824, 2)
                        if gb >= 1: return f"{gb} GB"
                        return f"{round(b / 1048576, 2)} MB"
                    
                    used_formatted = fmt_size(used_traffic)
                    
                    if data_limit == 0:
                        used_str = f"{used_formatted} (نامحدود)"
                    else:
                        total_formatted = fmt_size(data_limit)
                        remain = max(0, data_limit - used_traffic)
                        used_str = f"{used_formatted} از {total_formatted} ({fmt_size(remain)} مانده)"
                    
                    exp_val = panel_info.get("expire")
                    
                    if not exp_val:
                        time_str = "♾ نامحدود"
                    else:
                        expire_timestamp = 0
                        try:
                            expire_timestamp = int(float(exp_val))
                        except ValueError:
                            try:
                                dt_obj = datetime.fromisoformat(str(exp_val).replace("Z", ""))
                                expire_timestamp = int(dt_obj.timestamp())
                            except:
                                pass
                                
                        if expire_timestamp == 0:
                            time_str = "♾ نامحدود"
                        else:
                            now = time.time()
                            if expire_timestamp > now:
                                days = int((expire_timestamp - now) / 86400)
                                hours = int(((expire_timestamp - now) % 86400) / 3600)
                                time_str = f"{days} روز و {hours} ساعت"
                            else:
                                time_str = "❌ پایان یافته"
                except Exception as e:
                    used_str = "خطا در پردازش اطلاعات"
                    time_str = "خطا در پردازش اطلاعات"
        
        msg = f"🌐 **مدیریت سرویس VPN**\n━━━━ ❖ ━━━━\n📌 **نام پلن:** {v_data[3]}\n📅 **تاریخ خرید:** {v_data[7]}\n\n👇 جهت مدیریت از دکمه‌های زیر استفاده کنید:"
        
        markup = InlineKeyboardMarkup(row_width=1)
        markup.add(
            InlineKeyboardButton(f"📊 حجم: {used_str}", callback_data="ignore"),
            InlineKeyboardButton(f"⏳ زمان: {time_str}", callback_data="ignore")
        )
        markup.row(
            InlineKeyboardButton("🔗 دریافت لینک کانفیگ", callback_data=f"showlink_{vpn_id}", style="success"),
            InlineKeyboardButton("📱 دریافت QR Code", callback_data=f"showqr_{vpn_id}", style="success")
        )
        if tut_link != 'تنظیم نشده':
            markup.add(InlineKeyboardButton("📚 آموزش اتصال", url=tut_link))
        else:
            markup.add(InlineKeyboardButton("📚 آموزش اتصال (ثبت نشده)", callback_data="notut", style="danger"))
            
        markup.add(InlineKeyboardButton("🗑 حذف این سرویس", callback_data=f"askdelvpn_{vpn_id}", style="danger"))
        markup.add(InlineKeyboardButton("🔙 بازگشت به لیست", callback_data="myservices_vpn", style="primary"))
        
        if call.message.content_type == 'photo':
            bot.delete_message(chat_id, msg_id)
            bot.send_message(chat_id, msg, reply_markup=markup, parse_mode="Markdown")
        else:
            bot.edit_message_text(msg, chat_id, msg_id, reply_markup=markup, parse_mode="Markdown")

    elif data.startswith("showlink_"):
        vpn_id = data.split("_")[1]
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT config_link FROM vpn_orders WHERE id=?", (vpn_id,))
        link = c.fetchone()[0]
        conn.close()
        msg = f"🔗 **لینک اتصال کانفیگ شما:**\n\n`{link}`\n\n*(با یک لمس کپی می‌شود)*"
        markup = InlineKeyboardMarkup().add(InlineKeyboardButton("🔙 بازگشت به سرویس", callback_data=f"myvpn_{vpn_id}", style="danger"))
        if call.message.content_type == 'photo':
            bot.delete_message(chat_id, msg_id)
            bot.send_message(chat_id, msg, reply_markup=markup, parse_mode="Markdown")
        else:
            bot.edit_message_text(msg, chat_id, msg_id, reply_markup=markup, parse_mode="Markdown")

    elif data.startswith("showqr_"):
        vpn_id = data.split("_")[1]
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT config_link FROM vpn_orders WHERE id=?", (vpn_id,))
        link = c.fetchone()[0]
        conn.close()
        qr_url = f"https://api.qrserver.com/v1/create-qr-code/?size=400x400&data={quote(link)}"
        markup = InlineKeyboardMarkup().add(InlineKeyboardButton("🔙 بازگشت به سرویس", callback_data=f"myvpn_{vpn_id}", style="danger"))
        bot.delete_message(chat_id, msg_id)
        bot.send_photo(chat_id, qr_url, caption="📱 **این هم QR Code کانفیگ شما**\nمی‌توانید اسکن کنید.", reply_markup=markup, parse_mode="Markdown")

    elif data.startswith("askdelvpn_"):
        vpn_id = data.split("_")[1]
        msg = "⚠️ **هشدار بسیار مهم!**\n\nآیا از حذف دائمی این سرویس اطمینان دارید؟\nبا تایید شما، این کانفیگ از روی سرورها نیز کلاً پاک شده و **به هیچ وجه قابل بازیابی یا استفاده مجدد نخواهد بود.**"
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(
            InlineKeyboardButton("✅ بله، کاملاً حذف شود", callback_data=f"confdelvpn_{vpn_id}", style="success"),
            InlineKeyboardButton("❌ لغو و بازگشت", callback_data=f"myvpn_{vpn_id}", style="primary")
        )
        if call.message.content_type == 'photo':
            bot.delete_message(chat_id, msg_id)
            bot.send_message(chat_id, msg, reply_markup=markup, parse_mode="Markdown")
        else:
            bot.edit_message_text(msg, chat_id, msg_id, reply_markup=markup, parse_mode="Markdown")

    elif data.startswith("confdelvpn_"):
        vpn_id = data.split("_")[1]
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        
        c.execute("SELECT config_link FROM vpn_orders WHERE id=?", (vpn_id,))
        res = c.fetchone()
        if res:
            config_link = res[0]
            panel_user = ""
            try:
                c.execute("SELECT panel_username FROM vpn_orders WHERE id=?", (vpn_id,))
                p_res = c.fetchone()
                if p_res and p_res[0]: panel_user = p_res[0]
            except: pass
            
            if not panel_user:
                if "#" in config_link:
                    panel_user = unquote(config_link.split("#")[-1]).strip()
                else:
                    panel_user = get_username_by_sublink(config_link)
                
            if panel_user:
                delete_vpn_user(panel_user)
                
        c.execute("DELETE FROM vpn_orders WHERE id=?", (vpn_id,))
        conn.commit()
        conn.close()
        
        markup = InlineKeyboardMarkup().add(InlineKeyboardButton("🔙 بازگشت به لیست", callback_data="myservices_vpn", style="primary"))
        msg = "✅ **سرویس شما با موفقیت از سیستم ربات و سرور اصلی به طور کامل حذف شد.**"
        if call.message.content_type == 'photo':
            bot.delete_message(chat_id, msg_id)
            bot.send_message(chat_id, msg, reply_markup=markup, parse_mode="Markdown")
        else:
            bot.edit_message_text(msg, chat_id, msg_id, reply_markup=markup, parse_mode="Markdown")

    elif data.startswith("buyprod_"):
        prod_id = data.split("_")[1]
        nav = user_nav.get(chat_id, {})
        cat_id = nav.get('current_cat', 'telegram')
        
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT * FROM products WHERE id=?", (prod_id,))
        prod = c.fetchone()
        
        c.execute('''SELECT d.code, d.percent FROM user_discounts u JOIN discount_codes d ON u.code = d.code WHERE u.user_id=? AND u.remaining_uses > 0 AND (d.category=? OR d.category='all') ORDER BY d.percent DESC LIMIT 1''', (chat_id, cat_id))
        disc = c.fetchone()
        conn.close()
        
        user_steps[chat_id] = 'ask_order_qty'
        
        temp_data[chat_id] = {'type': 'virtual', 'prod_id': prod[0], 'name': prod[2], 'price': prod[3], 'min': prod[4], 'max': prod[5], 'sample': prod[6]}
        if disc:
            temp_data[chat_id]['discount_code'] = disc[0]
            temp_data[chat_id]['discount_percent'] = disc[1]
            
        bot.send_message(chat_id, f"سفارش **{prod[2]}**\nتعداد درخواستی (حداقل {prod[4]} | حداکثر {prod[5]}):", parse_mode="Markdown")

    elif data == "cancel_order":
        user_steps.pop(chat_id, None)
        bot.edit_message_text("❌ لغو شد.", chat_id, msg_id)

    elif data == "conf_order":
        if chat_id not in temp_data or temp_data[chat_id].get('type') != 'virtual': return
        d = temp_data[chat_id]
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT balance, total_orders FROM users WHERE user_id=?", (chat_id,))
        user = c.fetchone()
        if user[0] < d['total_price']:
            bot.edit_message_text("❌ موجودی شما کافی نیست! لطفا شارژ کنید.", chat_id, msg_id)
            conn.close()
            return
            
        new_balance = user[0] - d['total_price']
        track_code = generate_track_code()
        date_now = datetime.now().strftime("%Y-%m-%d %H:%M")
        
        c.execute("UPDATE users SET balance=?, total_orders=? WHERE user_id=?", (new_balance, user[1]+1, chat_id))
        
        disc_code = d.get('discount_code', '')
        c.execute("INSERT INTO orders (user_id, prod_id, prod_name, qty, order_link, total_price, status, track_code, date, discount_code) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                  (chat_id, d['prod_id'], d['name'], d['qty'], d['link'], d['total_price'], 'در حال انجام', track_code, date_now, disc_code))
        order_id = c.lastrowid
        
        if disc_code:
            c.execute("UPDATE user_discounts SET remaining_uses = remaining_uses - 1 WHERE user_id=? AND code=?", (chat_id, disc_code))
            
        # پاداش زیرمجموعه‌گیری
        c.execute("SELECT referrer_id FROM users WHERE user_id=?", (chat_id,))
        ref_res = c.fetchone()
        if ref_res and ref_res[0] != 0:
            referrer = ref_res[0]
            reward = int(d['total_price'] * 0.10)
            if reward > 0:
                c.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (reward, referrer))
                try: bot.send_message(referrer, f"✅ **تبریک!** زیرمجموعه شما سفارشی ثبت کرد و مبلغ **{reward:,} تومان** (10 درصد پورسانت) به کیف پول شما اضافه شد.", parse_mode="Markdown")
                except: pass
            
        conn.commit()
        conn.close()
        
        bot.edit_message_text(f"✅ ثبت شد.\nموجودی جدید: {new_balance:,}\nکد پیگیری: `{track_code}`", chat_id, msg_id, parse_mode="Markdown")
        
        msg_admin = f"🛒 **سفارش جدید**\n📌 {d['name']}\n🔢 {d['qty']}\n🔗 {d['link']}\n🧾 `{track_code}`"
        markup_admin = InlineKeyboardMarkup(row_width=2)
        markup_admin.add(InlineKeyboardButton("ℹ️ اطلاعات سفارش دهنده", callback_data=f"ordinfo_{chat_id}", style="primary"))
        markup_admin.add(InlineKeyboardButton("✅ تایید", callback_data=f"ordacc_{order_id}", style="success"), InlineKeyboardButton("❌ لغو", callback_data=f"ordrej_{order_id}", style="danger"))
        admins = get_all_admins()
        for admin in admins:
            try: bot.send_message(admin, msg_admin, reply_markup=markup_admin, parse_mode="Markdown")
            except: pass

    elif data.startswith("buyvpn_"):
        plan = data.replace("buyvpn_", "")
        
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        
        c.execute("SELECT key, value FROM settings WHERE key LIKE 'vpn_price_%'")
        vpn_db_prices = {row[0]: int(row[1]) for row in c.fetchall()}

        vpn_prices = {
            '15': {'price': vpn_db_prices.get('vpn_price_15', 50000), 'name': '15 گیگ (نامحدود)'},
            '25': {'price': vpn_db_prices.get('vpn_price_25', 85000), 'name': '25 گیگ (نامحدود)'},
            '35': {'price': vpn_db_prices.get('vpn_price_35', 120000), 'name': '35 گیگ (نامحدود)'},
            '50': {'price': vpn_db_prices.get('vpn_price_50', 175000), 'name': '50 گیگ (نامحدود)'},
            '100_1': {'price': vpn_db_prices.get('vpn_price_100_1', 250000), 'name': '100 گیگ (دو ماهه - تک کاربره)'},
            '100_2': {'price': vpn_db_prices.get('vpn_price_100_2', 275000), 'name': '100 گیگ (دو ماهه - دو کاربره)'},
            '100_3': {'price': vpn_db_prices.get('vpn_price_100_3', 300000), 'name': '100 گیگ (دو ماهه - سه کاربره)'},
            'test': {'price': 0, 'name': '50 مگ تست رایگان'}
        }
        
        if plan not in vpn_prices: 
            conn.close()
            return
            
        info = vpn_prices[plan]
        
        if plan == 'test':
            c.execute("SELECT id FROM vpn_orders WHERE user_id=? AND plan_id='test'", (chat_id,))
            has_test = c.fetchone()
            if has_test: 
                conn.close()
                return bot.answer_callback_query(call.id, "❌ شما قبلاً از سرویس تست استفاده کرده‌اید!", show_alert=True)

        c.execute('''SELECT d.code, d.percent FROM user_discounts u JOIN discount_codes d ON u.code = d.code WHERE u.user_id=? AND u.remaining_uses > 0 AND (d.category='vpn' OR d.category='all') ORDER BY d.percent DESC LIMIT 1''', (chat_id,))
        disc = c.fetchone()
        conn.close()

        final_price = info['price']
        price_txt = f"{final_price:,} تومان"
        
        temp_data[chat_id] = {'type': 'vpn', 'plan': plan, 'info': info}
        
        if disc and plan != 'test':
            temp_data[chat_id]['discount_code'] = disc[0]
            temp_data[chat_id]['discount_percent'] = disc[1]
            final_price = int(info['price'] * (100 - disc[1]) / 100)
            price_txt = f"❌ اصلی: {info['price']:,} تومان\n🎁 **با تخفیف ({disc[1]}%):** ✅ {final_price:,} تومان"
            temp_data[chat_id]['info']['final_price'] = final_price
        else:
            temp_data[chat_id]['info']['final_price'] = final_price

        msg = f"""🛒 **تایید نهایی خرید VPN**
━━━━ ❖ ━━━━
📌 **پلن انتخابی:** {info['name']}
💰 **مبلغ پرداخت:** 
{price_txt}
━━━━ ❖ ━━━━
⚠️ آیا از خرید این سرویس اطمینان دارید؟"""
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("✅ بله، خرید را انجام بده", callback_data="conf_vpn_order", style="success"),
                   InlineKeyboardButton("❌ لغو", callback_data="cancel_order", style="danger"))
        
        if call.message.content_type == 'photo':
            bot.delete_message(chat_id, msg_id)
            bot.send_message(chat_id, msg, reply_markup=markup, parse_mode="Markdown")
        else:
            bot.edit_message_text(msg, chat_id, msg_id, reply_markup=markup, parse_mode="Markdown")

    elif data == "conf_vpn_order":
        if chat_id not in temp_data or temp_data[chat_id].get('type') != 'vpn': return
        
        d = temp_data[chat_id]
        plan = d['plan']
        price = d['info']['final_price']
        name = d['info']['name']
        
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT balance, total_orders FROM users WHERE user_id=?", (chat_id,))
        user = c.fetchone()
        
        if user[0] < price:
            bot.edit_message_text("❌ موجودی حساب شما برای خرید این سرویس کافی نیست!\nلطفا از بخش کیف پول شارژ کنید.", chat_id, msg_id)
            conn.close()
            return
            
        new_bal = user[0] - price
        track_code = generate_track_code()
        date_now = datetime.now().strftime("%Y-%m-%d %H:%M")
        
        vol_total = "100 GB" if plan.startswith('100') else (plan + " GB" if plan.isdigit() else "50 MB")
        expire_date = "60 روز" if plan.startswith('100') else "نامحدود"
        if plan == 'test': expire_date = "24 ساعت"
        
        expire_time = 0
        if plan.startswith('100'):
            data_limit = 100 * 1073741824
            expire_time = int(time.time()) + (60 * 24 * 60 * 60)
        elif plan == 'test':
            data_limit = 50 * 1048576
            expire_time = int(time.time()) + (24 * 60 * 60)
        else:
            data_limit = int(plan) * 1073741824
            
        username = f"zisa_vpn_{chat_id}_{random.randint(100, 999)}"
        
        try:
            config_link = create_pasarguard_user(username, data_limit, expire_time, note=f"Zisa - {name}")
            
            c.execute("UPDATE users SET balance=?, total_orders=? WHERE user_id=?", (new_bal, user[1]+1, chat_id))
            
            disc_code = d.get('discount_code', '')
            c.execute("INSERT INTO vpn_orders (user_id, plan_id, name, price, config_link, track_code, date, vol_total, vol_used, expire, discount_code, panel_username) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                      (chat_id, plan, name, price, config_link, track_code, date_now, vol_total, "0 MB", expire_date, disc_code, username))
                      
            if disc_code:
                c.execute("UPDATE user_discounts SET remaining_uses = remaining_uses - 1 WHERE user_id=? AND code=?", (chat_id, disc_code))
                
            # پاداش زیرمجموعه‌گیری
            c.execute("SELECT referrer_id FROM users WHERE user_id=?", (chat_id,))
            ref_res = c.fetchone()
            if ref_res and ref_res[0] != 0:
                referrer = ref_res[0]
                reward = int(price * 0.10)
                if reward > 0:
                    c.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (reward, referrer))
                    try: bot.send_message(referrer, f"✅ **تبریک!** زیرمجموعه شما سرویس VPN خریداری کرد و مبلغ **{reward:,} تومان** (10 درصد پورسانت) به کیف پول شما اضافه شد.", parse_mode="Markdown")
                    except: pass
                
            conn.commit()
            
            msg = f"""✅ **خرید شما با موفقیت انجام شد!**
━━━━ ❖ ━━━━
📌 **پلن:** {name}
💰 **مبلغ کسر شده:** {price:,} تومان
💵 **موجودی جدید:** {new_bal:,} تومان
━━━━ ❖ ━━━━
برای دریافت QR Code و مدیریت کانفیگ، لطفاً از منوی اصلی روی دکمه **🛍 سرویس های من** کلیک کنید.

🔗 **لینک کانفیگ شما:**
`{config_link}`"""
            
            qr_url = f"https://api.qrserver.com/v1/create-qr-code/?size=400x400&data={quote(config_link)}"
            try: bot.delete_message(chat_id, msg_id)
            except: pass
            bot.send_photo(chat_id, qr_url, caption=msg, parse_mode="Markdown")
            
            masked_id = str(chat_id)[:2] + "***" + str(chat_id)[-2:]
            rep = f"✅ **خرید موفق VPN**\n\n📌 پلن: {name}\n💰 قیمت: {price:,} تومان\n🆔 آیدی: {masked_id}\n📅 تاریخ: {date_now}"
            send_channel_report(rep)
            
        except Exception as e:
            try: bot.edit_message_text(f"❌ **خطا در ساخت اکانت!**\n\nمتاسفانه ارتباط با سرور برقرار نشد. موجودی شما کسر نگردید.\n\nدلیل خطا:\n`{str(e)}`", chat_id, msg_id, parse_mode="Markdown")
            except: bot.send_message(chat_id, f"❌ **خطا در ساخت اکانت!**\n\nمتاسفانه ارتباط با سرور برقرار نشد. موجودی شما کسر نگردید.\n\nدلیل خطا:\n`{str(e)}`", parse_mode="Markdown")
        finally:
            conn.close()

    elif is_admin(chat_id) and data == "admin_lock_main":
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        locks = {}
        for cat in ['telegram', 'insta', 'tiktok', 'youtube', 'rubika', 'vpn']:
            c.execute("SELECT value FROM settings WHERE key=?", (f"lock_{cat}",))
            r = c.fetchone()
            locks[cat] = r[0] if r else '0'
        conn.close()
        markup = InlineKeyboardMarkup(row_width=1)
        cats = [("تلگرام", "telegram"), ("اینستاگرام", "insta"), ("تیک‌تاک", "tiktok"), ("یوتیوب", "youtube"), ("روبیکا", "rubika"), ("خرید VPN", "vpn")]
        for name, cid in cats:
            icon = "🔒" if locks[cid] == '1' else "🔓"
            markup.add(InlineKeyboardButton(f"{icon} {name}", callback_data=f"tgl_main_{cid}", style="primary"))
        bot.edit_message_text("دکمه‌های اصلی را برای قفل/باز کردن انتخاب کنید:", chat_id, msg_id, reply_markup=markup)

    elif is_admin(chat_id) and data.startswith("tgl_main_"):
        cid = data.split("_")[2]
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT value FROM settings WHERE key=?", (f"lock_{cid}",))
        r = c.fetchone()
        new_val = '0' if (r and r[0] == '1') else '1'
        c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (f"lock_{cid}", new_val))
        conn.commit()
        conn.close()
        call.data = "admin_lock_main"
        handle_query(call)

    elif is_admin(chat_id) and data == "admin_set_tutorial":
        user_steps[chat_id] = "ask_tutorial_link"
        bot.send_message(chat_id, "🔗 لطفاً لینک کانال آموزش اتصال را بفرستید (مثلاً https://t.me/channel):")
    elif is_admin(chat_id) and data == "admin_export_users":
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT * FROM users")
        users = c.fetchall()
        conn.close()
        with open("users.txt", "w", encoding="utf-8") as f:
            for u in users: f.write(f"ID:{u[0]} Name:{u[1]} User:{u[2]} Bal:{u[3]} Orders:{u[4]}\n")
        with open("users.txt", "rb") as f: bot.send_document(chat_id, f, caption="لیست کاربران")
        os.remove("users.txt")
    elif is_admin(chat_id) and data == "admin_reset_test":
        user_steps[chat_id] = "ask_reset_test_id"
        bot.send_message(chat_id, "آیدی عددی کاربر برای ریست تست VPN را بفرستید:")
    elif is_admin(chat_id) and data == "admin_set_admin":
        user_steps[chat_id] = "ask_admin_id"
        bot.send_message(chat_id, "آیدی عددی کاربر برای ادمین شدن:")
    elif is_admin(chat_id) and data == "admin_del_admin":
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT user_id, first_name FROM users WHERE is_admin=1")
        admins = c.fetchall()
        conn.close()
        markup = InlineKeyboardMarkup(row_width=1)
        for adm in admins:
            if adm[0] != OWNER_ID:
                markup.add(InlineKeyboardButton(f"❌ {adm[1]} ({adm[0]})", callback_data=f"deladm_{adm[0]}", style="danger"))
        if not markup.keyboard:
            bot.send_message(chat_id, "ادمین دیگری برای حذف وجود ندارد.")
        else:
            bot.send_message(chat_id, "یک ادمین را برای عزل انتخاب کنید:", reply_markup=markup)
            
    elif is_admin(chat_id) and data.startswith("deladm_"):
        adm_id = data.split("_")[1]
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("UPDATE users SET is_admin=0 WHERE user_id=?", (adm_id,))
        conn.commit()
        conn.close()
        bot.answer_callback_query(call.id, "ادمین از سیستم عزل شد.", show_alert=True)
        bot.delete_message(chat_id, msg_id)

    elif is_admin(chat_id) and data == "admin_search_order":
        user_steps[chat_id] = "ask_search_order"
        bot.send_message(chat_id, "🔍 کد پیگیری سفارش (مثلا TRC-XXXXX) را ارسال کنید:")
    elif is_admin(chat_id) and data == "admin_ban":
        user_steps[chat_id] = "ask_ban_id"
        bot.send_message(chat_id, "آیدی عددی کاربر برای بن کردن:")
    elif is_admin(chat_id) and data == "admin_unban":
        user_steps[chat_id] = "ask_unban_id"
        bot.send_message(chat_id, "آیدی عددی کاربر برای رفع بن:")
    elif is_admin(chat_id) and data == "admin_add_bal":
        user_steps[chat_id] = "ask_add_bal_id"
        bot.send_message(chat_id, "آیدی عددی کاربر برای افزایش موجودی:")
    elif is_admin(chat_id) and data == "admin_deduct_bal":
        user_steps[chat_id] = "ask_deduct_bal_id"
        bot.send_message(chat_id, "آیدی عددی کاربر برای کسر موجودی:")
    elif is_admin(chat_id) and data == "admin_set_card":
        user_steps[chat_id] = "ask_card_number"
        bot.send_message(chat_id, "💳 لطفاً شماره کارت جدید را بفرستید:")
    elif is_admin(chat_id) and data == "admin_broadcast":
        user_steps[chat_id] = "ask_broadcast"
        bot.send_message(chat_id, "پیام خود را بفرستید (متن، عکس، ویدیو، فوروارد و...):")
    elif is_admin(chat_id) and data == "admin_anon_msg":
        user_steps[chat_id] = "ask_anon_msg_id"
        bot.send_message(chat_id, "آیدی عددی کاربر برای ارسال پیام ناشناس:")
    elif is_admin(chat_id) and data == "admin_channels":
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT channel_id FROM channels")
        channels = c.fetchall()
        conn.close()
        markup = InlineKeyboardMarkup(row_width=1)
        for ch in channels: markup.add(InlineKeyboardButton(f"❌ حذف {ch[0]}", callback_data=f"delchan_{ch[0]}", style="danger"))
        markup.add(InlineKeyboardButton("➕ افزودن کانال جدید", callback_data="add_channel", style="success"))
        bot.edit_message_text("لیست کانال‌های اجباری:", chat_id, msg_id, reply_markup=markup)

    elif is_admin(chat_id) and data.startswith("delchan_"):
        ch_id = data.replace("delchan_", "")
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("DELETE FROM channels WHERE channel_id=?", (ch_id,))
        conn.commit()
        conn.close()
        bot.answer_callback_query(call.id, "کانال حذف شد.", show_alert=True)
        bot.delete_message(chat_id, msg_id)

    elif is_admin(chat_id) and data.startswith("managelist_sc_"):
        cat_id = data.split("_")[2]
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT id, name, is_locked FROM sub_categories WHERE parent_cat=?", (cat_id,))
        scs = c.fetchall()
        conn.close()
        markup = InlineKeyboardMarkup(row_width=1)
        for s in scs:
            l_icon = "🔒" if s[2]==1 else "🔓"
            markup.add(InlineKeyboardButton(f"{l_icon} {s[1]}", callback_data=f"opts_sc_{s[0]}", style="primary"))
        bot.edit_message_text("یک پوشه را برای مدیریت انتخاب کنید:", chat_id, msg_id, reply_markup=markup)
        
    elif is_admin(chat_id) and data.startswith("managelist_pr_"):
        subcat_id = data.split("_")[2]
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT id, name, is_locked FROM products WHERE subcat_id=?", (subcat_id,))
        prs = c.fetchall()
        conn.close()
        markup = InlineKeyboardMarkup(row_width=1)
        for p in prs:
            l_icon = "🔒" if p[2]==1 else "🔓"
            markup.add(InlineKeyboardButton(f"{l_icon} {p[1]}", callback_data=f"opts_pr_{p[0]}", style="primary"))
        bot.edit_message_text("یک محصول را برای مدیریت انتخاب کنید:", chat_id, msg_id, reply_markup=markup)

    elif is_admin(chat_id) and data.startswith("opts_sc_"):
        sc_id = data.split("_")[2]
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(InlineKeyboardButton("✏️ تغییر نام", callback_data=f"edit_sc_{sc_id}", style="primary"),
                   InlineKeyboardButton("🔒 قفل / 🔓 باز", callback_data=f"lock_sc_{sc_id}", style="primary"))
        markup.add(InlineKeyboardButton("🗑 حذف", callback_data=f"del_sc_{sc_id}", style="danger"))
        bot.edit_message_text("چه عملیاتی روی این پوشه انجام شود؟", chat_id, msg_id, reply_markup=markup)
        
    elif is_admin(chat_id) and data.startswith("opts_pr_"):
        pr_id = data.split("_")[2]
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(InlineKeyboardButton("✏️ تغییر نام", callback_data=f"edit_pr_{pr_id}", style="primary"),
                   InlineKeyboardButton("💰 ویرایش قیمت", callback_data=f"edit_prprice_{pr_id}", style="success"))
        markup.add(InlineKeyboardButton("🔒 قفل / 🔓 باز", callback_data=f"lock_pr_{pr_id}", style="primary"),
                   InlineKeyboardButton("🗑 حذف", callback_data=f"del_pr_{pr_id}", style="danger"))
        bot.edit_message_text("چه عملیاتی روی این محصول انجام شود؟", chat_id, msg_id, reply_markup=markup)

    elif is_admin(chat_id) and data.startswith("edit_prprice_"):
        pr_id = data.split("_")[2]
        user_steps[chat_id] = f"ask_edit_prprice_{pr_id}"
        bot.send_message(chat_id, "💰 لطفا قیمت جدید محصول را به تومان ارسال کنید (فقط عدد وارد کنید):")

    elif is_admin(chat_id) and data.startswith("lock_sc_"):
        sc_id = data.split("_")[2]
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT is_locked FROM sub_categories WHERE id=?", (sc_id,))
        curr = c.fetchone()[0]
        c.execute("UPDATE sub_categories SET is_locked=? WHERE id=?", (0 if curr==1 else 1, sc_id))
        conn.commit()
        conn.close()
        bot.answer_callback_query(call.id, "وضعیت قفل تغییر کرد.", show_alert=True)
        bot.delete_message(chat_id, msg_id)
        
    elif is_admin(chat_id) and data.startswith("del_sc_"):
        sc_id = data.split("_")[2]
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("DELETE FROM sub_categories WHERE id=?", (sc_id,))
        c.execute("DELETE FROM products WHERE subcat_id=?", (sc_id,))
        conn.commit()
        conn.close()
        bot.answer_callback_query(call.id, "پوشه و محصولات آن حذف شدند.", show_alert=True)
        bot.delete_message(chat_id, msg_id)
        
    elif is_admin(chat_id) and data.startswith("edit_sc_"):
        sc_id = data.split("_")[2]
        user_steps[chat_id] = f"edit_sc_{sc_id}"
        bot.send_message(chat_id, "نام جدید پوشه را ارسال کنید:")

    elif is_admin(chat_id) and data.startswith("lock_pr_"):
        pr_id = data.split("_")[2]
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT is_locked FROM products WHERE id=?", (pr_id,))
        curr = c.fetchone()[0]
        c.execute("UPDATE products SET is_locked=? WHERE id=?", (0 if curr==1 else 1, pr_id))
        conn.commit()
        conn.close()
        bot.answer_callback_query(call.id, "وضعیت قفل محصول تغییر کرد.", show_alert=True)
        bot.delete_message(chat_id, msg_id)
        
    elif is_admin(chat_id) and data.startswith("del_pr_"):
        pr_id = data.split("_")[2]
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("DELETE FROM products WHERE id=?", (pr_id,))
        conn.commit()
        conn.close()
        bot.answer_callback_query(call.id, "محصول حذف شد.", show_alert=True)
        bot.delete_message(chat_id, msg_id)
        
    elif is_admin(chat_id) and data.startswith("edit_pr_"):
        pr_id = data.split("_")[2]
        user_steps[chat_id] = f"edit_pr_{pr_id}"
        bot.send_message(chat_id, "نام جدید محصول را ارسال کنید:")

    elif data.startswith("supinfo_"):
        uid = data.split("_")[1]
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT first_name, username, balance, total_orders FROM users WHERE user_id=?", (uid,))
        u = c.fetchone()
        conn.close()
        if u: bot.answer_callback_query(call.id, f"👤 نام: {u[0]}\n🌐 یوزرنیم: @{u[1]}\n🆔 آیدی: {uid}\n💰 موجودی: {u[2]:,} تومان\n🛍 خریدها: {u[3]}", show_alert=True)
        
    elif data.startswith("suprep_"):
        ticket_id = data.split("_")[1]
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT user_id, status FROM support_tickets WHERE id=?", (ticket_id,))
        ticket = c.fetchone()
        conn.close()
        if ticket[1] != 0:
            bot.answer_callback_query(call.id, "⚠️ این پیام قبلاً توسط ادمین دیگری پیگیری شده است.", show_alert=True)
            return
        uid = ticket[0]
        user_steps[chat_id] = f"reply_sup_{ticket_id}_{uid}"
        bot.send_message(chat_id, "💬 متن پاسخ خود را بفرستید (به صورت ناشناس ارسال می‌شود):")
        
    elif data.startswith("supseen_"):
        ticket_id = data.split("_")[1]
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT user_id, status FROM support_tickets WHERE id=?", (ticket_id,))
        ticket = c.fetchone()
        if ticket[1] != 0:
            bot.answer_callback_query(call.id, "⚠️ این پیام قبلاً توسط ادمین دیگری پیگیری شده است.", show_alert=True)
            conn.close()
            return
        c.execute("UPDATE support_tickets SET status=1 WHERE id=?", (ticket_id,))
        conn.commit()
        conn.close()
        uid = ticket[0]
        try:
            bot.send_message(uid, "✅ پیام شما توسط مدیریت خوانده شد.")
            bot.edit_message_reply_markup(chat_id, msg_id, reply_markup=None)
            bot.edit_message_text(call.message.text + "\n\n✅ تیکت بسته شد.", chat_id, msg_id)
            bot.answer_callback_query(call.id, "تیک دیده شد ارسال شد.")
        except: bot.answer_callback_query(call.id, "خطا در ارسال تیک.")

    elif data.startswith("rec_acc_") and is_admin(chat_id):
        receipt_id = data.split("_")[2]
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT user_id, amount, status FROM receipts WHERE id=?", (receipt_id,))
        rec = c.fetchone()
        if not rec:
            conn.close()
            return
        if rec[2] != 0:
            bot.answer_callback_query(call.id, "⚠️ این فیش قبلاً توسط ادمین دیگری پیگیری شده است.", show_alert=True)
            conn.close()
            return
            
        uid, amount = rec[0], rec[1]
        c.execute("UPDATE receipts SET status=1 WHERE id=?", (receipt_id,))
        c.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (amount, uid))
        conn.commit()
        conn.close()
        bot.edit_message_text(call.message.caption + "\n\n✅ تایید شد." if call.message.caption else "✅ تایید شد.", chat_id, msg_id)
        try: bot.send_message(uid, f"✅ رسید تایید و {amount:,} تومان به حساب شما اضافه شد.")
        except: pass
        
    elif data.startswith("rec_rej_") and is_admin(chat_id):
        receipt_id = data.split("_")[2]
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT user_id, status FROM receipts WHERE id=?", (receipt_id,))
        rec = c.fetchone()
        if not rec:
            conn.close()
            return
        if rec[1] != 0:
            bot.answer_callback_query(call.id, "⚠️ این فیش قبلاً توسط ادمین دیگری پیگیری شده است.", show_alert=True)
            conn.close()
            return
            
        uid = rec[0]
        c.execute("UPDATE receipts SET status=-1 WHERE id=?", (receipt_id,))
        conn.commit()
        conn.close()
        bot.edit_message_text(call.message.caption + "\n\n❌ رد شد." if call.message.caption else "❌ رد شد.", chat_id, msg_id)
        try: bot.send_message(uid, "❌ رسید پرداختی شما توسط مدیریت رد شد.")
        except: pass

    elif data == "start_kyc":
        msg = """لطفاً عکس از روی کارت بانکی خود را ارسال کنید.

⚠️ **نکته بسیار مهم:**
حتماً در قسمت «کپشن» (توضیحات عکس)، ابتدا **شماره کارت خود را با فاصله** بنویسید و در خط بعدی **نام و نام خانوادگی مالک کارت** را وارد کنید تا به صورت صحیح در حساب کاربری شما ثبت شود."""
        bot.edit_message_text(msg, chat_id, msg_id, parse_mode="Markdown")
        user_steps[chat_id] = "ask_kyc_photo"
        
    elif data == "delete_kyc":
        markup = InlineKeyboardMarkup().add(InlineKeyboardButton("✅ حذف", callback_data="confirm_del_kyc", style="danger"), InlineKeyboardButton("❌ لغو", callback_data="cancel_del_kyc", style="primary"))
        bot.edit_message_text("آیا از حذف احراز هویت اطمینان دارید؟", chat_id, msg_id, reply_markup=markup)
        
    elif data == "confirm_del_kyc":
        bot.edit_message_text("درخواست حذف برای مدیریت ارسال شد.", chat_id, msg_id)
        markup = InlineKeyboardMarkup().add(InlineKeyboardButton("✅ تایید", callback_data=f"acc_del_kyc_{chat_id}", style="success"), InlineKeyboardButton("❌ لغو", callback_data=f"rej_del_kyc_{chat_id}", style="danger"))
        admins = get_all_admins()
        for admin in admins:
            try: bot.send_message(admin, f"درخواست حذف احراز هویت: `{chat_id}`", reply_markup=markup)
            except: pass
        
    elif data.startswith("kyc_accept_") and is_admin(chat_id):
        uid = data.split("_")[2]
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT kyc_status FROM users WHERE user_id=?", (uid,))
        k_stat = c.fetchone()[0]
        if k_stat != 1:
            bot.answer_callback_query(call.id, "⚠️ این درخواست قبلاً توسط ادمین دیگری پیگیری شده است.", show_alert=True)
            conn.close()
            return
            
        c.execute("UPDATE users SET kyc_status=2 WHERE user_id=?", (uid,))
        conn.commit()
        conn.close()
        bot.edit_message_text(call.message.caption + "\n\n✅ تایید شد." if call.message.caption else "✅ تایید شد.", chat_id, msg_id)
        try: bot.send_message(uid, "✅ احراز هویت شما تایید شد.")
        except: pass
        
    elif data.startswith("kyc_reject_") and is_admin(chat_id):
        uid = data.split("_")[2]
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT kyc_status FROM users WHERE user_id=?", (uid,))
        k_stat = c.fetchone()[0]
        if k_stat != 1:
            bot.answer_callback_query(call.id, "⚠️ این درخواست قبلاً توسط ادمین دیگری پیگیری شده است.", show_alert=True)
            conn.close()
            return
            
        c.execute("UPDATE users SET kyc_status=0, card_info='' WHERE user_id=?", (uid,))
        conn.commit()
        conn.close()
        bot.edit_message_text(call.message.caption + "\n\n❌ رد شد." if call.message.caption else "❌ رد شد.", chat_id, msg_id)
        try: bot.send_message(uid, "❌ احراز هویت شما توسط مدیریت رد شد.")
        except: pass
        
    elif data.startswith("acc_del_kyc_") and is_admin(chat_id):
        uid = data.split("_")[3]
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("UPDATE users SET kyc_status=0, card_info='' WHERE user_id=?", (uid,))
        conn.commit()
        conn.close()
        bot.edit_message_text("حذف شد.", chat_id, msg_id)

    elif data.startswith("ordinfo_") and is_admin(chat_id):
        uid = data.split("_")[1]
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT first_name, username, balance, total_orders FROM users WHERE user_id=?", (uid,))
        u = c.fetchone()
        conn.close()
        if u: bot.answer_callback_query(call.id, f"👤 نام: {u[0]}\n🌐 یوزرنیم: @{u[1]}\n🆔 آیدی: {uid}\n💰 موجودی: {u[2]:,} تومان\n🛍 خریدها: {u[3]}", show_alert=True)

    elif data.startswith("ordacc_") and is_admin(chat_id):
        order_id = data.split("_")[1]
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT user_id, prod_name, total_price, date, track_code, status FROM orders WHERE id=?", (order_id,))
        ord_data = c.fetchone()
        if ord_data:
            if ord_data[5] != 'در حال انجام':
                bot.answer_callback_query(call.id, "⚠️ این سفارش قبلاً توسط ادمین دیگری پیگیری شده است.", show_alert=True)
                conn.close()
                return
            uid, prod_name, total, date, trc, _ = ord_data
            c.execute("UPDATE orders SET status='تکمیل شده' WHERE id=?", (order_id,))
            conn.commit()
            bot.edit_message_text(call.message.text + "\n\n✅ انجام شد.", chat_id, msg_id)
            try: bot.send_message(uid, f"✅ کاربر گرامی، سفارش شما برای محصول **{prod_name}** با کد پیگیری `{trc}` تایید و با موفقیت انجام شد.", parse_mode="Markdown")
            except: pass
            masked_id = str(uid)[:2] + "***" + str(uid)[-2:]
            rep = f"✅ سفارش با موفقیت انجام شد\n\n📌 نام محصول: {prod_name}\n💰 قیمت: {total:,} تومان\n🆔 آیدی خریدار: {masked_id}\n📅 تاریخ: {date}"
            send_channel_report(rep)
        conn.close()
        
    elif data.startswith("ordrej_") and is_admin(chat_id):
        order_id = data.split("_")[1]
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        try: c.execute("SELECT user_id, prod_name, total_price, track_code, status, discount_code FROM orders WHERE id=?", (order_id,))
        except: c.execute("SELECT user_id, prod_name, total_price, track_code, status, '' FROM orders WHERE id=?", (order_id,))
        ord_data = c.fetchone()
        if ord_data:
            if ord_data[4] != 'در حال انجام':
                bot.answer_callback_query(call.id, "⚠️ این سفارش قبلاً توسط ادمین دیگری پیگیری شده است.", show_alert=True)
                conn.close()
                return
            uid, prod_name, total, trc, _, disc_code = ord_data
            c.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (total, uid))
            c.execute("UPDATE orders SET status='لغو شده' WHERE id=?", (order_id,))
            if disc_code:
                c.execute("UPDATE user_discounts SET remaining_uses = remaining_uses + 1 WHERE user_id=? AND code=?", (uid, disc_code))
            conn.commit()
            bot.edit_message_text(call.message.text + "\n\n❌ لغو شد و مبلغ برگشت داده شد.", chat_id, msg_id)
            try: bot.send_message(uid, f"❌ سفارش شما برای محصول **{prod_name}** با کد پیگیری `{trc}` توسط مدیریت لغو شد.\nمبلغ {total:,} تومان به حساب شما بازگشت داده شد.", parse_mode="Markdown")
            except: pass
        conn.close()

print("Bot is running...")
bot.infinity_polling()
