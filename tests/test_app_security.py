"""Security regression tests for the browser-side renderer."""

import shutil
import subprocess
from pathlib import Path

import pytest

APP_JS = Path(__file__).parents[1] / "amplifier_app_log_viewer" / "static" / "app.js"


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is required")
@pytest.mark.parametrize("detail_type", ["event", "transcript"])
@pytest.mark.parametrize(
    "payload",
    [
        '<img src=x onerror="globalThis.xss=true">',
        '</pre><svg onload="globalThis.xss=true">',
    ],
)
def test_detail_renders_log_metadata_as_text(detail_type, payload):
    script = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

class FakeElement {
    constructor(tagName) {
        this.tagName = tagName;
        this.children = [];
        this.className = '';
        this._textContent = '';
    }

    appendChild(child) {
        this.children.push(child);
        return child;
    }

    replaceChildren(...children) {
        this.children = children;
        this._textContent = '';
    }

    set textContent(value) {
        this._textContent = String(value);
        this.children = [];
    }

    get textContent() {
        return this._textContent + this.children.map(child => child.textContent).join('');
    }

    set innerHTML(value) {
        throw new Error(`Unsafe innerHTML assignment: ${value}`);
    }
}

const elements = {
    'overview-tab': new FakeElement('div'),
    'detail-title': new FakeElement('h2'),
};
const context = {
    console,
    document: {
        createElement: tagName => new FakeElement(tagName),
        getElementById: id => elements[id],
    },
    location: { pathname: '/', search: '', href: '' },
    window: {},
};
const source = fs.readFileSync(process.argv[1], 'utf8');
vm.runInNewContext(`${source}\nglobalThis.LogViewer = LogViewer;`, context);

const detailType = process.argv[2];
const payload = process.argv[3];
const viewer = {
    dataViewer: new FakeElement('div'),
    rawJson: new FakeElement('pre'),
};
const event = {
    event: payload,
    lvl: payload,
    ts: payload,
    session_id: payload,
    line: payload,
    schema: { name: payload, ver: payload },
    data: { value: payload },
};

const message = {
    role: payload,
    line: payload,
    content: [{ type: 'text', text: payload }],
    tool_calls: [{ name: payload, arguments: { value: payload } }],
    metadata: { _seq: payload, timestamp: payload },
};
const data = detailType === 'event' ? event : message;
const method = detailType === 'event' ? 'renderEventDetail' : 'renderTranscriptDetail';
context.LogViewer.prototype[method].call(viewer, data);

assert.ok(elements['overview-tab'].textContent.includes(payload));
const fallbackData = detailType === 'event' ? event.data : message;
assert.equal(viewer.dataViewer.textContent, JSON.stringify(fallbackData, null, 2));
assert.equal(viewer.rawJson.textContent, JSON.stringify(data, null, 2));
const title = detailType === 'event' ? 'Event' : 'Message';
assert.equal(elements['detail-title'].textContent, `${title}: ${payload}`);
assert.equal(viewer.dataViewer.children.length, 1);
assert.equal(viewer.dataViewer.children[0].tagName, 'pre');
assert.equal(viewer.dataViewer.children[0].children.length, 0);
assert.equal(context.xss, undefined);
"""

    subprocess.run(
        ["node", "-e", script, str(APP_JS), detail_type, payload],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
