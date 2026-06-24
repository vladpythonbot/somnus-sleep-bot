# Somnus Sleep Bot

Free sleep analytics pipeline:

```text
Mi Fitness -> Android Health Connect -> Flutter APK -> Python Telegram bot
```

The Telegram bot receives sleep data from the custom APK and sends a detailed text report directly to the user.

## Backend

Python backend:

- aiogram 3.x
- FastAPI
- uvicorn
- endpoint: `POST /webhook/sleep-apk`
- compatibility alias: `POST /webhook/sleep`

Environment variables:

```env
BOT_TOKEN=your_telegram_bot_token
WEBHOOK_SECRET=change_me
PORT=8000
```

Run:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

Railway uses:

```text
python main.py
```

## APK

Flutter app is in:

```text
flutter_app/
```

Main file:

```text
flutter_app/lib/main.dart
```

The app:

- requests Health Connect sleep permissions
- reads `SleepSession` and `SleepStage`
- registers a 24-hour Workmanager background task
- sends JSON to the backend

See Android permissions:

```text
flutter_app/ANDROID_SETUP.md
```

## Backend URL in APK

```text
https://YOUR_DOMAIN.up.railway.app/webhook/sleep-apk
```

If `WEBHOOK_SECRET` is enabled, enter the same secret in the APK field.

## JSON payload

```json
{
  "telegram_id": 123456789,
  "date": "2026-06-24T08:00:00",
  "source": "health_connect_flutter_apk",
  "total_sleep_minutes": 455,
  "deep_sleep_minutes": 92,
  "light_sleep_minutes": 285,
  "rem_sleep_minutes": 78,
  "awake_minutes": 21
}
```

## Notes

The report is not a medical diagnosis. It is practical sleep analytics based on wearable data.
