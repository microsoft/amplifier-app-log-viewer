"""Security regression tests for the browser-side renderer."""

import shutil
import subprocess
from pathlib import Path

import pytest


APP_JS = (
    Path(__file__).parents[1]
    / "amplifier_app_log_viewer"
    / "static"
    / "app.js"
)


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is required")
def test_event_detail_renders_log_metadata_as_text():
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

const payload = '<img src=x onerror="globalThis.xss=true">';
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

context.LogViewer.prototype.renderEventDetail.call(viewer, event);

assert.match(elements['overview-tab'].textContent, /<img src=x/);
assert.match(viewer.dataViewer.textContent, /<img src=x/);
assert.equal(elements['detail-title'].textContent, `Event: ${payload}`);
"""

    subprocess.run(
        ["node", "-e", script, str(APP_JS)],
        check=True,
        capture_output=True,
        text=True,
    )
