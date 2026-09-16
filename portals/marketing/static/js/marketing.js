/* Marketing Portal — rule builder and small page helpers. */
(function () {
    'use strict';

    const ATTRIBUTES = window.MKT_ATTRIBUTES || [];
    const OPERATORS = window.MKT_OPERATORS || {};

    function attributeByKey(key) {
        return ATTRIBUTES.find((a) => a.key === key) || null;
    }

    function operatorsFor(attribute) {
        if (!attribute) return [];
        return Object.entries(OPERATORS)
            .filter(([, spec]) => (spec.types || []).includes(attribute.type))
            .map(([key, spec]) => ({ key, label: spec.label, multi: !!spec.multi, noValue: !!spec.no_value }));
    }

    function buildValueInput(attribute, operator, current) {
        const spec = OPERATORS[operator] || {};
        if (spec.no_value) {
            const span = document.createElement('span');
            span.className = 'mkt-muted';
            span.textContent = 'No value needed';
            return span;
        }
        if (attribute && attribute.type === 'boolean') {
            const select = document.createElement('select');
            select.className = 'mkt-select mkt-rule-value';
            [['true', 'Yes'], ['false', 'No']].forEach(([value, label]) => {
                const option = new Option(label, value, false, String(current) === value);
                select.add(option);
            });
            return select;
        }
        if (attribute && attribute.type === 'enum' && !spec.multi) {
            const select = document.createElement('select');
            select.className = 'mkt-select mkt-rule-value';
            select.add(new Option('Choose…', ''));
            (attribute.values || []).forEach((value) => {
                select.add(new Option(value, value, false, current === value));
            });
            return select;
        }
        const input = document.createElement('input');
        input.className = 'mkt-input mkt-rule-value';
        input.type = attribute && attribute.type === 'number' ? 'number' : 'text';
        input.step = 'any';
        input.value = Array.isArray(current) ? current.join(', ') : (current === undefined ? '' : current);
        input.placeholder = spec.multi ? 'Comma-separated values' : 'Value';
        return input;
    }

    function renderRule(row, rule) {
        row.innerHTML = '';
        row.className = 'mkt-rule';

        const attributeSelect = document.createElement('select');
        attributeSelect.className = 'mkt-select mkt-rule-attribute';
        attributeSelect.add(new Option('Choose attribute…', ''));
        ATTRIBUTES.forEach((a) => {
            attributeSelect.add(new Option(a.label, a.key, false, a.key === rule.attribute));
        });

        const attribute = attributeByKey(rule.attribute);
        const operatorSelect = document.createElement('select');
        operatorSelect.className = 'mkt-select mkt-rule-operator';
        operatorsFor(attribute).forEach((op) => {
            operatorSelect.add(new Option(op.label, op.key, false, op.key === rule.operator));
        });

        const valueWrap = document.createElement('div');
        valueWrap.className = 'mkt-rule-value-wrap';
        valueWrap.appendChild(buildValueInput(attribute, operatorSelect.value, rule.value));

        const remove = document.createElement('button');
        remove.type = 'button';
        remove.className = 'mkt-btn mkt-btn-sm mkt-btn-danger';
        remove.textContent = 'Remove';
        remove.addEventListener('click', () => { row.remove(); sync(); });

        const source = document.createElement('div');
        source.className = 'mkt-rule-source';
        source.textContent = attribute ? `Source: ${attribute.source}` : '';

        attributeSelect.addEventListener('change', () => {
            renderRule(row, { attribute: attributeSelect.value, operator: '', value: '' });
            sync();
        });
        operatorSelect.addEventListener('change', () => {
            valueWrap.innerHTML = '';
            valueWrap.appendChild(buildValueInput(attributeByKey(attributeSelect.value), operatorSelect.value, ''));
            sync();
        });
        valueWrap.addEventListener('input', sync);
        valueWrap.addEventListener('change', sync);

        row.append(attributeSelect, operatorSelect, valueWrap, remove, source);
    }

    function collect() {
        const list = document.getElementById('mkt-rule-list');
        if (!list) return { match: 'all', rules: [] };
        const matchEl = document.getElementById('mkt-match');
        const rules = Array.from(list.querySelectorAll('.mkt-rule')).map((row) => {
            const valueEl = row.querySelector('.mkt-rule-value');
            const operator = row.querySelector('.mkt-rule-operator')?.value || '';
            const spec = OPERATORS[operator] || {};
            let value = valueEl ? valueEl.value : '';
            if (spec.multi && typeof value === 'string') {
                value = value.split(',').map((v) => v.trim()).filter(Boolean);
            }
            return {
                attribute: row.querySelector('.mkt-rule-attribute')?.value || '',
                operator,
                value
            };
        }).filter((rule) => rule.attribute && rule.operator);
        return { match: matchEl ? matchEl.value : 'all', rules };
    }

    let estimateTimer = null;

    function sync() {
        const hidden = document.getElementById('mkt-definition-json');
        const definition = collect();
        if (hidden) hidden.value = JSON.stringify(definition);
        const preview = document.getElementById('mkt-rule-preview');
        if (!preview) return;
        clearTimeout(estimateTimer);
        estimateTimer = setTimeout(() => refreshPreview(definition, preview), 350);
    }

    async function refreshPreview(definition, preview) {
        if (!definition.rules.length) {
            preview.innerHTML = '<span class="mkt-muted">Add a rule to see the audience definition.</span>';
            return;
        }
        try {
            const response = await fetch('/portals/marketing/api/segments/estimate', {
                method: 'POST',
                credentials: 'same-origin',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ definition })
            });
            const data = await response.json();
            if (!data.ok) {
                preview.innerHTML = '<span class="mkt-muted">'
                    + Object.values(data.errors || { _: 'Rules are incomplete.' }).join(' ')
                    + '</span>';
                return;
            }
            const lines = (data.rules || []).map((text) => `<li>${escapeHtml(text)}</li>`).join('');
            const sources = (data.sources || [])
                .map((s) => `<span class="mkt-chip ${s.connected ? 'mkt-chip-ok' : 'mkt-chip-warn'}">${escapeHtml(s.label)}</span>`)
                .join(' ');
            const size = data.available
                ? `<strong>${data.value}</strong> subscribers match`
                : `<span class="mkt-muted">${escapeHtml(data.reason || '')}</span>`;
            preview.innerHTML = `<ul class="mkt-rule-list">${lines}</ul>
                <div style="margin-top:10px">${size}</div>
                <div style="margin-top:8px;display:flex;gap:6px;flex-wrap:wrap">${sources}</div>`;
        } catch (_) {
            preview.innerHTML = '<span class="mkt-muted">Preview unavailable.</span>';
        }
    }

    function escapeHtml(value) {
        const div = document.createElement('div');
        div.textContent = String(value === undefined || value === null ? '' : value);
        return div.innerHTML;
    }

    function initRuleBuilder() {
        const list = document.getElementById('mkt-rule-list');
        if (!list) return;
        const initial = window.MKT_DEFINITION || { match: 'all', rules: [] };

        function addRow(rule) {
            const row = document.createElement('div');
            list.appendChild(row);
            renderRule(row, rule || { attribute: '', operator: '', value: '' });
            sync();
        }

        (initial.rules || []).forEach(addRow);
        document.getElementById('mkt-add-rule')?.addEventListener('click', () => addRow(null));
        document.getElementById('mkt-match')?.addEventListener('change', sync);
        sync();
    }

    function initChannelToggles() {
        document.querySelectorAll('[data-channel-toggle]').forEach((checkbox) => {
            const detail = document.getElementById(`channel-detail-${checkbox.value}`);
            if (!detail) return;
            const apply = () => { detail.hidden = !checkbox.checked; };
            checkbox.addEventListener('change', apply);
            apply();
        });
    }

    document.addEventListener('DOMContentLoaded', () => {
        initRuleBuilder();
        initChannelToggles();
    });
})();
