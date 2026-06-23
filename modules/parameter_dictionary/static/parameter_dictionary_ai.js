/**
 * Parameter Dictionary AI assistant chat panel
 */

let aiChatOpen = false;
let aiActiveVendor = 'all';
let aiVendorManual = false;
let aiSending = false;

document.addEventListener('DOMContentLoaded', () => {
    const toggleBtn = document.getElementById('pd-ai-toggle');
    const closeBtn = document.getElementById('pd-ai-close');
    const sendBtn = document.getElementById('pd-ai-send');
    const input = document.getElementById('pd-ai-input');
    const vendorSelect = document.getElementById('pd-ai-vendor');

    if (toggleBtn) {
        toggleBtn.addEventListener('click', () => setAiPanelOpen(!aiChatOpen));
    }
    if (closeBtn) {
        closeBtn.addEventListener('click', () => setAiPanelOpen(false));
    }
    if (sendBtn) {
        sendBtn.addEventListener('click', sendAiQuestion);
    }
    if (input) {
        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                sendAiQuestion();
            }
        });
    }
    if (vendorSelect) {
        vendorSelect.addEventListener('change', () => {
            aiActiveVendor = vendorSelect.value || 'all';
            aiVendorManual = true;
        });
    }

    document.querySelectorAll('.pd-ai-suggestion').forEach((btn) => {
        btn.addEventListener('click', () => {
            const q = btn.getAttribute('data-question') || '';
            if (input) input.value = q;
            sendAiQuestion();
        });
    });
});

function setAiPanelOpen(open) {
    aiChatOpen = !!open;
    const panel = document.getElementById('pd-ai-panel');
    const toggleBtn = document.getElementById('pd-ai-toggle');
    if (panel) {
        panel.classList.toggle('open', aiChatOpen);
        panel.setAttribute('aria-hidden', aiChatOpen ? 'false' : 'true');
    }
    if (toggleBtn) {
        toggleBtn.setAttribute('aria-expanded', aiChatOpen ? 'true' : 'false');
    }
    if (aiChatOpen) {
        const input = document.getElementById('pd-ai-input');
        if (input) input.focus();
    }
}

function setAiVendor(vendor, manual = false) {
    const vendorSelect = document.getElementById('pd-ai-vendor');
    const nextVendor = vendor || 'all';
    aiActiveVendor = nextVendor;
    if (vendorSelect) vendorSelect.value = nextVendor;
    if (manual) aiVendorManual = true;
}

function syncAiVendorFromPage(force = false) {
    if (aiVendorManual && !force) return;

    const nokiaVisible = document.getElementById('nokia-content')?.style.display !== 'none';
    const huaweiVisible = document.getElementById('huawei-content')?.style.display !== 'none';

    if (huaweiVisible && !nokiaVisible) {
        setAiVendor('huawei');
    } else if (nokiaVisible && !huaweiVisible) {
        setAiVendor('nokia');
    } else {
        setAiVendor('all');
    }
}

function appendAiMessage(role, htmlContent, meta) {
    const log = document.getElementById('pd-ai-messages');
    if (!log) return;

    const wrap = document.createElement('div');
    wrap.className = `pd-ai-msg pd-ai-msg-${role}`;
    wrap.innerHTML = `
        <div class="pd-ai-msg-body">${htmlContent}</div>
        ${meta ? `<div class="pd-ai-msg-meta">${meta}</div>` : ''}
    `;
    log.appendChild(wrap);
    log.scrollTop = log.scrollHeight;
}

function renderAiAnswer(text) {
    const escaped = escapeHtml(text || '');
    return escaped
        .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
        .replace(/`([^`]+)`/g, '<code>$1</code>')
        .replace(/\n/g, '<br>');
}

function renderAiSources(sources) {
    if (!Array.isArray(sources) || !sources.length) return '';
    const items = sources.slice(0, 8).map((src) => {
        const vendor = (src.vendor || '').toUpperCase();
        const label = escapeHtml(src.label || 'Reference');
        const desc = escapeHtml((src.description || '').slice(0, 140));
        if (src.vendor === 'huawei' && src.url) {
            const href = `/parameter-dictionary/huawei/${src.url}`;
            return `<li><span class="pd-ai-src-vendor">${vendor}</span> <a href="${href}" target="_blank" rel="noopener">${label}</a>${desc ? `<div class="pd-ai-src-desc">${desc}</div>` : ''}</li>`;
        }
        const moList = Array.isArray(src.mo_list) && src.mo_list.length
            ? `<div class="pd-ai-src-desc">MOs: ${escapeHtml(src.mo_list.join(', '))}</div>`
            : '';
        return `<li><span class="pd-ai-src-vendor">${vendor}</span> <strong>${label}</strong>${desc ? `<div class="pd-ai-src-desc">${desc}</div>` : ''}${moList}</li>`;
    }).join('');
    return `<div class="pd-ai-sources"><div class="pd-ai-sources-title">Sources</div><ul>${items}</ul></div>`;
}

async function sendAiQuestion() {
    if (aiSending) return;
    const input = document.getElementById('pd-ai-input');
    const question = (input?.value || '').trim();
    if (question.length < 3) {
        showNotification('Enter a question with at least 3 characters.', 'error');
        return;
    }

    const vendorSelect = document.getElementById('pd-ai-vendor');
    const vendor = vendorSelect?.value || aiActiveVendor || 'all';
    aiActiveVendor = vendor;
    aiSending = true;
    const sendBtn = document.getElementById('pd-ai-send');
    if (sendBtn) sendBtn.disabled = true;

    appendAiMessage('user', renderAiAnswer(question));
    if (input) input.value = '';
    appendAiMessage('assistant', '<span class="pd-ai-thinking">Searching parameter dictionary…</span>');

    const log = document.getElementById('pd-ai-messages');
    const pending = log?.lastElementChild;

    try {
        const response = await fetch('/api/parameter-dictionary/ai/ask', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
            credentials: 'same-origin',
            body: JSON.stringify({ question, vendor }),
        });
        const data = await response.json();
        if (pending) pending.remove();

        if (!response.ok || !data.success) {
            appendAiMessage('assistant', renderAiAnswer(data.error || 'Request failed.'), 'Error');
            return;
        }

        const modeLabel = data.mode === 'llm' ? 'AI summary' : 'Dictionary lookup';
        appendAiMessage(
            'assistant',
            renderAiAnswer(data.answer) + renderAiSources(data.sources),
            modeLabel,
        );
    } catch (error) {
        if (pending) pending.remove();
        appendAiMessage('assistant', renderAiAnswer(error.message || 'Network error.'), 'Error');
    } finally {
        aiSending = false;
        if (sendBtn) sendBtn.disabled = false;
    }
}

// Expose for vendor button handlers in parameter_dictionary.js
window.openParameterDictionaryAi = function openParameterDictionaryAi(vendor) {
    setAiPanelOpen(true);
    if (vendor) {
        setAiVendor(vendor, true);
    } else {
        syncAiVendorFromPage(true);
    }
};

window.setParameterDictionaryAiVendor = function setParameterDictionaryAiVendor(vendor) {
    setAiVendor(vendor);
};
