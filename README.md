# VYXBOT v4.0

Dual-platform (Discord + Telegram) selfbot spam dashboard with anti-detection.

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy)

## Features
- Choose Discord or Telegram at dashboard
- Load channels from your account automatically
- Send text + images
- Anti-detection: jittered intervals, message variation
- Live activity log via WebSocket

## Manual Deploy
1. Push this repo to GitHub
2. Go to https://render.com → New Web Service
3. Connect your repo
4. Build: `pip install -r requirements.txt`
5. Start: `gunicorn -k geventwebsocket.gunicorn.workers.GeventWebSocketWorker -w 1 app:app`
6. Done — open your Render URL
