# 🚀 Quick Start Guide - Nokia Configuration Manager

## ✅ Server is Currently Running!

**Access the application at:**
- 🏠 **Dashboard**: http://localhost:5000/dashboard
- 🔐 **Login**: http://localhost:5000/login

**Default Credentials:**
- Username: `admin`
- Password: `admin123`

---

## 📂 Clean Project Structure

```
Web_V2/
├── 📄 app.py                      ← Main application (NEW!)
├── 📄 ncm_core.py                 ← Core processing logic
├── 📄 database_enhanced.py        ← Database functions
├── 📄 mo_descriptions.py          ← Parameter descriptions
├── 💾 ncm_users.db                ← SQLite database
│
├── 📁 routes/                     ← Backend blueprints (NEW!)
│   ├── auth_routes.py            ← Login/logout/register
│   └── xml_parser_routes.py      ← XML Parser API
│
├── 📁 templates/                  ← HTML pages
│   ├── dashboard.html            ← Main hub (NEW!)
│   ├── login.html
│   ├── register.html
│   └── xml_parser.html           ← XML Parser (NEW!)
│
├── 📁 static/
│   ├── css/
│   │   ├── common.css            ← Shared styles (NEW!)
│   │   ├── dashboard.css         ← Dashboard (NEW!)
│   │   ├── xml_parser.css        ← XML Parser (NEW!)
│   │   └── auth.css
│   └── js/
│       ├── common.js             ← Shared utilities (NEW!)
│       ├── xml_parser.js         ← XML Parser logic (NEW!)
│       └── map.js
│
├── 📁 scripts/                    ← Utility scripts
│   ├── add_map_tables.py
│   ├── add_sample_map_data.py
│   └── init_database.py
│
├── 📁 old_files/                  ← Archived legacy code
│   ├── app_enhanced.py           (old monolithic version)
│   └── index.html                (old tab-based UI)
│
├── 📄 README.md                   ← Full documentation
├── 📄 PROJECT_STATUS.md           ← Current status
└── 📄 QUICKSTART.md               ← This file!
```

---

## 🎯 Available Features

### ✅ Working Now:

1. **Dashboard** (`/dashboard`)
   - Navigate to all features
   - Clean card-based UI
   - User info display

2. **XML Parser** (`/xml-parser`)
   - Upload XML files
   - Filter parameters
   - Convert to Excel
   - Download results

3. **Authentication** (`/login`, `/register`)
   - User login/logout
   - New user registration
   - Session management

### 🚧 Coming Soon:

4. **Excel Generator** - Convert Excel → XML
5. **NE Comparison** - Compare XML configurations
6. **Parameter Dictionary** - Browse MO parameters
7. **Network Map** - Interactive site map with KPIs
8. **Admin Panel** - User management

---

## 🔧 Server Management

### Check if Server is Running:
```bash
# Windows
netstat -ano | findstr :5000

# Should show process listening on port 5000
```

### Start Server:
```bash
cd C:\Users\malek.mohammad\Project\Web_V2
python app.py
```

### Stop Server:
```
Press Ctrl+C in the terminal
```

### Restart Server:
```bash
# Stop (Ctrl+C) then start again
python app.py
```

---

## 📊 What Changed from Old Version?

### Before (Monolithic):
- ❌ Single `app_enhanced.py` with ALL routes (1000+ lines)
- ❌ Single `index.html` with tabs for all functions
- ❌ Mixed frontend/backend code
- ❌ Hard to maintain and debug

### After (Modular):
- ✅ Separate page for each function
- ✅ Backend routes in separate blueprint files
- ✅ Clean separation: HTML + CSS + JS + Routes
- ✅ Easy to add new features
- ✅ Better code organization

---

## 🎨 Architecture Overview

```
┌─────────────┐
│  Dashboard  │  ← Main navigation hub
└──────┬──────┘
       │
       ├─→ XML Parser       (Dedicated page + route)
       ├─→ Excel Generator  (To be created)
       ├─→ NE Comparison    (To be created)
       ├─→ Parameter Dict   (To be created)
       ├─→ Network Map      (To be created)
       └─→ Admin Panel      (To be created)
```

Each module has:
- **Frontend**: HTML template + CSS + JavaScript
- **Backend**: Flask blueprint with API routes
- **Independent**: Can be developed/tested separately

---

## 📝 How to Use Each Feature

### XML Parser:
1. Login to dashboard
2. Click "XML Parser" card
3. Upload XML file
4. Select parameters to include (or skip to include all)
5. Click "Generate Excel"
6. Download result

### Dashboard:
- Click any card to navigate to that feature
- User info shown in header
- Logout button available

### Authentication:
- Register new users at `/register`
- Login at `/login`
- Sessions persist until logout

---

## 🐛 Troubleshooting

### "Port already in use" error:
```bash
# Find process using port 5000
netstat -ano | findstr :5000

# Kill the process (replace PID)
taskkill /PID <process_id> /F

# Restart server
python app.py
```

### "Module not found" error:
```bash
# Install dependencies
pip install -r requirements.txt
```

### "Database error":
```bash
# Reinitialize database
python scripts/init_database.py
```

### Page shows 404:
- Make sure you're going to `/dashboard` not just `/`
- Server redirects `/` to `/dashboard` automatically

---

## 📚 Documentation

- **Full Documentation**: `README.md`
- **Project Status**: `PROJECT_STATUS.md`
- **Network Map Guide**: `NETWORK_MAP_README.md`

---

## 🎉 Quick Demo

1. **Open browser**: http://localhost:5000/login
2. **Login**: admin / admin123
3. **Dashboard**: See all available functions
4. **Try XML Parser**:
   - Click "XML Parser" card
   - Upload an XML file
   - See parameter filtering
   - Download Excel output

---

## 💡 Tips

- **Development Mode**: Debug mode is ON (auto-reload on code changes)
- **Session Management**: Sessions persist across page refreshes
- **File Uploads**: Maximum 100MB per file
- **Supported Files**: XML for parser, Excel for generator

---

## 🚀 Next Development Steps

To add a new feature:
1. Create `templates/feature_name.html`
2. Create `static/css/feature_name.css`
3. Create `static/js/feature_name.js`
4. Create `routes/feature_name_routes.py`
5. Register blueprint in `app.py`
6. Add card to `dashboard.html`

See `README.md` for detailed instructions!

---

**Server Status**: ✅ RUNNING
**Version**: 4.0 (Modular)
**Last Updated**: February 12, 2024

**Ready to use!** 🎊
