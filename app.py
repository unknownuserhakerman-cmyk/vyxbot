from flask import Flask, request, jsonify, send_from_directory, send_file
from flask_socketio import SocketIO
import threading
import asyncio
import random
import string
import os
import json
import time
from datetime import datetime

app = Flask(__name__, static_folder="static", static_url_path="")
app.config["SECRET_KEY"] = os.urandom(16).hex()
socketio = SocketIO(app, cors_allowed_origins="*")

STATE_FILE = "state.json"
UPLOAD_FOLDER = "uploads"
PHOTO_FOLDER = "profiles"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(PHOTO_FOLDER, exist_ok=True)


# ─── Persistent State (survives server restarts) ───

def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE) as f:
                return json.load(f)
        except:
            pass
    return {
        "platform": None,
        "discord_token": None,
        "telegram_session": None,
        "telegram_api_id": None,
        "telegram_api_hash": None,
        "telegram_username": None,
        "telegram_first_name": None,
        "telegram_photo": None,
        "auto_reply": False,
        "auto_reply_message": "",
        "running": False,
    }

def save_state(s):
    with open(STATE_FILE, "w") as f:
        json.dump(s, f, indent=2)

state = load_state()

# Runtime-only state (not persisted)
runtime = {
    "spam_thread": None,
    "auto_reply_thread": None,
    "channel_id": None,
    "message": "",
    "interval": 5,
    "image_path": None,
}


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
            ch = self.get_channel(int(runtime["channel_id"]))
            if not ch:
                log("ERROR: Channel not found")
                state["running"] = False
                save_state(state)
                await self.close()
                return
            while state.get("running", False):
                try:
                    c = vary_message(runtime["message"])
                    if runtime["image_path"] and os.path.exists(runtime["image_path"]):
                        with open(runtime["image_path"], "rb") as f:
                            await ch.send(content=c, file=discord.File(f))
                    else:
                        await ch.send(content=c)
                    log(f"Sent to #{ch.name}")
                    await da.sleep(random_delay(runtime["interval"]))
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
            while state.get("running", False):
                try:
                    c = vary_message(runtime["message"])
                    if runtime["image_path"] and os.path.exists(runtime["image_path"]):
                        await app.send_photo(
                            chat_id=int(runtime["channel_id"]),
                            photo=runtime["image_path"],
                            caption=c,
                        )
                    else:
                        await app.send_message(
                            chat_id=int(runtime["channel_id"]),
                            text=c,
                        )
                    log(f"Sent to Telegram {runtime['channel_id']}")
                    await asyncio.sleep(random_delay(runtime["interval"]))
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
        save_state(state)

        log("Credentials saved — verifying in background...")
        t = threading.Thread(target=_verify_telegram, daemon=True)
        t.start()

        return jsonify({"status": "ok", "platform": "telegram"})

    elif platform == "discord":
        token = d.get("discord_token")
        if not token:
            return jsonify({"status": "error", "msg": "Discord token required"}), 400

        state["platform"] = "discord"
        state["discord_token"] = token
        save_state(state)

        log("Credentials saved — verifying in background...")
        t = threading.Thread(target=_verify_discord, daemon=True)
        t.start()

        return jsonify({"status": "ok", "platform": "discord"})

    return jsonify({"status": "error", "msg": "No platform specified"}), 400


def _verify_telegram():
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
                state["telegram_username"] = me.username
                state["telegram_first_name"] = me.first_name
                try:
                    photos = [p async for p in app.get_chat_photos("me")]
                    if photos:
                        photo_path = os.path.join(PHOTO_FOLDER, "profile.jpg")
                        await app.download_media(photos[0].file_id, file_name=photo_path)
                        state["telegram_photo"] = "/api/profile/photo"
                except:
                    pass
                save_state(state)
                # Push profile update to the browser via WebSocket
                socketio.emit("profile_update", {
                    "username": me.username or "",
                    "first_name": me.first_name or "",
                    "has_photo": os.path.exists(os.path.join(PHOTO_FOLDER, "profile.jpg")),
                })
                return me.first_name or me.username or str(me.id)

        name = asyncio.run(test())
        log(f"✓ Telegram verified — logged in as {name}")
    except Exception as e:
        log(f"✗ Telegram verification failed: {e}")
        state["platform"] = None
        state["telegram_username"] = None
        state["telegram_first_name"] = None
        save_state(state)


def _verify_discord():
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
            state["telegram_username"] = result[0]
            state["telegram_first_name"] = result[0]
            save_state(state)
            socketio.emit("profile_update", {
                "username": result[0],
                "first_name": result[0],
                "has_photo": False,
            })
            log(f"✓ Discord verified — logged in as {result[0]}")
    except Exception as e:
        log(f"✗ Discord verification failed: {e}")
        state["platform"] = None
        save_state(state)


@app.route("/api/profile/photo")
def profile_photo():
    photo_path = os.path.join(PHOTO_FOLDER, "profile.jpg")
    if os.path.exists(photo_path):
        return send_file(photo_path, mimetype="image/jpeg")
    return "", 204


@app.route("/api/session", methods=["GET"])
def api_session():
    if state.get("platform") and (
        (state["platform"] == "telegram" and state.get("telegram_session"))
        or (state["platform"] == "discord" and state.get("discord_token"))
    ):
        return jsonify({
            "connected": True,
            "platform": state["platform"],
            "username": state.get("telegram_username") or "",
            "first_name": state.get("telegram_first_name") or "",
            "has_photo": os.path.exists(os.path.join(PHOTO_FOLDER, "profile.jpg")),
        })
    return jsonify({"connected": False})


@app.route("/api/disconnect", methods=["POST"])
def api_disconnect():
    state["running"] = False
    state["auto_reply"] = False
    state["platform"] = None
    state["discord_token"] = None
    state["telegram_session"] = None
    state["telegram_api_id"] = None
    state["telegram_api_hash"] = None
    state["telegram_username"] = None
    state["telegram_first_name"] = None
    state["telegram_photo"] = None
    runtime["channel_id"] = None
    runtime["message"] = ""
    runtime["interval"] = 5
    runtime["image_path"] = None
    photo_path = os.path.join(PHOTO_FOLDER, "profile.jpg")
    if os.path.exists(photo_path):
        os.remove(photo_path)
    save_state(state)
    log("Disconnected — all credentials cleared")
    return jsonify({"status": "ok"})


@app.route("/api/start", methods=["POST"])
def api_start():
    d = request.json
    runtime["channel_id"] = d.get("channel_id")
    runtime["message"] = d.get("message")
    runtime["interval"] = float(d.get("interval", 5))
    runtime["image_path"] = d.get("image_path") or None
    if state.get("running", False):
        return jsonify({"status": "error", "msg": "Already running"}), 400
    state["running"] = True
    save_state(state)
    if state["platform"] == "discord":
        runtime["spam_thread"] = threading.Thread(target=discord_spam_loop, daemon=True)
    elif state["platform"] == "telegram":
        runtime["spam_thread"] = threading.Thread(target=telegram_spam_loop, daemon=True)
    else:
        state["running"] = False
        save_state(state)
        return jsonify({"status": "error", "msg": "No platform"}), 400
    runtime["spam_thread"].start()
    log(f"▶ Started {state['platform']} spam")
    return jsonify({"status": "ok"})


@app.route("/api/stop", methods=["POST"])
def api_stop():
    state["running"] = False
    save_state(state)
    log("■ Stopped")
    return jsonify({"status": "ok"})


@app.route("/api/status", methods=["GET"])
def api_status():
    return jsonify({
        "running": state.get("running", False),
        "platform": state.get("platform"),
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
    save_state(state)

    if not runtime.get("auto_reply_thread") or not runtime["auto_reply_thread"].is_alive():
        t = threading.Thread(target=auto_reply_loop, daemon=True)
        runtime["auto_reply_thread"] = t
        t.start()
        log(f"Auto-reply enabled: \"{message[:50]}...\"")
    else:
        log("Auto-reply already running, updated message")

    return jsonify({"status": "ok"})


@app.route("/api/auto-reply/stop", methods=["POST"])
def api_auto_reply_stop():
    state["auto_reply"] = False
    save_state(state)
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
    log("Image uploaded")
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
