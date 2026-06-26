from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit
import threading
import asyncio
import time
import random
import string
import os
from datetime import datetime

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")

# ─── Platform State ───
state = {
    "platform": None,           # "discord" | "telegram"
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

# ─── Anti-Detection Utils ───
def random_delay(base_interval):
    """Add jitter: ±40% of base interval with occasional longer pause."""
    jitter = base_interval * random.uniform(0.6, 1.4)
    # 10% chance of an extra "human pause"
    if random.random() < 0.1:
        jitter += random.uniform(2, 8)
    return jitter

def vary_message(msg):
    """Add subtle variations to avoid exact-repeat detection."""
    variants = [
        msg,
        msg + " " + random.choice(["", ".", "..", "!"]),
        msg.strip() + " " + random.choice(string.ascii_lowercase),
    ]
    return random.choice(variants)

# ─── Discord Spam Thread ───
def discord_spam_loop():
    import discord
    import asyncio as discord_asyncio

    class SelfBot(discord.Client):
        async def on_ready(self):
            log(f"Discord connected as {self.user}")
            channel = self.get_channel(int(state["channel_id"]))
            if not channel:
                log("Channel not found")
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
                    delay = random_delay(state["interval"])
                    await discord_asyncio.sleep(delay)
                except Exception as e:
                    log(f"Discord error: {e}")
                    await discord_asyncio.sleep(5)

            await self.close()

    bot = SelfBot()
    bot.run(state["discord_token"], bot=False)

# ─── Telegram Spam Thread ───
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
                            chat_id=state["channel_id"],
                            photo=state["image_path"],
                            caption=content,
                        )
                    else:
                        await app.send_message(
                            chat_id=state["channel_id"],
                            text=content,
                        )

                    log(f"Sent to Telegram chat {state['channel_id']}")
                    delay = random_delay(state["interval"])
                    await asyncio.sleep(delay)
                except Exception as e:
                    log(f"Telegram error: {e}")
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
    return app.send_static_file("index.html")

@app.route("/api/connect", methods=["POST"])
def api_connect():
    data = request.json
    state["platform"] = data.get("platform")
    state["discord_token"] = data.get("discord_token")
    state["telegram_session"] = data.get("telegram_session")
    state["telegram_api_id"] = data.get("telegram_api_id")
    state["telegram_api_hash"] = data.get("telegram_api_hash")
    return jsonify({"status": "ok"})

@app.route("/api/start", methods=["POST"])
def api_start():
    data = request.json
    state["channel_id"] = data.get("channel_id")
    state["message"] = data.get("message")
    state["interval"] = float(data.get("interval", 5))
    state["image_path"] = data.get("image_path")

    if state["running"]:
        return jsonify({"status": "error", "msg": "Already running"}), 400

    state["running"] = True

    if state["platform"] == "discord":
        state["thread"] = threading.Thread(target=discord_spam_loop, daemon=True)
    elif state["platform"] == "telegram":
        state["thread"] = threading.Thread(target=telegram_spam_loop, daemon=True)
    else:
        return jsonify({"status": "error", "msg": "No platform selected"}), 400

    state["thread"].start()
    log(f"Started {state['platform']} spam → {state['channel_id']}")
    return jsonify({"status": "ok"})

@app.route("/api/stop", methods=["POST"])
def api_stop():
    state["running"] = False
    log("Stopped all operations")
    return jsonify({"status": "ok"})

@app.route("/api/channels/telegram", methods=["POST"])
def api_telegram_channels():
    """Fetch user's Telegram chats/channels."""
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
                        "title": dialog.chat.title or "Private",
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
    """Fetch guilds and channels the user token has access to."""
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

if __name__ == "__main__":
    os.makedirs("static", exist_ok=True)
    socketio.run(app, host="0.0.0.0", port=5000, debug=False)
