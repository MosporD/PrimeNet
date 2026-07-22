(function () {
    const searchInput = document.getElementById('pbi-search');
    const grid = document.getElementById('pbi-grid');
    const countEl = document.getElementById('pbi-count');
    const emptyFilter = document.getElementById('pbi-empty-filter');

    if (!searchInput || !grid) {
        return;
    }

    const cards = Array.from(grid.querySelectorAll('.pbi-card'));
    const total = cards.length;

    function updateFilter() {
        const query = (searchInput.value || '').trim().toLowerCase();
        let visible = 0;

        cards.forEach((card) => {
            const title = (card.dataset.title || card.textContent || '').toLowerCase();
            const slug = (card.dataset.slug || '').toLowerCase();
            const match = !query || title.includes(query) || slug.includes(query);
            card.hidden = !match;
            if (match) {
                visible += 1;
            }
        });

        if (countEl) {
            countEl.textContent = query
                ? `${visible} of ${total} reports`
                : `${total} report${total === 1 ? '' : 's'}`;
        }
        if (emptyFilter) {
            emptyFilter.hidden = visible > 0;
        }
    }

    searchInput.addEventListener('input', updateFilter);
})();
