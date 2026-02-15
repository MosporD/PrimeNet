# Nokia Configuration Manager - Modular Version

## 📁 Project Structure

```
Web_V2/
├── app.py                          # Main application entry point
├── ncm_core.py                     # Core XML/Excel conversion logic
├── database_enhanced.py            # Database operations
├── mo_descriptions.py              # MO parameter descriptions
├── ncm_users.db                    # SQLite database
├── requirements.txt                # Python dependencies
│
├── routes/                         # Backend route blueprints
│   ├── __init__.py
│   ├── auth_routes.py             # Login, logout, registration
│   └── xml_parser_routes.py       # XML Parser functionality
│
├── templates/                      # HTML templates
│   ├── dashboard.html             # Main dashboard
│   ├── login.html                 # Login page
│   ├── register.html              # Registration page
│   └── xml_parser.html            # XML Parser page
│
├── static/                        # Static assets
│   ├── css/
│   │   ├── common.css            # Shared styles
│   │   ├── dashboard.css         # Dashboard styles
│   │   ├── auth.css              # Auth page styles
│   │   ├── xml_parser.css        # XML Parser styles
│   │   └── style.css             # Legacy styles (for Network Map)
│   │
│   └── js/
│       ├── common.js             # Shared utilities
│       ├── xml_parser.js         # XML Parser logic
│       ├── map.js                # Network Map logic
│       └── app.js                # Legacy JavaScript
│
├── scripts/                       # Utility scripts
│   ├── add_map_tables.py         # Create map database tables
│   ├── add_sample_map_data.py    # Generate sample data
│   ├── add_new_tables.py         # Add new database tables
│   └── init_database.py          # Initialize database
│
└── old_files/                     # Archived old files
    ├── app_enhanced.py
    ├── index.html
    └── ...
```

## 🚀 Quick Start

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Initialize Database
```bash
python scripts/init_database.py
```

### 3. Add Sample Network Map Data (Optional)
```bash
python scripts/add_sample_map_data.py
```

### 4. Start Server
```bash
python app.py
```

### 5. Access Application
- **Dashboard**: http://localhost:5000/dashboard
- **Login**: http://localhost:5000/login
- **Default Admin**: username: `admin`, password: `admin123`

## 📋 Features

### ✅ Completed Modules

1. **Dashboard** (`/dashboard`)
   - Central navigation hub
   - Function cards for all modules
   - User info and logout

2. **XML Parser** (`/xml-parser`)
   - Upload XML configuration files
   - Filter specific parameters
   - Convert to Excel format
   - Save/load filter profiles

3. **Authentication** (`/login`, `/register`)
   - User registration
   - Secure login/logout
   - Session management

### 🚧 Modules to Complete

4. **Excel Generator** (`/excel-generator`)
   - Convert Excel to XML
   - Template-based generation

5. **NE Comparison** (`/ne-comparison`)
   - Compare two XML configurations
   - Highlight differences

6. **Parameter Dictionary** (`/parameter-dictionary`)
   - Browse MO parameters
   - Search functionality
   - Parameter descriptions

7. **Network Map** (`/network-map`)
   - Interactive site map
   - Sector visualization
   - KPI dashboard

8. **Admin Panel** (`/admin-panel`)
   - User management
   - Activity logs
   - System settings

## 🏗️ Architecture

### Modular Design
Each function is separated into its own module:

**Frontend:**
- Dedicated HTML template
- Specific CSS file
- Independent JavaScript

**Backend:**
- Separate blueprint file in `routes/`
- Self-contained API endpoints
- Independent business logic

### Benefits
- ✅ Easy to maintain and debug
- ✅ Independent development of features
- ✅ Clear separation of concerns
- ✅ Scalable architecture
- ✅ Better code organization

## 🔧 Adding a New Module

To add a new feature, follow this pattern:

### 1. Create Frontend Files
```
templates/your_feature.html
static/css/your_feature.css
static/js/your_feature.js
```

### 2. Create Backend Blueprint
```python
# routes/your_feature_routes.py
from flask import Blueprint

your_feature_bp = Blueprint('your_feature', __name__)

@your_feature_bp.route('/your-feature')
def your_feature_page():
    return render_template('your_feature.html')

@your_feature_bp.route('/api/your-feature/action', methods=['POST'])
def your_feature_action():
    # Your logic here
    pass
```

### 3. Register Blueprint
```python
# app.py
from routes.your_feature_routes import your_feature_bp
app.register_blueprint(your_feature_bp)
```

### 4. Add to Dashboard
```html
<!-- templates/dashboard.html -->
<a href="/your-feature" class="function-card">
    <div class="function-icon">🎯</div>
    <div class="function-name">Your Feature</div>
    <div class="function-description">Description here</div>
</a>
```

## 📊 Database Schema

### Users Table
- `id`, `username`, `email`, `password_hash`, `created_at`, `is_active`, `role`

### Sessions Table
- `id`, `user_id`, `session_token`, `created_at`, `expires_at`

### Activity Logs
- `id`, `user_id`, `action_type`, `action_details`, `timestamp`

### Network Map Tables
- `sites`: Network site locations
- `sectors`: Cell sectors with azimuth
- `cells`: Individual cells
- `cell_kpis`: Performance metrics

## 🔐 Security

- Password hashing with bcrypt
- Session-based authentication
- HTTP-only cookies
- Login required decorators
- SQL injection prevention
- File upload validation

## 📝 API Endpoints

### Authentication
- `POST /api/login` - User login
- `POST /api/logout` - User logout
- `POST /api/register` - User registration

### XML Parser
- `POST /api/xml-parser/upload` - Upload XML file
- `POST /api/xml-parser/convert` - Convert to Excel
- `GET /api/xml-parser/download/<filename>` - Download result

### Network Map (Legacy endpoints in app_enhanced.py)
- `GET /api/map/sites` - Get all sites
- `GET /api/map/site/<site_id>` - Get site details
- `GET /api/map/sector/<sector_id>/kpis` - Get KPIs

## 🎨 UI/UX Design

### Color Scheme
- Primary: `#3498DB` (Blue)
- Secondary: `#2C3E50` (Dark Blue)
- Success: `#27ae60` (Green)
- Warning: `#f39c12` (Orange)
- Danger: `#e74c3c` (Red)
- Background: `#f5f7fa` (Light Gray)

### Typography
- Font Family: Segoe UI, Tahoma, Geneva, Verdana, sans-serif
- Headers: Bold, larger sizes
- Body: Regular weight, readable sizes

### Components
- Cards with hover effects
- Gradient headers
- Clean forms
- Responsive grid layouts
- Modal dialogs
- Notifications

## 🐛 Troubleshooting

### Server won't start
```bash
# Check if port 5000 is in use
netstat -ano | findstr :5000

# Kill process if needed
taskkill /PID <process_id> /F
```

### Database errors
```bash
# Reinitialize database
python scripts/init_database.py
```

### Module import errors
```bash
# Ensure you're in the project directory
cd C:\Users\malek.mohammad\Project\Web_V2

# Install missing dependencies
pip install -r requirements.txt
```

## 📚 Documentation

- Network Map feature: See `NETWORK_MAP_README.md`
- API documentation: See inline docstrings in route files
- Core logic: See docstrings in `ncm_core.py`

## 🔄 Migration from Old Version

The old monolithic `app_enhanced.py` has been archived in `old_files/`.

Key changes:
- Single-page tabs → Multiple dedicated pages
- All routes in one file → Modular blueprints
- Mixed frontend/backend → Separated concerns

## 📦 Dependencies

See `requirements.txt` for full list:
- Flask - Web framework
- openpyxl - Excel file handling
- pandas - Data processing
- bcrypt - Password hashing
- sqlite3 - Database (built-in)

## 📄 License

Internal Nokia project - All rights reserved

## 👥 Contributors

- Development Team
- Network Engineering Team

---

**Version**: 4.0 (Modular Architecture)
**Last Updated**: February 2024
