# 🖥️ Server Management Commands

## Quick Reference Guide

---

## ✅ Server is Currently RUNNING

**Status**: Active on port 5000
**URL**: http://localhost:5000

---

## 🚀 Server Control

### Start Server
```bash
cd C:\Users\malek.mohammad\Project\Web_V2
python app.py
```

### Stop Server
**In the terminal where server is running:**
```
Press: Ctrl + C
```

**If terminal is closed:**
```bash
# Find the process
netstat -ano | findstr :5000

# Kill the process (replace PID with actual number)
taskkill /F /PID <PID>
```

### Restart Server
```bash
# Stop (Ctrl+C), then:
python app.py
```

---

## 🔍 Server Status Checks

### Check if Server is Running
```bash
# Method 1: Check port
netstat -ano | findstr :5000

# Method 2: Test endpoint
curl http://localhost:5000/login

# Method 3: Open in browser
start http://localhost:5000/login
```

### View Server Logs
- Logs appear in the terminal where server is running
- Shows all HTTP requests and errors
- Debug mode shows detailed error traces

---

## 🗄️ Database Management

### Initialize Database
```bash
python scripts/init_database.py
```

### Add Sample Map Data
```bash
python scripts/add_sample_map_data.py
```

### Add Map Tables
```bash
python scripts/add_map_tables.py
```

### Backup Database
```bash
# Create backup
copy ncm_users.db ncm_users_backup_%date%.db

# Or with timestamp
copy ncm_users.db "ncm_users_backup_%date:~-4%%date:~-10,2%%date:~-7,2%_%time:~0,2%%time:~3,2%%time:~6,2%.db"
```

### Reset Database
```bash
# Backup first!
copy ncm_users.db ncm_users_backup.db

# Delete and reinitialize
del ncm_users.db
python scripts/init_database.py
```

---

## 🧹 Cleanup Commands

### Clear Python Cache
```bash
# Delete __pycache__ folders
for /d /r . %d in (__pycache__) do @if exist "%d" rd /s /q "%d"

# Delete .pyc files
del /s /q *.pyc
```

### Clear Temp Files
```bash
# Windows temp folder (where uploaded files go)
del /q %TEMP%\*.xml
del /q %TEMP%\*.xlsx
del /q %TEMP%\output_*
```

### Clean Old Logs
```bash
# If you create log files
del /q *.log
```

---

## 📦 Dependency Management

### Install Requirements
```bash
pip install -r requirements.txt
```

### Update Requirements
```bash
# After installing new packages
pip freeze > requirements.txt
```

### Check Installed Packages
```bash
pip list
```

### Virtual Environment (Optional)
```bash
# Create venv
python -m venv venv

# Activate (Windows)
venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Deactivate
deactivate
```

---

## 🧪 Testing Commands

### Test Login Endpoint
```bash
curl -X POST http://localhost:5000/api/login ^
  -H "Content-Type: application/json" ^
  -d "{\"username\":\"admin\",\"password\":\"admin123\"}"
```

### Test All Endpoints
```bash
curl http://localhost:5000/login
curl http://localhost:5000/register
curl http://localhost:5000/dashboard
curl http://localhost:5000/xml-parser
```

### Check Response Codes
```bash
curl -o nul -s -w "%%{http_code}\n" http://localhost:5000/login
```

---

## 🐛 Debugging Commands

### Run with Verbose Output
```bash
# Already enabled in app.py with debug=True
python app.py
```

### Check Python Version
```bash
python --version
```

### Check Flask Installation
```bash
python -c "import flask; print(flask.__version__)"
```

### Test Import of Modules
```bash
# Test if all modules load
python -c "import app; print('OK')"
python -c "import ncm_core; print('OK')"
python -c "import database_enhanced; print('OK')"
```

### View Module Path
```bash
python -c "import sys; print('\n'.join(sys.path))"
```

---

## 📊 Monitoring

### Watch Server Logs (Real-time)
```bash
# Server must be running, logs show in terminal
# To save logs to file:
python app.py > server.log 2>&1
```

### Monitor Port Activity
```bash
# Continuous monitoring
netstat -ano 1 | findstr :5000
```

### Check Memory Usage
```bash
# Task Manager -> Details tab -> Find python.exe
# Or use PowerShell:
Get-Process python | Select-Object Name, CPU, WorkingSet
```

---

## 🔧 Common Fixes

### "Address already in use"
```bash
# Find and kill process
netstat -ano | findstr :5000
taskkill /F /PID <PID>
```

### "Module not found"
```bash
# Reinstall dependencies
pip install -r requirements.txt
```

### "Permission denied"
```bash
# Run as administrator
# Or check if another process locked files
```

### "Template not found"
```bash
# Check templates folder exists
dir templates

# Check file is there
dir templates\*.html
```

### "Static files not loading"
```bash
# Clear browser cache: Ctrl + Shift + R
# Check static folder exists
dir static\css
dir static\js
```

---

## 🚀 Production Deployment (Future)

### Using Gunicorn (Linux)
```bash
pip install gunicorn
gunicorn -w 4 -b 0.0.0.0:5000 app:app
```

### Using Waitress (Windows)
```bash
pip install waitress
waitress-serve --listen=0.0.0.0:5000 app:app
```

### Using IIS (Windows Server)
- Install wfastcgi
- Configure IIS with Python handler
- Set up application pool

---

## 📝 Useful Aliases (Optional)

Create `start_server.bat`:
```batch
@echo off
cd C:\Users\malek.mohammad\Project\Web_V2
python app.py
pause
```

Create `stop_server.bat`:
```batch
@echo off
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :5000') do taskkill /F /PID %%a
pause
```

---

## 🎯 Quick Actions

| Action | Command |
|--------|---------|
| Start | `python app.py` |
| Stop | `Ctrl+C` |
| Restart | Stop + Start |
| Test | `curl http://localhost:5000/login` |
| Logs | Check terminal output |
| Status | `netstat -ano \| findstr :5000` |

---

## 📞 Port Information

- **Default Port**: 5000
- **Change Port**: Edit `app.py` → `app.run(port=XXXX)`
- **Firewall**: May need to allow port 5000

---

## ⚙️ Environment Variables (Optional)

```bash
# Set Flask environment
set FLASK_ENV=development
set FLASK_APP=app.py
set FLASK_DEBUG=1

# Then run with
flask run
```

---

**Last Updated**: February 12, 2024
**Server Version**: 4.0 (Modular)
**Current Status**: ✅ RUNNING
