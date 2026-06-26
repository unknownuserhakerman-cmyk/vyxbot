from flask import Flask, render_template, request, jsonify, send_from_directory
from flask_socketio import SocketIO, emit
import threading
import asyncio
import time
import random
import string
import os
import json
from datetime import datetime

app = Flask(__name__, static_folder="static", static_url_path="")
app.config["SECRET_KEY"] = os.urandom(16).hex()
socketio = SocketIO(app, cors_allowed_origins="*")

# ─── State ───
state = {
    "platform": None,
    "discord_token": None,
    "telegram_session": None,
    "telegram_api_id": None,
    "telegram_api_hash": None,
    "running": False,
    "thread": None,
    "channel_id": None,
    "message": "",
    "interval": 5,
    "image_path": None,
}

# ─── Anti-Detection ───
def random_delay(base_interval):
    jitter = base_interval * random.uniform(0.6, 1.4)
    if random.random() < 0.1:
        jitter += random.uniform(2, 8)
    return jitter

def vary_message(msg):
    variants = [
        msg,
        msg + random.choice(["", ".", "..", "!", " ✨", " 🔥"]),
        msg.strip() + " " + random.choice(string.ascii_lowercase),
    ]
    return random.choice(variants)

# ─── Discord Spam ───
def discord_spam_loop():
    import discord
    import asyncio as discord_asyncio

    class SelfBot(discord.Client):
        async def on_ready(self):
            log(f"Discord connected as {self.user}")
            channel = self.get_channel(int(state["channel_id"]))
            if not channel:
                log("ERROR: Discord channel not found")
                state["running"] = False
                await self.close()
                return

            while state["running"]:
                try:
                    content = vary_message(state["message"])
                    if state["image_path"] and os.path.exists(state["image_path"]):
                        with open(state["image_path"], "rb") as f:
                            await channel.send(content=content, file=discord.File(f))
                    else:
                        await channel.send(content=content)

                    log(f"Sent to Discord #{channel.name}")
                    await discord_asyncio.sleep(random_delay(state["interval"]))
                except Exception as e:
                    log(f"Discord send error: {e}")
                    await discord_asyncio.sleep(5)

            await self.close()

    bot = SelfBot()
    bot.run(state["discord_token"], bot=False)

# ─── Telegram Spam ───
def telegram_spam_loop():
    from pyrogram import Client

    async def spam():
        app = Client(
            ":memory:",
            api_id=state["telegram_api_id"],
            api_hash=state["telegram_api_hash"],
            session_string=state["telegram_session"],
        )

        async with app:
            me = await app.get_me()
            log(f"Telegram connected as {me.first_name}")

            while state["running"]:
                try:
                    content = vary_message(state["message"])
                    if state["image_path"] and os.path.exists(state["image_path"]):
                        await app.send_photo(
                            chat_id=int(state["channel_id"]),
                            photo=state["image_path"],
                            caption=content,
                        )
                    else:
                        await app.send_message(
                            chat_id=int(state["channel_id"]),
                            text=content,
                        )

                    log(f"Sent to Telegram chat {state['channel_id']}")
                    await asyncio.sleep(random_delay(state["interval"]))
                except Exception as e:
                    log(f"Telegram send error: {e}")
                    await asyncio.sleep(5)

    asyncio.run(spam())

# ─── Logging ───
def log(msg):
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] {msg}")
    socketio.emit("log", {"time": timestamp, "msg": msg})

# ─── Routes ───
@app.route("/")
def index():
    return send_from_directory("static", "index.html")

@app.route("/api/connect", methods=["POST"])
def api_connect():
    data = request.json
    state["platform"] = data.get("platform")
    state["discord_token"] = data.get("discord_token")
    state["telegram_session"] = data.get("telegram_session")
    state["telegram_api_id"] = data.get("telegram_api_id")
    state["telegram_api_hash"] = data.get("telegram_api_hash")
    log(f"Connected — Platform: {state['platform']}")
    return jsonify({"status": "ok"})

@app.route("/api/start", methods=["POST"])
def api_start():
    data = request.json
    state["channel_id"] = data.get("channel_id")
    state["message"] = data.get("message")
    state["interval"] = float(data.get("interval", 5))
    state["image_path"] = data.get("image_path") or None

    if state["running"]:
        return jsonify({"status": "error", "msg": "Already running"}), 400

    state["running"] = True

    if state["platform"] == "discord":
        state["thread"] = threading.Thread(target=discord_spam_loop, daemon=True)
    elif state["platform"] == "telegram":
        state["thread"] = threading.Thread(target=telegram_spam_loop, daemon=True)
    else:
        state["running"] = False
        return jsonify({"status": "error", "msg": "No platform selected"}), 400

    state["thread"].start()
    log(f"▶ Started {state['platform']} spam → channel {state['channel_id']}")
    return jsonify({"status": "ok"})

@app.route("/api/stop", methods=["POST"])
def api_stop():
    state["running"] = False
    log("■ Stopped all operations")
    return jsonify({"status": "ok"})

@app.route("/api/status", methods=["GET"])
def api_status():
    return jsonify({
        "running": state["running"],
        "platform": state["platform"],
    })

# ─── Image Upload ───
UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

@app.route("/api/upload", methods=["POST"])
def api_upload():
    if "image" not in request.files:
        return jsonify({"error": "No file provided"}), 400
    file = request.files["image"]
    if file.filename == "":
        return jsonify({"error": "Empty filename"}), 400
    ext = file.filename.rsplit(".", 1)[-1] if "." in file.filename else "png"
    name = f"spam_{int(time.time())}.{ext}"
    path = os.path.join(UPLOAD_FOLDER, name)
    file.save(path)
    log(f"Image uploaded: {name}")
    return jsonify({"path": os.path.abspath(path)})

# ─── Channel Fetching ───
@app.route("/api/channels/telegram", methods=["POST"])
def api_telegram_channels():
    from pyrogram import Client
    data = request.json
    results = []

    async def fetch():
        app = Client(
            ":memory:",
            api_id=data["api_id"],
            api_hash=data["api_hash"],
            session_string=data["session"],
        )
        async with app:
            async for dialog in app.get_dialogs():
                if dialog.chat.type in ("channel", "group", "supergroup"):
                    results.append({
                        "id": str(dialog.chat.id),
                        "title": dialog.chat.title or "Private Chat",
                        "type": str(dialog.chat.type),
                    })
        return results

    try:
        chats = asyncio.run(fetch())
        return jsonify({"channels": chats})
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route("/api/channels/discord", methods=["POST"])
def api_discord_channels():
    import discord
    import asyncio as da
    data = request.json
    results = []

    class Lister(discord.Client):
        async def on_ready(self):
            nonlocal results
            for guild in self.guilds:
                for ch in guild.text_channels:
                    results.append({
                        "id": str(ch.id),
                        "name": f"{guild.name} / #{ch.name}",
                    })
            await self.close()

    bot = Lister()
    try:
        bot.run(data["token"], bot=False)
        return jsonify({"channels": results})
    except Exception as e:
        return jsonify({"error": str(e)}), 400

# ─── Serve uploaded images ───
@app.route("/uploads/<filename>")
def uploaded_file(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host="0.0.0.0", port=port, debug=False, allow_unsafe_werkzeug=True)
