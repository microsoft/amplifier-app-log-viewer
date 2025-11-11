# Quick Start Guide - Amplifier Log Viewer

## Current Status ✅

**Port 8180 is now free** - you can run the viewer!

## Running the Viewer

```bash
amplifier-log-viewer

# Opens at http://localhost:8180
```

**If you see white background**: Hard refresh your browser (Ctrl+Shift+R or Cmd+Shift+R) to reload the updated CSS.

## Understanding LLM Events

Your current session has **DEBUG events**, not RAW events:

### What You Have Now (4 debug events)
- `llm:request:debug` - Request summary (model, message count, parameters)
- `llm:response:debug` - Response summary (usage, timings, content preview)

**To view these**:
1. Filter by "🔍 LLM Request (Debug)" or "🔍 LLM Response (Debug)"
2. Click any event
3. Go to **Data tab** to see the interactive JSON viewer

### What RAW Events Are (requires config)
- `llm:request:raw` - **Complete** vendor API request payload
- `llm:response:raw` - **Complete** vendor API response payload

**To enable RAW events** (for future sessions):
Add this to your amplifier profile:

```yaml
providers:
  - module: provider-anthropic
    config:
      debug: true        # Enables DEBUG events
      raw_debug: true    # Enables RAW events (full API payloads)
```

⚠️ **Warning**: RAW debug generates very large logs (complete LLM request/response objects)

## Layout Overview

**New 2-Pane Design** (Chrome DevTools Network tab style):

```
┌─────────────────────────────────────────────┐
│  Header: [Project ▼] [Session ▼] [🔄]     │
├──────────────┬──────────────────────────────┤
│ Event List   │    Detail Panel (wide!)     │
│ (~420px)     │    (flex-fill)               │
│              │                              │
│ [INFO] ...   │  Tabs:                       │
│ [DEBUG] ...  │  • Overview (metadata)       │
│ [ERROR] ...  │  • Data (JSON viewer)        │
│              │  • Raw JSON (full event)     │
└──────────────┴──────────────────────────────┘
```

## Key Features Working

✅ **Session Selection**: Header dropdowns (no more sidebar!)
✅ **Event List**: Narrow left pane, auto-width
✅ **Detail Panel**: Wide right pane with tabs
✅ **Interactive JSON Viewer**: Click ▶/▼ to expand/collapse
✅ **Filters**: Text search, log level, event type
✅ **Real-time Updates**: SSE streaming (polls every 2s)
✅ **Copy Buttons**: Export event JSON

## Known Issues Fixed

1. ✅ **Limit validation**: Backend now accepts limit=1000 (was rejecting)
2. ✅ **CSS tokens**: Updated to match style.css variable names
3. ✅ **JSONViewer**: Integrated from claude-trace-viewer
4. ✅ **Layout**: 2-pane instead of 3-pane

## Troubleshooting

### "White background with black text"
**Hard refresh your browser**: Ctrl+Shift+R (Windows/Linux) or Cmd+Shift+R (Mac)
- This reloads the updated CSS tokens

### "Can't see LLM events"
1. Check **Level filter** is set to "All Levels" (not just INFO)
2. Select "🔍 LLM Request (Debug)" from Event Type filter
3. Your session has 4 LLM debug events (2 requests, 2 responses)

### "Filters not working"
- Type in search box → waits 300ms → applies filter
- Change dropdown → applies immediately
- Click "Clear" to reset all filters

## Testing Checklist

Try these steps:

1. **Select project**: Choose from dropdown → loads sessions
2. **Select session**: Choose from dropdown → loads ~28 events
3. **Filter DEBUG**: Level filter → "DEBUG" → shows 4 events
4. **Select LLM event**: Click any DEBUG event → see details
5. **View Data tab**: Click "Data" tab → see interactive JSON
6. **Expand JSON**: Click ▶ triangle → expands nested objects
7. **Copy event**: Click "Copy" button → JSON in clipboard
8. **Search**: Type "prompt" in search → filters to matching events

## Design Credits

- **Layout**: Inspired by Chrome DevTools Network tab
- **JSONViewer**: Adapted from claude-trace-viewer
- **Design System**: Custom tokens following Amplifier philosophy
- **Architecture**: Flask backend + Vanilla JS frontend (no build step)
