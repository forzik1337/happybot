from twitchio.ext import commands
from flask import Flask
import requests
import asyncio
import threading
import time
import json
import os
import hmac
import hashlib
import base64
import subprocess
import tempfile


# =========================
# АЛИАСЫ
# =========================

GAME_ALIASES = {
    "cs": "Counter-Strike",
    "cs2": "Counter-Strike",
    "csgo": "Counter-Strike",
    "counter strike": "Counter-Strike",
    "jc": "just chatting"
}

# =========================
# НАСТРОЙКИ
# =========================
TOKEN = "oauth:4ss2f7rkv2oyk4nx6stm43ofwzb1yp"
CHANNEL = "mixarage"
CLIENT_ID = "gp762nuuoqcoxypju8c569th9wz7q5"
ACCESS_TOKEN = "6sd2sctpg01prnw1kr4m3q6og1c62f"
BROADCASTER_ID = "754043303"

SETTINGS_FILE = "settings.json"

# =========================
# DEFAULT VALUES
# =========================
auto_enabled = True

auto1_message = "LO LOL ChickenGunGuitar <--- НЕ ВИДИШЬ СМАЙЛИКИ? ТОГДА ПРОСТО СКАЧАЙ НА ПК РАСШИРЕНИЕ 7tv - 7tv.app ИЛИ НА ТЕЛЕФОН ПРИЛОЖЕНИЕ frosty"
auto1_interval = 30 * 60

auto2_message = "ТГ ТЕЛЕГРАММ КАНАЛ УБЛЮДКААААААА - https://t.me/mixarage"
auto2_interval = 60 * 60


# =========================
# SAVE / LOAD
# =========================
def save_settings():
    data = {
        "auto_enabled": auto_enabled,
        "auto1_message": auto1_message,
        "auto2_message": auto2_message,
        "auto1_interval": auto1_interval,
        "auto2_interval": auto2_interval
    }
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)


def load_settings():
    global auto_enabled
    global auto1_message, auto2_message
    global auto1_interval, auto2_interval

    if not os.path.exists(SETTINGS_FILE):
        return

    with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    auto_enabled       = data.get("auto_enabled", auto_enabled)
    auto1_message      = data.get("auto1_message", auto1_message)
    auto2_message      = data.get("auto2_message", auto2_message)
    auto1_interval     = data.get("auto1_interval", auto1_interval)
    auto2_interval     = data.get("auto2_interval", auto2_interval)


load_settings()


# =========================
# TWITCH BOT
# =========================
class Bot(commands.Bot):

    def __init__(self):
        super().__init__(
            token=TOKEN,
            prefix="!",
            initial_channels=[CHANNEL]
        )
        self._track_cooldown = 0  # антиспам

    async def event_ready(self):
        print("Бот запущен:", self.nick)

    # =========================
    # !title
    # =========================
    @commands.command()
    async def title(self, ctx, *, new_title):
        if not (ctx.author.is_mod or ctx.author.is_broadcaster):
            return

        headers = {
            "Client-ID": CLIENT_ID,
            "Authorization": f"Bearer {ACCESS_TOKEN}",
            "Content-Type": "application/json"
        }
        url = f"https://api.twitch.tv/helix/channels?broadcaster_id={BROADCASTER_ID}"
        r = requests.patch(url, headers=headers, json={"title": new_title})

        if r.status_code == 204:
            await ctx.send(f"📝 Название стрима изменено: {new_title}")
        else:
            await ctx.send("❌ Ошибка названия")

    # =========================
    # !game
    # =========================
    @commands.command()
    async def game(self, ctx, *, game_name):
        if not (ctx.author.is_mod or ctx.author.is_broadcaster):
            return

        query = GAME_ALIASES.get(game_name.lower(), game_name)
        headers = {
            "Client-ID": CLIENT_ID,
            "Authorization": f"Bearer {ACCESS_TOKEN}"
        }
        r = requests.get(
            "https://api.twitch.tv/helix/games",
            headers=headers,
            params={"name": query}
        )

        if r.status_code != 200:
            await ctx.send("❌ Twitch API ошибка")
            return

        data = r.json().get("data", [])
        if not data:
            await ctx.send("❌ Игра не найдена")
            return

        game = data[0]
        game_id = game["id"]
        real_name = game["name"]

        r2 = requests.patch(
            f"https://api.twitch.tv/helix/channels?broadcaster_id={BROADCASTER_ID}",
            headers=headers,
            json={"game_id": game_id}
        )

        if r2.status_code == 204:
            await ctx.send(f"🎮 Категория была изменена: {real_name}")
        else:
            await ctx.send("❌ Ошибка смены игры")

    # =========================
    # !tg / !tt / !donate
    # =========================
    @commands.command()
    async def tg(self, ctx):
        await ctx.send("📢 Новости о стримах тут https://t.me/mixarage")

    @commands.command()
    async def tt(self, ctx):
        await ctx.send("🎵 Нарезки: nertizxyecoc, Мой тик ток: xyecoc037")

    @commands.command()
    async def donate(self, ctx):
        await ctx.send("💰 Денег много сюда: https://www.donationalerts.com/r/mopsyara009")


# =========================
# FLASK
# =========================
app = Flask(__name__)


@app.route("/")
def home():
    return """
    <html>
    <head>
        <title>Twitch Panel</title>
        <style>
        body {
            margin: 0;
            background: #0f0f0f;
            color: white;
            font-family: sans-serif;
            text-align: center;
            padding-top: 30px;
        }
        h1 { margin-bottom: 20px; }
        .btn {
            width: 200px; height: 120px; font-size: 18px;
            border: none; border-radius: 20px; cursor: pointer;
            color: white; margin: 10px; transition: 0.15s;
        }
        .btn:active { transform: scale(0.95); filter: brightness(1.2); }
        .tg { background: #0088cc; }
        .smile { background: #ff4d6d; }
        .panel { margin-top: 10px; }
        .auto {
            margin-top: 30px; display: inline-block;
            background: #1a1a1a; padding: 20px; border-radius: 15px;
        }
        input { padding: 8px; width: 300px; margin: 5px; border-radius: 8px; border: none; }
        .smallBtn { padding: 10px 15px; border: none; border-radius: 10px; cursor: pointer; background: #2ecc71; color: white; }
        .toggle { margin-top: 15px; padding: 10px 20px; border-radius: 10px; border: none; cursor: pointer; background: #e74c3c; color: white; }
        #status { position: fixed; top: 20px; right: 20px; padding: 10px; background: #e74c3c; border-radius: 10px; }
        .gif-bet { position: relative; width: 200px; height: 120px; border-radius: 20px; overflow: hidden; cursor: pointer; }
        .gif-bet::before { content: ""; position: absolute; inset: 0; background: url("https://media1.tenor.com/m/YXMkqSh7Y4gAAAAd/gamba.gif"); background-size: cover; background-position: center; }
        .gif-bet::after { content: ""; position: absolute; inset: 0; background: rgba(0,0,0,0.4); }
        .gif-bet span { position: relative; color: white; z-index: 1; }
        .btn-gif { width: 200px; height: 120px; border-radius: 20px; border: none; cursor: pointer; position: relative; overflow: hidden; color: white; font-weight: bold; }
        .btn-gif span { position: relative; z-index: 2; text-shadow: 0 0 6px black; }
        .btn-gif::before { content: ""; position: absolute; inset: 0; background-size: cover; background-position: center; filter: brightness(0.7); }
        .btn-gif:active { transform: scale(0.95); }
        button[onclick*="tg"]::before { background-image: url("https://cdn.7tv.app/emote/01K5Y2ZB2Q7GYJGBFCSXK4S422/4x.avif"); }
        button[onclick*="smile"]::before { background-image: url("https://cdn.7tv.app/emote/01HS92S040000DP2RP0GR0ZDZZ/4x.avif"); }
        .corner-img { position: fixed; right: 20px; bottom: 20px; width: 160px; height: auto; border-radius: 12px; box-shadow: 0 0 20px rgba(0,0,0,0.5); z-index: 9999; pointer-events: none; }
        .tg-box { position: fixed; left: 20px; bottom: 20px; z-index: 9999; text-align: center; }
        .tg-label { color: white; margin-bottom: 8px; font-size: 16px; font-weight: bold; text-shadow: 0 0 10px rgba(0,0,0,0.8); }
        .tg-corner { width: 90px; height: 90px; object-fit: cover; border-radius: 20px; box-shadow: 0 0 25px rgba(0,136,204,0.8); cursor: pointer; transition: 0.2s; }
        .tg-corner:hover { transform: scale(1.08); box-shadow: 0 0 20px rgba(0,136,204,1), 0 0 40px rgba(0,136,204,0.8); }
        .tg-corner:active { transform: scale(0.95); }
        .social-bar { position: fixed; left: 50%; bottom: 20px; transform: translateX(-50%); display: flex; gap: 18px; z-index: 9999; }
        .social-icon { width: 70px; height: 70px; object-fit: cover; border-radius: 18px; cursor: pointer; transition: 0.2s; background: white; padding: 8px; box-shadow: 0 0 20px rgba(0,0,0,0.4); }
        .tg-icon { box-shadow: 0 0 25px rgba(0,136,204,0.8); }
        .gpt-icon { box-shadow: 0 0 25px rgba(16,163,127,0.8); }
        .yt-icon { box-shadow: 0 0 25px rgba(255,0,0,0.8); }
        .twitch-icon { box-shadow: 0 0 25px rgba(145,70,255,0.8); }
        .social-icon:hover { transform: scale(1.12); filter: brightness(1.1); }
        .social-icon:active { transform: scale(0.95); }
        .donate::before { content: ""; position: absolute; inset: 0; background: url("https://cdn.7tv.app/emote/01GBFAYKGR000FWWN7MDZZ8XQN/4x.avif"); background-size: cover; background-position: center; }
        .top-left-gif { position: fixed; top: 20px; left: 20px; width: 320px; height: auto; border-radius: 18px; box-shadow: 0 0 25px rgba(255,255,255,0.2); z-index: 9999; pointer-events: none; }
        .local-site-btn { position: fixed; top: 20px; left: 340px; width: 120px; height: 120px; border-radius: 20px; object-fit: cover; z-index: 99999; cursor: pointer; box-shadow: 0 0 25px rgba(0,255,120,0.7); transition: 0.2s; }
        .local-site-btn:hover { transform: scale(1.08); box-shadow: 0 0 25px rgba(0,255,120,1), 0 0 45px rgba(0,255,120,0.7); }
        .local-site-btn:active { transform: scale(0.95); }
        </style>
    </head>
    <body>
    <h1>ЭТО ПАНЕЛЬ ДЛЯ ЛЕНИВЫХ ДАУНОВ :)</h1>
    <div class="panel">
        <button class="btn-gif tg" onclick="send('tg')"><span>ТЕЛЕГРАМ</span></button>
        <button class="btn-gif smile" onclick="send('smile')"><span>СМАЙЛЫ</span></button>
        <button class="btn gif-bet" onclick="send('bet_start')"><span>СТАРТ СТАВКИ</span></button>
        <button class="btn-gif donate" onclick="send('donate')"><span>ДОНАТ</span></button>
        <img src="https://i.ibb.co/PZRnvpgg/sample-2a24be18c3db1a3b27063ec6b718f7b1.png" class="corner-img">
        <div class="tg-box">
            <div class="tg-label">Тгк крутешего</div>
            <a href="https://t.me/ZZZZZkruteyshiy" target="_blank">
                <img src="https://i.ibb.co/hFMSr71D/photo-2026-05-14-21-30-44.jpg" class="tg-corner">
            </a>
        </div>
        <div class="social-bar">
            <a href="https://t.me/forzikxDSvin" target="_blank"><img src="https://upload.wikimedia.org/wikipedia/commons/8/82/Telegram_logo.svg" class="social-icon tg-icon"></a>
            <a href="https://chatgpt.com" target="_blank"><img src="https://upload.wikimedia.org/wikipedia/commons/0/04/ChatGPT_logo.svg" class="social-icon gpt-icon"></a>
            <a href="https://youtube.com" target="_blank"><img src="https://upload.wikimedia.org/wikipedia/commons/e/ef/Youtube_logo.png" class="social-icon yt-icon"></a>
            <a href="https://twitch.tv/forzikxd" target="_blank"><img src="https://i.ibb.co/3m6BxbZ2/image-2.png" class="social-icon twitch-icon"></a>
        </div>
        <img src="https://i.ibb.co/5hYCCKWc/video.gif" class="top-left-gif">
        <a href="http://127.0.0.1:3000" target="_blank">
            <img src="https://i.ibb.co/hFMSr71D/photo-2026-05-14-21-30-44.jpg" class="local-site-btn">
        </a>
    </div>
    <div class="auto">
        <h3>⚙️ AUTO #1</h3>
        <input id="a1" value="LO LOL ChickenGunGuitar <--- НЕ ВИДИШЬ СМАЙЛИКИ? ТОГДА ПРОСТО СКАЧАЙ НА ПК РАСШИРЕНИЕ 7tv - 7tv.app ИЛИ НА ТЕЛЕФОН ПРИЛОЖЕНИЕ frosty">
        <input id="i1" type="number" value="30">
        <button class="smallBtn" onclick="save1()">Сохранить</button>
        <h3>⚙️ AUTO #2</h3>
        <input id="a2" value="ТГ ТЕЛЕГРАММ УБЛЮДКААААААА - https://t.me/mixarage">
        <input id="i2" type="number" value="60">
        <button class="smallBtn" onclick="save2()">Сохранить</button>
        <br>
        <button class="toggle" onclick="toggle()">ON / OFF AUTO</button>
    </div>
    <div id="status">OFF</div>
    <script>
    async function send(t){ await fetch('/send/' + t); }
    async function save1(){
        await fetch('/set_auto1/' + encodeURIComponent(a1.value));
        await fetch('/set_auto1_interval/' + i1.value);
        alert("AUTO1 сохранено");
    }
    async function save2(){
        await fetch('/set_auto2/' + encodeURIComponent(a2.value));
        await fetch('/set_auto2_interval/' + i2.value);
        alert("AUTO2 сохранено");
    }
    async function toggle(){
        let r = await fetch('/toggle_auto');
        let t = await r.text();
        let s = document.getElementById("status");
        if(t === "True"){ s.innerHTML = "ON"; s.style.background = "#2ecc71"; }
        else { s.innerHTML = "OFF"; s.style.background = "#e74c3c"; }
    }
    </script>
    </body>
    </html>
    """


# =========================
# КНОПКИ
# =========================
@app.route("/send/<action>")
def send(action):
    if action == "tg":
        msg = auto2_message
    elif action == "smile":
        msg = auto1_message
    elif action == "bet_start":
        msg = "СТАВКА НАЧАЛАСЬ❗❗❗"
        async def spam():
            await send_message(msg)
            await asyncio.sleep(0.8)
            await send_message(msg)
            await asyncio.sleep(0.8)
            await send_message(msg)
        asyncio.run_coroutine_threadsafe(spam(), bot.loop)
        return "OK"
    elif action == "donate":
        msg = "DONALERT ЗАДОНАТИТЬ ТИПОЧКУ - https://www.donationalerts.com/r/mopsyara009"
    else:
        msg = "..."

    asyncio.run_coroutine_threadsafe(send_message(msg), bot.loop)
    return "OK"


# =========================
# SETTINGS ROUTES
# =========================
@app.route("/set_auto1/<path:msg>")
def set_auto1(msg):
    global auto1_message
    auto1_message = msg
    save_settings()
    return "OK"

@app.route("/set_auto2/<path:msg>")
def set_auto2(msg):
    global auto2_message
    auto2_message = msg
    save_settings()
    return "OK"

@app.route("/set_auto1_interval/<mins>")
def set_auto1_interval_route(mins):
    global auto1_interval
    auto1_interval = int(mins) * 60
    save_settings()
    return "OK"

@app.route("/set_auto2_interval/<mins>")
def set_auto2_interval_route(mins):
    global auto2_interval
    auto2_interval = int(mins) * 60
    save_settings()
    return "OK"

@app.route("/toggle_auto")
def toggle_auto():
    global auto_enabled
    auto_enabled = not auto_enabled
    save_settings()
    return str(auto_enabled)


# =========================
# AUTO LOOP
# =========================
def auto_loop():
    print("AUTO LOOP STARTED")
    last1 = 0
    last2 = 0

    while True:
        time.sleep(1)
        if not auto_enabled:
            continue
        now = time.time()
        if now - last1 >= auto1_interval:
            last1 = now
            asyncio.run_coroutine_threadsafe(send_message(auto1_message), bot.loop)
        if now - last2 >= auto2_interval:
            last2 = now
            asyncio.run_coroutine_threadsafe(send_message(auto2_message), bot.loop)


# =========================
# START
# =========================
bot = Bot()

async def send_message(text):
    channel = bot.get_channel(CHANNEL)
    if channel:
        await channel.send(text)

def run_bot():
    bot.run()

threading.Thread(target=run_bot, daemon=True).start()
threading.Thread(target=auto_loop, daemon=True).start()

app.run(port=5000)
