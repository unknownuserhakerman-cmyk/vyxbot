from flask import Flask, request, jsonify, send_from_directory
from flask_socketio import SocketIO
import threading
import asyncio
import random
import string
import os
from datetime import datetime

app = Flask(__name__, static_folder="static", static_url_path="")
app.config["SECRET_KEY"] = os.urandom(16).hex()
socketio = SocketIO(app, cors_allowed_origins="*")

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

def random_delay(base_interval):
    jitter = base_interval * random.uniform(0.6, 1.4)
    if random.random() < 0.1:
        jitter += random.uniform(2, 8)
    return jitter

def vary_message(msg):
    variants = [
        msg,
        msg + random.choice(["", ".", "..", "!"]),
        msg.strip() + " " + random.choice(string.ascii_lowercase),
    ]
    return random.choice(variants)

def discord_spam_loop():
    import discord
    import asyncio as da
    class Bot(discord.Client):
        async def on_ready(self):
            log(f"Discord connected as {self.user}")
            ch = self.get_channel(int(state["channel_id"]))
            if not ch:
                log("ERROR: Channel not found")
                state["running"] = False
                await self.close()
                return
            while state["running"]:
                try:
                    c = vary_message(state["message"])
                    if state["image_path"] and os.path.exists(state["image_path"]):
                        with open(state["image_path"], "rb") as f:
                            await ch.send(content=c, file=discord.File(f))
                    else:
                        await ch.send(content=c)
                    log(f"Sent to #{ch.name}")
                    await da.sleep(random_delay(state["interval"]))
                except Exception as e:
                    log(f"Discord error: {e}")
                    await da.sleep(5)
            await self.close()
    bot = Bot()
    bot.run(state["discord_token"], bot=False)

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
                    c = vary_message(state["message"])
                    if state["image_path"] and os.path.exists(state["image_path"]):
                        await app.send_photo(
                            chat_id=int(state["channel_id"]),
                            photo=state["image_path"],
                            caption=c,
                        )
                    else:
                        await app.send_message(
                            chat_id=int(state["channel_id"]),
                            text=c,
                        )
                    log(f"Sent to Telegram {state['channel_id']}")
                    await asyncio.sleep(random_delay(state["interval"]))
                except Exception as e:
                    log(f"Telegram error: {e}")
                    await asyncio.sleep(5)
    asyncio.run(spam())

def log(msg):
    t = datetime.now().strftime("%H:%M:%S")
    print(f"[{t}] {msg}")
    socketio.emit("log", {"time": t, "msg": msg})

@app.route("/")
def index():
    return send_from_directory("static", "index.html")

@app.route("/api/connect", methods=["POST"])
def api_connect():
    d = request.json
    state["platform"] = d.get("platform")
    state["discord_token"] = d.get("discord_token")
    state["telegram_session"] = d.get("telegram_session")
    state["telegram_api_id"] = d.get("telegram_api_id")
    state["telegram_api_hash"] = d.get("telegram_api_hash")
    log(f"Connected — {state['platform']}")
    return jsonify({"status": "ok"})

@app.route("/api/start", methods=["POST"])
def api_start():
    d = request.json
    state["channel_id"] = d.get("channel_id")
    state["message"] = d.get("message")
    state["interval"] = float(d.get("interval", 5))
    state["image_path"] = d.get("image_path") or None
    if state["running"]:
        return jsonify({"status": "error", "msg": "Already running"}), 400
    state["running"] = True
    if state["platform"] == "discord":
        state["thread"] = threading.Thread(target=discord_spam_loop, daemon=True)
    elif state["platform"] == "telegram":
        state["thread"] = threading.Thread(target=telegram_spam_loop, daemon=True)
    else:
        state["running"] = False
        return jsonify({"status": "error", "msg": "No platform"}), 400
    state["thread"].start()
    log(f"▶ Started {state['platform']} spam")
    return jsonify({"status": "ok"})

@app.route("/api/stop", methods=["POST"])
def api_stop():
    state["running"] = False
    log("■ Stopped")
    return jsonify({"status": "ok"})

@app.route("/api/status", methods=["GET"])
def api_status():
    return jsonify({"running": state["running"], "platform": state["platform"]})

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

@app.route("/api/upload", methods=["POST"])
def api_upload():
    if "image" not in request.files:
        return jsonify({"error": "No file"}), 400
    f = request.files["image"]
    ext = f.filename.rsplit(".", 1)[-1] if "." in f.filename else "png"
    path = os.path.join(UPLOAD_FOLDER, f"spam_{int(time.time())}.{ext}")
    f.save(path)
    log(f"Image uploaded")
    return jsonify({"path": os.path.abspath(path)})

@app.route("/api/channels/telegram", methods=["POST"])
def api_tg_channels():
    from pyrogram import Client
    d = request.json
    r = []
    async def fetch():
        app = Client(
            ":memory:",
            api_id=d["api_id"],
            api_hash=d["api_hash"],
            session_string=d["session"],
        )
        async with app:
            async for dialog in app.get_dialogs():
                if dialog.chat.type in ("channel", "group", "supergroup"):
                    r.append({
                        "id": str(dialog.chat.id),
                        "title": dialog.chat.title or "Private",
                        "type": str(dialog.chat.type),
                    })
    try:
        asyncio.run(fetch())
        return jsonify({"channels": r})
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route("/api/channels/discord", methods=["POST"])
def api_dc_channels():
    import discord, asyncio as da
    d = request.json
    r = []
    class Lister(discord.Client):
        async def on_ready(self):
            nonlocal r
            for g in self.guilds:
                for ch in g.text_channels:
                    r.append({"id": str(ch.id), "name": f"{g.name} / #{ch.name}"})
            await self.close()
    try:
        Lister().run(d["token"], bot=False)
        return jsonify({"channels": r})
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route("/uploads/<filename>")
def uploaded(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host="0.0.0.0", port=port, debug=False, allow_unsafe_werkzeug=True)
import os

api_id = int(os.getenv("API_ID"))
api_hash = os.getenv("API_HASH")
