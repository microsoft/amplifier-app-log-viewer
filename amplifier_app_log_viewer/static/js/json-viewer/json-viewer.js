/**
 * JSON Viewer Module
 * A minimal JSON viewer with smart expand/collapse functionality
 */

class JSONViewer {
    constructor(container, options = {}) {
        this.container = typeof container === 'string' 
            ? document.querySelector(container) 
            : container;
        
        this.options = {
            maxTextLength: 100,  // Generic default for any JSON viewer
            smartExpansion: true,
            collapseByDefault: [],  // Empty by default - let consumer specify
            expandAllChildren: [],  // Empty by default - let consumer specify  
            autoExpandFields: [],  // Empty by default - let consumer specify
            ...options
        };
        
        this.expandedPaths = new Set();
    }

    render(data) {
        if (!this.container) return;
        this.container.innerHTML = '';
        this.container.classList.add('json-viewer');
        
        const element = this.renderValue(data, '', 0);
        this.container.appendChild(element);
    }

    renderValue(value, path, depth) {
        if (value === null) {
            return this.renderPrimitive('null', 'null');
        }
        
        if (value === undefined) {
            return this.renderPrimitive('undefined', 'undefined');
        }
        
        const type = typeof value;
        
        if (type === 'boolean') {
            return this.renderPrimitive(value.toString(), 'boolean');
        }
        
        if (type === 'number') {
            return this.renderPrimitive(value.toString(), 'number');
        }
        
        if (type === 'string') {
            return this.renderString(value);
        }
        
        if (Array.isArray(value)) {
            return this.renderArray(value, path, depth);
        }
        
        if (type === 'object') {
            return this.renderObject(value, path, depth);
        }
        
        return this.renderPrimitive(value.toString(), 'unknown');
    }

    renderPrimitive(text, className) {
        const span = document.createElement('span');
        span.className = `json-${className}`;
        span.textContent = text;
        return span;
    }

    renderString(value) {
        const span = document.createElement('span');
        span.className = 'json-string';

        // Check if string contains newlines - if so, use pre-wrap styling
        const hasNewlines = value.includes('\n');
        if (hasNewlines) {
            span.style.whiteSpace = 'pre-wrap';
            span.style.display = 'inline-block';
        }

        if (value.length > this.options.maxTextLength) {
            const truncated = value.substring(0, this.options.maxTextLength);
            span.textContent = `"${truncated}..."`;
            span.title = value;
            span.classList.add('truncated');

            span.addEventListener('click', (e) => {
                e.stopPropagation();
                if (span.classList.contains('expanded')) {
                    span.textContent = `"${truncated}..."`;
                    span.classList.remove('expanded');
                    if (hasNewlines) {
                        span.style.whiteSpace = 'pre-wrap';
                    }
                } else {
                    span.textContent = `"${value}"`;
                    span.classList.add('expanded');
                    if (hasNewlines) {
                        span.style.whiteSpace = 'pre-wrap';
                    }
                }
            });
        } else {
            span.textContent = `"${value}"`;
        }

        return span;
    }

    renderArray(arr, path, depth) {
        const container = document.createElement('span');
        container.className = 'json-array';
        
        const toggle = document.createElement('span');
        toggle.className = 'json-toggle';
        toggle.textContent = '▶';
        
        const bracket = document.createElement('span');
        bracket.className = 'json-bracket';
        bracket.textContent = '[';
        
        const preview = document.createElement('span');
        preview.className = 'json-preview';
        preview.textContent = `${arr.length} ${arr.length === 1 ? 'item' : 'items'}`;
        
        const content = document.createElement('div');
        content.className = 'json-content';
        content.style.display = 'none';
        
        // Add closing bracket for collapsed state (must be created before toggle listener)
        const collapsedCloseBracket = document.createElement('span');
        collapsedCloseBracket.className = 'json-bracket collapsed-bracket';
        collapsedCloseBracket.textContent = ']';
        
        const closeBracket = document.createElement('span');
        closeBracket.className = 'json-bracket';
        closeBracket.textContent = ']';
        
        // Smart expansion rules
        const key = path.split('.').pop();
        const shouldAutoExpand = this.shouldAutoExpand(key, path, depth);
        const expandAllChildren = this.options.expandAllChildren.includes(key);
        
        // Function to render content
        const renderContent = () => {
            if (content.children.length === 0) {
                arr.forEach((item, index) => {
                    const itemPath = `${path}[${index}]`;
                    const itemContainer = document.createElement('div');
                    itemContainer.className = 'json-item';
                    
                    const itemValue = this.renderValue(item, itemPath, depth + 1);
                    itemContainer.appendChild(itemValue);
                    
                    if (index < arr.length - 1) {
                        const comma = document.createElement('span');
                        comma.className = 'json-comma';
                        comma.textContent = ',';
                        itemContainer.appendChild(comma);
                    }
                    
                    content.appendChild(itemContainer);
                });
                
                // After rendering, handle auto-expansion of children
                this.handleChildExpansion(content, key);
            }
        };
        
        // If auto-expanding, render content immediately
        if (shouldAutoExpand) {
            toggle.textContent = '▼';
            content.style.display = 'block';
            preview.style.display = 'none';
            renderContent();
        }
        
        toggle.addEventListener('click', () => {
            const isExpanding = content.style.display === 'none';
            
            if (isExpanding) {
                toggle.textContent = '▼';
                content.style.display = 'block';
                preview.style.display = 'none';
                collapsedCloseBracket.style.display = 'none';
                closeBracket.style.display = 'inline';
                
                // Render content if not already rendered
                renderContent();
            } else {
                toggle.textContent = '▶';
                content.style.display = 'none';
                preview.style.display = 'inline';
                collapsedCloseBracket.style.display = 'inline';
                closeBracket.style.display = 'none';
            }
        });
        
        // Build the structure
        container.appendChild(toggle);
        container.appendChild(bracket);
        container.appendChild(preview);
        container.appendChild(collapsedCloseBracket);
        container.appendChild(content);
        container.appendChild(closeBracket);
        
        // Show/hide elements based on expansion state
        if (shouldAutoExpand) {
            preview.style.display = 'none';
            collapsedCloseBracket.style.display = 'none';
            closeBracket.style.display = 'inline';
        } else {
            preview.style.display = 'inline';
            collapsedCloseBracket.style.display = 'inline';
            closeBracket.style.display = 'none';
        }
        
        return container;
    }

    renderObject(obj, path, depth) {
        const container = document.createElement('span');
        container.className = 'json-object';
        
        const toggle = document.createElement('span');
        toggle.className = 'json-toggle';
        toggle.textContent = '▶';
        
        const bracket = document.createElement('span');
        bracket.className = 'json-bracket';
        bracket.textContent = '{';
        
        const keys = Object.keys(obj);
        const preview = document.createElement('span');
        preview.className = 'json-preview';
        preview.textContent = keys.length > 0 ? ' ... ' : ' ';
        
        const content = document.createElement('div');
        content.className = 'json-content';
        content.style.display = 'none';
        
        // Add closing bracket for collapsed state (must be created before toggle listener)
        const collapsedCloseBracket = document.createElement('span');
        collapsedCloseBracket.className = 'json-bracket collapsed-bracket';
        collapsedCloseBracket.textContent = '}';
        
        const closeBracket = document.createElement('span');
        closeBracket.className = 'json-bracket';
        closeBracket.textContent = '}';
        
        // Smart expansion rules
        const key = path.split('.').pop();
        const shouldAutoExpand = this.shouldAutoExpand(key, path, depth);
        
        // Function to render content
        const renderContent = () => {
            if (content.children.length === 0) {
                keys.forEach((key, index) => {
                    const itemPath = path ? `${path}.${key}` : key;
                    const itemContainer = document.createElement('div');
                    itemContainer.className = 'json-item';
                    
                    const keyElement = document.createElement('span');
                    keyElement.className = 'json-key';
                    keyElement.textContent = `"${key}"`;
                    
                    const colon = document.createElement('span');
                    colon.className = 'json-colon';
                    colon.textContent = ': ';
                    
                    const itemValue = this.renderValue(obj[key], itemPath, depth + 1);
                    
                    itemContainer.appendChild(keyElement);
                    itemContainer.appendChild(colon);
                    itemContainer.appendChild(itemValue);
                    
                    if (index < keys.length - 1) {
                        const comma = document.createElement('span');
                        comma.className = 'json-comma';
                        comma.textContent = ',';
                        itemContainer.appendChild(comma);
                    }
                    
                    content.appendChild(itemContainer);
                });
                
                // After rendering, handle auto-expansion of children
                this.handleChildExpansion(content, path);
            }
        };
        
        // If auto-expanding, render content immediately
        if (shouldAutoExpand) {
            toggle.textContent = '▼';
            content.style.display = 'block';
            preview.style.display = 'none';
            renderContent();
        }
        
        toggle.addEventListener('click', () => {
            const isExpanding = content.style.display === 'none';
            
            if (isExpanding) {
                toggle.textContent = '▼';
                content.style.display = 'block';
                preview.style.display = 'none';
                collapsedCloseBracket.style.display = 'none';
                closeBracket.style.display = 'inline';
                
                // Render content if not already rendered
                renderContent();
            } else {
                toggle.textContent = '▶';
                content.style.display = 'none';
                preview.style.display = 'inline';
                collapsedCloseBracket.style.display = 'inline';
                closeBracket.style.display = 'none';
            }
        });
        
        // Build the structure
        container.appendChild(toggle);
        container.appendChild(bracket);
        container.appendChild(preview);
        container.appendChild(collapsedCloseBracket);
        container.appendChild(content);
        container.appendChild(closeBracket);
        
        // Show/hide elements based on expansion state
        if (shouldAutoExpand) {
            preview.style.display = 'none';
            collapsedCloseBracket.style.display = 'none';
            closeBracket.style.display = 'inline';
        } else {
            preview.textContent = keys.length > 0 ? ' ... ' : ' ';
            collapsedCloseBracket.style.display = 'inline';
            closeBracket.style.display = 'none';
        }
        
        return container;
    }

    handleChildExpansion(contentElement, parentKey) {
        // Generic expansion handling based on configuration
        
        // Check if this parent key should have all children expanded
        if (parentKey && this.options.expandAllChildren.includes(parentKey)) {
            contentElement.querySelectorAll('.json-toggle').forEach(toggle => {
                if (toggle.textContent === '▶') {
                    toggle.click();
                }
            });
        }
        
        // Check for auto-expand fields within this content
        if (this.options.autoExpandFields && this.options.autoExpandFields.length > 0) {
            contentElement.querySelectorAll('.json-key').forEach(keyEl => {
                const keyText = keyEl.textContent.replace(/"/g, ''); // Remove quotes
                if (this.options.autoExpandFields.includes(keyText)) {
                    // Find the associated value element and expand it
                    const valueElement = keyEl.nextElementSibling?.nextElementSibling;
                    if (valueElement) {
                        const toggle = valueElement.querySelector('.json-toggle');
                        if (toggle && toggle.textContent === '▶') {
                            toggle.click();
                        }
                    }
                }
            });
        }
        
        // Check for custom expansion handler if provided
        if (this.options.customExpansionHandler && typeof this.options.customExpansionHandler === 'function') {
            this.options.customExpansionHandler(contentElement, parentKey);
        }
    }

    shouldAutoExpand(key, path, depth) {
        // Root level always expanded
        if (depth === 0) return true;
        
        // Force expand if flag is set
        if (this.options.forceExpand) return true;
        
        // Auto-expand specific fields
        if (this.options.autoExpandFields && this.options.autoExpandFields.includes(key)) {
            return true;
        }
        
        // Specific keys always collapsed
        if (this.options.collapseByDefault.includes(key)) return false;
        
        // Check if we're inside an expandAllChildren parent
        if (path) {
            const pathParts = path.split('.');
            for (const part of pathParts) {
                if (this.options.expandAllChildren.includes(part)) {
                    return true;
                }
            }
        }
        
        // Default to collapsed for deep nesting
        return false;
    }
}

// Export for use
if (typeof module !== 'undefined' && module.exports) {
    module.exports = JSONViewer;
}

// Also expose to global window object for browser usage
if (typeof window !== 'undefined') {
    window.JSONViewer = JSONViewer;
}
