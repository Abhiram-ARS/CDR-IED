
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
    const searchColumns = document.getElementById('searchColumns');
    const searchResults = document.getElementById('searchResults');
    const filterBtn = document.getElementById('filterBtn');
    const filterModal = document.getElementById('filterModal');
    const filterModalClose = document.getElementById('filterModalClose');
    const filterApplyBtn = document.getElementById('filterApplyBtn');
    const filterFieldList = document.getElementById('filterFieldList');
    const filterInput = document.getElementById('filterInput');
    const applySearchBtn = document.getElementById('applySearchBtn');
    const refreshBtn = document.getElementById('refreshBtn');
    const pdfExportBtn = document.getElementById('pdfExportBtn');
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

        const headings = ['Si No'].concat(REQUIRED_COLS);
        const headingHtml = headings.map((heading) => {
            return '<th>' + escapeHtml(heading) + '</th>';
        }).join('');
        const rowsHtml = matches.map((item) => {
            const values = [item.si].concat(
                REQUIRED_COLS.map((column) => item.row[column] || '')
            );
            return '<tr>' + values.map((value) => {
                return '<td>' + escapeHtml(value) + '</td>';
            }).join('') + '</tr>';
        }).join('');

        searchResults.innerHTML =
            '<div style="padding:8px 10px;background:#f8f8f8;border-bottom:1px solid #eee;">' +
                'Matches for <b>' + escapeHtml(field) + '</b>: <b>' + escapeHtml(query) + '</b> (' + matches.length + ')' +
            '</div>' +
            '<table>' +
                        '<thead><tr>' + headingHtml + '</tr></thead>' +
                        '<tbody>' + rowsHtml + '</tbody>' +
                    '</table>';
    }

    function renderSearchColumns(row){
        const rowsHtml = REQUIRED_COLS.map((column) => {
            return '<tr>' +
                '<th>' + escapeHtml(column) + '</th>' +
                '<td class="search-copy-value">' + escapeHtml(row[column] || '') + '</td>' +
                '<td><button class="btn search-copy-btn" type="button" ' +
                    'data-copy-column="' + escapeHtml(column) + '">Copy</button></td>' +
            '</tr>';
        }).join('');

        searchColumns.innerHTML =
            '<div style="padding:8px 10px;background:#f8f8f8;border-bottom:1px solid #eee;">' +
                'Selected record columns' +
            '</div>' +
            '<table><tbody>' + rowsHtml + '</tbody></table>';

        searchColumns.querySelectorAll('[data-copy-column]').forEach((button) => {
            button.addEventListener('click', () => {
                const column = button.dataset.copyColumn;
                const value = String(row[column] || '');
                const showCopied = () => {
                    button.textContent = 'Copied';
                    setTimeout(() => { button.textContent = 'Copy'; }, 1000);
                };
                const fallbackCopy = () => {
                    searchText.value = value;
                    searchText.select();
                    document.execCommand('copy');
                    showCopied();
                };

                if(navigator.clipboard && navigator.clipboard.writeText){
                    navigator.clipboard.writeText(value).then(showCopied).catch(fallbackCopy);
                } else {
                    fallbackCopy();
                }
            });
        });
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

    function renderStatisticsCards(statistics){
        if(!statistics || !statistics.length){
            return '<div class="statistics-empty">No statistics images are available.</div>';
        }

        return statistics.map((statistic) => {
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
    }

    function renderAlertCards(alerts){
        if(!alerts || !alerts.length){
            return '<div class="statistics-empty">No suspicious activity detected.</div>';
        }

        return '<div class="alerts-list">' + alerts.map((alert) => {
            const severityClass = alert.severity === 'High' ? ' alert-high' : '';
            return '<div class="alert-card' + severityClass + '">' +
                '<div class="alert-title">' +
                    '<span>B-Party: ' + escapeHtml(alert.b_party) + '</span>' +
                    '<span class="alert-severity">' + escapeHtml(alert.severity) + '</span>' +
                '</div>' +
                '<div class="alert-detail">' + escapeHtml(alert.message) + '</div>' +
                '<div class="alert-detail"><b>IMEI:</b> ' +
                    escapeHtml(alert.imeis.join(', ') || 'Not available') + '</div>' +
                '<div class="alert-detail"><b>IMSI:</b> ' +
                    escapeHtml(alert.imsis.join(', ') || 'Not available') + '</div>' +
                '<div class="alert-detail"><b>Records:</b> ' +
                    escapeHtml(alert.record_count) + '</div>' +
            '</div>';
        }).join('') + '</div>';
    }

    function renderDetailsDashboard(statistics, alerts){
        detailsPane.innerHTML =
            '<div class="details-dashboard">' +
                '<section class="details-section">' +
                    '<h2 class="details-section-heading">Statistics</h2>' +
                    '<div class="details-statistics">' +
                        renderStatisticsCards(statistics) +
                    '</div>' +
                '</section>' +
                '<section class="details-section">' +
                    '<h2 class="details-section-heading">Suspicious Detections / Alerts</h2>' +
                    renderAlertCards(alerts) +
                '</section>' +
            '</div>';

        detailsPane.querySelectorAll('[data-statistic-id]').forEach((card) => {
            card.addEventListener('click', () => {
                openStatisticsWindow(card.dataset.statisticId);
            });
        });
    }

    async function exportDisplayedPdf(){
        const displayedRecords = rowsData;
        const activeFilters = { expression: filterInput.value.trim() };

        try {
            const result = await window.pywebview.api.export_cdr_pdf(displayedRecords, activeFilters);
            if(!result.success){
                setStatus(result.error || 'Unable to export PDF.', true);
                return;
            }
            setStatus('PDF exported: ' + result.path, false);
            window.alert('PDF export completed successfully.\n\nSaved to:\n' + result.path);
        } catch(err) {
            setStatus('Error exporting PDF: ' + err, true);
        }
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
        renderSearchColumns(r);
        searchResults.innerHTML =
            '<div style="padding:10px;color:#666;">Click Search to find matching B-Party records.</div>';
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
    pdfExportBtn.addEventListener('click', exportDisplayedPdf);
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
                renderDetailsDashboard(result.statistics, result.alerts);
            }).catch(err => {
                setStatus('Error processing CSV: ' + err, true);
            });
        };
        reader.onerror = () => { setStatus('Failed to read file.', true); };
        reader.readAsText(f);
    });

    // initial state
    filterFieldList.innerHTML = REQUIRED_COLS.map((column) => {
        return '<label><input type="checkbox" name="filterField" value="' +
            escapeHtml(column) + '"> ' + escapeHtml(column) + '</label>';
    }).join('');
    tbody.innerHTML = '';
    searchColumns.innerHTML =
        '<div style="padding:10px;color:#666;">Click a record to view all columns.</div>';
    searchResults.innerHTML =
        '<div style="padding:10px;color:#666;">Search results will appear here.</div>';
    setStatus('Records: 0', false);
    
    // Wait for pywebview API to be ready
    window.addEventListener('pywebviewready', () => {
        console.log('PyWebView API is ready');
        setStatus('Ready. Upload a CSV file to get started.', false);
    });
})();
