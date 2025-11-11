// Amplifier Log Viewer - Network tab-style interface

class LogViewer {
    constructor() {
        this.projects = [];
        this.sessions = [];
        this.events = [];
        this.filteredEvents = [];
        this.selectedEvent = null;
        this.currentSessionId = null;
        this.eventStream = null;

        // LocalStorage keys
        this.STORAGE_PREFIX = 'amplifier-log-viewer-';

        // DOM elements
        this.projectSelector = document.getElementById('project-selector');
        this.sessionSelector = document.getElementById('session-selector');
        this.refreshBtn = document.getElementById('refresh-btn');
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
        // Restore filter state from localStorage
        this.restoreFilterState();

        // Load projects on startup
        this.loadProjects();

        // Setup event listeners
        this.projectSelector.addEventListener('change', () => this.onProjectChange());
        this.sessionSelector.addEventListener('change', () => this.onSessionChange());
        this.refreshBtn.addEventListener('click', () => this.refresh());

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

        // Tab switching
        document.querySelectorAll('.tab-button').forEach(btn => {
            btn.addEventListener('click', () => this.switchTab(btn.dataset.tab));
        });

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
            const lastProject = this.loadFromStorage('lastProject');
            if (lastProject && this.projects.find(p => p.slug === lastProject)) {
                this.projectSelector.value = lastProject;
                await this.loadSessions(lastProject);
            } else if (this.projects.length > 0) {
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

            this.sessionSelector.innerHTML = '<option value="">Select session...</option>';
            this.sessions.forEach(session => {
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

            // Restore last selected session or auto-select first
            const lastSession = this.loadFromStorage('lastSession');
            if (lastSession && this.sessions.find(s => s.id === lastSession)) {
                this.sessionSelector.value = lastSession;
                await this.loadEvents(lastSession);
            } else if (this.sessions.length > 0) {
                this.sessionSelector.value = this.sessions[0].id;
                await this.loadEvents(this.sessions[0].id);
            }
        } catch (error) {
            console.error('Failed to load sessions:', error);
            this.showError('Failed to load sessions');
        }
    }

    async loadEvents(sessionId) {
        if (!sessionId) return;

        this.currentSessionId = sessionId;
        this.showLoading(true);

        // Clear detail panel when switching sessions
        this.closeDetail();

        // Stop previous event stream
        if (this.eventStream) {
            this.eventStream.close();
        }

        try {
            const response = await fetch(`/api/events?session=${sessionId}&limit=1000`);
            const data = await response.json();
            this.events = data.events || [];

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
        }
    }

    startEventStream(sessionId) {
        this.eventStream = new EventSource(`/stream/${sessionId}`);
        this.eventStream.addEventListener('new_events', (e) => {
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

            // Text search (search in event type and data)
            if (searchText) {
                const eventStr = JSON.stringify(event).toLowerCase();
                if (!eventStr.includes(searchText)) return false;
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
        previewEl.textContent = this.getEventPreview(event);

        content.appendChild(typeEl);
        content.appendChild(timestampEl);
        content.appendChild(previewEl);

        item.appendChild(levelBadge);
        item.appendChild(content);

        item.addEventListener('click', () => this.selectEvent(index));

        return item;
    }

    getEventPreview(event) {
        if (!event.data) return '';

        // For LLM debug events, data is nested: event.data.data.request/response
        if (event.event.includes(':debug')) {
            const nestedData = event.data.data || {};

            if (event.event.startsWith('llm:request')) {
                const request = nestedData.request || {};
                const model = request.model || '';
                const messageCount = request.messages?.length || 0;
                if (model && messageCount > 0) {
                    return `${model} | ${messageCount} messages`;
                }
            }

            if (event.event.startsWith('llm:response')) {
                const response = nestedData.response || {};
                const usage = response.usage || {};
                const tokens = usage.total_tokens || usage.input_tokens || '';
                if (tokens) {
                    return `${tokens} tokens`;
                }
            }
        }

        // For standard LLM events (not debug), check data.data for nested structure
        if (event.event.startsWith('llm:')) {
            const nestedData = event.data.data || event.data;
            const provider = nestedData.provider;
            if (provider) {
                return `Provider: ${provider}`;
            }
        }

        // For tool events
        if (event.event.startsWith('tool:')) {
            const toolName = event.data.tool_name || event.data.name;
            if (toolName) {
                return `Tool: ${toolName}`;
            }
        }

        // For prompt events
        if (event.event.startsWith('prompt:')) {
            const prompt = event.data.prompt;
            if (prompt && prompt.length < 60) {
                return prompt;
            } else if (prompt) {
                return prompt.substring(0, 57) + '...';
            }
        }

        // For content blocks
        if (event.event.startsWith('content_block:')) {
            const blockType = event.data.block_type;
            const blockIndex = event.data.block_index;
            if (blockType !== undefined && blockIndex !== undefined) {
                return `Block ${blockIndex}: ${blockType}`;
            }
        }

        // Default: empty (don't show unhelpful data)
        return '';
    }

    selectEvent(index) {
        this.selectedEvent = this.filteredEvents[index];

        // Update UI
        this.eventListContent.querySelectorAll('.event-item').forEach(item => {
            item.classList.remove('selected');
        });
        const selectedItem = this.eventListContent.querySelector(`[data-index="${index}"]`);
        if (selectedItem) {
            selectedItem.classList.add('selected');
        }

        this.renderEventDetail(this.selectedEvent);
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
        document.querySelectorAll('.event-item').forEach(item => {
            item.classList.remove('selected');
        });
        // Reset to placeholder
        document.getElementById('overview-tab').innerHTML =
            '<div class="detail-content"><p class="placeholder">Select an event to view details</p></div>';
        this.dataViewer.innerHTML = '';
        this.rawJson.textContent = '';
    }

    showLoading(show) {
        const indicator = document.getElementById('loading-indicator');
        indicator.style.display = show ? 'block' : 'none';
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

    async onProjectChange() {
        const projectSlug = this.projectSelector.value;
        this.saveToStorage('lastProject', projectSlug);

        if (!projectSlug) {
            this.sessions = [];
            this.sessionSelector.innerHTML = '<option value="">Select session...</option>';
            return;
        }
        await this.loadSessions(projectSlug);
    }

    async onSessionChange() {
        const sessionId = this.sessionSelector.value;
        this.saveToStorage('lastSession', sessionId);

        if (!sessionId) return;
        await this.loadEvents(sessionId);
    }
}

// Initialize on page load
document.addEventListener('DOMContentLoaded', () => {
    new LogViewer();
});
