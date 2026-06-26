from flask import Flask, request, jsonify, send_from_directory
from flask_socketio import SocketIO
import threading
import asyncio
import random
import string
import os
import time
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
    "auto_reply": False,
    "auto_reply_message": "",
    "auto_reply_thread": None,
}

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


# ─── Utility ───

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


def log(msg):
    t = datetime.now().strftime("%H:%M:%S")
    print(f"[{t}] {msg}")
    socketio.emit("log", {"time": t, "msg": msg})


# ─── Spam Loops ───

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


# ─── Auto-Reply Loop ───

def auto_reply_loop():
    from pyrogram import Client, filters
    import asyncio as aio

    async def _run():
        app = Client(
            "auto_reply_session",
            api_id=state["telegram_api_id"],
            api_hash=state["telegram_api_hash"],
            session_string=state["telegram_session"],
        )

        @app.on_message(filters.private & ~filters.me)
        async def handler(client, msg):
            if not state.get("auto_reply"):
                return
            reply_text = state.get("auto_reply_message") or "I'm busy right now."
            try:
                await msg.reply(reply_text)
                name = msg.from_user.first_name if msg.from_user else "Unknown"
                log(f"Auto-replied to {name}: {reply_text[:50]}")
            except Exception as e:
                log(f"Auto-reply error: {e}")

        log("Auto-reply listener started")
        await app.run()

    try:
        loop = aio.new_event_loop()
        aio.set_event_loop(loop)
        loop.run_until_complete(_run())
    except Exception as e:
        log(f"Auto-reply stopped: {e}")


# ─── Routes ───

@app.route("/")
def index():
    return send_from_directory("static", "index.html")


# ─── Connect: INSTANT — saves credentials, doesn't test ───
@app.route("/api/connect", methods=["POST"])
def api_connect():
    d = request.json
    platform = d.get("platform")

    if platform == "telegram":
        api_id_val = d.get("telegram_api_id")
        api_hash_val = d.get("telegram_api_hash")
        session_val = d.get("telegram_session")
        if not api_id_val or not api_hash_val or not session_val:
            return jsonify({"status": "error", "msg": "All Telegram fields required"}), 400

        state["platform"] = "telegram"
        state["telegram_api_id"] = api_id_val
        state["telegram_api_hash"] = api_hash_val
        state["telegram_session"] = session_val
        log(f"Credentials saved — Telegram (testing in background...)")

        # Test connection in background thread
        t = threading.Thread(target=_verify_telegram, daemon=True)
        t.start()

        return jsonify({"status": "ok", "platform": "telegram"})

    elif platform == "discord":
        token = d.get("discord_token")
        if not token:
            return jsonify({"status": "error", "msg": "Discord token required"}), 400

        state["platform"] = "discord"
        state["discord_token"] = token
        log(f"Credentials saved — Discord (testing in background...)")

        t = threading.Thread(target=_verify_discord, daemon=True)
        t.start()

        return jsonify({"status": "ok", "platform": "discord"})

    return jsonify({"status": "error", "msg": "No platform specified"}), 400


def _verify_telegram():
    """Background test — logs result via WebSocket."""
    from pyrogram import Client
    try:
        async def test():
            app = Client(
                ":memory:",
                api_id=state["telegram_api_id"],
                api_hash=state["telegram_api_hash"],
                session_string=state["telegram_session"],
            )
            async with app:
                me = await app.get_me()
                return me.first_name or me.username or str(me.id)

        name = asyncio.run(test())
        log(f"✓ Telegram verified — logged in as {name}")
    except Exception as e:
        log(f"✗ Telegram verification failed: {e}")


def _verify_discord():
    """Background test — logs result via WebSocket."""
    import discord
    import asyncio as da
    try:
        result = []
        class Tester(discord.Client):
            async def on_ready(self):
                result.append(str(self.user))
                await self.close()
        Tester().run(state["discord_token"], bot=False)
        if result:
            log(f"✓ Discord verified — logged in as {result[0]}")
    except Exception as e:
        log(f"✗ Discord verification failed: {e}")


# ─── Disconnect / Logout ───
@app.route("/api/disconnect", methods=["POST"])
def api_disconnect():
    state["running"] = False
    state["auto_reply"] = False
    state["platform"] = None
    state["discord_token"] = None
    state["telegram_session"] = None
    state["telegram_api_id"] = None
    state["telegram_api_hash"] = None
    state["channel_id"] = None
    state["message"] = ""
    state["interval"] = 5
    state["image_path"] = None
    log("Disconnected — all credentials cleared")
    return jsonify({"status": "ok"})


# ─── Session check ───
@app.route("/api/session", methods=["GET"])
def api_session():
    if state["platform"]:
        return jsonify({"connected": True, "platform": state["platform"]})
    return jsonify({"connected": False})


# ─── Start / Stop spam ───
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
    return jsonify({
        "running": state["running"],
        "platform": state["platform"],
        "auto_reply": state.get("auto_reply", False),
    })


# ─── Auto-reply ───
@app.route("/api/auto-reply/start", methods=["POST"])
def api_auto_reply_start():
    d = request.json
    message = d.get("message", "").strip()
    if not message:
        return jsonify({"status": "error", "msg": "Auto-reply message cannot be empty"}), 400
    if state["platform"] != "telegram":
        return jsonify({"status": "error", "msg": "Auto-reply is only available for Telegram"}), 400

    state["auto_reply_message"] = message
    state["auto_reply"] = True

    if not state.get("auto_reply_thread") or not state["auto_reply_thread"].is_alive():
        t = threading.Thread(target=auto_reply_loop, daemon=True)
        state["auto_reply_thread"] = t
        t.start()
        log(f"Auto-reply enabled: \"{message[:50]}...\"")
    else:
        log("Auto-reply already running, updated message")

    return jsonify({"status": "ok"})


@app.route("/api/auto-reply/stop", methods=["POST"])
def api_auto_reply_stop():
    state["auto_reply"] = False
    log("Auto-reply disabled")
    return jsonify({"status": "ok"})


# ─── Upload ───
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


@app.route("/uploads/<filename>")
def uploaded(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)


# ─── Channel Loading ───
@app.route("/api/channels/telegram", methods=["POST"])
def api_tg_channels():
    from pyrogram import Client
    d = request.json
    r = []
    errors = []

    async def fetch():
        try:
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
        except Exception as e:
            errors.append(str(e))

    try:
        asyncio.run(fetch())
        if errors:
            return jsonify({"error": errors[0]}), 400
        return jsonify({"channels": r})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/channels/discord", methods=["POST"])
def api_dc_channels():
    import discord
    import asyncio as da
    d = request.json
    r = []
    errors = []

    class Lister(discord.Client):
        async def on_ready(self):
            try:
                nonlocal r
                for g in self.guilds:
                    for ch in g.text_channels:
                        r.append({"id": str(ch.id), "name": f"{g.name} / #{ch.name}"})
            except Exception as e:
                errors.append(str(e))
            await self.close()

    try:
        Lister().run(d["token"], bot=False)
        if errors:
            return jsonify({"error": errors[0]}), 400
        return jsonify({"channels": r})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host="0.0.0.0", port=port, debug=False, allow_unsafe_werkzeug=True)
