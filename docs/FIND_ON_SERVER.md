# Как найти папку проекта PnL-бота на сервере

Подключись по SSH и выполни команды по порядку.

## 1. Через systemd (если бот запущен как сервис)

```bash
# Список сервисов с pnl/binance в имени
systemctl list-units --type=service | grep -iE 'pnl|binance'

# Или посмотреть все сервисы
ls /etc/systemd/system/*.service

# Найти unit-файл с путём к проекту
grep -l -r "binance\|pnl\|account_report" /etc/systemd/system/ 2>/dev/null
cat /etc/systemd/system/pnl*.service   # или как он называется
```

В unit-файле будет строка `WorkingDirectory=` или `ExecStart=` с путём к проекту.

## 2. Через запущенные процессы

```bash
# Процессы Python
ps aux | grep python

# Или искать по имени модуля
ps aux | grep account_report
ps aux | grep pnl
```

В выводе будет что-то вроде `python -m account_report_bot.bot` — путь к проекту это текущая директория процесса.

## 3. Поиск по файловой системе

```bash
# Поиск папки binance_pnl_bot
find /home -name "binance_pnl_bot" -type d 2>/dev/null
find /opt -name "binance_pnl_bot" -type d 2>/dev/null
find / -name "binance_pnl_bot" -type d 2>/dev/null

# Поиск по характерному файлу
find / -name "account_report_bot" -type d 2>/dev/null
find / -path "*/account_tracker/binance_client.py" 2>/dev/null
```

## 4. Типичные места

```bash
ls -la ~/binance_pnl_bot
ls -la ~/pnl_bot
ls -la /opt/binance_pnl_bot
ls -la /home/*/binance_pnl_bot
```

## 5. После того как нашёл путь

```bash
cd /путь/к/binance_pnl_bot
git pull origin main
# Перезапуск (если systemd):
sudo systemctl restart pnl-bot   # или имя сервиса из systemctl list-units
```
