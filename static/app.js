// VYXBOT v4.0 — Client-side logic
const socket = io();

// ─── DOM refs ───
const platformEl          = document.getElementById('platform');
const channelSelect       = document.getElementById('channelSelect');
const loadChannelsBtn     = document.getElementById('loadChannelsBtn');
const dcFields            = document.getElementById('dcFields');
const tgFields            = document.getElementById('tgFields');
const discordToken        = document.getElementById('discordToken');
const apiId               = document.getElementById('apiId');
const apiHash             = document.getElementById('apiHash');
const sessionString       = document.getElementById('sessionString');
const connectBtn          = document.getElementById('connectBtn');
const statusDot           = document.getElementById('statusDot');
const statusText          = document.getElementById('statusText');
const connectedUser       = document.getElementById('connectedUser');
const spamToggle          = document.getElementById('spamToggle');
const spamState           = document.getElementById('spamState');
const spamConfig          = document.getElementById('spamConfig');
const messageInput        = document.getElementById('messageInput');
const imageInput          = document.getElementById('imageInput');
const intervalInput       = document.getElementById('intervalInput');
const startBtn            = document.getElementById('startBtn');
const stopBtn             = document.getElementById('stopBtn');
const autoReplyToggle     = document.getElementById('autoReplyToggle');
const autoReplyState      = document.getElementById('autoReplyState');
const autoReplyConfig     = document.getElementById('autoReplyConfig');
const autoReplyMessage    = document.getElementById('autoReplyMessage');
const autoReplySaveBtn    = document.getElementById('autoReplySaveBtn');
const logoutBtn           = document.getElementById('logoutBtn');
const logBox              = document.getElementById('logBox');

let connected  = false;
let isRunning  = false;
let isAutoReply = false;
let uploadedImagePath = null;

// ─── localStorage keys ───
const LS_PLATFORM     = 'vyxbot_platform';
const LS_DC_TOKEN     = 'vyxbot_dc_token';
const LS_API_ID       = 'vyxbot_api_id';
const LS_API_HASH     = 'vyxbot_api_hash';
const LS_SESSION      = 'vyxbot_session';
const LS_CHANNEL_OPTIONS = 'vyxbot_channels';
const LS_AUTO_REPLY_MSG  = 'vyxbot_auto_reply_msg';

// ─── On page load: restore saved session ───
window.addEventListener('DOMContentLoaded', async () => {
    // Restore auto-reply message
    const savedAutoReply = localStorage.getItem(LS_AUTO_REPLY_MSG);
    if (savedAutoReply) autoReplyMessage.value = savedAutoReply;

    // Restore platform
    const savedPlatform = localStorage.getItem(LS_PLATFORM);
    if (savedPlatform) {
        platformEl.value = savedPlatform;
        platformEl.dispatchEvent(new Event('change'));
    }

    // Restore credentials
    if (localStorage.getItem(LS_DC_TOKEN)) discordToken.value = localStorage.getItem(LS_DC_TOKEN);
    if (localStorage.getItem(LS_API_ID)) apiId.value = localStorage.getItem(LS_API_ID);
    if (localStorage.getItem(LS_API_HASH)) apiHash.value = localStorage.getItem(LS_API_HASH);
    if (localStorage.getItem(LS_SESSION)) sessionString.value = localStorage.getItem(LS_SESSION);

    // Restore saved channel list
    const savedChannels = localStorage.getItem(LS_CHANNEL_OPTIONS);
    if (savedChannels) {
        try {
            const channels = JSON.parse(savedChannels);
            channelSelect.innerHTML = '<option value="">-- Select channel --</option>';
            channels.forEach(ch => {
                const opt = document.createElement('option');
                opt.value = ch.id;
                opt.textContent = ch.title || ch.name;
                channelSelect.appendChild(opt);
            });
            channelSelect.disabled = false;
        } catch (e) {}
    }

    // Restore saved auto-reply message
    const savedArMsg = localStorage.getItem(LS_AUTO_REPLY_MSG);
    if (savedArMsg) autoReplyMessage.value = savedArMsg;

    // Check if backend still has session
    try {
        const res = await fetch('/api/session');
        const data = await res.json();
        if (data.connected) {
            setConnected(true, data.platform);
            addLog(`Session restored — ${data.platform}`);
            if (savedChannels) loadChannelsBtn.disabled = false;
            if (!savedChannels) autoLoadChannels();
        }
    } catch (e) {
        // Backend not available — that's fine
    }
});

// ─── Platform switch ───
platformEl.addEventListener('change', () => {
    const p = platformEl.value;
    dcFields.classList.toggle('active', p === 'discord');
    tgFields.classList.toggle('active', p === 'telegram');
    if (!connected) connectBtn.disabled = !p;
    if (!p && !connected) setConnected(false);
});

// ─── Connect ───
connectBtn.addEventListener('click', async () => {
    if (connected) return;
    const p = platformEl.value;
    if (!p) return;

    const payload = { platform: p };

    if (p === 'discord') {
        if (!discordToken.value.trim()) { addLog('ERROR: Discord token is required'); return; }
        payload.discord_token = discordToken.value.trim();
    } else {
        if (!apiId.value.trim() || !apiHash.value.trim() || !sessionString.value.trim()) {
            addLog('ERROR: All Telegram fields required'); return;
        }
        payload.telegram_api_id = parseInt(apiId.value.trim());
        payload.telegram_api_hash = apiHash.value.trim();
        payload.telegram_session = sessionString.value.trim();
    }

    connectBtn.disabled = true;
    statusText.textContent = 'Testing connection...';

    try {
        const res = await fetch('/api/connect', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        const data = await res.json();

        if (data.status === 'ok') {
            setConnected(true, p, data.user || p);
            addLog(`Connected — ${data.user || p}`);

            // Save to localStorage
            localStorage.setItem(LS_PLATFORM, p);
            if (p === 'discord') {
                localStorage.setItem(LS_DC_TOKEN, payload.discord_token);
            } else {
                localStorage.setItem(LS_API_ID, payload.telegram_api_id.toString());
                localStorage.setItem(LS_API_HASH, payload.telegram_api_hash);
                localStorage.setItem(LS_SESSION, payload.telegram_session);
            }

            // Auto-load channels after short delay
            setTimeout(() => autoLoadChannels(), 500);
        } else {
            setConnected(false);
            addLog(`ERROR: ${data.msg}`);
            statusText.textContent = 'Connect failed — try again';
            connectBtn.disabled = false;
        }
    } catch (e) {
        setConnected(false);
        addLog(`ERROR: ${e.message}`);
        statusText.textContent = 'Connect';
        connectBtn.disabled = false;
    }
});

// ─── Logout ───
logoutBtn.addEventListener('click', async () => {
    // Stop spam
    if (isRunning) {
        await fetch('/api/stop', { method: 'POST' });
        isRunning = false;
    }
    // Stop auto-reply
    if (isAutoReply) {
        await fetch('/api/auto-reply/stop', { method: 'POST' });
        isAutoReply = false;
    }

    await fetch('/api/disconnect', { method: 'POST' });

    // Clear all localStorage
    [LS_PLATFORM, LS_DC_TOKEN, LS_API_ID, LS_API_HASH, LS_SESSION, LS_CHANNEL_OPTIONS].forEach(k => localStorage.removeItem(k));

    // Reset UI
    setConnected(false);
    platformEl.value = '';
    discordToken.value = '';
    apiId.value = '';
    apiHash.value = '';
    sessionString.value = '';
    channelSelect.innerHTML = '<option value="">-- Load channels first --</option>';
    channelSelect.disabled = true;
    spamToggle.classList.remove('active');
    spamState.textContent = 'OFF';
    spamConfig.classList.add('hidden');
    startBtn.disabled = true;
    stopBtn.disabled = true;
    autoReplyToggle.classList.remove('active');
    autoReplyState.textContent = 'OFF';
    autoReplyConfig.classList.add('hidden');
    autoReplySaveBtn.disabled = true;
    connectedUser.classList.add('hidden');

    addLog('Logged out — all credentials cleared');
});

// ─── Auto-load channels ───
async function autoLoadChannels() {
    const p = platformEl.value;
    if (!p) return;

    loadChannelsBtn.disabled = true;
    loadChannelsBtn.textContent = 'Loading...';

    try {
        let payload;
        if (p === 'telegram') {
            if (!apiId.value.trim() || !apiHash.value.trim() || !sessionString.value.trim()) {
                addLog('ERROR: Missing Telegram credentials'); return;
            }
            payload = { api_id: parseInt(apiId.value.trim()), api_hash: apiHash.value.trim(), session: sessionString.value.trim() };
        } else {
            if (!discordToken.value.trim()) { addLog('ERROR: Missing Discord token'); return; }
            payload = { token: discordToken.value.trim() };
        }

        const res = await fetch(`/api/channels/${p}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        const data = await res.json();

        channelSelect.innerHTML = '<option value="">-- Select channel --</option>';
        if (data.channels && data.channels.length > 0) {
            data.channels.forEach(ch => {
                const opt = document.createElement('option');
                opt.value = ch.id;
                opt.textContent = ch.title || ch.name;
                channelSelect.appendChild(opt);
            });
            channelSelect.disabled = false;
            addLog(`Loaded ${data.channels.length} channels`);
            localStorage.setItem(LS_CHANNEL_OPTIONS, JSON.stringify(data.channels));
        } else if (data.channels && data.channels.length === 0) {
            addLog('No channels/groups found in your account');
            channelSelect.disabled = true;
        } else if (data.error) {
            addLog(`ERROR loading channels: ${data.error}`);
        }
    } catch (e) {
        addLog(`ERROR: ${e.message}`);
    } finally {
        loadChannelsBtn.disabled = false;
        loadChannelsBtn.textContent = 'Load Channels';
    }
}

// ─── Manual Load Channels ───
loadChannelsBtn.addEventListener('click', autoLoadChannels);

// ─── Spam Toggle ───
spamToggle.addEventListener('click', () => {
    spamToggle.classList.toggle('active');
    const on = spamToggle.classList.contains('active');
    spamState.textContent = on ? 'ON' : 'OFF';
    spamConfig.classList.toggle('hidden', !on);
    updateStartBtn();
});

channelSelect.addEventListener('change', updateStartBtn);

function updateStartBtn() {
    const on = spamToggle.classList.contains('active');
    startBtn.disabled = !on || !connected || !channelSelect.value || isRunning;
}

// ─── Image upload ───
imageInput.addEventListener('change', async () => {
    const file = imageInput.files[0];
    if (!file) return;
    const formData = new FormData();
    formData.append('image', file);
    try {
        const res = await fetch('/api/upload', { method: 'POST', body: formData });
        const data = await res.json();
        if (data.path) { uploadedImagePath = data.path; addLog('Image uploaded'); }
    } catch (e) { addLog(`ERROR: Upload failed — ${e.message}`); }
});

// ─── Start ───
startBtn.addEventListener('click', async () => {
    if (isRunning) return;
    const payload = {
        channel_id: channelSelect.value,
        message: messageInput.value.trim(),
        interval: parseInt(intervalInput.value) || 5,
        image_path: uploadedImagePath,
    };
    try {
        const res = await fetch('/api/start', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        const data = await res.json();
        if (data.status === 'ok') {
            isRunning = true;
            startBtn.disabled = true;
            stopBtn.disabled = false;
            addLog('▶ Started spamming');
        } else { addLog(`ERROR: ${data.msg}`); }
    } catch (e) { addLog(`ERROR: ${e.message}`); }
});

// ─── Stop ───
stopBtn.addEventListener('click', async () => {
    try {
        const res = await fetch('/api/stop', { method: 'POST' });
        const data = await res.json();
        if (data.status === 'ok') {
            isRunning = false;
            startBtn.disabled = false;
            stopBtn.disabled = true;
            updateStartBtn();
            addLog('■ Stopped');
        }
    } catch (e) { addLog(`ERROR: ${e.message}`); }
});

// ─── Auto-Reply Toggle ───
autoReplyToggle.addEventListener('click', () => {
    if (!connected || platformEl.value !== 'telegram') return;
    autoReplyToggle.classList.toggle('active');
    const on = autoReplyToggle.classList.contains('active');
    autoReplyState.textContent = on ? 'ON' : 'OFF';
    autoReplyConfig.classList.toggle('hidden', !on);
    autoReplySaveBtn.disabled = !on || !autoReplyMessage.value.trim();
});

autoReplyMessage.addEventListener('input', () => {
    if (autoReplyToggle.classList.contains('active')) {
        autoReplySaveBtn.disabled = !autoReplyMessage.value.trim();
    }
});

// ─── Save & Enable Auto-Reply ───
autoReplySaveBtn.addEventListener('click', async () => {
    const msg = autoReplyMessage.value.trim();
    if (!msg) { addLog('ERROR: Auto-reply message is empty'); return; }

    autoReplySaveBtn.disabled = true;
    autoReplySaveBtn.textContent = 'Enabling...';

    try {
        const res = await fetch('/api/auto-reply/start', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: msg }),
        });
        const data = await res.json();
        if (data.status === 'ok') {
            isAutoReply = true;
            localStorage.setItem(LS_AUTO_REPLY_MSG, msg);
            addLog(`Auto-reply enabled: "${msg.substring(0, 40)}..."`);
        } else {
            addLog(`ERROR: ${data.msg}`);
        }
    } catch (e) { addLog(`ERROR: ${e.message}`); }
    finally {
        autoReplySaveBtn.disabled = false;
        autoReplySaveBtn.textContent = 'Save & Enable Auto-Reply';
    }
});

// ─── WebSocket log ───
socket.on('log', (data) => { addLog(data.msg, data.time); });

// ─── Set connected state ───
function setConnected(state, platform, user) {
    connected = state;
    statusDot.className = 'status-indicator ' + (state ? 'online' : 'offline');
    statusText.textContent = state ? 'Connected' : 'Connect';
    loadChannelsBtn.disabled = !state;
    logoutBtn.classList.toggle('hidden', !state);

    if (state && user) {
        connectedUser.textContent = `Logged in as ${user}`;
        connectedUser.classList.remove('hidden');
    } else {
        connectedUser.classList.add('hidden');
    }

    if (!state) {
        channelSelect.disabled = true;
        autoReplyToggle.classList.remove('active');
        autoReplyState.textContent = 'OFF';
        autoReplyConfig.classList.add('hidden');
        autoReplySaveBtn.disabled = true;
        platformEl.disabled = false;
    } else {
        platformEl.disabled = true;
    }

    updateStartBtn();
}

// ─── Add log entry ───
function addLog(msg, time) {
    const t = time || new Date().toLocaleTimeString('en-US', { hour12: false });
    const entry = document.createElement('div');
    entry.className = 'log-entry';
    if (msg.startsWith('ERROR')) entry.classList.add('error');
    if (msg.startsWith('Connected') || msg.startsWith('Auto-reply enabled')) entry.classList.add('success');
    entry.innerHTML = `<span class="time">[${t}]</span> ${msg}`;
    logBox.appendChild(entry);
    logBox.scrollTop = logBox.scrollHeight;
            }
