
(function(){
    // rowsData holds parsed data rows from Python backend
    let rowsData = [];
    const REQUIRED_COLS = ['A-Party','B-Party','Call Type','Start Date','Start Time','Duration','IMEI','IMSI','Cell ID','Call Status'];
    
    // DOM element references
    const fileInput = document.getElementById('csvFileInput');
    const tbody = document.getElementById('packetBody');
    const statusLbl = document.getElementById('statusLbl');
    const statusBar = document.getElementById('statusBar');
    const selectionInfo = document.getElementById('selectionInfo');
    const modal = document.getElementById('detailModal');
    const modalBody = document.getElementById('modalBody');
    const modalClose = document.getElementById('modalClose');
    const searchText = document.getElementById('searchText');
    const searchBtn = document.getElementById('searchBtn');
    const searchResults = document.getElementById('searchResults');
    const filterBtn = document.getElementById('filterBtn');
    const filterModal = document.getElementById('filterModal');
    const filterModalClose = document.getElementById('filterModalClose');
    const filterApplyBtn = document.getElementById('filterApplyBtn');
    const filterInput = document.getElementById('filterInput');
    const applySearchBtn = document.getElementById('applySearchBtn');
    const refreshBtn = document.getElementById('refreshBtn');
    const statisticsBtn = document.getElementById('statisticsBtn');
    const detailsPane = document.getElementById('detailsPane');
    // ============ UI Utility Functions ============

    function setStatus(message, isError){
        statusLbl.textContent = message;
        statusBar.classList.toggle('error', !!isError);
    }

    function escapeHtml(value){
        return (value || '').toString()
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function renderSearchResults(matches, field, query){
        if(!query){
            searchResults.innerHTML = '<div style="padding:10px;color:#666;">Enter a value and click Search.</div>';
            return;
        }

        if(!matches.length){
            searchResults.innerHTML = '<div style="padding:10px;color:#a00;">No matching records found.</div>';
            return;
        }

        const rowsHtml = matches.map((item) => {
            return '<tr>' +
                '<td>' + escapeHtml(item.si) + '</td>' +
                '<td>' + escapeHtml(item.row["A-Party"]) + '</td>' +
                '<td>' + escapeHtml(item.row["B-Party"]) + '</td>' +
                '<td>' + escapeHtml(item.row["Call Type"]) + '</td>' +
                '<td>' + escapeHtml(item.row["Start Date"]) + '</td>' +
                '<td>' + escapeHtml(item.row["Start Time"]) + '</td>' +
                '</tr>';
        }).join('');

        searchResults.innerHTML =
            '<div style="padding:8px 10px;background:#f8f8f8;border-bottom:1px solid #eee;">' +
                'Matches for <b>' + escapeHtml(field) + '</b>: <b>' + escapeHtml(query) + '</b> (' + matches.length + ')' +
            '</div>' +
            '<table>' +
                '<thead><tr><th>Si No</th><th>A-Party</th><th>B-Party</th><th>Call Type</th><th>Start Date</th><th>Start Time</th></tr></thead>' +
                '<tbody>' + rowsHtml + '</tbody>' +
            '</table>';
    }

    function performSearch(){
        const field = 'B-Party';
        const query = searchText.value.trim();
        if(!query){
            searchResults.innerHTML = '<div style="padding:10px;color:#666;">Enter a value and click Search.</div>';
            return;
        }
        // Call Python backend to search
        window.pywebview.api.search_by_field(field, query).then(matches => {
            renderSearchResults(matches, field, query);
        }).catch(err => {
            searchResults.innerHTML = '<div style="padding:10px;color:#a00;">Error performing search: ' + escapeHtml(err) + '</div>';
        });
    }

    function getSelectedFilterLabels(){
        return Array.from(document.querySelectorAll('input[name="filterField"]:checked')).map((input) => input.value);
    }

    function openFilterModal(){
        filterModal.style.display = 'flex';
    }

    function closeFilterModal(){
        filterModal.style.display = 'none';
    }

    function applyFilterSelection(){
        const selected = getSelectedFilterLabels();
        filterInput.value = selected.map((field) => field + ' = ').join(', ');
        closeFilterModal();
        filterInput.focus();
    }

    function applyDisplayedFilters(){
        const expression = filterInput.value.trim();
        window.pywebview.api.filter_records(expression).then(result => {
            if(!result.success){
                setStatus(result.error, true);
                return;
            }

            renderRows(result.data);
            setStatus(`Showing ${result.count} of ${result.total} records`, false);
            selectionInfo.textContent = `Filters: ${result.filter_count}`;
        }).catch(err => {
            setStatus('Error applying filters: ' + err, true);
        });
    }

    function clearDisplayedFilters(){
        filterInput.value = '';
        window.pywebview.api.get_all_records().then(result => {
            renderRows(result.data);
            selectionInfo.textContent = 'Selected: None';
        }).catch(err => {
            setStatus('Error refreshing records: ' + err, true);
        });
    }

    function openStatisticsWindow(statisticId){
        window.pywebview.api.open_statistics_window(statisticId).then(result => {
            if(!result.success){
                setStatus(result.error, true);
            }
        }).catch(err => {
            setStatus('Error opening Matplotlib window: ' + err, true);
        });
    }

    function renderStatistics(statistics){
        if(!statistics || !statistics.length){
            detailsPane.innerHTML =
                '<div class="statistics-empty">No statistics images are available.</div>';
            return;
        }

        const cards = statistics.map((statistic) => {
            return '<button class="statistics-chart-card" type="button" ' +
                'data-statistic-id="' + escapeHtml(statistic.id) + '" ' +
                'title="Open interactive Matplotlib window">' +
                '<div class="statistics-chart-title">' +
                    escapeHtml(statistic.title) +
                '</div>' +
                '<img class="statistics-chart-image" src="' +
                    escapeHtml(statistic.preview) +
                    '" alt="' + escapeHtml(statistic.title) + '">' +
            '</button>';
        }).join('');

        detailsPane.innerHTML =
            '<div class="details-statistics">' +
                '<h2 class="statistics-heading">Statistics</h2>' +
                cards +
            '</div>';

        detailsPane.querySelectorAll('[data-statistic-id]').forEach((card) => {
            card.addEventListener('click', () => {
                openStatisticsWindow(card.dataset.statisticId);
            });
        });
    }

    function loadStatistics(){
        window.pywebview.api.get_statistics().then(result => {
            renderStatistics(result.statistics);
        }).catch(err => {
            setStatus('Error loading statistics: ' + err, true);
        });
    }

    // ============ Event Handlers ============

    function renderRows(rows, headerMap){
        tbody.innerHTML = '';
        rowsData = rows || [];
        rows.forEach((r, i) => {
            const tr = document.createElement('tr');
            const obj = r; // Data is already processed by Python
            rowsData[i] = obj;
            const cells = REQUIRED_COLS.map(col => obj[col] || '');
            // prepend serial number as first cell
            const si = i + 1;
            tr.innerHTML = [`<td>${si}</td>`].concat(cells.map(c => `<td>${escapeHtml(c)}</td>`)).join('');
            tr.addEventListener('click', () => showDetails(i, tr));
            tbody.appendChild(tr);
        });
        setStatus(`Records: ${rows.length}`, false);
    }

    function showDetails(index, trElement){
        // highlight selection
        Array.from(tbody.children).forEach(r => r.classList.remove('selected'));
        if(trElement) trElement.classList.add('selected');

        const r = rowsData[index] || {};
        searchText.value = r['B-Party'] || '';
        renderSearchResults([{ si: index + 1, row: r }], 'B-Party', searchText.value.trim());
        modal.style.display = 'flex';
        searchText.focus();
    }

    // modal close handlers
    modalClose.addEventListener('click', () => { modal.style.display = 'none'; });
    modal.addEventListener('click', (e) => { if(e.target === modal) modal.style.display = 'none'; });
    document.addEventListener('keydown', (e) => { if(e.key === 'Escape') modal.style.display = 'none'; });
    searchBtn.addEventListener('click', performSearch);
    searchText.addEventListener('keydown', (e) => {
        if(e.key === 'Enter'){
            e.preventDefault();
            performSearch();
        }
    });

    filterBtn.addEventListener('click', openFilterModal);
    filterModalClose.addEventListener('click', closeFilterModal);
    filterModal.addEventListener('click', (e) => { if(e.target === filterModal) closeFilterModal(); });
    filterApplyBtn.addEventListener('click', applyFilterSelection);
    applySearchBtn.addEventListener('click', applyDisplayedFilters);
    refreshBtn.addEventListener('click', clearDisplayedFilters);
    statisticsBtn.addEventListener('click', loadStatistics);
    filterInput.addEventListener('keydown', (e) => {
        if(e.key === 'Enter'){
            e.preventDefault();
            applyDisplayedFilters();
        }
    });

    fileInput.addEventListener('change', (ev) => {
        const f = ev.target.files && ev.target.files[0];
        if(!f) return;
        selectionInfo.textContent = `Selected: ${f.name}`;
        const reader = new FileReader();
        reader.onload = (e) => {
            const text = e.target.result;
            // Call Python backend to process CSV
            window.pywebview.api.process_csv_data(text).then(result => {
                if(!result.success){
                    setStatus(result.error, true);
                    return;
                }
                // Store data and render rows
                renderRows(result.data, null); // Pass null for headerMap since data is already processed
                renderStatistics(result.statistics);
            }).catch(err => {
                setStatus('Error processing CSV: ' + err, true);
            });
        };
        reader.onerror = () => { setStatus('Failed to read file.', true); };
        reader.readAsText(f);
    });

    // initial state
    tbody.innerHTML = '';
    searchResults.innerHTML = '<div style="padding:10px;color:#666;">Click a row to open search.</div>';
    setStatus('Records: 0', false);
    
    // Wait for pywebview API to be ready
    window.addEventListener('pywebviewready', () => {
        console.log('PyWebView API is ready');
        setStatus('Ready. Upload a CSV file to get started.', false);
    });
})();