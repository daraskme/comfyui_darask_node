// DARASK LTX 2.3 frontend.
//
// 1) Live size readout — both `DARASK LTX23 Video Settings` and
//    `DARASK LTX 2.3 Generator` draw a coloured pill at the top of the
//    node showing the final clip dimensions / aspect ratio / frame count
//    / duration. Updates immediately as the user edits width/height/
//    length/fps.
//
// 2) Dynamic LoRA UI on the Generator — same pattern as DARASK Lora
//    Loader. A `+ Add LoRA` button (and `− Remove Last LoRA`) appended
//    to the bottom of the node, each press inserts a toggle + combo +
//    number widget triple before the buttons. Restored on workflow load
//    by reading trailing widgets_values entries past the static
//    widgets.

import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const PREVIEW_NODES = new Set([
    "DARASK LTX23 Video Settings",
    "DARASK LTX 2.3 Generator",
]);
const GEN_NODE = "DARASK LTX 2.3 Generator";
const NONE_VALUE = "None";

// ─────────────────────────────────────────────────────────────────────────
// Size preview helpers
// ─────────────────────────────────────────────────────────────────────────

function gcd(a, b) {
    a = Math.abs(a | 0);
    b = Math.abs(b | 0);
    while (b) [a, b] = [b, a % b];
    return a || 1;
}

function formatInfo(width, height, length, fps) {
    width = width | 0;
    height = height | 0;
    length = length | 0;
    fps = +fps;
    if (!width || !height) return "";
    const g = gcd(width, height);
    const rw = width / g;
    const rh = height / g;
    if (fps > 0) {
        const duration = length / fps;
        const fpsTxt = Number.isInteger(fps) ? String(fps) : fps.toFixed(2).replace(/\.?0+$/, "");
        return `${width}×${height} (${rw}:${rh}) · ${length}f @ ${fpsTxt}fps = ${duration.toFixed(2)}s`;
    }
    return `${width}×${height} (${rw}:${rh}) · ${length}f`;
}

function pullSizeValues(node) {
    const out = { width: 0, height: 0, length: 0, fps: 0 };
    for (const w of node.widgets || []) {
        if (w && w.name in out) out[w.name] = w.value;
    }
    return out;
}

function recomputeAndDraw(node) {
    const { width, height, length, fps } = pullSizeValues(node);
    node._daraskLtx23Info = formatInfo(width, height, length, fps);
    node.setDirtyCanvas(true, true);
}

function hookSizeWidgets(node) {
    for (const w of node.widgets || []) {
        if (w._daraskSizeHooked) continue;
        if (!(w && w.name in { width: 1, height: 1, length: 1, fps: 1 })) continue;
        const orig = w.callback;
        w.callback = function (...args) {
            const r = orig ? orig.apply(this, args) : undefined;
            recomputeAndDraw(node);
            return r;
        };
        w._daraskSizeHooked = true;
    }
}

// ─────────────────────────────────────────────────────────────────────────
// Preserve manual resize
// ─────────────────────────────────────────────────────────────────────────

function preserveSize(node, savedSize) {
    if (!node || !node.size || !Array.isArray(savedSize)) return;
    let minSize = [0, 0];
    if (typeof node.computeSize === "function") {
        try { minSize = node.computeSize(); } catch (_) {}
    }
    node.size[0] = Math.max(savedSize[0] | 0, (minSize[0] | 0) || 0);
    node.size[1] = Math.max(savedSize[1] | 0, (minSize[1] | 0) || 0);
}

// ─────────────────────────────────────────────────────────────────────────
// LoRA list cache (same /object_info/LoraLoader hop as Lora Loader)
// ─────────────────────────────────────────────────────────────────────────

let LORA_LIST = [NONE_VALUE];
let LORA_LIST_LOADED = false;
let LORA_LIST_PROMISE = null;

async function ensureLoraList() {
    if (LORA_LIST_LOADED) return LORA_LIST;
    if (LORA_LIST_PROMISE) return LORA_LIST_PROMISE;
    LORA_LIST_PROMISE = (async () => {
        try {
            const resp = await api.fetchApi("/object_info/LoraLoader");
            const data = await resp.json();
            const list = data?.LoraLoader?.input?.required?.lora_name?.[0];
            if (Array.isArray(list) && list.length > 0) {
                LORA_LIST = [NONE_VALUE, ...list];
            }
        } catch (e) {
            console.warn("DARASK LTX 2.3 Generator: failed to fetch LoRA list:", e);
        }
        LORA_LIST_LOADED = true;
        return LORA_LIST;
    })();
    return LORA_LIST_PROMISE;
}

function refreshComboValues(node) {
    if (!node.widgets) return;
    for (const w of node.widgets) {
        if (w._daraskKind === "name" && w.options) {
            w.options.values = LORA_LIST;
        }
    }
    node.setDirtyCanvas(true, true);
}

// ─────────────────────────────────────────────────────────────────────────
// LoRA row management (only for the Generator)
// ─────────────────────────────────────────────────────────────────────────

function addLoraRow(node, initial) {
    const savedSize = node.size ? [node.size[0], node.size[1]] : null;
    const idx = (node._daraskNextLoraIdx = (node._daraskNextLoraIdx || 0) + 1);

    const initOn =
        initial && typeof initial.on === "boolean" ? initial.on : true;
    const initName =
        initial && typeof initial.lora === "string" && initial.lora
            ? initial.lora
            : NONE_VALUE;
    const initStrength =
        initial && typeof initial.strength === "number"
            ? initial.strength
            : 1.0;

    const onW = node.addWidget(
        "toggle", `lora_${idx}_on`, initOn, () => {}, { on: "✓", off: "—" },
    );
    const nameW = node.addWidget(
        "combo", `lora_${idx}`, initName, () => {}, { values: LORA_LIST },
    );
    const strW = node.addWidget(
        "number", `lora_${idx}_strength`, initStrength, () => {},
        { min: -4, max: 4, step: 0.05, precision: 2 },
    );

    for (const [w, kind] of [[onW, "on"], [nameW, "name"], [strW, "strength"]]) {
        w._daraskGroupIdx = idx;
        w._daraskKind = kind;
    }

    ensureLoraList().then(() => refreshComboValues(node));
    moveLoraControlsToEnd(node);
    preserveSize(node, savedSize);
    node.setDirtyCanvas(true, true);
}

function removeLastLoraRow(node) {
    const savedSize = node.size ? [node.size[0], node.size[1]] : null;
    const groups = (node.widgets || [])
        .filter((w) => w._daraskGroupIdx != null)
        .map((w) => w._daraskGroupIdx);
    if (!groups.length) return;
    const maxIdx = Math.max(...groups);
    node.widgets = (node.widgets || []).filter(
        (w) => w._daraskGroupIdx !== maxIdx,
    );
    preserveSize(node, savedSize);
    node.setDirtyCanvas(true, true);
}

function ensureLoraControls(node) {
    const hasAdd = (node.widgets || []).some((w) => w._daraskAddLoraBtn);
    if (!hasAdd) {
        const b = node.addWidget("button", "+ Add LoRA", null, () => {
            addLoraRow(node);
        });
        b._daraskAddLoraBtn = true;
    }
    const hasRem = (node.widgets || []).some((w) => w._daraskRemLoraBtn);
    if (!hasRem) {
        const b = node.addWidget("button", "− Remove Last LoRA", null, () => {
            removeLastLoraRow(node);
        });
        b._daraskRemLoraBtn = true;
    }
}

function moveLoraControlsToEnd(node) {
    const ctrls = (node.widgets || []).filter(
        (w) => w._daraskAddLoraBtn || w._daraskRemLoraBtn,
    );
    const rest = (node.widgets || []).filter(
        (w) => !w._daraskAddLoraBtn && !w._daraskRemLoraBtn,
    );
    node.widgets = [...rest, ...ctrls];
}

function clearLoraWidgets(node) {
    node.widgets = (node.widgets || []).filter(
        (w) =>
            w._daraskGroupIdx == null &&
            !w._daraskAddLoraBtn &&
            !w._daraskRemLoraBtn,
    );
    node._daraskNextLoraIdx = 0;
}

// ─────────────────────────────────────────────────────────────────────────
// Extension
// ─────────────────────────────────────────────────────────────────────────

app.registerExtension({
    name: "darask.ltx23",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (!PREVIEW_NODES.has(nodeData.name)) return;

        const isGenerator = nodeData.name === GEN_NODE;

        nodeType.prototype.serialize_widgets = true;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const r = onNodeCreated?.apply(this, arguments);
            if (isGenerator) {
                ensureLoraList().then(() => refreshComboValues(this));
                ensureLoraControls(this);
                moveLoraControlsToEnd(this);
            }
            hookSizeWidgets(this);
            recomputeAndDraw(this);
            return r;
        };

        const onConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function (info) {
            const savedSize =
                info && Array.isArray(info.size)
                    ? [info.size[0], info.size[1]]
                    : this.size
                    ? [this.size[0], this.size[1]]
                    : null;

            if (isGenerator) {
                // Strip any pre-existing LoRA widgets so super.configure
                // only sees the static declared widgets and applies the
                // saved values to them.
                clearLoraWidgets(this);
            }

            const r = onConfigure?.apply(this, arguments);

            if (isGenerator) {
                // After super.configure, the first N widgets_values were
                // consumed by the declared widgets. The trailing entries
                // are our LoRA rows (bool/string/number triplets, with
                // possible null gaps from old button widgets).
                const values = info?.widgets_values || [];
                const declaredCount = (this.widgets || []).length;
                const extra = values.slice(declaredCount);
                for (let i = 0; i + 2 < extra.length; ) {
                    const a = extra[i],
                        b = extra[i + 1],
                        c = extra[i + 2];
                    if (
                        typeof a === "boolean" &&
                        typeof b === "string" &&
                        typeof c === "number"
                    ) {
                        addLoraRow(this, { on: a, lora: b, strength: c });
                        i += 3;
                    } else {
                        i++;
                    }
                }
                ensureLoraControls(this);
                moveLoraControlsToEnd(this);
                ensureLoraList().then(() => refreshComboValues(this));
            }

            hookSizeWidgets(this);
            recomputeAndDraw(this);
            preserveSize(this, savedSize);
            this.setDirtyCanvas(true, true);
            return r;
        };

        const onExecuted = nodeType.prototype.onExecuted;
        nodeType.prototype.onExecuted = function (message) {
            const r = onExecuted?.apply(this, arguments);
            const t = message?.text?.[0];
            if (typeof t === "string" && t) {
                this._daraskLtx23Info = t;
                this.setDirtyCanvas(true, true);
            }
            return r;
        };

        const onDrawForeground = nodeType.prototype.onDrawForeground;
        nodeType.prototype.onDrawForeground = function (ctx) {
            onDrawForeground?.apply(this, arguments);
            if (!this._daraskLtx23Info || this.flags?.collapsed) return;

            ctx.save();
            ctx.font = "bold 12px sans-serif";
            ctx.textAlign = "center";
            ctx.textBaseline = "alphabetic";
            const text = this._daraskLtx23Info;
            const padX = 10;
            const w = ctx.measureText(text).width + padX * 2;
            const h = 20;
            const x = this.size[0] / 2 - w / 2;
            const y = -8 - h + 4;
            ctx.fillStyle = "rgba(30, 60, 90, 0.9)";
            if (typeof ctx.roundRect === "function") {
                ctx.beginPath();
                ctx.roundRect(x, y, w, h, 6);
                ctx.fill();
            } else {
                ctx.fillRect(x, y, w, h);
            }
            ctx.fillStyle = "#9be0ff";
            ctx.fillText(text, this.size[0] / 2, y + h - 6);
            ctx.restore();
        };
    },
});
