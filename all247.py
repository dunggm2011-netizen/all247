import os
import time
import json
import random
import string
import logging
import threading
import requests
import telebot
from datetime import datetime
from telebot import types
from flask import Flask, jsonify, request

# ==================== CONFIG ====================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8844628964:AAE3Wm5VUQIRqhBuwonAFRuuW5eHwPIczIw")
ADMIN_IDS = [7564889663]

API_URL = "https://api.tool247.fun/api/pred-log"
LIMIT = 50
POLL_INTERVAL = 3

# ==================== BANK INFO ====================
BANK_INFO = {
    "bank": "MB Bank",
    "account": "0982344729",
    "owner": "TRAN THANH NGAN",
    "qr_template": "https://img.vietqr.io/image/MB-0982344729-compact2.png?amount={amount}&addInfo={info}&accountName=TRAN%20THANH%20NGAN",
}

# ==================== BẢNG GIÁ KEY ====================
KEY_PRICES = {
    "1d":     {"label": "1 Ngày",    "price": 20000,   "hours": 24},
    "3d":     {"label": "3 Ngày",    "price": 50000,   "hours": 72},
    "1w":     {"label": "1 Tuần",    "price": 100000,  "hours": 168},
    "1m":     {"label": "1 Tháng",   "price": 170000,  "hours": 720},
    "2m":     {"label": "2 Tháng",   "price": 300000,  "hours": 1440},
    "forever":{"label": "Vĩnh Viễn", "price": 450000,  "hours": None},
}

# ==================== 18 GAME ====================
GAMES = {
    "68TX": "68tx",
    "789Club": "789club",
    "B52 MD5": "b52_md5",
    "B52 TX": "b52_tx",
    "BetVIP MD5": "betvip_md5",
    "BetVIP TX": "betvip_tx",
    "Hitclub MD5": "hitclub_md5",
    "Hitclub TX": "hitclub_tx",
    "LC79 Hũ": "lc79_hu",
    "LC79 MD5": "lc79_md5",
    "Luck8 MD5": "luck8_md5",
    "Luck8 TX": "luck8_tx",
    "Max789 MD5": "max789_md5",
    "Max789 TX": "max789_tx",
    "Rikvip Hũ": "rikvip_hu",
    "Rikvip MD5": "rikvip_md5",
    "Son789 MD5": "son789_md5",
    "Son789 TX": "son789_tx",
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("multi-bot")

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")

# ==================== STATE ====================
user_data = {}
valid_keys = {}
giftcode_used = {}
pending_payments = {}  # chat_id -> {amount, code, type}
pending_bills = {}     # bill_id -> {user_id, amount, code, msg_id, type}
bill_counter = 0

GIFTCODES = {
    "WELCOME2026": {"amount": 20000, "max_uses": 100},
    "THANHDUYVIP": {"amount": 50000, "max_uses": 50},
    "TOOLFREE":    {"amount": 10000, "max_uses": 200},
}

def get_user(chat_id):
    if chat_id not in user_data:
        user_data[chat_id] = {
            "game_id": None,   # None = chưa chọn game
            "running": False,
            "last_phien": None,
            "activated": False,
            "key": None,
            "expiry": None,
            "expiry_ts": None,
            "balance": 0,
            "history": [],
        }
    return user_data[chat_id]

def is_admin(uid):
    return uid in ADMIN_IDS

def is_admin_chat(x):
    try:
        if hasattr(x, "from_user"): return x.from_user.id in ADMIN_IDS
        return int(x) in ADMIN_IDS
    except: return False

def generate_key(length=10):
    chars = string.ascii_uppercase + string.digits
    return ''.join(random.choice(chars) for _ in range(length))

def generate_pay_code():
    return "NAP" + ''.join(random.choice(string.digits) for _ in range(6))

def fmt_price(n):
    return f"{n:,}đ".replace(",", ".")

# ==================== API ====================
def get_data(game_id):
    try:
        r = requests.get(API_URL, params={"game": game_id, "limit": LIMIT}, timeout=15)
        if r.status_code != 200: return None
        data = r.json()
        if not data.get("lich_su"): return None
        return data
    except Exception as e:
        log.warning(f"API err: {e}")
        return None

# ==================== FORMAT ====================
def to_txt(x):
    if not x: return "?"
    x = str(x).lower()
    if "tài" in x or "tai" in x: return "TÀI"
    if "xỉu" in x or "xiu" in x: return "XỈU"
    return "?"

def conf_label(conf):
    try: n = int(conf)
    except: return "?"
    if n >= 80: return "CAO"
    elif n >= 70: return "KHÁ CAO"
    elif n >= 60: return "TRUNG BÌNH"
    elif n >= 50: return "THẤP"
    else: return "RẤT THẤP"

def game_name(game_id):
    for name, gid in GAMES.items():
        if gid == game_id: return name
    return game_id

# ==================== SEND SIGNAL ====================
def send_ai_signal(chat_id, entry, game_id):
    phien = entry.get("phien", 0)
    ket_qua = to_txt(entry.get("ket_qua"))
    du_doan = to_txt(entry.get("du_doan"))
    conf = entry.get("do_tin_cay", 0)
    pattern = entry.get("loai_cau", "")
    ket_luan = entry.get("ket_luan", "")
    gname = game_name(game_id)

    if "Đúng" in ket_luan:
        check_line = f"📊 Kết quả #{phien}: ✅ CHÍNH XÁC  ({ket_qua})"
    elif "Sai" in ket_luan:
        check_line = f"📊 Kết quả #{phien}: ❌ SAI  ({ket_qua})"
    else:
        check_line = f"📊 Kết quả #{phien}: ℹ️  ({ket_qua})"

    caption = (
        f"🎯 <b>AI SIGNAL — {gname}</b>\n"
        f"🏷️ Phiên <b>#{phien}</b> → Dự đoán <b>#{phien + 1}</b>\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"{check_line}\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"🔮 Ván <b>#{phien + 1}</b> — Dự báo: <b>{du_doan}</b>\n"
        f"💯 Điểm tin cậy: <b>{conf}%</b>  ({conf_label(conf)})\n"
        f"🎴 <i>{pattern}</i>\n"
        f"━━━━━━━━━━━━━━━━"
    )

    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("⏹️ Tắt dự đoán", callback_data="menu_off"))
    kb.add(types.InlineKeyboardButton("⬅️ Menu", callback_data="menu_back"))

    try:
        bot.send_message(chat_id, caption, parse_mode="HTML", reply_markup=kb)
        return True
    except: return False

# ==================== INLINE MENU ====================
def main_menu(user):
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("💸 Nạp Tiền", callback_data="menu_nap"),
        types.InlineKeyboardButton("🛒 Mua Key", callback_data="menu_buy"),
    )
    kb.add(
        types.InlineKeyboardButton("🎮 Game", callback_data="menu_game"),
        types.InlineKeyboardButton("🎁 Giftcode", callback_data="menu_gift"),
    )
    kb.add(
        types.InlineKeyboardButton("📜 Lịch Sử", callback_data="menu_history"),
        types.InlineKeyboardButton("👤 Thông Tin", callback_data="menu_info"),
    )
    kb.add(
        types.InlineKeyboardButton("📊 Thống Kê", callback_data="menu_stats"),
        types.InlineKeyboardButton("💬 Hỗ Trợ", callback_data="menu_support"),
    )
    return kb

# ==================== START ====================
@bot.message_handler(commands=['start', 'menu'])
def cmd_start(message):
    chat_id = message.chat.id
    u = get_user(chat_id)

    if is_admin(chat_id):
        u["activated"] = True

    if u.get("activated") and u.get("key"):
        if u.get("expiry_ts") is not None and time.time() > u["expiry_ts"]:
            key_status = "❌ Hết Hạn"
        else:
            key_status = "✅ Đã Kích Hoạt"
    else:
        key_status = "❌ Chưa Kích Hoạt"

    game_line = game_name(u["game_id"]) if u.get("game_id") else "Chưa chọn"
    game_list = " • ".join([f"{name}" for name in GAMES.keys()])

    text = (
        f"⭐️ <b>SINGAL HỆ THỐNG TOOL</b> ⭐️\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🎉 Chào mừng <b>{message.from_user.full_name or 'User'}</b>💸!\n\n"
        f"👤 ID: <code>{chat_id}</code>\n"
        f"🔑 Trạng thái Key: <b>{key_status}</b>\n"
        f"💵 Số dư: <b>{fmt_price(u['balance'])}</b>\n"
        f"🎮 Game đang chọn: <b>{game_line}</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🖥 <b>BOT CÓ CÁC GAME:</b>\n"
        f"{game_list}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"💡 <b>Hướng dẫn sử dụng:</b>\n"
        f"Nạp tiền (💸 Nạp Tiền)\n"
        f"Mua key mới (🛒 Mua Key)\n"
        f"Chọn game (🎮 Game) — bấm là tự bật dự đoán\n\n"
        f"👉 Chọn tùy chọn từ menu bên dưới:"
    )
    bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=main_menu(u))

# ==================== CALLBACK ROUTER ====================
@bot.callback_query_handler(func=lambda c: c.data.startswith("menu_"))
def on_menu_callback(c):
    data = c.data
    chat_id = c.message.chat.id
    u = get_user(chat_id)
    bot.answer_callback_query(c.id)

    if data == "menu_nap":
        show_nap_menu(chat_id)
    elif data == "menu_buy":
        show_buy_menu(chat_id)
    elif data == "menu_game":
        show_game_menu(chat_id)
    elif data == "menu_gift":
        show_gift_menu(chat_id)
    elif data == "menu_history":
        show_history(chat_id, c.message.from_user)
    elif data == "menu_info":
        show_info(chat_id, c.message.from_user)
    elif data == "menu_off":
        toggle_off(chat_id)
    elif data == "menu_stats":
        show_stats(chat_id)
    elif data == "menu_support":
        show_support(chat_id)

# ==================== NẠP TIỀN ====================
def show_nap_menu(chat_id):
    u = get_user(chat_id)
    kb = types.InlineKeyboardMarkup(row_width=2)
    for amt in [20000, 50000, 100000, 200000, 500000, 1000000]:
        kb.add(types.InlineKeyboardButton(fmt_price(amt), callback_data=f"nap_{amt}"))
    kb.add(
        types.InlineKeyboardButton("✏️ Nhập số tiền", callback_data="nap_custom"),
        types.InlineKeyboardButton("⬅️ Menu", callback_data="menu_back"),
    )
    bot.send_message(chat_id,
        "💸 <b>NẠP TIỀN</b>\n\n"
        f"💰 Số dư hiện tại: <b>{fmt_price(u['balance'])}</b>\n\n"
        "Chọn mệnh giá hoặc nhập số tiền tùy ý:",
        parse_mode="HTML", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("nap_"))
def on_nap_callback(c):
    chat_id = c.message.chat.id
    data = c.data

    if data == "nap_custom":
        bot.answer_callback_query(c.id, "Nhập: /nap 75000")
        bot.send_message(chat_id,
            "✏️ Nhập số tiền bằng lệnh:\n<code>/nap 75000</code>",
            parse_mode="HTML")
        return

    try:
        amount = int(data.replace("nap_", ""))
    except:
        bot.answer_callback_query(c.id, "Số tiền sai."); return
    bot.answer_callback_query(c.id)
    show_nap_qr(chat_id, amount)

@bot.message_handler(commands=['nap'])
def cmd_nap_amount(message):
    chat_id = message.chat.id
    args = message.text.split()
    if len(args) < 2:
        bot.reply_to(message, "Cú pháp: /nap 75000"); return
    try:
        amount = int(args[1])
    except:
        bot.reply_to(message, "❌ Số tiền không hợp lệ."); return
    show_nap_qr(chat_id, amount)

def show_nap_qr(chat_id, amount):
    u = get_user(chat_id)
    code = generate_pay_code()
    pending_payments[chat_id] = {"amount": amount, "code": code, "type": "nap"}
    u["history"].append({
        "time": datetime.now().strftime("%H:%M %d/%m/%Y"),
        "action": "Tạo lệnh nạp",
        "detail": f"{fmt_price(amount)} — {code}",
        "status": "Chờ duyệt",
    })

    qr_url = BANK_INFO["qr_template"].format(amount=amount, info=code)
    caption = (
        f"💸 <b>LỆNH NẠP TIỀN</b>\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"💰 Số tiền: <b>{fmt_price(amount)}</b>\n"
        f"🏦 Ngân hàng: <b>{BANK_INFO['bank']}</b>\n"
        f"📱 STK: <code>{BANK_INFO['account']}</code>\n"
        f"👤 Chủ TK: <b>{BANK_INFO['owner']}</b>\n"
        f"📝 Nội dung: <code>{code}</code>\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"⚠️ Nhập ĐÚNG nội dung <code>{code}</code>\n"
        f"📸 Sau khi chuyển khoản, GỬI ẢNH BILL vào chat này.\n"
        f"Admin sẽ duyệt trong 1-5 phút."
    )
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("⬅️ Menu", callback_data="menu_back"))
    try:
        bot.send_photo(chat_id, qr_url, caption=caption, parse_mode="HTML", reply_markup=kb)
    except Exception as e:
        log.warning(f"QR err: {e}")
        bot.send_message(chat_id, caption, parse_mode="HTML", reply_markup=kb)

# ==================== NHẬN ẢNH BILL ====================
@bot.message_handler(content_types=['photo'])
def on_bill_photo(message):
    chat_id = message.chat.id
    u = get_user(chat_id)

    if chat_id not in pending_payments:
        bot.reply_to(message,
            "⚠️ Bạn chưa tạo lệnh nạp.\n"
            "Bấm <b>💸 Nạp Tiền</b> để tạo lệnh trước.",
            parse_mode="HTML")
        return

    p = pending_payments[chat_id]
    amount = p["amount"]
    code = p["code"]

    # Lấy ảnh lớn nhất
    file_id = message.photo[-1].file_id

    # Tạo bill_id
    global bill_counter
    bill_counter += 1
    bill_id = f"BILL{bill_counter:05d}"

    pending_bills[bill_id] = {
        "user_id": chat_id,
        "amount": amount,
        "code": code,
        "file_id": file_id,
        "msg_id": message.message_id,
        "username": message.from_user.username or "N/A",
        "fullname": message.from_user.full_name or "N/A",
        "time": datetime.now().strftime("%H:%M %d/%m/%Y"),
    }

    u["history"].append({
        "time": datetime.now().strftime("%H:%M %d/%m/%Y"),
        "action": "Gửi bill nạp",
        "detail": f"{fmt_price(amount)} — {code}",
        "status": "Chờ duyệt",
    })

    # Xác nhận cho user
    bot.reply_to(message,
        f"✅ <b>ĐÃ NHẬN BILL</b>\n\n"
        f"💰 Số tiền: <b>{fmt_price(amount)}</b>\n"
        f"📝 Mã nạp: <code>{code}</code>\n"
        f"🆔 Bill ID: <code>{bill_id}</code>\n\n"
        f"⏳ Vui lòng chờ admin duyệt (1-5 phút).",
        parse_mode="HTML")

    # Gửi cho tất cả admin
    for admin_id in ADMIN_IDS:
        try:
            admin_kb = types.InlineKeyboardMarkup(row_width=2)
            admin_kb.add(
                types.InlineKeyboardButton("✅ DUYỆT", callback_data=f"bill_ok_{bill_id}"),
                types.InlineKeyboardButton("❌ TỪ CHỐI", callback_data=f"bill_no_{bill_id}"),
            )
            admin_caption = (
                f"🔔 <b>BILL NẠP MỚI</b>\n"
                f"━━━━━━━━━━━━━━━━\n"
                f"🆔 Bill ID: <code>{bill_id}</code>\n"
                f"👤 User ID: <code>{chat_id}</code>\n"
                f"👤 Tên: <b>{message.from_user.full_name or 'N/A'}</b>\n"
                f"🌐 Username: @{message.from_user.username or 'N/A'}\n"
                f"💰 Số tiền: <b>{fmt_price(amount)}</b>\n"
                f"📝 Mã nạp: <code>{code}</code>\n"
                f"🕐 Thời gian: <b>{datetime.now().strftime('%H:%M %d/%m/%Y')}</b>\n"
                f"━━━━━━━━━━━━━━━━"
            )
            bot.send_photo(admin_id, file_id, caption=admin_caption,
                           parse_mode="HTML", reply_markup=admin_kb)
        except Exception as e:
            log.warning(f"Không gửi bill cho admin {admin_id}: {e}")

# ==================== DUYỆT BILL ====================
@bot.callback_query_handler(func=lambda c: c.data.startswith("bill_"))
def on_bill_callback(c):
    if not is_admin_chat(c):
        bot.answer_callback_query(c.id, "⛔ Admin only.")
        return

    data = c.data
    if data.startswith("bill_ok_"):
        bill_id = data.replace("bill_ok_", "")
        action = "ok"
    elif data.startswith("bill_no_"):
        bill_id = data.replace("bill_no_", "")
        action = "no"
    else:
        return

    if bill_id not in pending_bills:
        bot.answer_callback_query(c.id, "❌ Bill không tồn tại.")
        return

    bill = pending_bills[bill_id]
    uid = bill["user_id"]
    amount = bill["amount"]
    code = bill["code"]

    if action == "ok":
        u = get_user(uid)
        u["balance"] += amount
        u["history"].append({
            "time": datetime.now().strftime("%H:%M %d/%m/%Y"),
            "action": "Admin duyệt nạp",
            "detail": f"+{fmt_price(amount)} — {code}",
            "status": "Thành công",
        })
        bot.answer_callback_query(c.id, f"✅ Đã duyệt {fmt_price(amount)}")

        # Sửa caption của admin (bỏ nút)
        try:
            bot.edit_message_caption(
                chat_id=c.message.chat.id,
                message_id=c.message.message_id,
                caption=c.message.caption + f"\n\n✅ <b>ĐÃ DUYỆT</b> bởi admin",
                parse_mode="HTML"
            )
        except: pass

        # Thông báo user
        try:
            bot.send_message(uid,
                f"✅ <b>NẠP TIỀN THÀNH CÔNG</b>\n\n"
                f"💰 Số tiền: <b>{fmt_price(amount)}</b>\n"
                f"📝 Mã nạp: <code>{code}</code>\n"
                f"💵 Số dư mới: <b>{fmt_price(u['balance'])}</b>\n\n"
                f"Cảm ơn bạn đã nạp tiền! 🎉",
                parse_mode="HTML")
        except: pass

        del pending_bills[bill_id]
        # Xóa pending payment của user
        if uid in pending_payments:
            del pending_payments[uid]

    else:  # from chối
        bot.answer_callback_query(c.id, "❌ Đã từ chối")
        try:
            bot.edit_message_caption(
                chat_id=c.message.chat.id,
                message_id=c.message.message_id,
                caption=c.message.caption + f"\n\n❌ <b>ĐÃ TỪ CHỐI</b> bởi admin",
                parse_mode="HTML"
            )
        except: pass

        u = get_user(uid)
        u["history"].append({
            "time": datetime.now().strftime("%H:%M %d/%m/%Y"),
            "action": "Admin từ chối nạp",
            "detail": f"{fmt_price(amount)} — {code}",
            "status": "Từ chối",
        })
        try:
            bot.send_message(uid,
                f"❌ <b>BILL NẠP BỊ TỪ CHỐI</b>\n\n"
                f"💰 Số tiền: <b>{fmt_price(amount)}</b>\n"
                f"📝 Mã nạp: <code>{code}</code>\n\n"
                f"Vui lòng liên hệ admin để biết lý do.",
                parse_mode="HTML")
        except: pass

        del pending_bills[bill_id]
        if uid in pending_payments:
            del pending_payments[uid]

# ==================== MUA KEY ====================
def show_buy_menu(chat_id):
    u = get_user(chat_id)
    kb = types.InlineKeyboardMarkup(row_width=2)
    for pid, info in KEY_PRICES.items():
        kb.add(types.InlineKeyboardButton(
            f"{info['label']} — {fmt_price(info['price'])}",
            callback_data=f"buy_{pid}"
        ))
    kb.add(types.InlineKeyboardButton("⬅️ Menu", callback_data="menu_back"))
    bot.send_message(chat_id,
        f"🛒 <b>MUA KEY — DÙNG CHUNG MỌI GAME</b>\n\n"
        f"💰 Số dư: <b>{fmt_price(u['balance'])}</b>\n"
        f"🎮 Key áp dụng cho cả 18 game.\n\n"
        "Chọn gói key muốn mua:",
        parse_mode="HTML", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("buy_"))
def on_buy_callback(c):
    chat_id = c.message.chat.id
    package_id = c.data.replace("buy_", "")
    if package_id not in KEY_PRICES:
        bot.answer_callback_query(c.id, "Gói không hợp lệ."); return

    u = get_user(chat_id)
    info = KEY_PRICES[package_id]

    if u["balance"] < info["price"]:
        bot.answer_callback_query(c.id, "❌ Số dư không đủ.")
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("💸 Nạp Tiền", callback_data="menu_nap"))
        kb.add(types.InlineKeyboardButton("⬅️ Menu", callback_data="menu_back"))
        bot.send_message(chat_id,
            f"❌ <b>SỐ DƯ KHÔNG ĐỦ</b>\n\n"
            f"💰 Cần: <b>{fmt_price(info['price'])}</b>\n"
            f"💵 Có: <b>{fmt_price(u['balance'])}</b>\n\n"
            "Nhấn Nạp Tiền để nạp thêm.",
            parse_mode="HTML", reply_markup=kb)
        return

    u["balance"] -= info["price"]
    new_key = generate_key()
    expiry_ts = None
    if info["hours"] is not None:
        expiry_ts = time.time() + info["hours"] * 3600
    # KEY CHUNG — không gắn game_id
    valid_keys[new_key] = {
        "game": "ALL",
        "expiry": expiry_ts,
        "price": info["price"],
        "label": info["label"],
        "used": False,
    }

    u["history"].append({
        "time": datetime.now().strftime("%H:%M %d/%m/%Y"),
        "action": "Mua key",
        "detail": f"{info['label']} — {fmt_price(info['price'])}",
        "status": "Thành công",
        "key": new_key,
    })

    bot.answer_callback_query(c.id, "✅ Mua key thành công.")
    expiry_text = "Vĩnh viễn" if expiry_ts is None else datetime.fromtimestamp(expiry_ts).strftime("%H:%M %d/%m/%Y")
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🎮 Chọn Game", callback_data="menu_game"))
    kb.add(types.InlineKeyboardButton("⬅️ Menu", callback_data="menu_back"))
    bot.send_message(chat_id,
        f"✅ <b>MUA KEY THÀNH CÔNG</b>\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"🔑 Key: <code>{new_key}</code>\n"
        f"📦 Gói: <b>{info['label']}</b>\n"
        f"💰 Đã trừ: <b>{fmt_price(info['price'])}</b>\n"
        f"💵 Số dư còn: <b>{fmt_price(u['balance'])}</b>\n"
        f"📅 Hết hạn: <b>{expiry_text}</b>\n"
        f"🎮 Áp dụng: <b>TẤT CẢ 18 GAME</b>\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"Kích hoạt: <code>/key {new_key}</code>",
        parse_mode="HTML", reply_markup=kb)

# ==================== KÍCH HOẠT KEY ====================
@bot.message_handler(commands=['key'])
def cmd_key(message):
    chat_id = message.chat.id
    args = message.text.split()
    if len(args) < 2:
        bot.reply_to(message, "Cú pháp: /key YOUR_KEY"); return
    key = args[1].upper().strip()
    u = get_user(chat_id)

    if key not in valid_keys:
        bot.reply_to(message, "❌ Key không tồn tại."); return

    info = valid_keys[key]
    if info.get("used") and u.get("key") != key:
        bot.reply_to(message, "❌ Key đã được sử dụng."); return

    if info["expiry"] is not None and time.time() > info["expiry"]:
        bot.reply_to(message, "❌ Key đã hết hạn."); return

    info["used"] = True
    u["key"] = key
    u["expiry"] = "Vĩnh viễn" if info["expiry"] is None else datetime.fromtimestamp(info["expiry"]).strftime("%H:%M %d/%m/%Y")
    u["expiry_ts"] = info["expiry"]
    u["activated"] = True

    u["history"].append({
        "time": datetime.now().strftime("%H:%M %d/%m/%Y"),
        "action": "Kích hoạt key",
        "detail": f"{info['label']}",
        "status": "Thành công",
        "key": key,
    })

    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🎮 Chọn Game", callback_data="menu_game"))
    kb.add(types.InlineKeyboardButton("⬅️ Menu", callback_data="menu_back"))

    bot.reply_to(message,
        f"✅ <b>KÍCH HOẠT THÀNH CÔNG</b>\n\n"
        f"🔑 Key: <code>{key}</code>\n"
        f"📦 Gói: <b>{info['label']}</b>\n"
        f"🎮 Áp dụng: <b>TẤT CẢ GAME</b>\n"
        f"📅 Hết hạn: <b>{u['expiry']}</b>\n\n"
        "Chọn game để bắt đầu nhận dự đoán.",
        parse_mode="HTML", reply_markup=kb)

# ==================== CHỌN GAME (BẤM = TỰ BẬT) ====================
def show_game_menu(chat_id):
    u = get_user(chat_id)
    kb = types.InlineKeyboardMarkup(row_width=2)
    buttons = []
    for name, gid in GAMES.items():
        mark = "✅ " if gid == u["game_id"] else ""
        buttons.append(types.InlineKeyboardButton(f"{mark}{name}", callback_data=f"setgame_{gid}"))
    kb.add(*buttons)
    kb.add(types.InlineKeyboardButton("⬅️ Menu", callback_data="menu_back"))
    bot.send_message(chat_id,
        f"🎮 <b>CHỌN GAME</b>\n"
        f"Hiện tại: <b>{game_name(u['game_id']) if u.get('game_id') else 'Chưa chọn'}</b>\n\n"
        "Bấm vào game để TỰ ĐỘNG bật dự đoán.\n"
        "Key dùng cho TẤT CẢ game.",
        parse_mode="HTML", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("setgame_"))
def on_game_callback(c):
    chat_id = c.message.chat.id
    u = get_user(chat_id)
    new_gid = c.data.replace("setgame_", "")
    if new_gid not in GAMES.values():
        bot.answer_callback_query(c.id, "❌ Game sai."); return

    # Check key
    if not u["activated"]:
        bot.answer_callback_query(c.id, "🔒 Chưa kích hoạt key.")
        bot.send_message(chat_id, "🔒 Vui lòng mua và kích hoạt key trước.")
        return
    if u["expiry_ts"] is not None and time.time() > u["expiry_ts"]:
        bot.answer_callback_query(c.id, "❌ Key hết hạn.")
        bot.send_message(chat_id, "❌ Key đã hết hạn. Mua key mới.")
        return

    # Đổi game + tự bật
    u["game_id"] = new_gid
    u["last_phien"] = None
    u["running"] = True

    bot.answer_callback_query(c.id, f"✅ Đã chọn {game_name(new_gid)}")

    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("⏹️ Tắt dự đoán", callback_data="menu_off"))
    kb.add(types.InlineKeyboardButton("🎮 Đổi Game", callback_data="menu_game"))
    kb.add(types.InlineKeyboardButton("⬅️ Menu", callback_data="menu_back"))

    bot.send_message(chat_id,
        f"✅ <b>ĐÃ CHỌN GAME</b>\n"
        f"🎮 Game: <b>{game_name(new_gid)}</b>\n"
        f"🟢 Trạng thái: <b>ĐANG BẬT DỰ ĐOÁN</b>\n\n"
        f"Bot sẽ tự gửi dự đoán mỗi phiên.\n"
        f"Bấm <b>⏹️ Tắt dự đoán</b> nếu muốn dừng.",
        parse_mode="HTML", reply_markup=kb)

# ==================== TẮT DỰ ĐOÁN ====================
def toggle_off(chat_id):
    u = get_user(chat_id)
    u["running"] = False
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🎮 Chọn Game", callback_data="menu_game"))
    kb.add(types.InlineKeyboardButton("⬅️ Menu", callback_data="menu_back"))
    bot.send_message(chat_id,
        "⏹️ <b>ĐÃ TẮT DỰ ĐOÁN</b>\n\n"
        "Bot sẽ ngừng gửi tin.\n"
        "Bấm <b>🎮 Chọn Game</b> để bật lại.",
        parse_mode="HTML", reply_markup=kb)

# ==================== GIFCODE ====================
def show_gift_menu(chat_id):
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("⬅️ Menu", callback_data="menu_back"))
    bot.send_message(chat_id,
        "🎁 <b>NHẬP GIFTCODE</b>\n\n"
        "Gửi giftcode theo cú pháp:\n"
        "<code>/gift CODE</code>\n\n"
        "VD: <code>/gift WELCOME2026</code>",
        parse_mode="HTML", reply_markup=kb)

@bot.message_handler(commands=['gift'])
def cmd_gift_code(message):
    chat_id = message.chat.id
    u = get_user(chat_id)
    args = message.text.split()
    if len(args) < 2:
        bot.reply_to(message, "Cú pháp: /gift CODE"); return
    code = args[1].upper().strip()

    if code not in GIFTCODES:
        bot.reply_to(message, "❌ Giftcode không tồn tại."); return

    info = GIFTCODES[code]
    if code not in giftcode_used:
        giftcode_used[code] = set()

    if chat_id in giftcode_used[code]:
        bot.reply_to(message, "❌ Bạn đã dùng giftcode này rồi."); return

    if len(giftcode_used[code]) >= info["max_uses"]:
        bot.reply_to(message, "❌ Giftcode đã hết lượt."); return

    giftcode_used[code].add(chat_id)
    u["balance"] += info["amount"]
    u["history"].append({
        "time": datetime.now().strftime("%H:%M %d/%m/%Y"),
        "action": "Nhập giftcode",
        "detail": f"{code} — +{fmt_price(info['amount'])}",
        "status": "Thành công",
    })
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("⬅️ Menu", callback_data="menu_back"))
    bot.reply_to(message,
        f"🎁 <b>GIFTCODE THÀNH CÔNG</b>\n\n"
        f"➕ Cộng: <b>{fmt_price(info['amount'])}</b>\n"
        f"💰 Số dư mới: <b>{fmt_price(u['balance'])}</b>",
        parse_mode="HTML", reply_markup=kb)

# ==================== LỊCH SỬ ====================
def show_history(chat_id, from_user):
    u = get_user(chat_id)
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("⬅️ Menu", callback_data="menu_back"))
    if not u["history"]:
        bot.send_message(chat_id, "📜 Chưa có giao dịch nào.", reply_markup=kb); return
    text = "📜 <b>LỊCH SỬ GIAO DỊCH</b>\n\n"
    for h in u["history"][-20:]:
        text += (
            f"🕐 {h['time']}\n"
            f"📌 {h['action']}: {h['detail']}\n"
            f"➡️ {h['status']}\n\n"
        )
    bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=kb)

# ==================== THÔNG TIN USER ====================
def show_info(chat_id, from_user):
    u = get_user(chat_id)
    game_line = game_name(u["game_id"]) if u.get("game_id") else "Chưa chọn"
    text = (
        f"👤 <b>THÔNG TIN TÀI KHOẢN</b>\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"🆔 ID: <code>{chat_id}</code>\n"
        f"👤 Tên: <b>{from_user.full_name or 'N/A'}</b>\n"
        f"🌐 Username: @{from_user.username or 'N/A'}\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"💰 Số dư: <b>{fmt_price(u['balance'])}</b>\n"
        f"🎮 Game: <b>{game_line}</b>\n"
        f"🔑 Key: <b>{u['key'] or 'Chưa có'}</b>\n"
        f"📅 Hết hạn: <b>{u['expiry'] or '—'}</b>\n"
        f"🟢 Trạng thái: <b>{'Đang bật' if u['running'] else 'Đã tắt'}</b>\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"📜 Số giao dịch: <b>{len(u['history'])}</b>"
    )
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("⬅️ Menu", callback_data="menu_back"))
    bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=kb)

# ==================== HỖ TRỢ ====================
def show_support(chat_id):
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("⬅️ Menu", callback_data="menu_back"))
    text = (
        "💬 <b>HỖ TRỢ</b>\n\n"
        "Mọi thắc mắc vui lòng liên hệ admin.\n\n"
        "⏰ Thời gian hỗ trợ: 12:00 - 18:00 hàng ngày."
    )
    bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=kb)

# ==================== THỐNG KÊ ====================
def show_stats(chat_id):
    u = get_user(chat_id)
    if not u.get("game_id"):
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("🎮 Chọn Game", callback_data="menu_game"))
        kb.add(types.InlineKeyboardButton("⬅️ Menu", callback_data="menu_back"))
        bot.send_message(chat_id, "⚠️ Chưa chọn game.", reply_markup=kb)
        return
    data = get_data(u["game_id"])
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("⬅️ Menu", callback_data="menu_back"))
    if not data:
        bot.send_message(chat_id, "❌ Không lấy được dữ liệu API.", reply_markup=kb); return
    text = (
        f"📊 <b>THỐNG KÊ — {game_name(u['game_id'])}</b>\n\n"
        f"📦 Tổng: <b>{data.get('tong', 0)}</b>\n"
        f"✅ Đúng: <b>{data.get('dung', 0)}</b>\n"
        f"❌ Sai: <b>{data.get('sai', 0)}</b>\n"
        f"⏸ Bỏ qua: <b>{data.get('bo_qua', 0)}</b>\n"
        f"🎯 Chính xác: <b>{data.get('chinh_xac', '0%')}</b>"
    )
    bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=kb)

# ==================== BACK TO MENU ====================
@bot.callback_query_handler(func=lambda c: c.data == "menu_back")
def on_menu_back(c):
    chat_id = c.message.chat.id
    u = get_user(chat_id)
    bot.answer_callback_query(c.id)
    bot.send_message(chat_id, "🏠 <b>MENU CHÍNH</b>", parse_mode="HTML", reply_markup=main_menu(u))

# ==================== ADMIN PANEL ====================
@bot.message_handler(commands=['admin'])
def cmd_admin(message):
    if not is_admin_chat(message):
        bot.reply_to(message, "⛔ Admin only."); return
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("📋 Bill chờ duyệt", callback_data="adm_bills"),
        types.InlineKeyboardButton("👥 Danh sách user", callback_data="adm_users"),
    )
    kb.add(
        types.InlineKeyboardButton("➕ Cộng tiền", callback_data="adm_add_balance"),
        types.InlineKeyboardButton("🔑 Tạo key", callback_data="adm_taokey"),
    )
    kb.add(
        types.InlineKeyboardButton("📋 Danh sách key", callback_data="adm_listkey"),
        types.InlineKeyboardButton("🧹 Xóa key hết hạn", callback_data="adm_clean"),
    )
    kb.add(
        types.InlineKeyboardButton("🎁 Tạo giftcode", callback_data="adm_giftcode"),
        types.InlineKeyboardButton("📢 Broadcast", callback_data="adm_broadcast"),
    )
    bot.reply_to(message, "⚙️ <b>PANEL ADMIN</b>", parse_mode="HTML", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("adm_"))
def on_admin_callback(c):
    if not is_admin_chat(c):
        bot.answer_callback_query(c.id, "⛔ Admin only."); return
    data = c.data

    if data == "adm_bills":
        bot.answer_callback_query(c.id)
        if not pending_bills:
            bot.send_message(c.message.chat.id, "📭 Không có bill chờ duyệt.")
            return
        text = f"📋 <b>BILL CHỜ DUYỆT ({len(pending_bills)})</b>\n\n"
        for bid, b in list(pending_bills.items())[:10]:
            text += (
                f"🆔 <code>{bid}</code>\n"
                f"👤 User: <code>{b['user_id']}</code>\n"
                f"💰 {fmt_price(b['amount'])}\n"
                f"📝 {b['code']}\n"
                f"🕐 {b['time']}\n\n"
            )
        bot.send_message(c.message.chat.id, text, parse_mode="HTML")

    elif data == "adm_users":
        bot.answer_callback_query(c.id)
        total = len(user_data)
        running = sum(1 for u in user_data.values() if u.get("running"))
        activated = sum(1 for u in user_data.values() if u.get("activated"))
        total_balance = sum(u.get("balance", 0) for u in user_data.values())
        text = (
            f"👥 <b>NGƯỜI DÙNG</b>\n\n"
            f"📦 Tổng: <b>{total}</b>\n"
            f"🔓 Đã kích hoạt: <b>{activated}</b>\n"
            f"▶️ Đang bật tool: <b>{running}</b>\n"
            f"💰 Tổng số dư: <b>{fmt_price(total_balance)}</b>"
        )
        bot.send_message(c.message.chat.id, text, parse_mode="HTML")

    elif data == "adm_add_balance":
        bot.answer_callback_query(c.id)
        bot.send_message(c.message.chat.id,
            "➕ <b>CỘNG TIỀN USER</b>\n\n"
            "<code>/addbalance USER_ID SỐ_TIỀN</code>",
            parse_mode="HTML")

    elif data == "adm_taokey":
        bot.answer_callback_query(c.id)
        bot.send_message(c.message.chat.id,
            "🔑 <b>TẠO KEY (CHUNG MỌI GAME)</b>\n\n"
            "<code>/taokey 1d</code>\n\n"
            "Gói: 1d, 3d, 1w, 1m, 2m, forever",
            parse_mode="HTML")

    elif data == "adm_listkey":
        bot.answer_callback_query(c.id)
        cmd_listkey(c.message)

    elif data == "adm_clean":
        removed = 0
        for k in list(valid_keys.keys()):
            if valid_keys[k]["expiry"] is not None and time.time() > valid_keys[k]["expiry"]:
                del valid_keys[k]; removed += 1
        bot.answer_callback_query(c.id, f"Đã xóa {removed} key.")
        bot.send_message(c.message.chat.id, f"🧹 Đã xóa <b>{removed}</b> key hết hạn.", parse_mode="HTML")

    elif data == "adm_giftcode":
        bot.answer_callback_query(c.id)
        bot.send_message(c.message.chat.id,
            "🎁 <b>TẠO GIFTCODE</b>\n\n"
            "<code>/addgift CODE SỐ_TIỀN MAX_USES</code>",
            parse_mode="HTML")

    elif data == "adm_broadcast":
        bot.answer_callback_query(c.id)
        bot.send_message(c.message.chat.id,
            "📢 <b>BROADCAST</b>\n\n"
            "<code>/broadcast Nội dung tin nhắn</code>",
            parse_mode="HTML")

# ==================== ADMIN COMMANDS ====================
@bot.message_handler(commands=['addbalance'])
def cmd_addbalance(message):
    if not is_admin_chat(message): return
    args = message.text.split()
    if len(args) < 3:
        bot.reply_to(message, "Cú pháp: /addbalance USER_ID SỐ_TIỀN"); return
    try:
        uid = int(args[1]); amount = int(args[2])
    except:
        bot.reply_to(message, "❌ Sai định dạng."); return
    u = get_user(uid)
    u["balance"] += amount
    u["history"].append({
        "time": datetime.now().strftime("%H:%M %d/%m/%Y"),
        "action": "Admin cộng tiền",
        "detail": f"+{fmt_price(amount)}",
        "status": "Thành công",
    })
    bot.reply_to(message, f"✅ Đã cộng {fmt_price(amount)} cho user {uid}.")
    try:
        bot.send_message(uid, f"💰 Admin đã cộng <b>{fmt_price(amount)}</b> vào số dư.", parse_mode="HTML")
    except: pass

@bot.message_handler(commands=['taokey'])
def cmd_taokey(message):
    if not is_admin_chat(message): return
    args = message.text.split()
    if len(args) == 2:
        pkg = args[1].lower()
        game_id = "ALL"
    elif len(args) >= 3:
        if args[1].lower() in GAMES.values():
            game_id = args[1].lower()
            pkg = args[2].lower()
        else:
            pkg = args[1].lower()
            game_id = "ALL"
    else:
        bot.reply_to(message, "Cú pháp: /taokey 1d"); return

    if pkg not in KEY_PRICES:
        bot.reply_to(message, "❌ Gói không hợp lệ. Gói: 1d, 3d, 1w, 1m, 2m, forever"); return

    info = KEY_PRICES[pkg]
    new_key = generate_key()
    expiry = None if info["hours"] is None else time.time() + info["hours"] * 3600
    valid_keys[new_key] = {
        "game": game_id, "expiry": expiry,
        "price": 0, "label": info["label"], "used": False,
    }
    game_text = "TẤT CẢ 18 GAME" if game_id == "ALL" else game_name(game_id)
    bot.reply_to(message,
        f"✅ <b>ĐÃ TẠO KEY</b>\n\n"
        f"🔑 Key: <code>{new_key}</code>\n"
        f"🎮 Áp dụng: <b>{game_text}</b>\n"
        f"📦 Gói: <b>{info['label']}</b>",
        parse_mode="HTML")

@bot.message_handler(commands=['listkey'])
def cmd_listkey(message):
    if not is_admin_chat(message): return
    if not valid_keys:
        bot.reply_to(message, "📭 Không có key."); return
    text = f"🔑 <b>DANH SÁCH KEY ({len(valid_keys)})</b>\n\n"
    for k, info in list(valid_keys.items())[:30]:
        exp = "Vĩnh viễn" if info["expiry"] is None else datetime.fromtimestamp(info["expiry"]).strftime("%d/%m %H:%M")
        used = "✅" if info.get("used") else "⬜"
        text += f"{used} <code>{k}</code> | {info['label']} | {exp}\n"
    bot.reply_to(message, text, parse_mode="HTML")

@bot.message_handler(commands=['addgift'])
def cmd_addgift(message):
    if not is_admin_chat(message): return
    args = message.text.split()
    if len(args) < 4:
        bot.reply_to(message, "Cú pháp: /addgift CODE SỐ_TIỀN MAX_USES"); return
    code = args[1].upper()
    try:
        amount = int(args[2]); max_uses = int(args[3])
    except:
        bot.reply_to(message, "❌ Sai định dạng."); return
    GIFTCODES[code] = {"amount": amount, "max_uses": max_uses}
    giftcode_used[code] = set()
    bot.reply_to(message, f"✅ Đã tạo giftcode <code>{code}</code> — {fmt_price(amount)} x {max_uses} lượt.", parse_mode="HTML")

@bot.message_handler(commands=['broadcast'])
def cmd_broadcast(message):
    if not is_admin_chat(message): return
    text = message.text.replace("/broadcast", "").strip()
    if not text:
        bot.reply_to(message, "Cú pháp: /broadcast Nội dung"); return
    count = 0
    for uid in user_data:
        try:
            bot.send_message(uid, f"📢 <b>THÔNG BÁO</b>\n\n{text}", parse_mode="HTML")
            count += 1
        except: pass
    bot.reply_to(message, f"✅ Đã gửi cho {count} user.")

# ==================== MONITORING LOOP ====================
def monitoring_loop():
    log.info("Monitoring loop started")
    while True:
        try:
            game_ids = set([
                u["game_id"] for u in user_data.values()
                if u.get("running") and u.get("game_id")
            ])

            for gid in game_ids:
                data = get_data(gid)
                if not data or not data.get("lich_su"): continue
                entry = data["lich_su"][0]
                current_phien = entry.get("phien", 0)

                for chat_id, u in list(user_data.items()):
                    if not u.get("running"): continue
                    if u.get("game_id") != gid: continue
                    if u.get("last_phien") == current_phien: continue

                    send_ai_signal(chat_id, entry, gid)
                    u["last_phien"] = current_phien

            time.sleep(POLL_INTERVAL)
        except Exception as e:
            log.error(f"Monitoring err: {e}")
            time.sleep(5)

# ==================== FLASK ====================
flask_app = Flask(__name__)
_start = time.time()

@flask_app.route("/")
def home():
    return jsonify({
        "status": "ok", "service": "multi-game-bot",
        "uptime": round(time.time() - _start, 2),
        "users": len(user_data),
        "keys": len(valid_keys),
        "pending_bills": len(pending_bills),
    })

@flask_app.route("/health")
def health():
    return jsonify({"status": "healthy"})

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    flask_app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

# ==================== MAIN ====================
def main():
    log.info("=" * 60)
    log.info("MULTI-GAME BOT — DUYỆT BILL + GAME TỰ BẬT")
    log.info(f"API: {API_URL}")
    log.info(f"Games: {len(GAMES)} | Packages: {len(KEY_PRICES)}")
    log.info(f"Admin IDs: {ADMIN_IDS}")
    log.info("=" * 60)

    try:
        bot.remove_webhook()
        log.info("✅ Đã xóa webhook cũ")
    except Exception as e:
        log.warning(f"remove_webhook err: {e}")

    threading.Thread(target=run_flask, daemon=True).start()
    threading.Thread(target=monitoring_loop, daemon=True).start()
    bot.infinity_polling(timeout=30, long_polling_timeout=30)

if __name__ == "__main__":
    main()
