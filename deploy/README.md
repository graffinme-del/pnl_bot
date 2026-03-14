# Деплой бота на сервер (systemd)

## 1. На сервере: клонировать репозиторий

```bash
cd ~
git clone https://github.com/graffinme-del/pnl_bot.git
cd pnl_bot
```

## 2. Создать venv и установить зависимости

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
deactivate
```

## 3. Создать .env

Скопировать переменные с локального ПК (BINANCE_API_KEY, BINANCE_API_SECRET, TELEGRAM_BOT_TOKEN, TIMEZONE, REPORT_CHAT_ID) в файл на сервере:

```bash
nano .env
# вставить строки вида:
# BINANCE_API_KEY=...
# BINANCE_API_SECRET=...
# TELEGRAM_BOT_TOKEN=...
# TIMEZONE=Europe/Moscow
# REPORT_CHAT_ID=...
```

## 4. Установить systemd-сервис

Подставить свой логин вместо `YOUR_USER` в unit-файле (или отредактировать пути), затем:

```bash
sudo cp deploy/pnl-bot.service /etc/systemd/system/
sudo sed -i "s/YOUR_USER/$(whoami)/g" /etc/systemd/system/pnl-bot.service
sudo systemctl daemon-reload
sudo systemctl enable pnl-bot
sudo systemctl start pnl-bot
```

## 5. Проверка и управление

```bash
sudo systemctl status pnl-bot   # статус
sudo systemctl restart pnl-bot # перезапуск
sudo journalctl -u pnl-bot -f   # логи в реальном времени
```

## Обновление кода

```bash
cd ~/pnl_bot
git pull origin main
sudo systemctl restart pnl-bot
```
