// Amplifier Log Viewer - Network tab-style interface with progressive loading

class LogViewer {
    constructor() {
        this.projects = [];
        this.sessions = [];
        this.events = [];           // Lightweight event headers
        this.filteredEvents = [];
        this.selectedEvent = null;  // Full event data (fetched on demand)
        this.selectedEventIndex = null;
        this.currentSessionId = null;
        this.eventStream = null;
        this.isRestoringState = false;  // Flag to prevent saving during restore

        // Event detail cache: line_num -> full event data
        this.eventCache = new Map();
        this.EVENT_CACHE_MAX = 50;  // Keep last 50 viewed events

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
            eventListScroll: 'eventListScroll',
            detailPanelScroll: 'detailPanelScroll',
        };

        // DOM elements
        this.projectSelector = document.getElementById('project-selector');
        this.sessionSelector = document.getElementById('session-selector');
        this.refreshBtn = document.getElementById('refresh-btn');
        this.sortByTimestampCheckbox = document.getElementById('sort-by-timestamp-checkbox');
        this.filterInput = document.getElementById('filter-input');
        this.levelFilter = document.getElementById('level-filter');
        this.eventTypeFilter = document.getElementById('event-type-filter');
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

        // Status polling
        this.statusPollInterval = null;

        this.init();
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
        this.restoreFilterState();
        this.restoreSortPreference();
        this.restoreActiveTab();

        // Load projects on startup
        this.loadProjects();

        // Setup event listeners
        this.projectSelector.addEventListener('change', () => this.onProjectChange());
        this.sessionSelector.addEventListener('change', () => this.onSessionChange());
        this.refreshBtn.addEventListener('click', () => this.refresh());
        this.sortByTimestampCheckbox.addEventListener('change', () => this.onSortPreferenceChange());
        
        // Save scroll positions on scroll (debounced)
        let scrollTimeout;
        this.eventListContent.addEventListener('scroll', () => {
            clearTimeout(scrollTimeout);
            scrollTimeout = setTimeout(() => this.saveScrollPositions(), 200);
        });

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

    saveScrollPositions() {
        this.saveToStorage(this.STATE_KEYS.eventListScroll, this.eventListContent.scrollTop);
    }

    restoreScrollPositions() {
        const eventListScroll = this.loadFromStorage(this.STATE_KEYS.eventListScroll, 0);
        if (eventListScroll > 0) {
            // Use requestAnimationFrame to ensure DOM is ready
            requestAnimationFrame(() => {
                this.eventListContent.scrollTop = eventListScroll;
            });
        }
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
            const response = await fetch('/api/projects');
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
            const response = await fetch(`/api/sessions?project=${projectSlug}`);
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

    renderSessionList() {
        // Sort sessions based on checkbox preference
        const sortedSessions = this.sortSessions(this.sessions);

        // Render the sorted sessions
        this.sessionSelector.innerHTML = '<option value="">Select session...</option>';
        sortedSessions.forEach(session => {
            const option = document.createElement('option');
            option.value = session.id;

            // Format session display
            let displayText = '';

            // Check if it's a sub-agent session (has suffix after 5th hyphen)
            const parts = session.id.split('-');
            if (parts.length > 5) {
                // Sub-agent session: show short ID + agent name
                const shortId = session.id.substring(0, 8);
                const agentPart = parts.slice(5).join('-'); // Everything after UUID
                displayText = `${shortId}... [${agentPart}]`;
            } else {
                // Parent session: show short ID
                displayText = session.id.substring(0, 8) + '...';
            }

            // Add timestamp if available
            if (session.timestamp) {
                const ts = new Date(session.timestamp);
                displayText += ` - ${ts.toLocaleString()}`;
            } else {
                displayText += ' - No timestamp';
            }

            option.textContent = displayText;
            this.sessionSelector.appendChild(option);
        });
    }

    async loadEvents(sessionId) {
        if (!sessionId) return;

        // Check if we're restoring the same session - if so, don't clear the saved selection
        const savedEvent = this.loadFromStorage(this.STATE_KEYS.selectedEventId, null);
        if (savedEvent && sessionId === savedEvent.sessionId) {
            this.isRestoringState = true;
        }

        this.currentSessionId = sessionId;
        this.showLoading(true);

        // Clear detail panel when switching sessions
        this.closeDetail();

        // Clear event cache when switching sessions
        this.eventCache.clear();

        // Stop previous event stream
        if (this.eventStream) {
            this.eventStream.close();
        }

        try {
            // NEW: Load lightweight event list (no payloads)
            const response = await fetch(`/api/events/list?session=${sessionId}`);
            const data = await response.json();
            this.events = data.events || [];  // Lightweight event headers

            // Populate dynamic filters from actual event data
            this.populateDynamicFilters();

            // Restore event type filter value after dynamic population
            const savedFilters = this.loadFromStorage('filters', {});
            if (savedFilters.eventType) {
                // Check if saved value exists in the dropdown
                const options = Array.from(this.eventTypeFilter.options);
                const exists = options.some(opt => opt.value === savedFilters.eventType);
                if (exists) {
                    this.eventTypeFilter.value = savedFilters.eventType;
                } else {
                    // Reset to default if saved value doesn't exist
                    this.eventTypeFilter.value = '';
                }
            }

            this.applyFilters();

            // Start real-time stream
            this.startEventStream(sessionId);
        } catch (error) {
            console.error('Failed to load events:', error);
            this.showError('Failed to load events');
        } finally {
            this.showLoading(false);
            
            // Restore selected event AFTER loading is complete and DOM is rendered
            // Use requestAnimationFrame to ensure DOM paint is done
            requestAnimationFrame(() => {
                this.restoreSelectedEvent();
            });
        }
    }

    startEventStream(sessionId) {
        this.eventStream = new EventSource(`/stream/${sessionId}`);
        this.eventStream.addEventListener('new_events', (e) => {
            // NEW: SSE now sends lightweight events
            const newEvents = JSON.parse(e.data);
            this.events.push(...newEvents);
            this.applyFilters();
        });
    }

    applyFilters() {
        const searchText = this.filterInput.value.toLowerCase();
        const levelFilter = this.levelFilter.value;
        const typeFilter = this.eventTypeFilter.value;

        this.filteredEvents = this.events.filter(event => {
            // Level filter
            if (levelFilter && event.lvl !== levelFilter) return false;

            // Event type filter - support prefix matching
            if (typeFilter) {
                if (!event.event.startsWith(typeFilter)) return false;
            }

            // Text search (search in event type and preview)
            if (searchText) {
                const searchable = `${event.event} ${event.preview || ''}`.toLowerCase();
                if (!searchable.includes(searchText)) return false;
            }

            return true;
        });

        this.renderEvents();
        this.updateFilterCount();
    }

    populateDynamicFilters() {
        // Populate event type filter from actual events
        const eventTypes = new Set();
        this.events.forEach(event => {
            eventTypes.add(event.event);
        });

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
    }

    renderEvents() {
        if (this.filteredEvents.length === 0) {
            this.eventListContent.innerHTML = '<div class="welcome-message"><p>No events match filters</p></div>';
            return;
        }

        this.eventListContent.innerHTML = '';
        this.filteredEvents.forEach((event, index) => {
            const item = this.createEventItem(event, index);
            this.eventListContent.appendChild(item);
        });
    }

    createEventItem(event, index) {
        const item = document.createElement('div');
        item.className = 'event-item';
        item.dataset.index = index;
        item.dataset.line = event.line;  // Store line number for fetching

        const level = event.lvl.toLowerCase();
        const levelBadge = document.createElement('span');
        levelBadge.className = `event-level ${level}`;
        levelBadge.textContent = event.lvl;

        const content = document.createElement('div');
        content.className = 'event-content';

        const typeEl = document.createElement('div');
        typeEl.className = 'event-type';
        typeEl.textContent = event.event;

        const timestampEl = document.createElement('div');
        timestampEl.className = 'event-timestamp';
        timestampEl.textContent = new Date(event.ts).toLocaleTimeString();

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
            const response = await fetch(
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
        overviewTab.innerHTML = `
            <div class="overview-grid">
                <div class="overview-section">
                    <h4>Event Information</h4>
                    <table class="detail-table">
                        <tr><td>Event Type:</td><td>${event.event}</td></tr>
                        <tr><td>Level:</td><td>${event.lvl}</td></tr>
                        <tr><td>Timestamp:</td><td>${event.ts}</td></tr>
                        <tr><td>Session ID:</td><td>${event.session_id?.substring(0, 8)}...</td></tr>
                        <tr><td>Line Number:</td><td>${event.line}</td></tr>
                    </table>
                </div>
                <div class="overview-section">
                    <h4>Schema</h4>
                    <table class="detail-table">
                        <tr><td>Name:</td><td>${event.schema?.name || 'N/A'}</td></tr>
                        <tr><td>Version:</td><td>${event.schema?.ver || 'N/A'}</td></tr>
                    </table>
                </div>
            </div>
        `;

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
            this.dataViewer.innerHTML = '<pre class="json-display">' +
                JSON.stringify(event.data, null, 2) + '</pre>';
        }

        // Raw JSON tab
        this.rawJson.textContent = JSON.stringify(event, null, 2);

        // Update title
        document.getElementById('detail-title').textContent = `Event: ${event.event}`;
    }

    updateFilterCount() {
        const total = this.events.length;
        const filtered = this.filteredEvents.length;

        if (filtered === total) {
            this.filterCount.textContent = `${total} events`;
        } else {
            this.filterCount.textContent = `${filtered} of ${total} events`;
        }
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
            const response = await fetch('/api/projects');
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
            const response = await fetch(`/api/sessions?project=${projectSlug}`);
            const data = await response.json();
            const newSessions = data.sessions || [];

            // Only update if there are changes
            if (JSON.stringify(newSessions) !== JSON.stringify(this.sessions)) {
                const currentSelection = this.sessionSelector.value;
                this.sessions = newSessions;

                // Rebuild dropdown
                this.sessionSelector.innerHTML = '<option value="">Select session...</option>';
                this.sessions.forEach(session => {
                    const option = document.createElement('option');
                    option.value = session.id;

                    // Format session display
                    let displayText = '';
                    const parts = session.id.split('-');
                    if (parts.length > 5) {
                        const shortId = session.id.substring(0, 8);
                        const agentPart = parts.slice(5).join('-');
                        displayText = `${shortId}... [${agentPart}]`;
                    } else {
                        displayText = session.id.substring(0, 8) + '...';
                    }

                    if (session.timestamp) {
                        const ts = new Date(session.timestamp);
                        displayText += ` - ${ts.toLocaleString()}`;
                    } else {
                        displayText += ' - No timestamp';
                    }

                    option.textContent = displayText;
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
            const response = await fetch('/api/refresh', { method: 'POST' });
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
        document.querySelectorAll('.event-item').forEach(item => {
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
        // Poll every 500ms to catch scan status changes
        this.statusPollInterval = setInterval(() => this.checkScanStatus(), 500);
    }

    async checkScanStatus() {
        try {
            const response = await fetch('/api/status');
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
        this.saveToStorage(this.STATE_KEYS.eventListScroll, 0);

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
        this.saveToStorage(this.STATE_KEYS.eventListScroll, 0);

        if (!sessionId) return;
        await this.loadEvents(sessionId);
    }
}

// Initialize on page load (expose globally for debugging)
document.addEventListener('DOMContentLoaded', () => {
    window.logViewer = new LogViewer();
});
