// Amplifier Log Viewer - Network tab-style interface with progressive loading

// One-shot guard: many in-flight requests can 401 simultaneously; only the
// first should navigate.
let _authRedirecting = false;

function handleUnauthorized(response) {
    if (response.status !== 401) return false;
    if (_authRedirecting) return true;
    _authRedirecting = true;
    const next = encodeURIComponent(location.pathname + location.search);
    location.href = `${API_BASE}/login?next=${next}`;
    return true;
}

function renderOverviewSections(container, sections) {
    const grid = document.createElement('div');
    grid.className = 'overview-grid';

    sections.forEach(({ title, rows }) => {
        const section = document.createElement('div');
        section.className = 'overview-section';

        const heading = document.createElement('h4');
        heading.textContent = title;
        section.appendChild(heading);

        const table = document.createElement('table');
        table.className = 'detail-table';
        rows.forEach(([label, value]) => {
            const row = document.createElement('tr');
            const labelCell = document.createElement('td');
            const valueCell = document.createElement('td');
            labelCell.textContent = label;
            valueCell.textContent = String(value);
            row.appendChild(labelCell);
            row.appendChild(valueCell);
            table.appendChild(row);
        });
        section.appendChild(table);
        grid.appendChild(section);
    });

    container.replaceChildren(grid);
}

function renderJsonFallback(container, data) {
    const pre = document.createElement('pre');
    pre.className = 'json-display';
    pre.textContent = JSON.stringify(data, null, 2);
    container.replaceChildren(pre);
}

class LogViewer {
    constructor(apiBase = "") {
        this.projects = [];
        this.sessions = [];
        this.events = [];           // Lightweight event headers
        this.filteredEvents = [];
        this.selectedEvent = null;  // Full event data (fetched on demand)
        this.selectedEventIndex = null;
        this.currentSessionId = null;
        this.eventStream = null;
        this.isRestoringState = false;  // Flag to prevent saving during restore
        
        // API base path for app-specific routing (e.g., '/amplifier/logs')
        this.apiBase = apiBase;

        // Event detail cache: line_num -> full event data
        this.eventCache = new Map();
        this.EVENT_CACHE_MAX = 50;  // Keep last 50 viewed events

        // --- Full-session load ---
        this.FIRST_PAGE_LIMIT = 200;    // phase 1 — unchanged first-paint cost
        this.PAGE_LIMIT = 5000;         // phase 2 — server's max (server.py:392)
        this.AUTO_LOAD_MAX = 20000;     // auto-complete ceiling
        this.MAX_PAGES = 64;            // hard stop against a pathological loop
        this._loadToken = 0;            // invalidates in-flight pages when the session changes
        this.loadComplete = false;      // true when this.events holds the whole session
        this.eventsTotal = 0;           // server-reported line total for the session
        this.knownEventTypes = new Set();
        this._desiredEventType = '';    // persisted type filter, applied once it becomes available

        // --- Windowed render (events view only; transcript is unaffected) ---
        this.RENDER_CHUNK = 200;        // rows added per window growth step
        this.SCROLL_EXTEND_PX = 400;    // proximity to an edge that triggers a grow
        this.PIN_TOLERANCE_PX = 40;     // "user is parked at the bottom"
        this.renderStart = 0;
        this.renderEnd = 0;
        this._extending = false;

        // Transcript view state
        this.viewMode = 'events';              // 'events' | 'transcript'
        this.transcriptMessages = [];
        this.filteredMessages = [];
        this.selectedMessageIndex = null;
        this.sessionCaps = { has_events: true, has_transcript: false };

        // LocalStorage keys
        this.STORAGE_PREFIX = 'amplifier-log-viewer-';
        
        // State persistence keys
        this.STATE_KEYS = {
            lastProject: 'lastProject',
            lastSession: 'lastSession',
            filters: 'filters',
            sortByTimestamp: 'sortByTimestamp',
            activeTab: 'activeTab',
            selectedEventId: 'selectedEventId',
            detailPanelScroll: 'detailPanelScroll',
            dateRange: 'dateRange',
            viewMode: 'viewMode',
        };

        // DOM elements
        this.dateRangeSelector = document.getElementById('date-range-selector');
        this.customDateInputs = document.getElementById('custom-date-inputs');
        this.dateFrom = document.getElementById('date-from');
        this.dateTo = document.getElementById('date-to');
        this.projectSelector = document.getElementById('project-selector');
        this.sessionSelector = document.getElementById('session-selector');
        this.refreshBtn = document.getElementById('refresh-btn');
        this.sortByTimestampCheckbox = document.getElementById('sort-by-timestamp-checkbox');
        this.filterInput = document.getElementById('filter-input');
        this.levelFilter = document.getElementById('level-filter');
        this.eventTypeFilter = document.getElementById('event-type-filter');
        this.eventFilters = document.getElementById('event-filters');
        this.viewToggle = document.getElementById('view-toggle');
        this.clearFiltersBtn = document.getElementById('clear-filters');
        this.filterCount = document.getElementById('filter-count');
        this.eventListContent = document.getElementById('event-list-content');
        this.dataViewer = document.getElementById('data-viewer');
        this.rawJson = document.getElementById('raw-json');
        this.copyEventBtn = document.getElementById('copy-event-btn');
        this.copyRawBtn = document.getElementById('copy-raw-btn');
        this.closeDetailBtn = document.getElementById('close-detail-btn');
        this.scanStatus = document.getElementById('scan-status');
        this.scanText = this.scanStatus?.querySelector('.scan-text');
        this.jumpLatestBtn = document.getElementById('jump-latest-btn');
        this.loadBanner = document.getElementById('event-load-banner');

        // Status polling
        this.statusPollInterval = null;

        this.init();
    }

    // URL building helper for app-specific routing
    buildUrl(path) {
        return this.apiBase + path;
    }

    // fetch() wrapper that redirects to /login on a 401 instead of letting
    // the caller silently treat it as "no data" -- see handleUnauthorized().
    async apiFetch(path, options) {
        const response = await fetch(this.buildUrl(path), options);
        if (handleUnauthorized(response)) {
            throw new Error('unauthenticated');
        }
        return response;
    }


    // LocalStorage helpers
    saveToStorage(key, value) {
        try {
            localStorage.setItem(this.STORAGE_PREFIX + key, JSON.stringify(value));
        } catch (e) {
            console.warn('Failed to save to localStorage:', e);
        }
    }

    loadFromStorage(key, defaultValue = null) {
        try {
            const stored = localStorage.getItem(this.STORAGE_PREFIX + key);
            return stored ? JSON.parse(stored) : defaultValue;
        } catch (e) {
            console.warn('Failed to load from localStorage:', e);
            return defaultValue;
        }
    }

    init() {
        // Restore all persisted state from localStorage
        this.restoreDateRange();
        this.restoreFilterState();
        this.restoreSortPreference();
        this.restoreActiveTab();
        this.restoreViewMode();

        // Load projects on startup
        this.loadProjects();

        // Setup event listeners
        this.dateRangeSelector.addEventListener('change', () => this.onDateRangeChange());
        this.dateFrom.addEventListener('change', () => this.onCustomDateChange());
        this.dateTo.addEventListener('change', () => this.onCustomDateChange());
        this.projectSelector.addEventListener('change', () => this.onProjectChange());
        this.sessionSelector.addEventListener('change', () => this.onSessionChange());
        this.refreshBtn.addEventListener('click', () => this.refresh());
        this.sortByTimestampCheckbox.addEventListener('change', () => this.onSortPreferenceChange());
        
        // Windowed-render scroll handler (grows the render window near either edge)
        this.eventListContent.addEventListener('scroll', () => this.onEventListScroll());

        // Refresh when dropdowns are opened (focused)
        this.projectSelector.addEventListener('focus', () => this.refreshProjectList());
        this.sessionSelector.addEventListener('focus', () => this.refreshSessionList());
        this.clearFiltersBtn.addEventListener('click', () => this.clearFilters());

        // Filter listeners with debounce and localStorage save
        let filterTimeout;
        const applyFiltersDebounced = () => {
            clearTimeout(filterTimeout);
            filterTimeout = setTimeout(() => {
                this.saveFilterState();
                this.applyFilters();
            }, 300);
        };
        this.filterInput.addEventListener('input', applyFiltersDebounced);
        this.levelFilter.addEventListener('change', () => {
            this.saveFilterState();
            this.applyFilters();
        });
        this.eventTypeFilter.addEventListener('change', () => {
            this._desiredEventType = this.eventTypeFilter.value;
            this.saveFilterState();
            this.applyFilters();
        });

        // Tab switching (with persistence)
        document.querySelectorAll('.tab-button').forEach(btn => {
            btn.addEventListener('click', () => {
                this.switchTab(btn.dataset.tab);
                this.saveToStorage(this.STATE_KEYS.activeTab, btn.dataset.tab);
            });
        });

        // Start status polling
        this.startStatusPolling();

        // Copy buttons
        this.copyEventBtn.addEventListener('click', () => this.copyCurrentEvent());
        this.copyRawBtn.addEventListener('click', () => this.copyRawJson());
        this.closeDetailBtn.addEventListener('click', () => this.closeDetail());

        // Jump to latest (events view) — pairs with the tail-poll auto-follow-when-pinned behavior
        if (this.jumpLatestBtn) this.jumpLatestBtn.addEventListener('click', () => this.jumpToLatest());

        // View mode toggle (Events / Transcript)
        if (this.viewToggle) {
            this.viewToggle.querySelectorAll('.view-btn').forEach(btn => {
                btn.addEventListener('click', () => this.setViewMode(btn.dataset.view));
            });
        }
    }

    saveFilterState() {
        this.saveToStorage('filters', {
            search: this.filterInput.value,
            level: this.levelFilter.value,
            eventType: this.eventTypeFilter.value
        });
    }

    restoreFilterState() {
        const filters = this.loadFromStorage('filters', {});
        if (filters.search) this.filterInput.value = filters.search;
        if (filters.level) this.levelFilter.value = filters.level;
        if (filters.eventType) this.eventTypeFilter.value = filters.eventType;
    }

    restoreSortPreference() {
        const sortByTimestamp = this.loadFromStorage(this.STATE_KEYS.sortByTimestamp, false);
        this.sortByTimestampCheckbox.checked = sortByTimestamp;
    }

    restoreDateRange() {
        // Default to '2d' (last 2 days) if no saved preference
        const saved = this.loadFromStorage(this.STATE_KEYS.dateRange, { preset: '2d' });
        
        // Handle legacy string format (just the preset value)
        if (typeof saved === 'string') {
            this.dateRangeSelector.value = saved;
            this.updateCustomDateVisibility();
            return;
        }
        
        // New object format with preset and custom dates
        this.dateRangeSelector.value = saved.preset || '2d';
        if (saved.preset === 'custom' && saved.from && saved.to) {
            this.dateFrom.value = saved.from;
            this.dateTo.value = saved.to;
        }
        this.updateCustomDateVisibility();
    }

    onDateRangeChange() {
        const preset = this.dateRangeSelector.value;
        
        // Show/hide custom date inputs
        this.updateCustomDateVisibility();
        
        if (preset === 'custom') {
            // Set default custom range to last 7 days if not already set
            if (!this.dateFrom.value || !this.dateTo.value) {
                const today = new Date();
                const weekAgo = new Date(today);
                weekAgo.setDate(weekAgo.getDate() - 7);
                this.dateTo.value = today.toISOString().split('T')[0];
                this.dateFrom.value = weekAgo.toISOString().split('T')[0];
            }
            this.saveCustomDateState();
            this.loadProjects();
        } else {
            // Save preset and reload
            this.saveToStorage(this.STATE_KEYS.dateRange, { preset });
            this.loadProjects();
        }
    }

    onCustomDateChange() {
        // Only trigger reload if both dates are set
        if (this.dateFrom.value && this.dateTo.value) {
            this.saveCustomDateState();
            this.loadProjects();
        }
    }

    saveCustomDateState() {
        this.saveToStorage(this.STATE_KEYS.dateRange, {
            preset: 'custom',
            from: this.dateFrom.value,
            to: this.dateTo.value
        });
    }

    updateCustomDateVisibility() {
        const isCustom = this.dateRangeSelector.value === 'custom';
        this.customDateInputs.style.display = isCustom ? 'flex' : 'none';
    }

    getDateRangeParams() {
        // Return object with since/until params for API calls
        const preset = this.dateRangeSelector.value;
        
        if (preset === 'custom') {
            return {
                since: this.dateFrom.value || '',
                until: this.dateTo.value || ''
            };
        }
        
        return {
            since: preset || '',
            until: ''
        };
    }

    restoreActiveTab() {
        const activeTab = this.loadFromStorage(this.STATE_KEYS.activeTab, 'overview');
        // Validate the tab exists before switching
        const validTabs = ['overview', 'data', 'raw'];
        if (validTabs.includes(activeTab) && activeTab !== 'overview') {
            // Defer tab switch to ensure DOM is ready
            requestAnimationFrame(() => {
                this.switchTab(activeTab);
            });
        }
    }

    restoreViewMode() {
        const savedMode = this.loadFromStorage(this.STATE_KEYS.viewMode, 'events');
        const mode = savedMode === 'transcript' ? 'transcript' : 'events';
        // No session loaded yet at this point, so reload is a no-op; this
        // only syncs the toggle buttons/placeholder to the saved preference.
        this.setViewMode(mode, { reload: false });
    }

    saveSelectedEvent() {
        // Don't save during restore phase - this prevents overwriting saved state
        if (this.isRestoringState) {
            return;
        }
        
        if (this.selectedEvent && this.currentSessionId) {
            // Save by line number + session for reliable matching across reloads
            this.saveToStorage(this.STATE_KEYS.selectedEventId, {
                sessionId: this.currentSessionId,
                line: this.selectedEvent.line,
                ts: this.selectedEvent.ts,
                event: this.selectedEvent.event,
                index: this.selectedEventIndex
            });
        } else {
            this.saveToStorage(this.STATE_KEYS.selectedEventId, null);
        }
    }

    restoreSelectedEvent() {
        this.isRestoringState = true;

        const saved = this.loadFromStorage(this.STATE_KEYS.selectedEventId, null);
        if (!saved || this.filteredEvents.length === 0) {
            this.isRestoringState = false;
            return;
        }

        // Try to find by line number first (most reliable)
        let foundIndex = this.filteredEvents.findIndex(e => e.line === saved.line);

        // Fallback: try exact match (ts + event type)
        if (foundIndex === -1) {
            foundIndex = this.filteredEvents.findIndex(e => 
                e.ts === saved.ts && e.event === saved.event
            );
        }

        // Fallback: try saved index if within bounds
        if (foundIndex === -1 && saved.index !== undefined) {
            if (saved.index >= 0 && saved.index < this.filteredEvents.length) {
                foundIndex = saved.index;
            }
        }

        // Select the event if found
        if (foundIndex !== -1) {
            this.ensureIndexRendered(foundIndex);     // the row must exist before we select/scroll to it
            this.selectEvent(foundIndex);
            // Scroll the selected item into view
            const selectedItem = this.eventListContent.querySelector(`[data-index="${foundIndex}"]`);
            if (selectedItem) {
                selectedItem.scrollIntoView({ block: 'center', behavior: 'instant' });
            }
        }

        this.isRestoringState = false;
    }

    onSortPreferenceChange() {
        // Save preference
        this.saveToStorage(this.STATE_KEYS.sortByTimestamp, this.sortByTimestampCheckbox.checked);

        // Re-render session list with new sort order
        this.renderSessionList();
    }

    sortSessions(sessions) {
        // Create a copy to avoid mutating original
        const sorted = [...sessions];

        if (this.sortByTimestampCheckbox.checked) {
            // Sort by timestamp: no timestamp at top, then most recent first
            sorted.sort((a, b) => {
                const aHasTs = !!a.timestamp;
                const bHasTs = !!b.timestamp;

                // No timestamp goes first
                if (!aHasTs && bHasTs) return -1;
                if (aHasTs && !bHasTs) return 1;
                if (!aHasTs && !bHasTs) return 0;

                // Both have timestamps - sort descending (most recent first)
                return b.timestamp.localeCompare(a.timestamp);
            });
        } else {
            // Sort by session ID (default)
            sorted.sort((a, b) => a.id.localeCompare(b.id));
        }

        return sorted;
    }

    async loadProjects() {
        try {
            const { since, until } = this.getDateRangeParams();
            let url = '/api/projects';
            const params = [];
            if (since) params.push(`since=${since}`);
            if (until) params.push(`until=${until}`);
            if (params.length) url += '?' + params.join('&');
            const response = await this.apiFetch(url);
            const data = await response.json();
            this.projects = data.projects || [];

            this.projectSelector.innerHTML = '<option value="">Select project...</option>';
            this.projects.forEach(project => {
                const option = document.createElement('option');
                option.value = project.slug;
                option.textContent = `${project.slug} (${project.session_count} sessions)`;
                this.projectSelector.appendChild(option);
            });

            // Restore last selected project or auto-select first
            const lastProject = this.loadFromStorage(this.STATE_KEYS.lastProject);
            if (lastProject && this.projects.find(p => p.slug === lastProject)) {
                this.projectSelector.value = lastProject;
                await this.loadSessions(lastProject);
            } else if (this.projects.length > 0) {
                // Fallback: select first project if saved one doesn't exist
                this.projectSelector.value = this.projects[0].slug;
                await this.loadSessions(this.projects[0].slug);
            }
        } catch (error) {
            console.error('Failed to load projects:', error);
            this.showError('Failed to load projects');
        }
    }

    async loadSessions(projectSlug) {
        if (!projectSlug) {
            this.sessions = [];
            this.sessionSelector.innerHTML = '<option value="">Select session...</option>';
            return;
        }

        try {
            const { since, until } = this.getDateRangeParams();
            let url = `/api/sessions?project=${projectSlug}`;
            if (since) url += `&since=${since}`;
            if (until) url += `&until=${until}`;
            const response = await this.apiFetch(url);
            const data = await response.json();
            this.sessions = data.sessions || [];

            // Render the session list with current sort order
            this.renderSessionList();

            // Restore last selected session or auto-select first
            const lastSession = this.loadFromStorage(this.STATE_KEYS.lastSession);
            if (lastSession && this.sessions.find(s => s.id === lastSession)) {
                this.sessionSelector.value = lastSession;
                await this.loadEvents(lastSession);
            } else if (this.sessions.length > 0) {
                // Fallback: select first session if saved one doesn't exist
                this.sessionSelector.value = this.sessions[0].id;
                await this.loadEvents(this.sessions[0].id);
            }
        } catch (error) {
            console.error('Failed to load sessions:', error);
            this.showError('Failed to load sessions');
        }
    }

    /**
     * Format session display text for dropdowns.
     * Always shows short ID (for sorting/identification), plus name if available.
     */
    formatSessionDisplay(session) {
        const shortId = session.id.substring(0, 8);
        const parts = session.id.split('-');
        
        // Build ID portion
        let idPart = '';
        if (parts.length > 5) {
            // Sub-agent session: show short ID + agent name
            const agentPart = parts.slice(5).join('-');
            idPart = `${shortId}... [${agentPart}]`;
        } else {
            // Parent session: show short ID
            idPart = shortId;
        }

        // Build display text: ID first (for sorting), then name if present
        let displayText = idPart;
        
        if (session.name) {
            // Truncate long names
            const name = session.name.length > 35
                ? session.name.substring(0, 32) + '...'
                : session.name;
            displayText += ` - ${name}`;
        }

        // Add timestamp
        if (session.timestamp) {
            const ts = new Date(session.timestamp);
            displayText += ` - ${ts.toLocaleString()}`;
        } else {
            displayText += ' - No timestamp';
        }

        return displayText;
    }

    renderSessionList() {
        // Sort sessions based on checkbox preference
        const sortedSessions = this.sortSessions(this.sessions);

        // Render the sorted sessions
        this.sessionSelector.innerHTML = '<option value="">Select session...</option>';
        sortedSessions.forEach(session => {
            const option = document.createElement('option');
            option.value = session.id;
            option.textContent = this.formatSessionDisplay(session);

            // Add description as tooltip
            if (session.description) {
                option.title = session.description;
            }

            this.sessionSelector.appendChild(option);
        });
    }

    async fetchEventPage(sessionId, offset, limit) {
        const path =
            `/api/events/list?session=${encodeURIComponent(sessionId)}` +
            `&offset=${offset}&limit=${limit}`;
        const response = await this.apiFetch(path);
        if (!response.ok) throw new Error(`events/list HTTP ${response.status}`);
        return response.json();
    }

    async loadEvents(sessionId) {
        if (!sessionId) return;

        // Check if we're restoring the same session - if so, don't clear the saved selection
        const savedEvent = this.loadFromStorage(this.STATE_KEYS.selectedEventId, null);
        if (savedEvent && sessionId === savedEvent.sessionId) {
            this.isRestoringState = true;
        }

        const token = ++this._loadToken;   // any in-flight phase-2 page for a prior session is now stale
        this.currentSessionId = sessionId;
        this.showLoading(true);

        // Clear detail panel when switching sessions
        this.closeDetail();

        // Clear event cache when switching sessions
        this.eventCache.clear();

        // Stop previous event poll
        if (this.eventStream) {
            clearInterval(this.eventStream);
            this.eventStream = null;
        }

        // Reset per-session load + window state
        this.events = [];
        this.filteredEvents = [];
        this.loadComplete = false;
        this.eventsTotal = 0;
        this.knownEventTypes = new Set();
        this.renderStart = 0;
        this.renderEnd = 0;
        this.setLoadBanner(null);
        this._desiredEventType = (this.loadFromStorage('filters', {}).eventType) || '';

        let nextOffset = 0;

        try {
            // Phase 1: fast first page — unchanged first-paint cost, even on huge sessions
            const data = await this.fetchEventPage(sessionId, 0, this.FIRST_PAGE_LIMIT);
            if (token !== this._loadToken) return;          // session changed mid-flight

            this.events = data.events || [];  // Lightweight event headers
            this.eventsTotal = data.total || this.events.length;
            this.loadComplete = !data.has_more;
            nextOffset = data.offset + data.limit;          // NOT + events.length (blank/malformed lines)

            // Capture capabilities in one round trip so we know whether to
            // offer/auto-switch to the Transcript view.
            this.sessionCaps = {
                has_events: data.has_events !== false,
                has_transcript: !!data.has_transcript,
            };

            // Capture tail position for polling — starts exactly where this load ended.
            // Overwritten by the LAST page fetched in phase 2 (closes the 200..EOF gap).
            this._pollPosition = data.tail_position || 0;
            this._pollLineCount = data.tail_line_count || this.events.length;

            if (!this.sessionCaps.has_events && !this.sessionCaps.has_transcript) {
                this.events = [];
                this.filteredEvents = [];
                this.eventListContent.innerHTML =
                    '<div class="welcome-message"><p>This session has no events or transcript.</p></div>';
                this.updateFilterCount();
                return;
            }

            // A session with no events (but a transcript) is useless in Events view,
            // and Transcript may already be the user's persisted preference —
            // auto-switch either way rather than showing an empty pane.
            if (this.sessionCaps.has_transcript &&
                (!this.sessionCaps.has_events || this.viewMode === 'transcript')) {
                this.setViewMode('transcript');
                return;
            }

            this.populateDynamicFilters();   // now owns saved-filter restoration
            this.applyFilters();             // window anchored 'top'
        } catch (error) {
            console.error('Failed to load events:', error);
            this.showError('Failed to load events');
            return;
        } finally {
            this.showLoading(false);

            // Restore selected event AFTER loading is complete and DOM is rendered
            // Use requestAnimationFrame to ensure DOM paint is done
            requestAnimationFrame(() => {
                this.restoreSelectedEvent();
            });
        }

        // ---- Phase 2: complete the session in the background ----
        if (token !== this._loadToken) return;

        if (this.loadComplete) {
            this.startEventStream(sessionId);
            return;
        }
        if (this.eventsTotal > this.AUTO_LOAD_MAX) {
            // Too big to complete implicitly. State it and offer the opt-in.
            this.setLoadBanner({ sessionId, token, nextOffset });
            return;
        }
        await this.loadRemainingEvents(sessionId, nextOffset, token);
    }

    async loadRemainingEvents(sessionId, startOffset, token, { unlimited = false } = {}) {
        let offset = startOffset;
        let pages = 0;

        this.setLoadBanner(null);

        try {
            while (pages++ < this.MAX_PAGES) {
                this.showLoadProgress(this.events.length, this.eventsTotal);

                const data = await this.fetchEventPage(sessionId, offset, this.PAGE_LIMIT);
                if (token !== this._loadToken) return;      // session changed — drop this page

                const page = data.events || [];
                if (page.length) this.events.push(...page);
                this.eventsTotal = data.total || this.eventsTotal;

                // Poll markers always come from the most recent page fetched — this is
                // what closes the 200..EOF gap left by the phase-1-only load.
                this._pollPosition = data.tail_position || this._pollPosition;
                this._pollLineCount = data.tail_line_count || this._pollLineCount;

                offset = data.offset + data.limit;

                if (!data.has_more) { this.loadComplete = true; break; }
                if (!unlimited && this.events.length >= this.AUTO_LOAD_MAX) break;
            }
        } catch (error) {
            console.error('Failed to complete event load:', error);
        } finally {
            this.showLoadProgress(null);
        }

        if (token !== this._loadToken) return;

        this.populateDynamicFilters();                   // now sees every type in the session
        this.applyFilters({ window: 'preserve' });       // keep the user where they are

        // The deep-event case: the persisted selection may only now be reachable.
        if (this.selectedEventIndex === null) {
            requestAnimationFrame(() => this.restoreSelectedEvent());
        }

        if (this.loadComplete) {
            this.setLoadBanner(null);
            this.startEventStream(sessionId);            // only when whole
        } else {
            this.setLoadBanner({ sessionId, token, nextOffset: offset });
        }
    }

    showLoadProgress(loaded, total) {
        const indicator = document.getElementById('loading-indicator');
        if (loaded === null) { indicator.style.display = 'none'; return; }
        indicator.textContent = `Loading events… ${loaded.toLocaleString()} of ${(total || 0).toLocaleString()}`;
        indicator.style.display = 'block';
    }

    setLoadBanner(state) {
        if (!this.loadBanner) return;
        if (!state) {
            this.loadBanner.style.display = 'none';
            this.loadBanner.innerHTML = '';
            return;
        }
        const { sessionId, token, nextOffset } = state;
        this.loadBanner.innerHTML = '';

        const text = document.createElement('span');
        text.textContent =
            `Loaded ${this.events.length.toLocaleString()} of ${this.eventsTotal.toLocaleString()} events. ` +
            `Filters cover loaded events only; live updates paused.`;

        const btn = document.createElement('button');
        btn.className = 'btn-small';
        btn.textContent = 'Load all';
        btn.addEventListener('click', () => {
            btn.disabled = true;
            this.loadRemainingEvents(sessionId, nextOffset, token, { unlimited: true });
        });

        this.loadBanner.appendChild(text);
        this.loadBanner.appendChild(btn);
        this.loadBanner.style.display = 'flex';
    }

    startEventStream(sessionId) {
        // _pollPosition and _pollLineCount are set by loadEvents() from the
        // /api/events/list response's tail_position and tail_line_count fields.
        // This means polling starts exactly where the REST load left off —
        // no separate init request, no gap, no wasted I/O.
        this._pollSessionId = sessionId;
        this._pollErrorCount = 0;

        // Short-lived poll every 2s — thread is released between polls
        this.eventStream = setInterval(async () => {
            if (this._pollSessionId !== sessionId) return;
            try {
                const path =
                    `/api/events/since?session=${encodeURIComponent(sessionId)}` +
                    `&position=${this._pollPosition}&line_count=${this._pollLineCount}`;
                const response = await this.apiFetch(path);
                if (!response.ok) {
                    this._pollErrorCount++;
                    return;
                }
                this._pollErrorCount = 0;
                const data = await response.json();
                if (data.events && data.events.length > 0) {
                    const pinned = this.isPinnedToBottom();     // read BEFORE mutating the DOM
                    const typesBefore = this.knownEventTypes.size;

                    this.events.push(...data.events);
                    data.events.forEach(e => this.knownEventTypes.add(e.event));

                    if (this.knownEventTypes.size !== typesBefore) {
                        this.populateDynamicFilters();          // a genuinely new type appeared
                    }

                    this.applyFilters({ window: pinned ? 'bottom' : 'preserve' });
                    if (pinned) this.eventListContent.scrollTop = this.eventListContent.scrollHeight;
                }
                this._pollPosition = data.position;
                this._pollLineCount = data.line_count;
                this.eventsTotal = data.line_count || this.eventsTotal;
            } catch (e) {
                this._pollErrorCount++;
                if (this._pollErrorCount >= 5) {
                    console.warn('Event polling: multiple consecutive failures, server may be down');
                }
            }
        }, 2000);
    }

    isPinnedToBottom() {
        const el = this.eventListContent;
        return (el.scrollHeight - el.scrollTop - el.clientHeight) < this.PIN_TOLERANCE_PX
            && this.renderEnd >= this.filteredEvents.length;
    }

    setViewMode(mode, { reload = true } = {}) {
        this.viewMode = mode === 'transcript' ? 'transcript' : 'events';
        this.saveToStorage(this.STATE_KEYS.viewMode, this.viewMode);

        if (this.viewToggle) {
            this.viewToggle.querySelectorAll('.view-btn').forEach(btn => {
                btn.classList.toggle('active', btn.dataset.view === this.viewMode);
            });
        }

        const mainContent = document.querySelector('.main-content');
        if (mainContent) {
            mainContent.classList.toggle('transcript-mode', this.viewMode === 'transcript');
        }

        if (this.eventFilters) {
            this.eventFilters.style.display = this.viewMode === 'transcript' ? 'none' : '';
        }

        if (this.filterInput) {
            this.filterInput.placeholder = this.viewMode === 'transcript'
                ? 'Search transcript...'
                : 'Search events...';
        }

        // Transcript mode never polls; events mode restarts its own poll via loadEvents().
        if (this.viewMode === 'transcript' && this.eventStream) {
            clearInterval(this.eventStream);
            this.eventStream = null;
        }

        if (!reload || !this.currentSessionId) return;

        if (this.viewMode === 'transcript') {
            this.loadTranscript(this.currentSessionId);
        } else {
            this.loadEvents(this.currentSessionId);
        }
    }

    async loadTranscript(sessionId) {
        if (!sessionId) return;

        this.currentSessionId = sessionId;
        this.showLoading(true);

        try {
            const response = await this.apiFetch(`/api/transcript/list?session=${sessionId}`);
            const data = await response.json();
            this.transcriptMessages = data.messages || [];
            this.sessionCaps.has_transcript = data.has_transcript !== false;

            this.applyFilters();
        } catch (error) {
            console.error('Failed to load transcript:', error);
            this.showError('Failed to load transcript');
        } finally {
            this.showLoading(false);
        }
    }

    renderTranscript() {
        if (this.filteredMessages.length === 0) {
            this.eventListContent.innerHTML = '<div class="welcome-message"><p>No messages match filters</p></div>';
            return;
        }

        this.eventListContent.innerHTML = '';
        this.filteredMessages.forEach((msg, index) => {
            const item = this.createTranscriptItem(msg, index);
            this.eventListContent.appendChild(item);
        });
    }

    createTranscriptItem(msg, index) {
        const item = document.createElement('div');
        item.className = 'transcript-message';
        item.dataset.index = index;
        item.dataset.line = msg.line;

        const role = (msg.role || 'unknown').toLowerCase();
        const roleBadge = document.createElement('span');
        roleBadge.className = `role-badge ${role}`;
        roleBadge.textContent = msg.role || 'unknown';

        const content = document.createElement('div');
        content.className = 'transcript-content';

        (msg.blocks || []).forEach(block => {
            if (block.type === 'thinking') {
                const details = document.createElement('details');
                details.className = 'transcript-thinking';
                const summary = document.createElement('summary');
                summary.textContent = 'thinking';
                details.appendChild(summary);
                const text = document.createElement('div');
                text.textContent = block.text || '';
                details.appendChild(text);
                content.appendChild(details);
            } else if (block.type === 'text') {
                const textEl = document.createElement('div');
                textEl.className = 'transcript-text';
                textEl.textContent = block.text || '';
                content.appendChild(textEl);
            } else {
                const summaryEl = document.createElement('div');
                summaryEl.className = 'transcript-text';
                summaryEl.textContent = block.summary || block.text || '';
                content.appendChild(summaryEl);
            }
        });

        (msg.tool_calls || []).forEach(call => {
            const chip = document.createElement('span');
            chip.className = 'transcript-tool-call';
            chip.textContent = call.tool || 'tool';
            chip.title = call.preview || '';
            content.appendChild(chip);
        });

        if (msg.truncated) {
            const expandBtn = document.createElement('button');
            expandBtn.className = 'transcript-expand-btn';
            expandBtn.textContent = 'Show full message';
            expandBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                this.selectTranscriptMessage(index, { expand: true });
            });
            content.appendChild(expandBtn);
        }

        item.appendChild(roleBadge);
        item.appendChild(content);

        item.addEventListener('click', () => this.selectTranscriptMessage(index));

        return item;
    }

    async selectTranscriptMessage(index, opts = {}) {
        const msg = this.filteredMessages[index];
        if (!msg) return;

        this.selectedMessageIndex = index;
        this.highlightSelectedTranscriptItem(index);

        const cacheKey = `t${msg.line}`;

        if (!opts.expand && this.eventCache.has(cacheKey)) {
            this.renderTranscriptDetail(this.eventCache.get(cacheKey));
            return;
        }

        this.showDetailLoading(true);

        try {
            const response = await this.apiFetch(
                `/api/transcript/${this.currentSessionId}/${msg.line}?byte_offset=${msg.byte_offset}`
            );
            if (!response.ok) {
                throw new Error('Failed to load message');
            }
            const fullMessage = await response.json();

            this.cacheEvent(cacheKey, fullMessage);

            this.renderTranscriptDetail(fullMessage);
        } catch (error) {
            console.error('Failed to load transcript message:', error);
            this.showDetailError('Failed to load message details');
        } finally {
            this.showDetailLoading(false);
        }
    }

    highlightSelectedTranscriptItem(index) {
        this.eventListContent.querySelectorAll('.transcript-message').forEach(item => {
            item.classList.remove('selected');
        });
        const selectedItem = this.eventListContent.querySelector(`[data-index="${index}"]`);
        if (selectedItem) {
            selectedItem.classList.add('selected');
        }
    }

    renderTranscriptDetail(msg) {
        const overviewTab = document.getElementById('overview-tab');
        const metadata = msg.metadata || {};
        const blockCount = Array.isArray(msg.content) ? msg.content.length : (msg.content ? 1 : 0);
        renderOverviewSections(overviewTab, [
            {
                title: 'Message Information',
                rows: [
                    ['Role:', msg.role || ''],
                    ['Line Number:', msg.line],
                    ['Blocks:', blockCount],
                    ['Tool calls:', (msg.tool_calls || []).length],
                ],
            },
            {
                title: 'Metadata',
                rows: [
                    ['Seq:', metadata._seq ?? 'N/A'],
                    ['Timestamp:', metadata.timestamp || 'N/A'],
                ],
            },
        ]);

        if (window.JSONViewer) {
            const viewer = new JSONViewer(this.dataViewer, {
                maxTextLength: 200,
                smartExpansion: true,
                forceExpand: false,
                collapseByDefault: [],
                expandAllChildren: ['content', 'tool_calls'],
                autoExpandFields: ['content', 'tool_calls', 'metadata'],
            });
            viewer.render(msg);
        } else {
            renderJsonFallback(this.dataViewer, msg);
        }

        this.rawJson.textContent = JSON.stringify(msg, null, 2);

        document.getElementById('detail-title').textContent = `Message: ${msg.role || ''}`;
    }

    applyFilters(opts = {}) {
        const searchText = this.filterInput.value.toLowerCase();

        if (this.viewMode === 'transcript') {
            this.filteredMessages = this.transcriptMessages.filter(msg => {
                if (!searchText) return true;
                const blockText = (msg.blocks || [])
                    .map(b => b.text || b.summary || '')
                    .join(' ');
                const toolText = (msg.tool_calls || []).map(c => c.tool || '').join(' ');
                const searchable = `${blockText} ${toolText}`.toLowerCase();
                return searchable.includes(searchText);
            });

            this.renderTranscript();
            this.updateFilterCount();
            return;
        }

        const levelFilter = this.levelFilter.value;
        const typeFilter = this.eventTypeFilter.value;

        this.filteredEvents = this.events.filter(event => {
            // Level filter
            if (levelFilter && event.lvl !== levelFilter) return false;

            // Event type filter - support prefix matching
            if (typeFilter) {
                if (!(event.event || '').startsWith(typeFilter)) return false;
            }

            // Text search (search in event type and preview)
            if (searchText) {
                const searchable = `${event.event} ${event.preview || ''}`.toLowerCase();
                if (!searchable.includes(searchText)) return false;
            }

            return true;
        });

        this.renderEvents({ window: opts.window || 'top' });
        this.updateFilterCount();
    }

    populateDynamicFilters() {
        // Populate event type filter from actual events (the FULL loaded set, not a page sample)
        const eventTypes = new Set();
        this.events.forEach(event => {
            eventTypes.add(event.event);
        });
        this.knownEventTypes = eventTypes;   // used by the tail poll to detect genuinely new types

        // Preserve whatever is currently selected (or the persisted-but-not-yet-available
        // choice) so a saved filter isn't destroyed just because phase 1 hadn't loaded its type yet.
        const desired = this.eventTypeFilter.value || this._desiredEventType || '';

        const sortedTypes = Array.from(eventTypes).sort();

        this.eventTypeFilter.innerHTML = '<option value="">All Event Types</option>';

        // Group by prefix for better UX
        const groups = {};
        sortedTypes.forEach(type => {
            const prefix = type.split(':')[0];
            if (!groups[prefix]) groups[prefix] = [];
            groups[prefix].push(type);
        });

        // Add grouped options
        Object.keys(groups).sort().forEach(prefix => {
            if (groups[prefix].length > 1) {
                // Add prefix filter
                const prefixOption = document.createElement('option');
                prefixOption.value = prefix + ':';
                prefixOption.textContent = `All ${prefix} events`;
                this.eventTypeFilter.appendChild(prefixOption);
            }
            // Add specific events
            groups[prefix].forEach(type => {
                const option = document.createElement('option');
                option.value = type;
                option.textContent = type;
                this.eventTypeFilter.appendChild(option);
            });
        });

        // Re-apply the selection if (and only if) it now exists among the options. Never
        // writes storage here, so a filter the user saved is not destroyed just because
        // phase 1 hadn't loaded its type yet — it survives until phase 2 completes.
        const options = Array.from(this.eventTypeFilter.options);
        this.eventTypeFilter.value = options.some(o => o.value === desired) ? desired : '';
    }

    renderEvents({ window = 'top', anchorIndex = null } = {}) {
        const total = this.filteredEvents.length;

        if (total === 0) {
            this.eventListContent.innerHTML =
                '<div class="welcome-message"><p>No events match filters</p></div>';
            this.renderStart = 0;
            this.renderEnd = 0;
            return;
        }

        const chunk = this.RENDER_CHUNK;
        let start, end;

        if (window === 'bottom') {
            end = total;
            start = Math.max(0, total - chunk);
        } else if (window === 'index' && anchorIndex !== null) {
            start = Math.max(0, Math.min(anchorIndex - Math.floor(chunk / 2), total - chunk));
            start = Math.max(0, start);
            end = Math.min(total, start + chunk);
        } else if (window === 'preserve' && this.renderEnd > this.renderStart) {
            start = Math.min(this.renderStart, Math.max(0, total - 1));
            end = Math.min(total, Math.max(start + chunk, this.renderEnd));
        } else {                                   // 'top' — the default
            start = 0;
            end = Math.min(total, chunk);
        }

        this.renderStart = start;
        this.renderEnd = end;

        this.eventListContent.innerHTML = '';
        this.eventListContent.appendChild(this.buildEventRange(start, end));
        this.updateSentinels();
    }

    buildEventRange(start, end) {
        const frag = document.createDocumentFragment();
        for (let i = start; i < end; i++) {
            frag.appendChild(this.createEventItem(this.filteredEvents[i], i));
        }
        return frag;
    }

    updateSentinels() {
        const el = this.eventListContent;
        el.querySelectorAll('.event-sentinel').forEach(n => n.remove());

        if (this.renderStart > 0) {
            el.insertBefore(this.makeSentinel('top', this.renderStart), el.firstChild);
        }
        const below = this.filteredEvents.length - this.renderEnd;
        if (below > 0) {
            el.appendChild(this.makeSentinel('bottom', below));
        }
    }

    makeSentinel(edge, remaining) {
        const div = document.createElement('div');
        div.className = 'event-sentinel';
        div.dataset.edge = edge;
        const step = Math.min(this.RENDER_CHUNK, remaining);
        div.textContent = edge === 'top'
            ? `▲ Load ${step} older — ${remaining.toLocaleString()} above`
            : `▼ Load ${step} more — ${remaining.toLocaleString()} below`;
        div.addEventListener('click',
            () => edge === 'top' ? this.extendWindowUp() : this.extendWindowDown());
        return div;
    }

    extendWindowDown() {
        const total = this.filteredEvents.length;
        if (this._extending || this.renderEnd >= total) return;
        this._extending = true;

        const start = this.renderEnd;
        const end = Math.min(total, start + this.RENDER_CHUNK);
        const sentinel = this.eventListContent.querySelector('.event-sentinel[data-edge="bottom"]');
        this.eventListContent.insertBefore(this.buildEventRange(start, end), sentinel);
        this.renderEnd = end;
        this.updateSentinels();

        this._extending = false;
    }

    extendWindowUp() {
        if (this._extending || this.renderStart <= 0) return;
        this._extending = true;

        const el = this.eventListContent;
        const fromBottom = el.scrollHeight - el.scrollTop;   // capture BEFORE mutating

        const end = this.renderStart;
        const start = Math.max(0, end - this.RENDER_CHUNK);
        el.insertBefore(this.buildEventRange(start, end), el.querySelector('.event-item'));
        this.renderStart = start;
        this.updateSentinels();

        el.scrollTop = el.scrollHeight - fromBottom;         // keep the viewport steady

        this._extending = false;
    }

    onEventListScroll() {
        if (this.viewMode !== 'events' || this._extending) return;
        const el = this.eventListContent;

        if (el.scrollTop < this.SCROLL_EXTEND_PX && this.renderStart > 0) {
            this.extendWindowUp();
        } else if (el.scrollHeight - el.scrollTop - el.clientHeight < this.SCROLL_EXTEND_PX
                   && this.renderEnd < this.filteredEvents.length) {
            this.extendWindowDown();
        }
    }

    ensureIndexRendered(index) {
        if (index >= this.renderStart && index < this.renderEnd) return;
        this.renderEvents({ window: 'index', anchorIndex: index });
    }

    jumpToLatest() {
        if (this.viewMode !== 'events' || this.filteredEvents.length === 0) return;
        this.renderEvents({ window: 'bottom' });
        this.eventListContent.scrollTop = this.eventListContent.scrollHeight;
        // Auto-select the newest event so its detail opens without an extra click.
        this.selectEvent(this.filteredEvents.length - 1);
    }

    createEventItem(event, index) {
        const item = document.createElement('div');
        item.className = 'event-item';
        item.dataset.index = index;
        item.dataset.line = event.line;  // Store line number for fetching
        if (index === this.selectedEventIndex) item.classList.add('selected');

        const level = (event.lvl || 'info').toLowerCase();
        const levelBadge = document.createElement('span');
        levelBadge.className = `event-level ${level}`;
        levelBadge.textContent = event.lvl || 'INFO';

        const content = document.createElement('div');
        content.className = 'event-content';

        const typeEl = document.createElement('div');
        typeEl.className = 'event-type';
        typeEl.textContent = event.event;

        const timestampEl = document.createElement('div');
        timestampEl.className = 'event-timestamp';
        const ts = event.ts ? new Date(event.ts) : null;
        timestampEl.textContent = ts && !isNaN(ts) ? ts.toLocaleTimeString() : '—';

        const previewEl = document.createElement('div');
        previewEl.className = 'event-preview';
        previewEl.textContent = event.preview || '';  // Use server-computed preview

        content.appendChild(typeEl);
        content.appendChild(timestampEl);
        content.appendChild(previewEl);

        // Show size indicator for large events (> 50KB)
        if (event.size > 50000) {
            const sizeIndicator = document.createElement('span');
            sizeIndicator.className = 'event-size-indicator';
            sizeIndicator.textContent = `${Math.round(event.size / 1024)}KB`;
            sizeIndicator.title = 'Large event payload';
            content.appendChild(sizeIndicator);
        }

        item.appendChild(levelBadge);
        item.appendChild(content);

        item.addEventListener('click', () => this.selectEvent(index));

        return item;
    }

    async selectEvent(index) {
        const eventHeader = this.filteredEvents[index];
        const lineNum = eventHeader.line;

        // Update UI immediately with what we have
        this.selectedEventIndex = index;
        this.highlightSelectedItem(index);

        // Check cache first
        if (this.eventCache.has(lineNum)) {
            this.selectedEvent = this.eventCache.get(lineNum);
            this.renderEventDetail(this.selectedEvent);
            this.saveSelectedEvent();
            return;
        }

        // Show loading state in detail panel
        this.showDetailLoading(true);

        try {
            // Fetch full event by line number
            const response = await this.apiFetch(
                `/api/events/${this.currentSessionId}/${lineNum}`
            );
            
            if (!response.ok) {
                throw new Error('Failed to load event');
            }
            
            const fullEvent = await response.json();

            // Cache it
            this.cacheEvent(lineNum, fullEvent);

            this.selectedEvent = fullEvent;
            this.renderEventDetail(this.selectedEvent);
            this.saveSelectedEvent();
        } catch (error) {
            console.error('Failed to load event detail:', error);
            this.showDetailError('Failed to load event details');
        } finally {
            this.showDetailLoading(false);
        }
    }

    highlightSelectedItem(index) {
        // Update UI highlighting
        this.eventListContent.querySelectorAll('.event-item').forEach(item => {
            item.classList.remove('selected');
        });
        const selectedItem = this.eventListContent.querySelector(`[data-index="${index}"]`);
        if (selectedItem) {
            selectedItem.classList.add('selected');
        }
    }

    cacheEvent(lineNum, event) {
        // Simple LRU-ish: if cache is full, delete oldest entry
        if (this.eventCache.size >= this.EVENT_CACHE_MAX) {
            const firstKey = this.eventCache.keys().next().value;
            this.eventCache.delete(firstKey);
        }
        this.eventCache.set(lineNum, event);
    }

    renderEventDetail(event) {
        // Overview tab
        const overviewTab = document.getElementById('overview-tab');
        renderOverviewSections(overviewTab, [
            {
                title: 'Event Information',
                rows: [
                    ['Event Type:', event.event],
                    ['Level:', event.lvl || 'INFO'],
                    ['Timestamp:', event.ts || event.timestamp || '—'],
                    ['Session ID:', event.session_id ? event.session_id.substring(0, 8) + '…' : '—'],
                    ['Line Number:', event.line],
                ],
            },
            {
                title: 'Schema',
                rows: [
                    ['Name:', event.schema?.name || 'N/A'],
                    ['Version:', event.schema?.ver || 'N/A'],
                ],
            },
        ]);

        // Data tab with JSONViewer - auto-expand data and first level
        if (window.JSONViewer && event.data) {
            const viewer = new JSONViewer(this.dataViewer, {
                maxTextLength: 200,
                smartExpansion: true,
                forceExpand: false,  // Don't force ALL levels
                collapseByDefault: [],  // Don't collapse anything by default
                expandAllChildren: ['messages', 'content', 'system', 'data'],  // Auto-expand these
                autoExpandFields: ['data', 'content', 'text', 'input', 'output', 'request', 'response', 'messages']
            });
            viewer.render(event.data);
        } else {
            renderJsonFallback(this.dataViewer, event.data);
        }

        // Raw JSON tab
        this.rawJson.textContent = JSON.stringify(event, null, 2);

        // Update title
        document.getElementById('detail-title').textContent = `Event: ${event.event}`;
    }

    updateFilterCount() {
        const isTranscript = this.viewMode === 'transcript';
        const total = isTranscript ? this.transcriptMessages.length : this.events.length;
        const filtered = isTranscript ? this.filteredMessages.length : this.filteredEvents.length;
        const label = isTranscript ? 'messages' : 'events';

        let text = (filtered === total)
            ? `${total.toLocaleString()} ${label}`
            : `${filtered.toLocaleString()} of ${total.toLocaleString()} ${label}`;

        // Never let the counter imply completeness it doesn't have.
        if (!isTranscript && !this.loadComplete && this.eventsTotal > total) {
            text += ` (${total.toLocaleString()} of ${this.eventsTotal.toLocaleString()} loaded)`;
        }
        this.filterCount.textContent = text;
    }

    clearFilters() {
        this.filterInput.value = '';
        this.levelFilter.value = '';
        this.eventTypeFilter.value = '';
        this.applyFilters();
    }

    async refreshProjectList() {
        // Refresh project list when dropdown is opened (focused)
        try {
            const { since, until } = this.getDateRangeParams();
            let url = '/api/projects';
            const params = [];
            if (since) params.push(`since=${since}`);
            if (until) params.push(`until=${until}`);
            if (params.length) url += '?' + params.join('&');
            const response = await this.apiFetch(url);
            const data = await response.json();
            const newProjects = data.projects || [];

            // Only update if there are changes
            if (JSON.stringify(newProjects) !== JSON.stringify(this.projects)) {
                const currentSelection = this.projectSelector.value;
                this.projects = newProjects;

                // Rebuild dropdown
                this.projectSelector.innerHTML = '<option value="">Select project...</option>';
                this.projects.forEach(project => {
                    const option = document.createElement('option');
                    option.value = project.slug;
                    option.textContent = `${project.slug} (${project.session_count} sessions)`;
                    this.projectSelector.appendChild(option);
                });

                // Restore selection if it still exists
                if (currentSelection && this.projects.find(p => p.slug === currentSelection)) {
                    this.projectSelector.value = currentSelection;
                }
            }
        } catch (error) {
            console.error('Failed to refresh project list:', error);
        }
    }

    async refreshSessionList() {
        // Refresh session list when dropdown is opened (focused)
        const projectSlug = this.projectSelector.value;
        if (!projectSlug) return;

        try {
            const { since, until } = this.getDateRangeParams();
            let url = `/api/sessions?project=${projectSlug}`;
            if (since) url += `&since=${since}`;
            if (until) url += `&until=${until}`;
            const response = await this.apiFetch(url);
            const data = await response.json();
            const newSessions = data.sessions || [];

            // Only update if there are changes
            if (JSON.stringify(newSessions) !== JSON.stringify(this.sessions)) {
                const currentSelection = this.sessionSelector.value;
                this.sessions = newSessions;

                // Rebuild dropdown using shared helper
                this.sessionSelector.innerHTML = '<option value="">Select session...</option>';
                this.sessions.forEach(session => {
                    const option = document.createElement('option');
                    option.value = session.id;
                    option.textContent = this.formatSessionDisplay(session);

                    // Add description as tooltip
                    if (session.description) {
                        option.title = session.description;
                    }

                    this.sessionSelector.appendChild(option);
                });

                // Restore selection if it still exists
                if (currentSelection && this.sessions.find(s => s.id === currentSelection)) {
                    this.sessionSelector.value = currentSelection;
                }
            }
        } catch (error) {
            console.error('Failed to refresh session list:', error);
        }
    }

    async refresh() {
        // Force server-side refresh by calling /api/refresh endpoint
        try {
            const response = await this.apiFetch('/api/refresh', { method: 'POST' });
            if (!response.ok) {
                console.error('Failed to refresh session tree');
            }
        } catch (error) {
            console.error('Error calling refresh endpoint:', error);
        }

        // Always reload projects list to get new projects/sessions
        await this.loadProjects();

        // If we were viewing a specific project, reload its sessions
        if (this.projectSelector.value) {
            await this.loadSessions(this.projectSelector.value);
        }

        // If we were viewing a specific session, reload its events
        if (this.currentSessionId) {
            await this.loadEvents(this.currentSessionId);
        }
    }

    switchTab(tabName) {
        // Update buttons
        document.querySelectorAll('.tab-button').forEach(btn => {
            btn.classList.remove('active');
        });
        document.querySelector(`[data-tab="${tabName}"]`).classList.add('active');

        // Update panes
        document.querySelectorAll('.tab-pane').forEach(pane => {
            pane.classList.remove('active');
        });
        document.getElementById(`${tabName}-tab`).classList.add('active');
    }

    copyCurrentEvent() {
        if (this.selectedEvent) {
            const json = JSON.stringify(this.selectedEvent, null, 2);
            navigator.clipboard.writeText(json);
            this.showNotification('Event JSON copied to clipboard');
        }
    }

    copyRawJson() {
        const json = this.rawJson.textContent;
        navigator.clipboard.writeText(json);
        this.showNotification('Raw JSON copied to clipboard');
    }

    closeDetail() {
        this.selectedEvent = null;
        this.selectedEventIndex = null;
        this.selectedMessageIndex = null;
        document.querySelectorAll('.event-item').forEach(item => {
            item.classList.remove('selected');
        });
        document.querySelectorAll('.transcript-message').forEach(item => {
            item.classList.remove('selected');
        });
        // Reset to placeholder
        document.getElementById('overview-tab').innerHTML =
            '<div class="detail-content"><p class="placeholder">Select an event to view details</p></div>';
        this.dataViewer.innerHTML = '';
        this.rawJson.textContent = '';
        
        // Clear persisted selection
        this.saveSelectedEvent();
    }

    showLoading(show) {
        const indicator = document.getElementById('loading-indicator');
        indicator.style.display = show ? 'block' : 'none';
    }

    showDetailLoading(show) {
        const overviewTab = document.getElementById('overview-tab');
        if (show) {
            overviewTab.innerHTML = '<div class="detail-content loading"><p>Loading event details...</p></div>';
            this.dataViewer.innerHTML = '<div class="loading-placeholder">Loading...</div>';
            this.rawJson.textContent = 'Loading...';
        }
    }

    showDetailError(message) {
        const overviewTab = document.getElementById('overview-tab');
        overviewTab.innerHTML = `<div class="detail-content error"><p>${message}</p></div>`;
        this.dataViewer.innerHTML = '';
        this.rawJson.textContent = '';
    }

    showError(message) {
        this.eventListContent.innerHTML = `
            <div class="welcome-message">
                <p style="color: var(--color-status-error-fg);">❌ ${message}</p>
            </div>
        `;
    }

    showNotification(message) {
        // Simple notification (could be enhanced)
        console.log(message);
    }

    // Status polling for scan indicator
    startStatusPolling() {
        // Poll every 2s — fast enough to catch scan transitions (scans take 0.5-5s),
        // while reducing the original 500ms (2 req/s) to a more reasonable rate.
        this.statusPollInterval = setInterval(() => this.checkScanStatus(), 2000);
    }

    async checkScanStatus() {
        try {
            const response = await this.apiFetch('/api/status')
            const status = await response.json();
            this.updateScanIndicator(status);
        } catch (error) {
            // Silently ignore status check errors
        }
    }

    updateScanIndicator(status) {
        if (!this.scanStatus) return;

        if (status.is_scanning) {
            this.scanStatus.style.display = 'flex';
            this.refreshBtn.classList.add('scanning');
            if (this.scanText) {
                this.scanText.textContent = 'Scanning...';
            }
        } else {
            this.scanStatus.style.display = 'none';
            this.refreshBtn.classList.remove('scanning');
        }
    }

    async onProjectChange() {
        const projectSlug = this.projectSelector.value;
        this.saveToStorage(this.STATE_KEYS.lastProject, projectSlug);
        
        // Clear session-specific state when changing projects
        this.saveToStorage(this.STATE_KEYS.lastSession, null);
        this.saveToStorage(this.STATE_KEYS.selectedEventId, null);

        if (!projectSlug) {
            this.sessions = [];
            this.sessionSelector.innerHTML = '<option value="">Select session...</option>';
            return;
        }
        await this.loadSessions(projectSlug);
    }

    async onSessionChange() {
        const sessionId = this.sessionSelector.value;
        this.saveToStorage(this.STATE_KEYS.lastSession, sessionId);
        
        // Clear event-specific state when changing sessions
        this.saveToStorage(this.STATE_KEYS.selectedEventId, null);

        // Clear transcript-specific state when changing sessions
        this.selectedMessageIndex = null;
        this.transcriptMessages = [];
        this.filteredMessages = [];

        if (!sessionId) return;

        if (this.viewMode === 'transcript') {
            await this.loadTranscript(sessionId);
        } else {
            await this.loadEvents(sessionId);
        }
    }
}
