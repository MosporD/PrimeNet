let allTasks = [];
let defaultTaskName = '';
let filteredTasks = [];
let currentPage = 1;
let pageSize = 10;
let inputFilePolicy = {};
let resultAllowedExtensions = [];
let resultMaxSizeBytes = 0;
let canManageTasks = false;
let canCreateTasks = false;
let canDeleteTasks = false;

window.addEventListener('DOMContentLoaded', () => {
    loadTasks();
});

function esc(value) {
    return String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}

async function loadTasks() {
    const tbody = document.getElementById('tasksTableBody');
    tbody.innerHTML = '<tr><td colspan="9" class="table-empty">Loading tasks...</td></tr>';
    try {
        const res = await fetch('/api/config-task-scheduler/tasks');
        const data = await res.json();
        if (!data.success) throw new Error(data.error || 'Could not load tasks');
        allTasks = data.tasks || [];
        defaultTaskName = data.default_task_name || '';
        canCreateTasks = !!data.can_create_tasks;
        canManageTasks = !!data.can_manage_tasks;
        canDeleteTasks = !!data.can_delete_tasks;
        inputFilePolicy = data.input_file_policy || {};
        resultAllowedExtensions = data.result_allowed_extensions || [];
        resultMaxSizeBytes = Number(data.result_max_size_bytes || 0);
        applyFiltersAndRender();
        updateVendorPolicyHint();
        updateResultPolicyHint();
    } catch (error) {
        tbody.innerHTML = `<tr><td colspan="9" class="table-empty table-error">${esc(error.message)}</td></tr>`;
    }
}

function renderTasks(tasks) {
    const tbody = document.getElementById('tasksTableBody');
    if (!tasks.length) {
        tbody.innerHTML = '<tr><td colspan="9" class="table-empty">No tasks yet. Click "Add New Task".</td></tr>';
        return;
    }
    tbody.innerHTML = tasks.map((task) => {
        const scheduleText = task.schedule_mode === 'scheduled'
            ? `Scheduled: ${task.scheduled_at || '-'}`
            : 'Run now';
        const inputFiles = (task.files || []).map((f) =>
            `<a href="/api/config-task-scheduler/tasks/${task.id}/file/${f.id}/download">${esc(f.original_file_name)}</a>`
        ).join('<br>') || '-';
        const resultFiles = (task.result_files || []).map((f) =>
            `<a href="/api/config-task-scheduler/tasks/${task.id}/result/${f.id}/download">${esc(f.original_file_name)}</a>`
        ).join('<br>') || '-';
        const canStart = canManageTasks && task.status === 'pending';
        const canFinish = canManageTasks && ['completed', 'partial_completed', 'failed'].indexOf(task.status) === -1;
        const manageActions = canManageTasks
            ? `
                <button class="btn-small" onclick="startTask(${task.id})" ${canStart ? '' : 'disabled'}>
                    Start
                </button>
                <button class="btn-small btn-small-secondary" onclick="openFinishModal(${task.id})" ${canFinish ? '' : 'disabled'}>
                    Finish
                </button>
              `
            : '<span class="muted">View only</span>';
        const deleteAction = canDeleteTasks
            ? `<button class="btn-small btn-small-danger" onclick="deleteTask(${task.id})">Delete</button>`
            : '';
        return `
        <tr>
            <td>${esc(task.task_name)}</td>
            <td>${esc(task.vendor)}</td>
            <td>${esc(scheduleText)}</td>
            <td>${esc(task.run_mode)}</td>
            <td><span class="status-badge status-${esc(task.status)}">${esc(task.status)}</span></td>
            <td>${esc(task.creator_username || '-')}</td>
            <td class="file-col">${inputFiles}</td>
            <td class="file-col">${resultFiles}</td>
            <td>
                ${manageActions}
                ${deleteAction}
            </td>
        </tr>`;
    }).join('');
}

function onFiltersChanged() {
    currentPage = 1;
    applyFiltersAndRender();
}

function onPageSizeChanged() {
    pageSize = Number(document.getElementById('pageSize').value || 10);
    currentPage = 1;
    applyFiltersAndRender();
}

function applyFiltersAndRender() {
    const search = (document.getElementById('taskSearch')?.value || '').trim().toLowerCase();
    const statusFilter = (document.getElementById('statusFilter')?.value || '').trim().toLowerCase();
    const vendorFilter = (document.getElementById('vendorFilter')?.value || '').trim().toLowerCase();

    filteredTasks = allTasks.filter((task) => {
        const text = `${task.task_name || ''} ${task.creator_username || ''} ${task.vendor || ''}`.toLowerCase();
        if (search && !text.includes(search)) return false;
        if (statusFilter && String(task.status || '').toLowerCase() !== statusFilter) return false;
        if (vendorFilter && String(task.vendor || '').toLowerCase() !== vendorFilter) return false;
        return true;
    });

    const totalPages = Math.max(1, Math.ceil(filteredTasks.length / pageSize));
    if (currentPage > totalPages) currentPage = totalPages;
    const start = (currentPage - 1) * pageSize;
    const rows = filteredTasks.slice(start, start + pageSize);
    renderTasks(rows);
    renderPagination(totalPages);
}

function renderPagination(totalPages) {
    const pageInfo = document.getElementById('pageInfo');
    const prevBtn = document.getElementById('prevPageBtn');
    const nextBtn = document.getElementById('nextPageBtn');
    pageInfo.textContent = `Page ${currentPage} of ${totalPages}`;
    prevBtn.disabled = currentPage <= 1;
    nextBtn.disabled = currentPage >= totalPages;
}

function goToPage(step) {
    const totalPages = Math.max(1, Math.ceil(filteredTasks.length / pageSize));
    const next = currentPage + Number(step || 0);
    if (next < 1 || next > totalPages) return;
    currentPage = next;
    applyFiltersAndRender();
}

function openCreateModal() {
    if (!canCreateTasks) {
        alert('You cannot create tasks.');
        return;
    }
    document.getElementById('createTaskModal').style.display = 'flex';
    document.getElementById('createTaskForm').reset();
    document.getElementById('taskName').value = defaultTaskName;
    document.getElementById('fileOrderContainer').innerHTML = '';
    onScheduleModeChange();
    updateVendorPolicyHint();
}

function closeCreateModal() {
    document.getElementById('createTaskModal').style.display = 'none';
}

function onScheduleModeChange() {
    const mode = document.getElementById('scheduleMode').value;
    const wrapper = document.getElementById('scheduledAtWrapper');
    const input = document.getElementById('scheduledAt');
    if (mode === 'scheduled') {
        wrapper.classList.remove('hidden');
        input.required = true;
    } else {
        wrapper.classList.add('hidden');
        input.required = false;
        input.value = '';
    }
}

function renderFileOrderInputs() {
    const files = document.getElementById('taskFiles').files;
    const container = document.getElementById('fileOrderContainer');
    if (!files || !files.length) {
        container.innerHTML = '';
        return;
    }
    container.innerHTML = Array.from(files).map((file, idx) => `
        <div class="file-order-item">
            <span>${esc(file.name)}</span>
            <label>Order
                <input type="number" name="file_order" min="1" value="${idx + 1}" required>
            </label>
        </div>
    `).join('');
}

function updateVendorPolicyHint() {
    const vendor = document.getElementById('vendor')?.value || 'mixed';
    const info = inputFilePolicy[vendor];
    const hint = document.getElementById('vendorPolicyHint');
    if (!hint || !info) return;
    const maxMb = Math.round(Number(info.max_size_bytes || 0) / (1024 * 1024));
    hint.textContent = `Allowed for ${vendor}: ${info.extensions.join(', ')} | Max size per file: ${maxMb}MB`;
}

function updateResultPolicyHint() {
    const hint = document.getElementById('resultPolicyHint');
    if (!hint) return;
    const maxMb = Math.round(Number(resultMaxSizeBytes || 0) / (1024 * 1024));
    hint.textContent = `Result policy: ${resultAllowedExtensions.join(', ')} | Max size per file: ${maxMb}MB`;
}

async function submitTask(event) {
    event.preventDefault();
    if (!canCreateTasks) {
        alert('You cannot create tasks.');
        return;
    }
    const form = document.getElementById('createTaskForm');
    const fd = new FormData(form);
    try {
        const res = await fetch('/api/config-task-scheduler/tasks', {
            method: 'POST',
            body: fd,
        });
        const data = await res.json();
        if (!data.success) throw new Error(data.error || 'Task creation failed');
        closeCreateModal();
        await loadTasks();
    } catch (error) {
        alert(error.message);
    }
}

async function startTask(taskId) {
    if (!canManageTasks) {
        alert('You have view-only access for tasks.');
        return;
    }
    try {
        const res = await fetch(`/api/config-task-scheduler/tasks/${taskId}/status`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ status: 'in_progress' }),
        });
        const data = await res.json();
        if (!data.success) throw new Error(data.error || 'Could not move task to in progress');
        await loadTasks();
    } catch (error) {
        alert(error.message);
    }
}

function openFinishModal(taskId) {
    if (!canManageTasks) {
        alert('You have view-only access for tasks.');
        return;
    }
    document.getElementById('finishTaskId').value = String(taskId);
    document.getElementById('finishTaskForm').reset();
    document.getElementById('finishTaskModal').style.display = 'flex';
}

function closeFinishModal() {
    document.getElementById('finishTaskModal').style.display = 'none';
}

async function submitFinishTask(event) {
    event.preventDefault();
    if (!canManageTasks) {
        alert('You have view-only access for tasks.');
        return;
    }
    const taskId = document.getElementById('finishTaskId').value;
    const fd = new FormData();
    fd.append('completion_status', document.getElementById('completionStatus').value);
    fd.append('completion_notes', document.getElementById('completionNotes').value || '');
    const resultFiles = document.getElementById('resultFiles').files;
    Array.from(resultFiles).forEach((file) => {
        fd.append('result_files', file);
    });

    try {
        const res = await fetch(`/api/config-task-scheduler/tasks/${taskId}/complete`, {
            method: 'POST',
            body: fd,
        });
        const data = await res.json();
        if (!data.success) throw new Error(data.error || 'Could not finish task');
        closeFinishModal();
        await loadTasks();
    } catch (error) {
        alert(error.message);
    }
}

async function deleteTask(taskId) {
    if (!canDeleteTasks) {
        alert('Only Owner and NOC SYS can delete tasks.');
        return;
    }
    if (!confirm('Delete this task permanently?')) return;
    try {
        const res = await fetch(`/api/config-task-scheduler/tasks/${taskId}`, { method: 'DELETE' });
        const data = await res.json();
        if (!data.success) throw new Error(data.error || 'Could not delete task');
        await loadTasks();
    } catch (error) {
        alert(error.message);
    }
}
