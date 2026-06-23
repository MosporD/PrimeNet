// ============================================================================
// NOKIA CONFIGURATION MANAGER - COMPLETE FRONTEND
// Includes: Basic functionality + Profile Management + Task Creation + Admin Panel
// ============================================================================

// ============================================================================
// SECTION 1: BASIC TAB & AUTH FUNCTIONALITY
// ============================================================================

function escHtml(v) {
    return String(v ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function escJsStr(v) {
    return String(v ?? '').replace(/\\/g, '\\\\').replace(/'/g, "\\'");
}

function openTab(evt, tabName) {
    // Hide welcome screen
    const welcomeScreen = document.getElementById('welcome');
    if (welcomeScreen) {
        welcomeScreen.classList.remove('active');
    }

    const tabContents = document.getElementsByClassName("tab-content");
    for (let content of tabContents) {
        content.classList.remove("active");
    }

    const tabButtons = document.getElementsByClassName("tab-button");
    for (let button of tabButtons) {
        button.classList.remove("active");
    }

    document.getElementById(tabName).classList.add("active");
    evt.currentTarget.classList.add("active");

    // Load admin data when admin tab is opened
    if (tabName === 'admin-panel') {
        loadAllUsers();
    }

    // Initialize map when map tab is opened
    if (tabName === 'map-view') {
        initializeMap();
    }
}

async function logout() {
    if (confirm('Are you sure you want to logout?')) {
        try {
            const response = await fetch('/api/logout', { method: 'POST' });
            if (response.ok) {
                window.location.href = '/login';
            }
        } catch (error) {
            console.error('Logout error:', error);
            window.location.href = '/login';
        }
    }
}

function toggleDarkMode() {
    document.body.classList.toggle('dark-mode');
    const isDark = document.body.classList.contains('dark-mode');
    localStorage.setItem('darkMode', isDark);
    
    const btn = document.getElementById('dark-mode-btn');
    if (btn) {
        btn.textContent = isDark ? '☀️ Light' : '🌙 Dark';
    }
}

window.addEventListener('load', () => {
    if (localStorage.getItem('darkMode') === 'true') {
        document.body.classList.add('dark-mode');
        const btn = document.getElementById('dark-mode-btn');
        if (btn) {
            btn.textContent = '☀️ Light';
        }
    }
    
    // Check user role and show/hide admin tab
    checkAdminAccess();
});

// ============================================================================
// SECTION 2: FILE UPLOAD HELPERS
// ============================================================================

const xmlUploadArea = document.getElementById('xml-upload-area');
const xmlFileInput = document.getElementById('xml-file');
const xmlFileName = document.getElementById('xml-file-name');

const paramsUploadArea = document.getElementById('params-upload-area');
const paramsFileInput = document.getElementById('params-file');
const paramsFileName = document.getElementById('params-file-name');

const convertXmlBtn = document.getElementById('convert-xml-btn');

setupDragAndDrop(xmlUploadArea, xmlFileInput, xmlFileName, () => {
    updateConvertButton();
});

setupDragAndDrop(paramsUploadArea, paramsFileInput, paramsFileName);

convertXmlBtn.addEventListener('click', async () => {
    const xmlFile = xmlFileInput.files[0];
    const paramsFile = paramsFileInput.files[0];
    
    if (!xmlFile) {
        alert('Please select an XML file');
        return;
    }
    
    const formData = new FormData();
    formData.append('xml_file', xmlFile);
    if (paramsFile) {
        formData.append('params_file', paramsFile);
    }
    
    showProgress('xml-progress', 'xml-progress-fill', 'xml-progress-text', 0, 'Uploading...');
    convertXmlBtn.disabled = true;
    
    try {
        const response = await fetch('/api/xml-to-excel', {
            method: 'POST',
            body: formData
        });
        
        if (response.ok) {
            const blob = await response.blob();
            const downloadUrl = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = downloadUrl;
            a.download = `Nokia_Config_${getTimestamp()}.xlsx`;
            document.body.appendChild(a);
            a.click();
            a.remove();
            window.URL.revokeObjectURL(downloadUrl);
            
            showProgress('xml-progress', 'xml-progress-fill', 'xml-progress-text', 100, 'Complete! File downloaded.');
            setTimeout(() => {
                hideProgress('xml-progress');
            }, 3000);
        } else {
            const error = await response.json();
            alert(`Error: ${error.error}`);
            hideProgress('xml-progress');
        }
    } catch (error) {
        alert(`Error: ${error.message}`);
        hideProgress('xml-progress');
    } finally {
        convertXmlBtn.disabled = false;
    }
});

function updateConvertButton() {
    convertXmlBtn.disabled = !xmlFileInput.files[0];
}

// ============================================================================
// SECTION 3: EXCEL TO XML FUNCTIONALITY
// ============================================================================

const excelUploadArea = document.getElementById('excel-upload-area');
const excelFileInput = document.getElementById('excel-file');
const excelFileName = document.getElementById('excel-file-name');

const operationsSection = document.getElementById('operations-section');
const moOperationsList = document.getElementById('mo-operations-list');
const convertExcelBtn = document.getElementById('convert-excel-btn');

let currentMoClasses = [];
let currentXmlFilePath = null;
let currentXmlFileName = null;

setupDragAndDrop(excelUploadArea, excelFileInput, excelFileName, async () => {
    await loadMoClasses();
});

async function loadMoClasses() {
    const file = excelFileInput.files[0];
    if (!file) return;
    
    const formData = new FormData();
    formData.append('excel_file', file);
    
    try {
        const response = await fetch('/api/discover-sheets', {
            method: 'POST',
            body: formData
        });
        
        if (response.ok) {
            const data = await response.json();
            currentMoClasses = data.mo_classes;
            displayMoOperations(currentMoClasses);
            operationsSection.style.display = 'block';
        } else {
            const error = await response.json();
            alert(`Error: ${error.error}`);
        }
    } catch (error) {
        alert(`Error: ${error.message}`);
    }
}

function displayMoOperations(moClasses) {
    moOperationsList.innerHTML = '';
    
    moClasses.forEach(mo => {
        const div = document.createElement('div');
        div.className = 'mo-operation-item';
        
        const label = document.createElement('label');
        label.textContent = mo;
        
        const select = document.createElement('select');
        select.id = `op-${mo}`;
        select.innerHTML = `
            <option value="create">CREATE</option>
            <option value="update">UPDATE</option>
            <option value="delete">DELETE</option>
        `;
        
        div.appendChild(label);
        div.appendChild(select);
        moOperationsList.appendChild(div);
    });
}

convertExcelBtn.addEventListener('click', async () => {
    const file = excelFileInput.files[0];
    if (!file) {
        alert('Please select an Excel file');
        return;
    }
    
    const operations = {};
    currentMoClasses.forEach(mo => {
        const select = document.getElementById(`op-${mo}`);
        operations[mo] = select.value;
    });
    
    const formData = new FormData();
    formData.append('excel_file', file);
    formData.append('operations', JSON.stringify(operations));
    
    showProgress('excel-progress', 'excel-progress-fill', 'excel-progress-text', 0, 'Uploading...');
    convertExcelBtn.disabled = true;
    
    try {
        const response = await fetch('/api/excel-to-xml', {
            method: 'POST',
            body: formData
        });
        
        if (response.ok) {
            const blob = await response.blob();
            const downloadUrl = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = downloadUrl;
            const timestamp = getTimestamp();
            const filename = `Nokia_Config_${timestamp}.xml`;
            a.download = filename;
            document.body.appendChild(a);
            a.click();
            a.remove();
            window.URL.revokeObjectURL(downloadUrl);
            
            // Store XML file info for task creation
            currentXmlFileName = filename;
            currentXmlFilePath = `/tmp/${filename}`; // This is a placeholder path
            
            showProgress('excel-progress', 'excel-progress-fill', 'excel-progress-text', 100, 'Complete! File downloaded.');
            
            // Show "Create Task" button
            showCreateTaskButton();
            
            setTimeout(() => {
                hideProgress('excel-progress');
            }, 3000);
        } else {
            const error = await response.json();
            alert(`Error: ${error.error}`);
            hideProgress('excel-progress');
        }
    } catch (error) {
        alert(`Error: ${error.message}`);
        hideProgress('excel-progress');
    } finally {
        convertExcelBtn.disabled = false;
    }
});

// ============================================================================
// SECTION 4: XML COMPARISON FUNCTIONALITY
// ============================================================================

const compareXml1Area = document.getElementById('compare-xml1-area');
const compareXml1Input = document.getElementById('compare-xml1');
const compareXml1Name = document.getElementById('compare-xml1-name');

const compareXml2Area = document.getElementById('compare-xml2-area');
const compareXml2Input = document.getElementById('compare-xml2');
const compareXml2Name = document.getElementById('compare-xml2-name');

const compareBtn = document.getElementById('compare-btn');

setupDragAndDrop(compareXml1Area, compareXml1Input, compareXml1Name, () => {
    updateCompareButton();
});

setupDragAndDrop(compareXml2Area, compareXml2Input, compareXml2Name, () => {
    updateCompareButton();
});

compareBtn.addEventListener('click', async () => {
    const xml1 = compareXml1Input.files[0];
    const xml2 = compareXml2Input.files[0];
    
    if (!xml1 || !xml2) {
        alert('Please select both XML files');
        return;
    }
    
    const formData = new FormData();
    formData.append('xml1_file', xml1);
    formData.append('xml2_file', xml2);
    
    showProgress('compare-progress', 'compare-progress-fill', 'compare-progress-text', 0, 'Uploading...');
    compareBtn.disabled = true;
    
    try {
        const response = await fetch('/api/compare-xml', {
            method: 'POST',
            body: formData
        });
        
        if (response.ok) {
            const blob = await response.blob();
            const downloadUrl = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = downloadUrl;
            a.download = `XML_Comparison_${getTimestamp()}.xlsx`;
            document.body.appendChild(a);
            a.click();
            a.remove();
            window.URL.revokeObjectURL(downloadUrl);
            
            showProgress('compare-progress', 'compare-progress-fill', 'compare-progress-text', 100, 'Complete! File downloaded.');
            setTimeout(() => {
                hideProgress('compare-progress');
            }, 3000);
        } else {
            const error = await response.json();
            alert(`Error: ${error.error}`);
            hideProgress('compare-progress');
        }
    } catch (error) {
        alert(`Error: ${error.message}`);
        hideProgress('compare-progress');
    } finally {
        compareBtn.disabled = false;
    }
});

function updateCompareButton() {
    compareBtn.disabled = !(compareXml1Input.files[0] && compareXml2Input.files[0]);
}

// ============================================================================
// SECTION 5: UTILITY FUNCTIONS
// ============================================================================

function setupDragAndDrop(area, input, nameDisplay, onFileChange) {
    area.addEventListener('click', () => {
        input.click();
    });
    
    input.addEventListener('change', (e) => {
        const file = e.target.files[0];
        if (file) {
            nameDisplay.textContent = file.name;
            area.classList.add('has-file');
            if (onFileChange) onFileChange();
        }
    });
    
    area.addEventListener('dragover', (e) => {
        e.preventDefault();
        area.classList.add('drag-over');
    });
    
    area.addEventListener('dragleave', () => {
        area.classList.remove('drag-over');
    });
    
    area.addEventListener('drop', (e) => {
        e.preventDefault();
        area.classList.remove('drag-over');
        
        const files = e.dataTransfer.files;
        if (files.length > 0) {
            input.files = files;
            nameDisplay.textContent = files[0].name;
            area.classList.add('has-file');
            if (onFileChange) onFileChange();
        }
    });
}

function showProgress(sectionId, fillId, textId, percent, message) {
    const section = document.getElementById(sectionId);
    const fill = document.getElementById(fillId);
    const text = document.getElementById(textId);
    
    section.style.display = 'block';
    fill.style.width = `${percent}%`;
    text.textContent = message;
}

function hideProgress(sectionId) {
    const section = document.getElementById(sectionId);
    section.style.display = 'none';
}

function getTimestamp() {
    const now = new Date();
    return now.toISOString().replace(/[:-]/g, '').replace('T', '_').slice(0, 15);
}

window.addEventListener('load', async () => {
    try {
        const response = await fetch('/api/health');
        const data = await response.json();
        console.log('Backend connected:', data);
    } catch (error) {
        console.error('Backend connection failed:', error);
    }
});

// ============================================================================
// SECTION 6: PROFILE MANAGEMENT & TASK CREATION
// ============================================================================

function showCreateTaskButton() {
    const section = document.getElementById('create-task-section');
    if (section) {
        section.style.display = 'block';
        
        // Auto-hide after 30 seconds
        setTimeout(() => {
            section.style.display = 'none';
        }, 30000);
    }
}

async function openCreateTaskFromXmlModal() {
    const modal = document.getElementById('create-task-modal');
    
    // Set XML file info
    document.getElementById('task-xml-filename').textContent = currentXmlFileName || 'Generated XML file';
    document.getElementById('task-xml-path').textContent = currentXmlFilePath || 'Temporary file';
    
    // Set default task type
    document.getElementById('task-type').value = 'excel_to_xml';
    
    // Load users for assignment
    await loadUsersForAssignment();
    
    modal.style.display = 'block';
}

async function loadUsersForAssignment() {
    try {
        const response = await fetch('/api/users');
        if (response.ok) {
            const data = await response.json();
            const select = document.getElementById('task-assignee');
            
            // Clear existing options except first one
            select.innerHTML = '<option value="">-- Unassigned --</option>';
            
            data.users.forEach(user => {
                const option = document.createElement('option');
                option.value = user.id;
                option.textContent = `${user.full_name || user.username} (${user.department || 'No dept'})`;
                select.appendChild(option);
            });
        }
    } catch (error) {
        console.error('Error loading users:', error);
    }
}

async function createTaskFromXml() {
    const title = document.getElementById('task-title').value.trim();
    const description = document.getElementById('task-description').value.trim();
    const taskType = document.getElementById('task-type').value;
    const priority = document.getElementById('task-priority').value;
    const assignedTo = document.getElementById('task-assignee').value;
    
    if (!title) {
        alert('Please enter a task title');
        return;
    }
    
    try {
        const response = await fetch('/api/tasks', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                title,
                description,
                task_type: taskType,
                priority,
                assigned_to: assignedTo || null,
                xml_file_path: currentXmlFilePath,
                xml_file_name: currentXmlFileName
            })
        });
        
        if (response.ok) {
            const data = await response.json();
            alert(`Task created successfully! Task ID: ${data.task_id}`);
            
            // Close modal and hide create task button
            document.getElementById('create-task-modal').style.display = 'none';
            document.getElementById('create-task-section').style.display = 'none';
            
            // Clear form
            document.getElementById('task-title').value = '';
            document.getElementById('task-description').value = '';
        } else {
            const error = await response.json();
            alert(`Error creating task: ${error.error}`);
        }
    } catch (error) {
        alert(`Error: ${error.message}`);
    }
}

// Load profile with improved modal UI
async function loadProfileDialog() {
    const modal = document.getElementById('profile-modal');
    const container = document.getElementById('profile-cards');
    
    // Show modal
    modal.style.display = 'block';
    
    // Load profiles
    try {
        const response = await fetch('/api/profiles');
        if (response.ok) {
            const data = await response.json();
            displayProfileCards(data.profiles);
        } else {
            container.innerHTML = '<p style="text-align: center; color: #e74c3c;">Error loading profiles</p>';
        }
    } catch (error) {
        container.innerHTML = '<p style="text-align: center; color: #e74c3c;">Connection error</p>';
    }
}

function displayProfileCards(profiles) {
    const container = document.getElementById('profile-cards');
    
    if (profiles.length === 0) {
        container.innerHTML = `
            <div class="profile-empty-state">
                <div class="empty-icon">📋</div>
                <h3>No Profiles Yet</h3>
                <p>Save your first filter profile to see it here</p>
            </div>
        `;
        return;
    }
    
    container.innerHTML = profiles.map(profile => {
        const filterData = typeof profile.filter_data === 'string' ? 
            JSON.parse(profile.filter_data) : profile.filter_data;
        
        const moCount = Object.keys(filterData).length;
        const paramCount = Object.values(filterData).reduce((sum, params) => sum + params.length, 0);
        const createdDate = new Date(profile.created_at).toLocaleDateString();
        
        return `
            <div class="profile-card" onclick="selectProfile(${Number(profile.id)})">
                <div class="profile-card-header">
                    <h3>${escHtml(profile.profile_name)}</h3>
                    ${profile.is_shared ? '<span class="profile-shared-badge">🌐 Shared</span>' : ''}
                </div>
                <div class="profile-card-body">
                    <p class="profile-description">${escHtml(profile.description || 'No description')}</p>
                    <div class="profile-stats">
                        <span class="profile-stat">📊 ${escHtml(moCount)} MO classes</span>
                        <span class="profile-stat">📋 ${escHtml(paramCount)} parameters</span>
                    </div>
                    <div class="profile-date">Created: ${escHtml(createdDate)}</div>
                </div>
            </div>
        `;
    }).join('');
}

function filterProfileList() {
    const searchTerm = document.getElementById('profile-search-input').value.toLowerCase();
    const cards = document.querySelectorAll('.profile-card');
    
    cards.forEach(card => {
        const text = card.textContent.toLowerCase();
        card.style.display = text.includes(searchTerm) ? 'block' : 'none';
    });
}

async function selectProfile(profileId) {
    try {
        const response = await fetch(`/api/profiles/${profileId}`);
        if (response.ok) {
            const data = await response.json();
            const profile = data.profile;
            
            // Apply profile to UI (this would be implemented based on your UI structure)
            console.log('Loading profile:', profile);
            
            // Show notification
            showNotification(`Profile "${profile.profile_name}" loaded successfully!`, 'success');
            
            // Close modal
            document.getElementById('profile-modal').style.display = 'none';
        } else {
            showNotification('Error loading profile', 'error');
        }
    } catch (error) {
        showNotification('Connection error', 'error');
    }
}

function showNotification(message, type = 'info') {
    // Simple notification - you can enhance this
    alert(message);
}

// ============================================================================
// SECTION 7: ADMIN PANEL FUNCTIONALITY
// ============================================================================

let allUsers = [];
let editingUserId = null;

function checkAdminAccess() {
    const role = window.currentUserRole;
    const adminTab = document.getElementById('admin-tab');
    const roleBadge = document.getElementById('user-role-badge');
    
    if (role === 'admin') {
        adminTab.style.display = 'block';
        if (roleBadge) {
            roleBadge.style.background = '#e74c3c';
            roleBadge.textContent = '🔑 Admin';
        }
    } else if (role === 'config_team') {
        if (roleBadge) {
            roleBadge.style.background = '#3498db';
            roleBadge.textContent = '⚙️ Config Team';
        }
    } else {
        if (roleBadge) {
            roleBadge.style.background = '#95a5a6';
            roleBadge.textContent = '👤 User';
        }
    }
}

async function loadAllUsers() {
    try {
        const response = await fetch('/api/admin/users');

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({ error: 'Unknown error' }));
            throw new Error(errorData.error || `HTTP ${response.status}: ${response.statusText}`);
        }

        const data = await response.json();

        if (!data.success) {
            throw new Error(data.error || 'Failed to load users');
        }

        allUsers = data.users;

        displayUsers(allUsers);
        updateStats(allUsers);

    } catch (error) {
        console.error('Error loading users:', error);
        document.getElementById('users-table-body').innerHTML = `
            <tr><td colspan="8" style="text-align: center; color: #e74c3c;">
                Error loading users: ${escHtml(error.message)}
            </td></tr>
        `;
    }
}

function displayUsers(users) {
    const tbody = document.getElementById('users-table-body');
    
    if (users.length === 0) {
        tbody.innerHTML = '<tr><td colspan="8" style="text-align: center;">No users found</td></tr>';
        return;
    }
    
    tbody.innerHTML = users.map(user => `
        <tr>
            <td><strong>${escHtml(user.username)}</strong></td>
            <td>${escHtml(user.full_name || '-')}</td>
            <td>${escHtml(user.email)}</td>
            <td>${escHtml(user.department || '-')}</td>
            <td>
                <span class="role-badge role-${escHtml(user.role)}">
                    ${user.role === 'admin' ? '🔑' : user.role === 'config_team' ? '⚙️' : '👤'} 
                    ${escHtml(user.role)}
                </span>
            </td>
            <td>
                <span class="status-badge status-${user.is_active ? 'active' : 'inactive'}">
                    ${user.is_active ? '✅ Active' : '❌ Inactive'}
                </span>
            </td>
            <td>${escHtml(user.last_login ? formatDate(user.last_login) : 'Never')}</td>
            <td>
                <button onclick="editUserRole(${Number(user.id)}, '${escJsStr(user.username)}', '${escJsStr(user.role)}')" class="btn-small btn-edit">Edit Role</button>
                ${user.is_active ? 
                    `<button onclick="deactivateUser(${Number(user.id)})" class="btn-small btn-danger">Deactivate</button>` :
                    `<button onclick="activateUser(${Number(user.id)})" class="btn-small btn-success">Activate</button>`
                }
            </td>
        </tr>
    `).join('');
}

function updateStats(users) {
    const totalUsers = users.length;
    const adminUsers = users.filter(u => u.role === 'admin').length;
    const configTeam = users.filter(u => u.role === 'config_team').length;
    const activeUsers = users.filter(u => u.is_active).length;
    
    document.getElementById('stat-total-users').textContent = totalUsers;
    document.getElementById('stat-admin-users').textContent = adminUsers;
    document.getElementById('stat-config-team').textContent = configTeam;
    document.getElementById('stat-active-users').textContent = activeUsers;
}

function filterUsers() {
    const searchTerm = document.getElementById('user-search').value.toLowerCase();
    const roleFilter = document.getElementById('role-filter').value;
    
    const filtered = allUsers.filter(user => {
        const matchesSearch = 
            user.username.toLowerCase().includes(searchTerm) ||
            (user.full_name && user.full_name.toLowerCase().includes(searchTerm)) ||
            user.email.toLowerCase().includes(searchTerm) ||
            (user.department && user.department.toLowerCase().includes(searchTerm));
        
        const matchesRole = !roleFilter || user.role === roleFilter;
        
        return matchesSearch && matchesRole;
    });
    
    displayUsers(filtered);
}

// Add event listeners for search and filter
if (document.getElementById('user-search')) {
    document.getElementById('user-search').addEventListener('input', filterUsers);
}
if (document.getElementById('role-filter')) {
    document.getElementById('role-filter').addEventListener('change', filterUsers);
}

function editUserRole(userId, username, currentRole) {
    editingUserId = userId;
    
    document.getElementById('edit-user-name').textContent = username;
    document.getElementById('edit-role-select').value = currentRole;
    document.getElementById('edit-role-modal').style.display = 'block';
}

async function saveUserRole() {
    const newRole = document.getElementById('edit-role-select').value;
    
    if (!editingUserId) return;
    
    try {
        const response = await fetch(`/api/admin/users/${editingUserId}/role`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ role: newRole })
        });
        
        if (response.ok) {
            alert('User role updated successfully!');
            document.getElementById('edit-role-modal').style.display = 'none';
            loadAllUsers();
        } else {
            const error = await response.json();
            alert(`Error: ${error.error}`);
        }
    } catch (error) {
        alert(`Error: ${error.message}`);
    }
}

async function activateUser(userId) {
    if (!confirm('Activate this user?')) return;
    
    try {
        const response = await fetch(`/api/admin/users/${userId}/status`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ is_active: true })
        });
        
        if (response.ok) {
            alert('User activated!');
            loadAllUsers();
        } else {
            const error = await response.json();
            alert(`Error: ${error.error}`);
        }
    } catch (error) {
        alert(`Error: ${error.message}`);
    }
}

async function deactivateUser(userId) {
    if (!confirm('Deactivate this user? They will not be able to login.')) return;
    
    try {
        const response = await fetch(`/api/admin/users/${userId}/status`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ is_active: false })
        });
        
        if (response.ok) {
            alert('User deactivated!');
            loadAllUsers();
        } else {
            const error = await response.json();
            alert(`Error: ${error.error}`);
        }
    } catch (error) {
        alert(`Error: ${error.message}`);
    }
}

function formatDate(dateString) {
    const date = new Date(dateString);
    const now = new Date();
    const diffMs = now - date;
    const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));

    if (diffDays === 0) return 'Today';
    if (diffDays === 1) return 'Yesterday';
    if (diffDays < 7) return `${diffDays} days ago`;

    return date.toLocaleDateString();
}

// ============================================================================
// SECTION 7: MO DATABASE SEARCH & INFO
// ============================================================================

// Load MO stats on page load
document.addEventListener('DOMContentLoaded', function() {
    loadMoStats();

    // Add enter key listener for search
    const searchInput = document.getElementById('mo-search-input');
    if (searchInput) {
        searchInput.addEventListener('keypress', function(e) {
            if (e.key === 'Enter') {
                searchMoDatabase();
            }
        });
    }
});

async function loadMoStats() {
    try {
        const response = await fetch('/api/mo/stats');
        if (response.ok) {
            const data = await response.json();
            if (data.success && data.stats) {
                document.getElementById('mo-total-mos').textContent = data.stats.total_mos.toLocaleString();
                document.getElementById('mo-total-params').textContent = data.stats.total_params.toLocaleString();
            }
        }
    } catch (error) {
        console.error('Error loading MO stats:', error);
    }
}

async function searchMoDatabase() {
    const query = document.getElementById('mo-search-input').value.trim();
    const searchType = document.getElementById('mo-search-type').value;

    if (query.length < 2) {
        alert('Please enter at least 2 characters to search');
        return;
    }

    const resultsList = document.getElementById('mo-results-list');
    resultsList.innerHTML = '<div class="mo-loading">Searching...</div>';

    try {
        const response = await fetch(`/api/mo/search?q=${encodeURIComponent(query)}&type=${searchType}&limit=100`);
        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.error || 'Search failed');
        }

        displaySearchResults(data);
    } catch (error) {
        resultsList.innerHTML = `<div class="mo-error">Error: ${escHtml(error.message)}</div>`;
    }
}

function displaySearchResults(data) {
    const resultsList = document.getElementById('mo-results-list');
    const resultsCount = document.getElementById('mo-results-count');

    const totalResults = data.total_mos + data.total_params;
    resultsCount.textContent = `${totalResults} result(s)`;

    if (totalResults === 0) {
        resultsList.innerHTML = `
            <div class="mo-empty-state">
                <div class="mo-empty-icon">🔍</div>
                <p>No results found for "${escHtml(data.query)}"</p>
                <p class="mo-hint">Try a different search term</p>
            </div>
        `;
        return;
    }

    let html = '';

    // MO Classes section
    if (data.results.mos.length > 0) {
        html += '<div class="mo-results-section">';
        html += '<h4 class="mo-section-title">MO Classes</h4>';
        for (const mo of data.results.mos) {
            html += `
                <div class="mo-result-item mo-class-item" onclick="showMoInfo('${encodeURIComponent(mo.name)}')">
                    <div class="mo-result-icon">📦</div>
                    <div class="mo-result-content">
                        <div class="mo-result-name">${highlightMatch(mo.name, data.query)}</div>
                        <div class="mo-result-desc">${escHtml(mo.description)}</div>
                        <div class="mo-result-meta">
                            <span class="mo-result-category">${escHtml(mo.category)}</span>
                            <span class="mo-result-count">${escHtml(mo.param_count)} parameters</span>
                        </div>
                    </div>
                </div>
            `;
        }
        html += '</div>';
    }

    // Parameters section
    if (data.results.params.length > 0) {
        html += '<div class="mo-results-section">';
        html += '<h4 class="mo-section-title">Parameters</h4>';
        for (const param of data.results.params) {
            html += `
                <div class="mo-result-item mo-param-item" onclick="showParamInfo('${encodeURIComponent(param.name)}')">
                    <div class="mo-result-icon">⚙️</div>
                    <div class="mo-result-content">
                        <div class="mo-result-name">${highlightMatch(param.name, data.query)}</div>
                        <div class="mo-result-desc">${escHtml(truncateText(param.description, 150))}</div>
                        <div class="mo-result-meta">
                            <span class="mo-result-count">Used in ${escHtml(param.mo_count)} MO(s)</span>
                        </div>
                    </div>
                </div>
            `;
        }
        html += '</div>';
    }

    resultsList.innerHTML = html;
}

function _escapeRegExp(s) {
    return String(s).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}
function highlightMatch(text, query) {
    const safeText = escHtml(text || '');
    const q = String(query || '').trim();
    if (!q) return safeText;
    const regex = new RegExp(`(${_escapeRegExp(escHtml(q))})`, 'gi');
    return safeText.replace(regex, '<mark>$1</mark>');
}

function truncateText(text, maxLength) {
    if (!text) return '';
    if (text.length <= maxLength) return text;
    return text.substring(0, maxLength) + '...';
}

async function showMoInfo(moNameEncoded) {
    const moName = decodeURIComponent(moNameEncoded);
    const infoContent = document.getElementById('mo-info-content');
    infoContent.innerHTML = '<div class="mo-loading">Loading...</div>';

    // Highlight selected item
    document.querySelectorAll('.mo-result-item').forEach(item => item.classList.remove('selected'));
    event.currentTarget.classList.add('selected');

    try {
        const response = await fetch(`/api/mo/${encodeURIComponent(moName)}`);
        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.error || 'Failed to load MO info');
        }

        displayMoInfo(data.mo);
    } catch (error) {
        infoContent.innerHTML = `<div class="mo-error">Error: ${escHtml(error.message)}</div>`;
    }
}

function displayMoInfo(mo) {
    const infoContent = document.getElementById('mo-info-content');

    let paramsHtml = '';
    if (mo.parameters && mo.parameters.length > 0) {
        paramsHtml = '<div class="mo-params-list">';
        for (const param of mo.parameters) {
            paramsHtml += `
                <div class="mo-param-item-info" onclick="showParamInfo('${encodeURIComponent(param.name)}')">
                    <div class="mo-param-name">${escHtml(param.name)}</div>
                    <div class="mo-param-desc">${escHtml(truncateText(param.description, 100))}</div>
                </div>
            `;
        }
        paramsHtml += '</div>';
    }

    infoContent.innerHTML = `
        <div class="mo-info-details">
            <div class="mo-info-type">MO Class</div>
            <h2 class="mo-info-name">${escHtml(mo.name)}</h2>
            <div class="mo-info-category-badge">${escHtml(mo.category)}</div>

            <div class="mo-info-section">
                <h4>Description</h4>
                <p class="mo-info-description">${escHtml(mo.description)}</p>
            </div>

            <div class="mo-info-section">
                <h4>Parameters (${escHtml(mo.param_count)})</h4>
                ${paramsHtml || '<p class="mo-no-params">No parameters found</p>'}
            </div>
        </div>
    `;
}

async function showParamInfo(paramNameEncoded) {
    const paramName = decodeURIComponent(paramNameEncoded);
    const infoContent = document.getElementById('mo-info-content');
    infoContent.innerHTML = '<div class="mo-loading">Loading...</div>';

    // Highlight selected item if clicked from results
    if (event && event.currentTarget) {
        document.querySelectorAll('.mo-result-item').forEach(item => item.classList.remove('selected'));
        event.currentTarget.classList.add('selected');
    }

    try {
        const response = await fetch(`/api/param/${encodeURIComponent(paramName)}`);
        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.error || 'Failed to load parameter info');
        }

        displayParamInfo(data.param);
    } catch (error) {
        infoContent.innerHTML = `<div class="mo-error">Error: ${escHtml(error.message)}</div>`;
    }
}

function displayParamInfo(param) {
    const infoContent = document.getElementById('mo-info-content');

    let mosHtml = '';
    if (param.mos && param.mos.length > 0) {
        mosHtml = '<div class="mo-mos-list">';
        for (const mo of param.mos) {
            mosHtml += `
                <div class="mo-mo-item-info" onclick="showMoInfo('${encodeURIComponent(mo)}')">
                    <span class="mo-mo-name">${escHtml(mo)}</span>
                </div>
            `;
        }
        mosHtml += '</div>';
    }

    infoContent.innerHTML = `
        <div class="mo-info-details">
            <div class="mo-info-type">Parameter</div>
            <h2 class="mo-info-name">${escHtml(param.name)}</h2>

            <div class="mo-info-section">
                <h4>Description</h4>
                <p class="mo-info-description">${escHtml(param.description)}</p>
            </div>

            <div class="mo-info-section">
                <h4>Used in MO Classes (${escHtml(param.mo_count)})</h4>
                ${mosHtml || '<p class="mo-no-params">No MO classes found</p>'}
            </div>
        </div>
    `;
}