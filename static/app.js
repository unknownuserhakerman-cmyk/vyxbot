const socket = io();

const loginPanel          = document.getElementById('loginPanel');
const dashboard           = document.getElementById('dashboard');
const platformEl          = document.getElementById('platform');
const dcFields            = document.getElementById('dcFields');
const tgFields            = document.getElementById('tgFields');
const discordToken        = document.getElementById('discordToken');
const apiId               = document.getElementById('apiId');
const apiHash             = document.getElementById('apiHash');
const sessionString       = document.getElementById('sessionString');
const connectBtn          = document.getElementById('connectBtn');
const statusDot           = document.getElementById('statusDot');
const statusText          = document.getElementById('statusText');
const channelSelect       = document.getElementById('channelSelect');
const loadChannelsBtn     = document.getElementById('loadChannelsBtn');
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
const avatarImg           = document.getElementById('avatarImg');
const avatarInitials      = document.getElementById('avatarInitials');
const displayName         = document.getElementById('displayName');
const displayUsername     = document.getElementById('displayUsername');
const platformBadge       = document.getElementById('platformBadge');
const logBox              = document.getElementById('logBox');

let connected   = false;
let isRunning   = false;
let isAutoReply = false;
let uploadedImagePath = null;

const LS_PLATFORM     = 'vyxbot_platform';
const LS_DC_TOKEN     = 'vyxbot_dc_token';
const LS_API_ID       = 'vyxbot_api_id';
const LS_API_HASH     = 'vyxbot_api_hash';
const LS_SESSION      = 'vyxbot_session';
const LS_CHANNELS     = 'vyxbot_channels';
const LS_AUTO_REPLY   = 'vyxbot_auto_reply_msg';

// ─── On load: check session and auto-reconnect ───
window.addEventListener('DOMContentLoaded', async () => {
  const savedArMsg = localStorage.getItem(LS_AUTO_REPLY);
  if (savedArMsg) autoReplyMessage.value = savedArMsg;

  const savedPlatform = localStorage.getItem(LS_PLATFORM);
  if (savedPlatform) {
    platformEl.value = savedPlatform;
    platformEl.dispatchEvent(new Event('change'));
  }
  if (localStorage.getItem(LS_DC_TOKEN)) discordToken.value = localStorage.getItem(LS_DC_TOKEN);
  if (localStorage.getItem(LS_API_ID)) apiId.value = localStorage.getItem(LS_API_ID);
  if (localStorage.getItem(LS_API_HASH)) apiHash.value = localStorage.getItem(LS_API_HASH);
  if (localStorage.getItem(LS_SESSION)) sessionString.value = localStorage.getItem(LS_SESSION);

  // Restore cached channels
  const savedChannels = localStorage.getItem(LS_CHANNELS);
  if (savedChannels) {
    try {
      const chs = JSON.parse(savedChannels);
      channelSelect.innerHTML = '<option value="">— Select channel —</option>';
      chs.forEach(function(ch) {
        var opt = document.createElement('option');
        opt.value = ch.id;
        opt.textContent = ch.title || ch.name;
        channelSelect.appendChild(opt);
      });
      channelSelect.disabled = false;
    } catch(e) {}
  }

  // Check with server
  try {
    var res = await fetch('/api/session');
    var data = await res.json();
    if (data.connected) {
      // Server remembers us — show dashboard immediately
      showDashboard(data);
      if (savedChannels && savedChannels.length > 0) {
        loadChannelsBtn.disabled = false;
      }
      // Auto-load channels if not cached
      if (!savedChannels) {
        setTimeout(function() { autoLoadChannels(); }, 300);
      }
      addLog('Session restored — ' + data.platform);
    } else if (localStorage.getItem(LS_PLATFORM)) {
      // Server forgot us but we have saved creds — auto-reconnect
      statusText.textContent = 'Auto-reconnecting...';
      connectBtn.click();
    }
  } catch(e) {}
});

// ─── Platform switch ───
platformEl.addEventListener('change', function() {
  var p = this.value;
  dcFields.classList.toggle('active', p === 'discord');
  tgFields.classList.toggle('active', p === 'telegram');
  connectBtn.disabled = !p;
});

// ─── Connect ───
connectBtn.addEventListener('click', async function() {
  if (connected) return;
  var p = platformEl.value;
  if (!p) return;

  var payload = { platform: p };

  if (p === 'discord') {
    if (!discordToken.value.trim()) { addLog('ERROR: Discord token required'); return; }
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
  statusText.textContent = 'Saving...';

  try {
    var res = await fetch('/api/connect', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    var data = await res.json();

    if (data.status === 'ok') {
      addLog('Credentials saved — verifying...');
      localStorage.setItem(LS_PLATFORM, p);
      if (p === 'discord') localStorage.setItem(LS_DC_TOKEN, payload.discord_token);
      else {
        localStorage.setItem(LS_API_ID, String(payload.telegram_api_id));
        localStorage.setItem(LS_API_HASH, payload.telegram_api_hash);
        localStorage.setItem(LS_SESSION, payload.telegram_session);
      }
      // Show dashboard immediately (background will verify)
      showDashboard({ platform: p, username: '', first_name: 'Connected', has_photo: false });
      setTimeout(function() { autoLoadChannels(); }, 600);
    } else {
      statusText.textContent = 'Failed';
      addLog('ERROR: ' + data.msg);
      connectBtn.disabled = false;
    }
  } catch(e) {
    statusText.textContent = 'Connect';
    addLog('ERROR: ' + e.message);
    connectBtn.disabled = false;
  }
});

// ─── Show dashboard, hide login ───
function showDashboard(sessionData) {
  connected = true;
  loginPanel.style.display = 'none';
  dashboard.classList.add('active');

  var name = sessionData.first_name || sessionData.platform || 'User';
  var uname = sessionData.username ? '@' + sessionData.username : '@' + sessionData.platform;
  displayName.textContent = name;
  displayUsername.textContent = uname;
  platformBadge.textContent = (sessionData.platform || 'telegram').charAt(0).toUpperCase() + (sessionData.platform || 'telegram').slice(1);

  // Avatar
  if (sessionData.has_photo) {
    avatarImg.src = '/api/profile/photo?t=' + Date.now();
    avatarImg.style.display = 'block';
    avatarInitials.style.display = 'none';
  } else {
    avatarImg.style.display = 'none';
    avatarInitials.style.display = 'block';
    avatarInitials.textContent = name.charAt(0).toUpperCase();
  }

  loadChannelsBtn.disabled = false;
  channelSelect.disabled = false;
  // Enable auto-reply toggle
  autoReplyToggle.classList.remove('active');
  autoReplyState.textContent = 'OFF';
  autoReplyConfig.classList.remove('active');
}

// ─── Logout ───
logoutBtn.addEventListener('click', async function() {
  if (isRunning) { await fetch('/api/stop', { method: 'POST' }); isRunning = false; }
  if (isAutoReply) { await fetch('/api/auto-reply/stop', { method: 'POST' }); isAutoReply = false; }
  await fetch('/api/disconnect', { method: 'POST' });
  [LS_PLATFORM, LS_DC_TOKEN, LS_API_ID, LS_API_HASH, LS_SESSION, LS_CHANNELS].forEach(function(k) { localStorage.removeItem(k); });

  connected = false;
  dashboard.classList.remove('active');
  loginPanel.style.display = 'block';
  platformEl.value = '';
  dcFields.classList.remove('active');
  tgFields.classList.remove('active');
  discordToken.value = '';
  apiId.value = '';
  apiHash.value = '';
  sessionString.value = '';
  channelSelect.innerHTML = '<option value="">— Load channels first —</option>';
  channelSelect.disabled = true;
  loadChannelsBtn.disabled = true;
  connectBtn.disabled = true;
  statusDot.className = 'dot offline';
  statusText.textContent = 'Connect';
  spamToggle.classList.remove('active');
  spamState.textContent = 'OFF';
  spamConfig.classList.remove('active');
  startBtn.disabled = true;
  stopBtn.disabled = true;
  addLog('Logged out — all credentials cleared');
});

// ─── Auto-load channels ───
async function autoLoadChannels() {
  var p = platformEl.value;
  if (!p) return;
  loadChannelsBtn.disabled = true;
  loadChannelsBtn.textContent = '...';
  try {
    var payload;
    if (p === 'telegram') {
      if (!apiId.value.trim() || !apiHash.value.trim() || !sessionString.value.trim()) return;
      payload = { api_id: parseInt(apiId.value.trim()), api_hash: apiHash.value.trim(), session: sessionString.value.trim() };
    } else {
      if (!discordToken.value.trim()) return;
      payload = { token: discordToken.value.trim() };
    }
    var res = await fetch('/api/channels/' + p, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    var data = await res.json();
    channelSelect.innerHTML = '<option value="">— Select channel —</option>';
    if (data.channels && data.channels.length > 0) {
      data.channels.forEach(function(ch) {
        var opt = document.createElement('option');
        opt.value = ch.id;
        opt.textContent = ch.title || ch.name;
        channelSelect.appendChild(opt);
      });
      channelSelect.disabled = false;
      addLog('Loaded ' + data.channels.length + ' channels');
      localStorage.setItem(LS_CHANNELS, JSON.stringify(data.channels));
    } else if (data.channels && data.channels.length === 0) {
      addLog('No channels/groups found');
      channelSelect.disabled = true;
    } else if (data.error) {
      addLog('ERROR loading channels: ' + data.error);
    }
  } catch(e) { addLog('ERROR: ' + e.message); }
  finally { loadChannelsBtn.disabled = false; loadChannelsBtn.textContent = '⟳'; }
}

loadChannelsBtn.addEventListener('click', autoLoadChannels);

// ─── Spam toggle ───
spamToggle.addEventListener('click', function() {
  this.classList.toggle('active');
  var on = this.classList.contains('active');
  spamState.textContent = on ? 'ON' : 'OFF';
  spamConfig.classList.toggle('active', on);
  updateStartBtn();
});

channelSelect.addEventListener('change', updateStartBtn);

function updateStartBtn() {
  var on = spamToggle.classList.contains('active');
  startBtn.disabled = !on || !connected || !channelSelect.value || isRunning;
}

imageInput.addEventListener('change', async function() {
  var file = this.files[0];
  if (!file) return;
  var fd = new FormData();
  fd.append('image', file);
  try {
    var res = await fetch('/api/upload', { method: 'POST', body: fd });
    var d = await res.json();
    if (d.path) { uploadedImagePath = d.path; addLog('Image uploaded'); }
  } catch(e) { addLog('ERROR: Upload — ' + e.message); }
});

startBtn.addEventListener('click', async function() {
  if (isRunning) return;
  var payload = {
    channel_id: channelSelect.value,
    message: messageInput.value.trim(),
    interval: parseInt(intervalInput.value) || 5,
    image_path: uploadedImagePath,
  };
  try {
    var res = await fetch('/api/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    var d = await res.json();
    if (d.status === 'ok') { isRunning = true; startBtn.disabled = true; stopBtn.disabled = false; addLog('▶ Spam started'); }
    else { addLog('ERROR: ' + d.msg); }
  } catch(e) { addLog('ERROR: ' + e.message); }
});

stopBtn.addEventListener('click', async function() {
  try {
    var res = await fetch('/api/stop', { method: 'POST' });
    var d = await res.json();
    if (d.status === 'ok') { isRunning = false; startBtn.disabled = false; stopBtn.disabled = true; updateStartBtn(); addLog('■ Spam stopped'); }
  } catch(e) { addLog('ERROR: ' + e.message); }
});

// ─── Auto-Reply ───
autoReplyToggle.addEventListener('click', function() {
  if (!connected || platformEl.value !== 'telegram') return;
  this.classList.toggle('active');
  var on = this.classList.contains('active');
  autoReplyState.textContent = on ? 'ON' : 'OFF';
  autoReplyConfig.classList.toggle('active', on);
  autoReplySaveBtn.disabled = !on || !autoReplyMessage.value.trim();
});

autoReplyMessage.addEventListener('input', function() {
  if (autoReplyToggle.classList.contains('active'))
    autoReplySaveBtn.disabled = !this.value.trim();
});

autoReplySaveBtn.addEventListener('click', async function() {
  var msg = autoReplyMessage.value.trim();
  if (!msg) { addLog('ERROR: Auto-reply message empty'); return; }
  this.disabled = true;
  this.textContent = 'Enabling...';
  try {
    var res = await fetch('/api/auto-reply/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: msg }),
    });
    var d = await res.json();
    if (d.status === 'ok') {
      isAutoReply = true;
      localStorage.setItem(LS_AUTO_REPLY, msg);
      addLog('Auto-reply enabled ✓');
    } else { addLog('ERROR: ' + d.msg); }
  } catch(e) { addLog('ERROR: ' + e.message); }
  finally { this.disabled = false; this.textContent = 'Save & Enable'; }
});

// ─── WebSocket: real-time logs ───
socket.on('log', function(data) {
  addLog(data.msg, data.time);
});

// ─── WebSocket: profile update (after background verification) ───
socket.on('profile_update', function(data) {
  if (data.first_name) displayName.textContent = data.first_name;
  if (data.username) displayUsername.textContent = '@' + data.username;
  if (data.has_photo) {
    avatarImg.src = '/api/profile/photo?t=' + Date.now();
    avatarImg.style.display = 'block';
    avatarInitials.style.display = 'none';
  }
});

// ─── addLog ───
function addLog(msg, time) {
  var t = time || new Date().toLocaleTimeString('en-US', { hour12: false });
  var entry = document.createElement('div');
  entry.className = 'log-entry';
  if (msg.indexOf('ERROR') !== -1 || msg.indexOf('✗') !== -1) entry.className += ' error';
  if (msg.indexOf('✓') !== -1 || msg.indexOf('enabled') !== -1 || msg.indexOf('verified') !== -1) entry.className += ' success';
  entry.innerHTML = '<span class="time">[' + t + ']</span> ' + escapeHtml(msg);
  logBox.appendChild(entry);
  logBox.scrollTop = logBox.scrollHeight;
}

function escapeHtml(str) {
  var d = document.createElement('div');
  d.textContent = str;
  return d.innerHTML;
}
