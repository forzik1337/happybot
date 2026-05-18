import threading
import socket
import ssl
import queue
import json
import random
import time
from flask import Flask, Response, stream_with_context, request, redirect, session
import urllib.parse
import urllib.request

app = Flask(__name__)
app.secret_key = "twitch_player_secret_123"

CLIENT_ID = "nyv9h504lcvgf8w15zf4opn7zkxeq3"
REDIRECT_URI = "http://localhost:3000/auth/callback"
SCOPES = "chat:read chat:edit"

chat_queues = {}
chat_queues_lock = threading.Lock()
channel_threads = {}


def twitch_irc_worker(channel):
    while True:
        try:
            sock = socket.create_connection(("irc.chat.twitch.tv", 443))
            conn = ssl.create_default_context().wrap_socket(sock, server_hostname="irc.chat.twitch.tv")
            conn.settimeout(None)

            def send(msg):
                conn.sendall((msg + "\r\n").encode())

            send("PASS oauth:SCHMOOPIIE")
            send(f"NICK justinfan{random.randint(10000,99999)}")
            send("CAP REQ :twitch.tv/tags twitch.tv/commands")
            send(f"JOIN #{channel}")

            buffer = ""
            while True:
                data = conn.recv(4096).decode("utf-8", errors="ignore")
                if not data:
                    break
                buffer += data
                lines = buffer.split("\r\n")
                buffer = lines[-1]
                for line in lines[:-1]:
                    if "PING" in line:
                        send("PONG :tmi.twitch.tv")
                        continue
                    if "PRIVMSG" not in line:
                        continue
                    tags = {}
                    if line.startswith("@"):
                        parts_line = line[1:].split(" ", 1)
                        if len(parts_line) != 2:
                            continue
                        tag_str, line = parts_line
                        for tag in tag_str.split(";"):
                            k, _, v = tag.partition("=")
                            tags[k] = v
                    parts = line.split(" ", 3)
                    if len(parts) < 4:
                        continue
                    prefix = parts[0].lstrip(":")
                    username = prefix.split("!")[0]
                    message = parts[3].lstrip(":")
                    color = tags.get("color", "#9146ff") or "#9146ff"
                    display_name = tags.get("display-name", username) or username
                    badges_raw = tags.get("badges", "")
                    emotes_raw = tags.get("emotes", "")
                    msg_data = json.dumps({
                        "username": display_name,
                        "color": color,
                        "message": message,
                        "badges": badges_raw,
                        "emotes": emotes_raw,
                    })
                    with chat_queues_lock:
                        if channel in chat_queues:
                            for q in chat_queues[channel]:
                                q.put(msg_data)
        except Exception as e:
            print(f"IRC disconnected ({channel}): {e}, reconnecting in 5s...")
        time.sleep(5)


def ensure_worker(channel):
    if channel not in channel_threads or not channel_threads[channel].is_alive():
        t = threading.Thread(target=twitch_irc_worker, args=(channel,), daemon=True)
        channel_threads[channel] = t
        t.start()


@app.route("/auth/login")
def auth_login():
    params = urllib.parse.urlencode({
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "response_type": "token",
        "scope": SCOPES,
        "force_verify": "false",
    })
    return redirect(f"https://id.twitch.tv/oauth2/authorize?{params}")


@app.route("/auth/callback")
def auth_callback():
    return """
    <script>
    const hash = window.location.hash.substring(1);
    const params = new URLSearchParams(hash);
    const token = params.get('access_token');
    if (token) {
        fetch('/auth/save', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({token})
        }).then(() => {
            window.location.href = sessionStorage.getItem('redirect_after_login') || '/';
        });
    } else { window.location.href = '/'; }
    </script>
    """


@app.route("/auth/save", methods=["POST"])
def auth_save():
    data = request.get_json()
    token = data.get("token", "")
    session["token"] = token
    try:
        req = urllib.request.Request(
            "https://api.twitch.tv/helix/users",
            headers={"Authorization": f"Bearer {token}", "Client-Id": CLIENT_ID}
        )
        with urllib.request.urlopen(req) as resp:
            user_data = json.loads(resp.read())
            session["username"] = user_data["data"][0]["login"]
            session["display_name"] = user_data["data"][0]["display_name"]
    except Exception as e:
        print(f"Failed to get user info: {e}")
    return {"ok": True}


@app.route("/auth/me")
def auth_me():
    return {
        "username": session.get("username", ""),
        "display_name": session.get("display_name", ""),
        "token": session.get("token", ""),
    }


@app.route("/auth/logout")
def auth_logout():
    session.clear()
    return redirect("/")


@app.route("/send/<channel>", methods=["POST"])
def send_message(channel):
    token = session.get("token")
    if not token:
        return {"error": "not logged in"}, 401
    data = request.get_json()
    message = data.get("message", "").strip()
    if not message:
        return {"error": "empty"}, 400
    try:
        sock = socket.create_connection(("irc.chat.twitch.tv", 443))
        conn = ssl.create_default_context().wrap_socket(sock, server_hostname="irc.chat.twitch.tv")
        conn.settimeout(10)
        def send(msg):
            conn.sendall((msg + "\r\n").encode())
        send(f"PASS oauth:{token}")
        send(f"NICK {session.get('username', 'user')}")
        send(f"JOIN #{channel}")
        send(f"PRIVMSG #{channel} :{message}")
        time.sleep(0.5)
        conn.close()
        return {"ok": True}
    except Exception as e:
        return {"error": str(e)}, 500


@app.route("/chat/<channel>")
def chat_stream(channel):
    q = queue.Queue()
    with chat_queues_lock:
        if channel not in chat_queues:
            chat_queues[channel] = []
        chat_queues[channel].append(q)
    ensure_worker(channel)

    def generate():
        try:
            while True:
                try:
                    msg = q.get(timeout=25)
                    yield f"data: {msg}\n\n"
                except queue.Empty:
                    yield 'data: {"ping":1}\n\n'
        finally:
            with chat_queues_lock:
                if channel in chat_queues:
                    try:
                        chat_queues[channel].remove(q)
                    except ValueError:
                        pass

    return Response(stream_with_context(generate()),
                    mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/")
def home():
    return """
    <html><head><title>Выбор канала</title>
    <style>
    body { margin:0; background:#0f0f0f; color:white; font-family:sans-serif;
           display:flex; justify-content:center; align-items:center; height:100vh; flex-direction:column; gap:30px; }
    .box { display:flex; gap:30px; }
    .channel-card { position:relative; width:300px; height:200px; border-radius:20px;
                    overflow:hidden; cursor:pointer; transition:0.2s; box-shadow:0 4px 15px rgba(0,0,0,0.5); }
    .channel-card:hover { transform:scale(1.05); box-shadow:0 6px 25px rgba(0,0,0,0.7); }
    .channel-card img { width:100%; height:100%; object-fit:cover; filter:brightness(0.5); transition:0.2s; }
    .channel-card:hover img { filter:brightness(0.7); }
    .channel-overlay { position:absolute; bottom:0; left:0; right:0;
                       background:linear-gradient(to top,rgba(0,0,0,0.9),transparent);
                       padding:20px; font-size:24px; font-weight:bold;
                       text-align:center; text-shadow:2px 2px 4px rgba(0,0,0,0.8); }
    .forzik .channel-overlay { color:#9146ff; }
    .mixarage .channel-overlay { color:#ff4d4d; }
    .auth-bar { font-size:14px; color:#aaa; display:flex; gap:12px; align-items:center; }
    .btn { padding:8px 16px; border-radius:8px; border:none; cursor:pointer; font-size:14px; }
    .btn-twitch { background:#9146ff; color:white; }
    .btn-logout { background:#333; color:white; }
    </style></head><body>
    <div class="auth-bar" id="authBar">Загрузка...</div>
    <div class="box">
        <div class="channel-card forzik" onclick="location.href='/watch/forzikxd'">
            <img src="https://media.giphy.com/media/3o7btPCcdNniyf0ArS/giphy.gif">
            <div class="channel-overlay">forzikxd</div>
        </div>
        <div class="channel-card mixarage" onclick="location.href='/watch/mixarage'">
            <img src="https://media.giphy.com/media/26xBI73gWquCBBCDe/giphy.gif">
            <div class="channel-overlay">mixarage</div>
        </div>
    </div>
    <script>
    fetch('/auth/me').then(r=>r.json()).then(data => {
        const bar = document.getElementById('authBar');
        if (data.username) {
            bar.innerHTML = `Вошёл как <b style="color:#9146ff">${data.display_name}</b>
                <button class="btn btn-logout" onclick="location.href='/auth/logout'">Выйти</button>`;
        } else {
            bar.innerHTML = `<button class="btn btn-twitch" onclick="location.href='/auth/login'">Войти через Twitch</button>`;
        }
    });
    </script>
    </body></html>
    """


@app.route("/watch/<channel>")
def watch(channel):
    return f"""
    <html><head><title>{channel}</title>
    <style>
    * {{ box-sizing: border-box; margin:0; padding:0; }}
    body {{ background:#000; display:flex; height:100vh; overflow:hidden; font-family:sans-serif; color:white; }}
    .player {{ flex:3; min-height:100vh; }}
    .player iframe {{ width:100%; height:100%; border:none; display:block; }}
    .chat {{ flex:1; display:flex; flex-direction:column; background:#18181b; min-width:300px; max-width:340px; position:relative; }}
    .chat-header {{ padding:10px 12px; background:#0e0e10; border-bottom:1px solid #222;
                    display:flex; justify-content:space-between; align-items:center; font-size:13px; flex-shrink:0; }}
    .viewer-count {{ color:#9146ff; font-weight:bold; }}
    .connection-status {{ font-size:12px; }}
    .chat-messages {{ flex:1; overflow-y:auto; padding:8px 10px; font-size:13px; }}
    .message {{ margin-bottom:5px; line-height:1.7; word-break:break-word; color:#fff; }}
    .username {{ font-weight:bold; margin-right:3px; cursor:pointer; }}
    .badges {{ display:inline-flex; gap:3px; margin-right:4px; vertical-align:middle; }}
    .badge {{ width:18px; height:18px; vertical-align:middle; }}

    /* Эмоут в чате */
    .emote-wrap {{ display:inline-block; position:relative; vertical-align:middle; }}
    .emote {{ height:28px; vertical-align:middle; margin:0 1px; cursor:pointer; }}

    /* Превью эмоута при hover */
    .emote-tooltip {{
        display:none;
        position:fixed;
        z-index:9999;
        background:#18181b;
        border:1px solid #444;
        border-radius:10px;
        padding:12px 16px;
        text-align:center;
        pointer-events:none;
        box-shadow:0 4px 20px rgba(0,0,0,0.7);
        min-width:120px;
    }}
    .emote-tooltip img {{ width:64px; height:64px; object-fit:contain; display:block; margin:0 auto 8px; }}
    .emote-tooltip .tip-name {{ font-weight:bold; font-size:14px; color:#fff; }}
    .emote-tooltip .tip-source {{ font-size:11px; color:#888; margin-top:3px; }}

    /* Инпут */
    .chat-input-area {{ padding:8px 10px; background:#0e0e10; border-top:1px solid #222; flex-shrink:0; }}
    .chat-input-row {{ display:flex; gap:6px; align-items:center; }}
    .emote-picker-btn {{
        background:#2a2a2d; border:1px solid #444; border-radius:6px;
        width:34px; height:34px; cursor:pointer; font-size:18px;
        display:flex; align-items:center; justify-content:center;
        flex-shrink:0; transition:background 0.15s;
    }}
    .emote-picker-btn:hover {{ background:#3a3a3d; }}
    .chat-input {{ flex:1; background:#2a2a2d; border:1px solid #444; border-radius:6px;
                   padding:8px 10px; color:white; font-size:13px; outline:none; height:34px; }}
    .chat-input:focus {{ border-color:#9146ff; }}
    .send-btn {{ background:#9146ff; color:white; border:none; border-radius:6px;
                 width:34px; height:34px; cursor:pointer; font-size:14px; flex-shrink:0; }}
    .send-btn:hover {{ background:#7d2fe0; }}
    .send-btn:disabled {{ background:#555; cursor:default; }}
    .login-hint {{ font-size:11px; color:#666; text-align:center; margin-top:6px; }}
    .login-hint a {{ color:#9146ff; text-decoration:none; }}

    /* Пикер эмоутов */
    .emote-picker {{
        display:none;
        position:absolute;
        bottom:58px;
        left:8px;
        right:8px;
        background:#18181b;
        border:1px solid #333;
        border-radius:12px;
        z-index:1000;
        box-shadow:0 -4px 24px rgba(0,0,0,0.6);
        flex-direction:column;
        max-height:320px;
    }}
    .emote-picker.open {{ display:flex; }}
    .picker-tabs {{ display:flex; border-bottom:1px solid #333; flex-shrink:0; }}
    .picker-tab {{
        flex:1; padding:8px; text-align:center; cursor:pointer;
        font-size:12px; color:#888; border-bottom:2px solid transparent;
        transition:0.15s;
    }}
    .picker-tab.active {{ color:#fff; border-bottom-color:#9146ff; }}
    .picker-search {{
        margin:8px; background:#111; border:1px solid #333; border-radius:6px;
        padding:6px 10px; color:white; font-size:12px; outline:none; flex-shrink:0;
    }}
    .picker-search:focus {{ border-color:#9146ff; }}
    .picker-grid {{
        display:grid;
        grid-template-columns: repeat(7, 1fr);
        gap:2px;
        padding:4px 8px 8px;
        overflow-y:auto;
        flex:1;
    }}
    .picker-emote {{
        width:100%; aspect-ratio:1; display:flex; align-items:center;
        justify-content:center; cursor:pointer; border-radius:6px;
        padding:3px; transition:background 0.1s; position:relative;
    }}
    .picker-emote:hover {{ background:#2a2a2d; }}
    .picker-emote img {{ max-width:100%; max-height:36px; object-fit:contain; }}
    .picker-empty {{ padding:20px; text-align:center; color:#555; font-size:13px; }}

    .back {{ position:fixed; top:12px; left:12px; padding:7px 13px;
             background:rgba(15,15,15,0.9); color:white; border:1px solid #333;
             border-radius:10px; cursor:pointer; z-index:9999; font-size:13px; }}
    .back:hover {{ background:rgba(40,40,40,0.95); }}
    ::-webkit-scrollbar {{ width:5px; }}
    ::-webkit-scrollbar-track {{ background:#18181b; }}
    ::-webkit-scrollbar-thumb {{ background:#444; border-radius:3px; }}
    </style></head><body>

    <div class="emote-tooltip" id="emoteTip">
        <img id="tipImg" src="">
        <div class="tip-name" id="tipName"></div>
        <div class="tip-source" id="tipSource"></div>
    </div>

    <button class="back" onclick="location.href='/'">← Назад</button>

    <div class="player">
        <iframe src="https://player.twitch.tv/?channel={channel}&parent=localhost&parent=127.0.0.1" allowfullscreen></iframe>
    </div>

    <div class="chat">
        <div class="chat-header">
            <span class="connection-status" id="status" style="color:#aaa">Подключение...</span>
            <span class="viewer-count" id="viewers">👁️ -</span>
        </div>
        <div class="chat-messages" id="messages"></div>

        <!-- Пикер эмоутов -->
        <div class="emote-picker" id="emotePicker">
            <div class="picker-tabs">
                <div class="picker-tab active" onclick="switchTab('7tv')" id="tab7tv">7TV</div>
                <div class="picker-tab" onclick="switchTab('bttv')" id="tabBttv">BTTV</div>
                <div class="picker-tab" onclick="switchTab('ffz')" id="tabFfz">FFZ</div>
                <div class="picker-tab" onclick="switchTab('twitch')" id="tabTwitch">Twitch</div>
            </div>
            <input class="picker-search" id="pickerSearch" placeholder="Поиск эмоута..." oninput="filterEmotes()">
            <div class="picker-grid" id="pickerGrid"></div>
        </div>

        <div class="chat-input-area">
            <div class="chat-input-row">
                <button class="emote-picker-btn" id="pickerBtn" onclick="togglePicker()" title="Эмоуты">🙂</button>
                <input class="chat-input" id="chatInput" placeholder="Войдите чтобы писать..." disabled>
                <button class="send-btn" id="sendBtn" disabled onclick="sendMessage()">➤</button>
            </div>
            <div class="login-hint" id="loginHint">
                <a href="/auth/login" onclick="saveRedirect()">Войти через Twitch</a> чтобы писать в чат
            </div>
        </div>
    </div>

    <script>
    const channel = '{channel}';
    const messagesDiv = document.getElementById('messages');
    const statusDiv = document.getElementById('status');
    const chatInput = document.getElementById('chatInput');
    const sendBtn = document.getElementById('sendBtn');
    const loginHint = document.getElementById('loginHint');
    const emotePicker = document.getElementById('emotePicker');
    const pickerGrid = document.getElementById('pickerGrid');
    const pickerSearch = document.getElementById('pickerSearch');
    const emoteTip = document.getElementById('emoteTip');

    let sevenTVEmotes = {{}};
    let bttvEmotes = {{}};
    let ffzEmotes = {{}};
    let twitchEmotes = {{}};
    let currentTab = '7tv';
    let pickerOpen = false;

    function saveRedirect() {{
        sessionStorage.setItem('redirect_after_login', window.location.href);
    }}

    function escapeHtml(t) {{
        const d = document.createElement('div');
        d.textContent = t;
        return d.innerHTML;
    }}

    const BADGE_URLS = {{
        broadcaster: 'https://static-cdn.jtvnw.net/badges/v1/5527c58c-fb7d-422d-b71b-f309dcb85cc1/2',
        moderator:   'https://static-cdn.jtvnw.net/badges/v1/3267646d-33f0-4b17-b3df-f923a41db1d0/2',
        vip:         'https://static-cdn.jtvnw.net/badges/v1/b817aba4-fad8-49e2-b88a-7cc744dfa6ec/2',
        subscriber:  'https://static-cdn.jtvnw.net/badges/v1/5d9f2208-5dd8-11e7-8513-2ff4adfae661/2',
        premium:     'https://static-cdn.jtvnw.net/badges/v1/bbbe0db0-a598-423e-86d0-f9fb98ca1933/2',
        staff:       'https://static-cdn.jtvnw.net/badges/v1/d97c37be-f9f7-4cc5-a6c4-ddbebece3188/2',
    }};

    function renderBadges(badgesRaw) {{
        if (!badgesRaw) return '';
        let html = '<span class="badges">';
        badgesRaw.split(',').forEach(b => {{
            const name = b.split('/')[0];
            if (BADGE_URLS[name]) html += `<img class="badge" src="${{BADGE_URLS[name]}}" title="${{name}}">`;
        }});
        return html + '</span>';
    }}

    // Эмоут с hover превью
    function emoteHtml(src, name, source) {{
        const s = encodeURIComponent(source);
        const n = encodeURIComponent(name);
        return `<span class="emote-wrap"
            onmouseenter="showTip(event,'${{src}}','${{n}}','${{s}}')"
            onmouseleave="hideTip()">
            <img class="emote" src="${{src}}" alt="${{name}}" title="${{name}}">
        </span>`;
    }}

    function showTip(e, src, name, source) {{
        const tip = emoteTip;
        document.getElementById('tipImg').src = src;
        document.getElementById('tipName').textContent = decodeURIComponent(name);
        document.getElementById('tipSource').textContent = decodeURIComponent(source);
        tip.style.display = 'block';
        positionTip(e);
    }}

    function positionTip(e) {{
        const tip = emoteTip;
        const x = e.clientX;
        const y = e.clientY;
        const tw = tip.offsetWidth || 140;
        const th = tip.offsetHeight || 110;
        const vw = window.innerWidth;
        const vh = window.innerHeight;
        let left = x + 12;
        let top = y - th - 12;
        if (left + tw > vw) left = x - tw - 12;
        if (top < 8) top = y + 12;
        tip.style.left = left + 'px';
        tip.style.top = top + 'px';
    }}

    function hideTip() {{
        emoteTip.style.display = 'none';
    }}

    function renderMessage(text, emotesRaw) {{
        if (emotesRaw) {{
            const positions = [];
            emotesRaw.split('/').forEach(part => {{
                const [id, ranges] = part.split(':');
                if (!ranges) return;
                ranges.split(',').forEach(range => {{
                    const [s, e] = range.split('-').map(Number);
                    positions.push({{ s, e, id }});
                }});
            }});
            positions.sort((a,b) => a.s - b.s);
            let html = '', last = 0;
            positions.forEach(p => {{
                html += escapeHtml(text.slice(last, p.s));
                const name = text.slice(p.s, p.e+1);
                const src = `https://static-cdn.jtvnw.net/emoticons/v2/${{p.id}}/default/dark/2.0`;
                html += emoteHtml(src, name, 'Twitch');
                last = p.e + 1;
            }});
            html += escapeHtml(text.slice(last));
            return html;
        }}
        return text.split(' ').map(word => {{
            if (sevenTVEmotes[word]) return emoteHtml(sevenTVEmotes[word], word, '7TV');
            if (bttvEmotes[word])   return emoteHtml(bttvEmotes[word], word, 'BTTV');
            if (ffzEmotes[word])    return emoteHtml(ffzEmotes[word], word, 'FFZ');
            return escapeHtml(word);
        }}).join(' ');
    }}

    // ── Пикер ────────────────────────────────────────────────────────────────

    function togglePicker() {{
        pickerOpen = !pickerOpen;
        emotePicker.classList.toggle('open', pickerOpen);
        if (pickerOpen) {{
            pickerSearch.value = '';
            renderPickerGrid();
            pickerSearch.focus();
        }}
    }}

    function switchTab(tab) {{
        currentTab = tab;
        ['7tv','bttv','ffz','twitch'].forEach(t => {{
            document.getElementById('tab' + t.charAt(0).toUpperCase() + t.slice(1)).classList.toggle('active', t === tab);
        }});
        pickerSearch.value = '';
        renderPickerGrid();
    }}

    function getTabEmotes() {{
        if (currentTab === '7tv')    return sevenTVEmotes;
        if (currentTab === 'bttv')   return bttvEmotes;
        if (currentTab === 'ffz')    return ffzEmotes;
        if (currentTab === 'twitch') return twitchEmotes;
        return {{}};
    }}

    function filterEmotes() {{
        renderPickerGrid();
    }}

    function renderPickerGrid() {{
        const emotes = getTabEmotes();
        const q = pickerSearch.value.toLowerCase();
        const keys = Object.keys(emotes).filter(k => !q || k.toLowerCase().includes(q));
        if (keys.length === 0) {{
            pickerGrid.innerHTML = '<div class="picker-empty">Эмоуты не найдены</div>';
            return;
        }}
        pickerGrid.innerHTML = keys.slice(0, 200).map(name => {{
            const src = emotes[name];
            return `<div class="picker-emote" title="${{escapeHtml(name)}}" onclick="insertEmote('${{escapeHtml(name)}}')">
                <img src="${{src}}" alt="${{escapeHtml(name)}}" loading="lazy">
            </div>`;
        }}).join('');
    }}

    function insertEmote(name) {{
        const inp = chatInput;
        const pos = inp.selectionStart;
        const val = inp.value;
        const before = val.slice(0, pos).replace(/\\S+$/, '');
        const after = val.slice(pos).replace(/^\\S+/, '');
        inp.value = before + name + ' ' + after;
        inp.focus();
        const newPos = before.length + name.length + 1;
        inp.setSelectionRange(newPos, newPos);
    }}

    // Закрыть пикер при клике вне
    document.addEventListener('click', e => {{
        if (pickerOpen && !emotePicker.contains(e.target) && e.target.id !== 'pickerBtn') {{
            pickerOpen = false;
            emotePicker.classList.remove('open');
        }}
    }});

    // ── Загрузка эмоутов ─────────────────────────────────────────────────────

    async function loadExternalEmotes() {{
        try {{
            const r = await fetch(`https://decapi.me/twitch/id/${{channel}}`);
            const userId = (await r.text()).trim();
            if (!userId || userId.includes(' ')) return;

            fetch(`https://7tv.io/v3/users/twitch/${{userId}}`).then(r=>r.json()).then(d => {{
                if (d.emote_set && d.emote_set.emotes)
                    d.emote_set.emotes.forEach(e => sevenTVEmotes[e.name] = `https://cdn.7tv.app/emote/${{e.id}}/2x.webp`);
                if (currentTab === '7tv' && pickerOpen) renderPickerGrid();
            }}).catch(()=>{{}});

            fetch(`https://api.betterttv.net/3/cached/users/twitch/${{userId}}`).then(r=>r.json()).then(d => {{
                [...(d.channelEmotes||[]), ...(d.sharedEmotes||[])].forEach(e =>
                    bttvEmotes[e.code] = `https://cdn.betterttv.net/emote/${{e.id}}/2x`);
            }}).catch(()=>{{}});

            fetch(`https://api.frankerfacez.com/v1/room/${{channel}}`).then(r=>r.json()).then(d => {{
                if (d.sets) Object.values(d.sets).forEach(set =>
                    set.emoticons.forEach(e => ffzEmotes[e.name] = e.urls['2']||e.urls['1']));
            }}).catch(()=>{{}});
        }} catch(e) {{}}
    }}

    // ── SSE ───────────────────────────────────────────────────────────────────

    const es = new EventSource('/chat/' + channel);
    es.onopen = () => {{
        statusDiv.textContent = '✓ Подключено';
        statusDiv.style.color = '#00ff00';
    }};
    es.onmessage = (e) => {{
        const data = JSON.parse(e.data);
        if (!data.username || data.ping) return;
        const el = document.createElement('div');
        el.className = 'message';
        el.innerHTML =
            renderBadges(data.badges) +
            `<span class="username" style="color:${{data.color}}">${{escapeHtml(data.username)}}</span>: ` +
            renderMessage(data.message, data.emotes);
        messagesDiv.appendChild(el);
        messagesDiv.scrollTop = messagesDiv.scrollHeight;
        if (messagesDiv.children.length > 150)
            messagesDiv.removeChild(messagesDiv.firstChild);
    }};
    es.onerror = () => {{
        statusDiv.textContent = '✗ Ошибка';
        statusDiv.style.color = '#ff0000';
    }};

    // ── Отправка ─────────────────────────────────────────────────────────────

    async function sendMessage() {{
        const msg = chatInput.value.trim();
        if (!msg) return;
        chatInput.value = '';
        await fetch('/send/' + channel, {{
            method: 'POST',
            headers: {{'Content-Type': 'application/json'}},
            body: JSON.stringify({{message: msg}})
        }});
    }}

    chatInput.addEventListener('keydown', e => {{
        if (e.key === 'Enter') sendMessage();
        if (e.key === 'Escape' && pickerOpen) togglePicker();
    }});

    // ── Auth ─────────────────────────────────────────────────────────────────

    fetch('/auth/me').then(r=>r.json()).then(data => {{
        if (data.username) {{
            chatInput.disabled = false;
            chatInput.placeholder = 'Написать в чат...';
            sendBtn.disabled = false;
            loginHint.style.display = 'none';
        }}
    }});

    // ── Зрители ──────────────────────────────────────────────────────────────

    async function updateViewerCount() {{
        try {{
            const r = await fetch(`https://decapi.me/twitch/viewercount/${{channel}}`);
            const t = await r.text();
            document.getElementById('viewers').textContent =
                t && !t.includes('offline') ? '👁️ ' + parseInt(t).toLocaleString() : '👁️ Офлайн';
        }} catch {{}}
    }}

    loadExternalEmotes();
    updateViewerCount();
    setInterval(updateViewerCount, 30000);
    </script>
    </body></html>
    """


if __name__ == "__main__":
    app.run(host='localhost', port=3000, debug=True)