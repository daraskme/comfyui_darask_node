// DARASK Lora Loader — single-widget-per-row LoRA stacker.
//
// Each row is one custom canvas widget that hosts: drag handle, on/off
// toggle, LoRA file picker (nested-folder menu), model strength, optional
// CLIP strength (toggle via row right-click → "Show CLIP strength"), and
// remove button. Rows can be drag-reordered or moved via the row context
// menu. Widget values save as `{on, lora, strength, strengthTwo}` dicts
// so the Python side and rgthree Power Lora Loader workflows stay
// interoperable.
//
// UX modelled after rgthree-comfy's Power Lora Loader (MIT,
// https://github.com/rgthree/rgthree-comfy). This is an independent
// implementation — no rgthree code is bundled.

import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const NODE_NAME = "DARASK Lora Loader";
const NONE_VALUE = "None";
const ROW_TYPE = "DARASK_LORA_ROW";
const ROW_HEIGHT = 22;
const STRENGTH_STEP = 0.05;
const STRENGTH_MIN = -10;
const STRENGTH_MAX = 10;
const SCRUB_PER_PX = 0.01;

// --- LoRA filename list -------------------------------------------------

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
            console.warn("DARASK Lora Loader: failed to fetch LoRA list:", e);
        }
        LORA_LIST_LOADED = true;
        return LORA_LIST;
    })();
    return LORA_LIST_PROMISE;
}

// --- Display helpers ----------------------------------------------------

function shortName(lora) {
    if (!lora || lora === NONE_VALUE) return NONE_VALUE;
    const base = String(lora).replace(/\\/g, "/").split("/").pop() || lora;
    return base.replace(/\.(safetensors|ckpt|pt|bin|sft)$/i, "");
}

function fmtStrength(v) {
    return Number(v).toFixed(2);
}

function clampStrength(v) {
    if (!isFinite(v)) return 0;
    return Math.max(STRENGTH_MIN, Math.min(STRENGTH_MAX, v));
}

function roundToStep(v) {
    return Math.round(v / STRENGTH_STEP) * STRENGTH_STEP;
}

// --- Row drawing --------------------------------------------------------

function drawRow(ctx, widget, node, width, y) {
    const h = ROW_HEIGHT;
    const value = widget.value || {};
    const isOn = value.on !== false;
    const hasTwo = typeof value.strengthTwo === "number";

    const padL = 6, padR = 6, gap = 4;
    const handleW = 12;
    const toggleW = 18;
    const strW = 56;
    const removeW = 14;
    const totalStrW = hasTwo ? strW * 2 + gap : strW;

    const handleX = padL;
    const toggleX = handleX + handleW + gap;
    const nameX = toggleX + toggleW + gap;
    const removeX = width - padR - removeW;
    const strRight = removeX - gap;
    const strLeft = strRight - totalStrW;
    const nameW = Math.max(40, strLeft - gap - nameX);

    ctx.save();

    // Row background
    ctx.fillStyle = isOn ? "rgba(60, 60, 70, 0.55)" : "rgba(35, 35, 40, 0.55)";
    ctx.beginPath();
    if (typeof ctx.roundRect === "function") {
        ctx.roundRect(padL - 2, y + 1, width - padL - padR + 4, h - 2, 4);
    } else {
        ctx.rect(padL - 2, y + 1, width - padL - padR + 4, h - 2);
    }
    ctx.fill();

    // Drag handle (three short bars)
    ctx.strokeStyle = "rgba(220, 220, 220, 0.5)";
    ctx.lineWidth = 1.2;
    for (const dy of [-4, 0, 4]) {
        const cy = y + h / 2 + dy;
        ctx.beginPath();
        ctx.moveTo(handleX + 1, cy);
        ctx.lineTo(handleX + handleW - 1, cy);
        ctx.stroke();
    }

    ctx.textBaseline = "middle";

    // Toggle
    ctx.fillStyle = isOn ? "rgb(110, 220, 130)" : "rgb(150, 150, 150)";
    ctx.font = "bold 14px sans-serif";
    ctx.textAlign = "center";
    ctx.fillText(isOn ? "✓" : "—", toggleX + toggleW / 2, y + h / 2);

    // LoRA name
    ctx.fillStyle = isOn ? "rgba(235, 235, 235, 1)" : "rgba(140, 140, 140, 1)";
    ctx.font = "12px sans-serif";
    ctx.textAlign = "left";
    const full = shortName(value.lora);
    let display = full;
    while (display.length > 0 && ctx.measureText(display + "…").width > nameW - 4) {
        display = display.slice(0, -1);
    }
    if (display.length < full.length && display.length > 0) display += "…";
    else if (display.length === 0) display = "";
    ctx.fillText(display, nameX, y + h / 2);

    // Strength cells
    function drawStrengthCell(cx, cw, val) {
        ctx.fillStyle = "rgba(15, 15, 20, 0.6)";
        ctx.beginPath();
        if (typeof ctx.roundRect === "function") {
            ctx.roundRect(cx, y + 3, cw, h - 6, 3);
        } else {
            ctx.rect(cx, y + 3, cw, h - 6);
        }
        ctx.fill();

        ctx.fillStyle = isOn ? "rgba(200, 200, 220, 0.7)" : "rgba(120, 120, 130, 0.5)";
        ctx.font = "10px sans-serif";
        ctx.textAlign = "center";
        ctx.fillText("◀", cx + 6, y + h / 2);
        ctx.fillText("▶", cx + cw - 6, y + h / 2);

        ctx.fillStyle = isOn ? "rgba(255, 255, 255, 0.95)" : "rgba(150, 150, 150, 0.7)";
        ctx.font = "11px sans-serif";
        ctx.fillText(fmtStrength(val), cx + cw / 2, y + h / 2);
    }

    drawStrengthCell(strLeft, strW, typeof value.strength === "number" ? value.strength : 1.0);
    if (hasTwo) {
        drawStrengthCell(strLeft + strW + gap, strW, value.strengthTwo);
    }

    // Remove
    ctx.fillStyle = "rgba(225, 110, 110, 0.75)";
    ctx.font = "bold 14px sans-serif";
    ctx.textAlign = "center";
    ctx.fillText("×", removeX + removeW / 2, y + h / 2);

    ctx.restore();

    widget._zones = {
        handle: [handleX, y, handleW, h],
        toggle: [toggleX, y, toggleW, h],
        name: [nameX, y, nameW, h],
        strength: [strLeft, y, strW, h],
        strengthTwo: hasTwo ? [strLeft + strW + gap, y, strW, h] : null,
        remove: [removeX, y, removeW, h],
        full: [0, y, width, h],
    };
}

function pointInZone(zone, pos) {
    if (!zone) return false;
    const [x, y, w, h] = zone;
    return pos[0] >= x && pos[0] < x + w && pos[1] >= y && pos[1] < y + h;
}

// --- Strength interactions ---------------------------------------------

function bumpStrength(widget, node, key, delta) {
    const cur = typeof widget.value[key] === "number" ? widget.value[key] : 1.0;
    widget.value[key] = clampStrength(roundToStep(cur + delta));
    node.setDirtyCanvas(true, true);
}

function scrubStrength(widget, node, key, downEvent) {
    const startVal = typeof widget.value[key] === "number" ? widget.value[key] : 1.0;
    const startX = downEvent.clientX;
    const scale = app.canvas?.ds?.scale ?? 1;
    let moved = false;

    function onMove(e) {
        const dx = (e.clientX - startX) / scale;
        if (Math.abs(dx) > 2) moved = true;
        if (!moved) return;
        widget.value[key] = clampStrength(roundToStep(startVal + dx * SCRUB_PER_PX));
        node.setDirtyCanvas(true, true);
    }
    function onUp() {
        document.removeEventListener("pointermove", onMove);
        document.removeEventListener("pointerup", onUp);
    }
    document.addEventListener("pointermove", onMove);
    document.addEventListener("pointerup", onUp);
}

function promptStrength(widget, node, key) {
    const cur = typeof widget.value[key] === "number" ? widget.value[key] : 1.0;
    const v = window.prompt("Strength:", String(cur));
    if (v === null) return;
    const n = parseFloat(v);
    if (!isNaN(n)) {
        widget.value[key] = clampStrength(n);
        node.setDirtyCanvas(true, true);
    }
}

// --- LoRA picker --------------------------------------------------------

function buildLoraTree(list) {
    const root = { files: [], folders: {} };
    for (const f of list) {
        if (f === NONE_VALUE) {
            root.files.push({ name: NONE_VALUE, full: NONE_VALUE });
            continue;
        }
        const parts = String(f).replace(/\\/g, "/").split("/");
        let cur = root;
        for (let i = 0; i < parts.length - 1; i++) {
            const p = parts[i];
            cur.folders[p] = cur.folders[p] || { files: [], folders: {} };
            cur = cur.folders[p];
        }
        cur.files.push({ name: parts[parts.length - 1], full: f });
    }
    return root;
}

function openLoraPicker(widget, node, event) {
    ensureLoraList().then((list) => {
        const tree = buildLoraTree(list);

        function menuFor(tree) {
            const items = [];
            for (const name of Object.keys(tree.folders).sort((a, b) => a.localeCompare(b))) {
                const sub = tree.folders[name];
                items.push({
                    content: "📁 " + name,
                    has_submenu: true,
                    callback: (val, opts, e, parentMenu) => {
                        new LiteGraph.ContextMenu(menuFor(sub), { event: e, parentMenu });
                    },
                });
            }
            for (const f of tree.files.sort((a, b) => a.name.localeCompare(b.name))) {
                items.push({
                    content: f.full === NONE_VALUE ? "(None)" : shortName(f.full),
                    callback: () => {
                        widget.value.lora = f.full;
                        if (f.full !== NONE_VALUE && widget.value.on === false) {
                            widget.value.on = true;
                        }
                        node.setDirtyCanvas(true, true);
                    },
                });
            }
            return items;
        }

        new LiteGraph.ContextMenu(menuFor(tree), { event });
    });
}

// --- Row management ----------------------------------------------------

function getRowWidgets(node) {
    return (node.widgets || []).filter((w) => w.type === ROW_TYPE);
}

function renumberRows(node) {
    let i = 1;
    for (const w of node.widgets || []) {
        if (w.type === ROW_TYPE) w.name = `lora_${i++}`;
    }
}

function moveRow(node, widget, dir) {
    const idx = (node.widgets || []).indexOf(widget);
    if (idx < 0) return;
    const rowIndices = [];
    for (let i = 0; i < node.widgets.length; i++) {
        if (node.widgets[i].type === ROW_TYPE) rowIndices.push(i);
    }
    const rowPos = rowIndices.indexOf(idx);
    const newPos = rowPos + dir;
    if (newPos < 0 || newPos >= rowIndices.length) return;
    const swap = rowIndices[newPos];
    [node.widgets[idx], node.widgets[swap]] = [node.widgets[swap], node.widgets[idx]];
    renumberRows(node);
    node.setDirtyCanvas(true, true);
}

function startRowDrag(node, widget, downEvent) {
    // Threshold-based reorder: when the cursor crosses one row height in
    // either direction, swap with the adjacent row and reset the anchor.
    let anchorY = downEvent.clientY;
    const scale = app.canvas?.ds?.scale ?? 1;
    const step = ROW_HEIGHT * scale;

    function onMove(e) {
        const dy = e.clientY - anchorY;
        if (dy >= step) {
            moveRow(node, widget, 1);
            anchorY += step;
        } else if (dy <= -step) {
            moveRow(node, widget, -1);
            anchorY -= step;
        }
    }
    function onUp() {
        document.removeEventListener("pointermove", onMove);
        document.removeEventListener("pointerup", onUp);
    }
    document.addEventListener("pointermove", onMove);
    document.addEventListener("pointerup", onUp);
}

function openRowMenu(node, widget, event) {
    const rows = getRowWidgets(node);
    const idx = rows.indexOf(widget);
    const items = [
        {
            content: "Move Up",
            disabled: idx <= 0,
            callback: () => moveRow(node, widget, -1),
        },
        {
            content: "Move Down",
            disabled: idx >= rows.length - 1,
            callback: () => moveRow(node, widget, 1),
        },
        null,
        {
            content: widget.value.on === false ? "Enable" : "Disable",
            callback: () => {
                widget.value.on = widget.value.on === false;
                node.setDirtyCanvas(true, true);
            },
        },
        {
            content: typeof widget.value.strengthTwo === "number"
                ? "Hide CLIP strength"
                : "Show CLIP strength",
            callback: () => {
                if (typeof widget.value.strengthTwo === "number") {
                    delete widget.value.strengthTwo;
                } else {
                    widget.value.strengthTwo = typeof widget.value.strength === "number"
                        ? widget.value.strength
                        : 1.0;
                }
                node.setDirtyCanvas(true, true);
            },
        },
        null,
        {
            content: "Remove",
            callback: () => node.daraskRemoveRow(widget),
        },
    ];
    new LiteGraph.ContextMenu(items, { event });
}

// --- Widget factory ----------------------------------------------------

function createRowWidget(initial) {
    const value = {
        on: typeof initial?.on === "boolean" ? initial.on : true,
        lora: typeof initial?.lora === "string" ? initial.lora : NONE_VALUE,
        strength: typeof initial?.strength === "number" ? initial.strength : 1.0,
    };
    if (typeof initial?.strengthTwo === "number") {
        value.strengthTwo = initial.strengthTwo;
    }

    return {
        type: ROW_TYPE,
        name: "lora_0",
        value,
        options: { serialize: true },

        draw(ctx, node, width, y) {
            drawRow(ctx, this, node, width, y);
        },

        computeSize() {
            return [240, ROW_HEIGHT];
        },

        mouse(event, pos, node) {
            const z = this._zones;
            if (!z) return false;
            const isDown = event.type === "pointerdown" || event.type === "mousedown";
            const isDbl = event.type === "dblclick" || event.type === "pointerdblclick";

            if (isDbl) {
                if (pointInZone(z.strength, pos)) {
                    promptStrength(this, node, "strength");
                    return true;
                }
                if (pointInZone(z.strengthTwo, pos)) {
                    promptStrength(this, node, "strengthTwo");
                    return true;
                }
                return false;
            }

            if (!isDown) return false;

            if (event.button === 2) {
                openRowMenu(node, this, event);
                return true;
            }
            if (pointInZone(z.handle, pos)) {
                startRowDrag(node, this, event);
                return true;
            }
            if (pointInZone(z.toggle, pos)) {
                this.value.on = !this.value.on;
                node.setDirtyCanvas(true, true);
                return true;
            }
            if (pointInZone(z.remove, pos)) {
                node.daraskRemoveRow(this);
                return true;
            }
            for (const key of ["strength", "strengthTwo"]) {
                const zone = z[key];
                if (!zone) continue;
                if (pointInZone(zone, pos)) {
                    const [zx, , zw] = zone;
                    const rel = pos[0] - zx;
                    if (rel < 14) {
                        bumpStrength(this, node, key, -STRENGTH_STEP);
                    } else if (rel > zw - 14) {
                        bumpStrength(this, node, key, STRENGTH_STEP);
                    } else {
                        scrubStrength(this, node, key, event);
                    }
                    return true;
                }
            }
            if (pointInZone(z.name, pos)) {
                openLoraPicker(this, node, event);
                return true;
            }
            return false;
        },
    };
}

// --- Node lifecycle ----------------------------------------------------

app.registerExtension({
    name: "darask.lora_loader",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE_NAME) return;

        nodeType.prototype.serialize_widgets = true;

        nodeType.prototype.daraskAddRow = function (initial) {
            const w = createRowWidget(initial);
            const widgets = this.widgets || [];
            let insertAt = widgets.length;
            for (let i = 0; i < widgets.length; i++) {
                if (widgets[i]._daraskAddBtn) { insertAt = i; break; }
            }
            widgets.splice(insertAt, 0, w);
            this.widgets = widgets;
            renumberRows(this);
            this.setDirtyCanvas(true, true);
            return w;
        };

        nodeType.prototype.daraskRemoveRow = function (widget) {
            const i = (this.widgets || []).indexOf(widget);
            if (i < 0) return;
            this.widgets.splice(i, 1);
            renumberRows(this);
            this.setDirtyCanvas(true, true);
        };

        nodeType.prototype._daraskEnsureControls = function () {
            const widgets = this.widgets || [];
            if (!widgets.some((w) => w._daraskAddBtn)) {
                const b = this.addWidget("button", "+ Add LoRA", null, () => {
                    this.daraskAddRow();
                });
                b._daraskAddBtn = true;
            }
        };

        // Surface row actions in the node's right-click menu as a fallback
        // (LiteGraph's widget.mouse() doesn't always receive contextmenu).
        const getExtraMenuOptions = nodeType.prototype.getExtraMenuOptions;
        nodeType.prototype.getExtraMenuOptions = function (canvas, options) {
            getExtraMenuOptions?.apply(this, arguments);
            options.push(null);
            options.push({
                content: "+ Add LoRA",
                callback: () => this.daraskAddRow(),
            });
        };

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const r = onNodeCreated?.apply(this, arguments);
            this._daraskEnsureControls();
            ensureLoraList();
            if (typeof this.computeSize === "function") {
                this.size = this.computeSize();
            }
            return r;
        };

        const onConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function (info) {
            const savedSize =
                info && Array.isArray(info.size) ? [info.size[0], info.size[1]] : null;

            // Clear widgets so super.configure can't bind saved values to
            // slots that won't exist after we rebuild from widgets_values.
            this.widgets = [];

            const r = onConfigure?.apply(this, arguments);

            const values = info?.widgets_values || [];

            // 1) Dict format: {on, lora, strength, strengthTwo} per row.
            const dicts = values.filter(
                (v) => v && typeof v === "object" && !Array.isArray(v) && typeof v.lora !== "undefined",
            );

            if (dicts.length > 0) {
                for (const v of dicts) {
                    this.daraskAddRow({
                        on: typeof v.on === "boolean" ? v.on : true,
                        lora: typeof v.lora === "string" ? v.lora : NONE_VALUE,
                        strength: typeof v.strength === "number" ? v.strength : 1.0,
                        strengthTwo: typeof v.strengthTwo === "number" ? v.strengthTwo : undefined,
                    });
                }
            } else {
                // 2) Legacy split format: (bool, str, num) triplets from the
                //    old three-widgets-per-row layout.
                for (let i = 0; i + 2 < values.length; ) {
                    const a = values[i], b = values[i + 1], c = values[i + 2];
                    if (typeof a === "boolean" && typeof b === "string" && typeof c === "number") {
                        this.daraskAddRow({ on: a, lora: b, strength: c });
                        i += 3;
                    } else {
                        i++;
                    }
                }
            }

            this._daraskEnsureControls();
            ensureLoraList();

            if (savedSize && this.size) {
                let minSize = [0, 0];
                if (typeof this.computeSize === "function") {
                    try { minSize = this.computeSize(); } catch (_) {}
                }
                this.size[0] = Math.max(savedSize[0] | 0, (minSize[0] | 0) || 0);
                this.size[1] = Math.max(savedSize[1] | 0, (minSize[1] | 0) || 0);
            }

            this.setDirtyCanvas(true, true);
            return r;
        };
    },
});
