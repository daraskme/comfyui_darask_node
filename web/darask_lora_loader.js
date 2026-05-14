// DARASK Lora Loader — frontend.
//
// A compact multi-LoRA stacker in one node. Each row has:
//   - on/off toggle (left)
//   - LoRA filename, click to open picker (middle)
//   - strength number (right), click to edit, drag to scrub
//
// Inspired by rgthree's Power Lora Loader but standalone — no external
// dependencies beyond ComfyUI's app + api.
//
// Widget value format per row: {on: bool, lora: string, strength: float, strengthTwo: float|null}
// Saved into widgets_values via `node.serialize_widgets = true`.

import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const NODE_NAME = "DARASK Lora Loader";
const ROW_HEIGHT = 22;
const PROP_SHOW_STRENGTHS = "Show Strengths";
const PROP_SHOW_STRENGTHS_SINGLE = "Single";
const PROP_SHOW_STRENGTHS_SEPARATE = "Model + Clip";

// Cache of available LoRA filenames, populated on demand.
let LORA_LIST = null;
let LORA_LIST_PROMISE = null;

async function loadLoraList(force = false) {
    if (LORA_LIST && !force) return LORA_LIST;
    if (LORA_LIST_PROMISE) return LORA_LIST_PROMISE;
    LORA_LIST_PROMISE = (async () => {
        try {
            const resp = await api.fetchApi("/object_info/LoraLoader");
            const data = await resp.json();
            LORA_LIST = data?.LoraLoader?.input?.required?.lora_name?.[0] || [];
        } catch (e) {
            console.warn("DARASK Lora Loader: couldn't fetch LoRA list", e);
            LORA_LIST = [];
        }
        return LORA_LIST;
    })();
    return LORA_LIST_PROMISE;
}

function fitString(ctx, str, maxW) {
    if (!str) return "";
    if (ctx.measureText(str).width <= maxW) return str;
    let s = str;
    while (s.length > 1 && ctx.measureText(s + "…").width > maxW) {
        s = s.slice(0, -1);
    }
    return s + "…";
}

function clampRound(v, step) {
    return Math.round(v / step) * step;
}

// ---------------------------------------------------------------------------
// Row widget — one LoRA entry.
// ---------------------------------------------------------------------------

class DaraskLoraRowWidget {
    constructor(name) {
        this.name = name;
        this.type = "custom";
        this.value = { on: true, lora: null, strength: 1, strengthTwo: null };
        this._hitAreas = {};
        this._dragging = null;
    }

    get y() {
        return this.last_y || 0;
    }

    serializeValue() {
        return this.value;
    }

    computeSize(_width) {
        return [0, ROW_HEIGHT];
    }

    draw(ctx, node, width, posY, height) {
        this.last_y = posY;
        const margin = 8;
        const innerPad = 4;
        const midY = posY + height / 2;

        const sepMode =
            node.properties?.[PROP_SHOW_STRENGTHS] === PROP_SHOW_STRENGTHS_SEPARATE;

        ctx.save();
        // Row background.
        ctx.fillStyle = this.value.on ? "rgba(60,90,60,0.20)" : "rgba(40,40,40,0.25)";
        ctx.fillRect(margin, posY + 1, width - margin * 2, height - 2);

        // ----- Toggle (left) -----
        const toggleW = 30;
        const toggleX = margin + 4;
        const tknobR = 6;
        ctx.fillStyle = this.value.on ? "#4ade80" : "#555";
        // Track
        ctx.beginPath();
        const trackY = midY - 5;
        const trackH = 10;
        const trackR = trackH / 2;
        ctx.moveTo(toggleX + trackR, trackY);
        ctx.lineTo(toggleX + toggleW - trackR, trackY);
        ctx.arc(toggleX + toggleW - trackR, trackY + trackR, trackR, -Math.PI / 2, Math.PI / 2);
        ctx.lineTo(toggleX + trackR, trackY + trackH);
        ctx.arc(toggleX + trackR, trackY + trackR, trackR, Math.PI / 2, -Math.PI / 2);
        ctx.fill();
        // Knob
        ctx.fillStyle = "#fff";
        const knobX = this.value.on ? toggleX + toggleW - trackR : toggleX + trackR;
        ctx.beginPath();
        ctx.arc(knobX, midY, tknobR, 0, Math.PI * 2);
        ctx.fill();
        this._hitAreas.toggle = [toggleX, posY, toggleW + 4, height];

        // ----- Strength widget(s) on the right -----
        const strBoxW = 70;
        const strBoxGap = 4;
        const totalStrW = sepMode ? strBoxW * 2 + strBoxGap : strBoxW;
        const strRight = width - margin - 4;
        const strLeft = strRight - totalStrW;

        const drawStrengthBox = (x, val, hitPrefix) => {
            ctx.fillStyle = "rgba(255,255,255,0.08)";
            ctx.fillRect(x, posY + 3, strBoxW, height - 6);

            // − button
            ctx.fillStyle = "#aaa";
            ctx.font = "bold 12px sans-serif";
            ctx.textAlign = "center";
            ctx.textBaseline = "middle";
            ctx.fillText("−", x + 10, midY);
            // value
            ctx.fillStyle = this.value.on ? "#fff" : "#999";
            ctx.font = "11px sans-serif";
            ctx.fillText(
                (val ?? 0).toFixed(2),
                x + strBoxW / 2,
                midY,
            );
            // + button
            ctx.fillStyle = "#aaa";
            ctx.font = "bold 12px sans-serif";
            ctx.fillText("+", x + strBoxW - 10, midY);

            this._hitAreas[hitPrefix + "Dec"] = [x, posY, 20, height];
            this._hitAreas[hitPrefix + "Inc"] = [x + strBoxW - 20, posY, 20, height];
            this._hitAreas[hitPrefix + "Val"] = [x + 20, posY, strBoxW - 40, height];
        };

        drawStrengthBox(strLeft, this.value.strength, "str");
        if (sepMode) {
            const two =
                this.value.strengthTwo != null
                    ? this.value.strengthTwo
                    : this.value.strength;
            drawStrengthBox(strLeft + strBoxW + strBoxGap, two, "str2");
        } else {
            // ensure stale hit areas don't catch clicks
            this._hitAreas.str2Dec = [0, -1, 0, 0];
            this._hitAreas.str2Inc = [0, -1, 0, 0];
            this._hitAreas.str2Val = [0, -1, 0, 0];
        }

        // ----- LoRA name (middle, fills remaining) -----
        const nameX = toggleX + toggleW + innerPad + 6;
        const nameW = strLeft - nameX - 6;
        if (nameW > 20) {
            ctx.fillStyle = this.value.on ? "#e5e5e5" : "#888";
            ctx.font = "12px sans-serif";
            ctx.textAlign = "left";
            ctx.textBaseline = "middle";
            const display = this.value.lora || "(click to choose LoRA)";
            ctx.fillText(fitString(ctx, display, nameW), nameX, midY);
        }
        this._hitAreas.lora = [nameX - 4, posY, Math.max(0, nameW + 8), height];

        ctx.restore();
    }

    _hitTest(pos) {
        const [x, y] = pos;
        for (const [name, [hx, hy, hw, hh]] of Object.entries(this._hitAreas)) {
            if (hw <= 0 || hh <= 0) continue;
            if (x >= hx && x <= hx + hw && y >= hy && y <= hy + hh) return name;
        }
        return null;
    }

    mouse(event, pos, node) {
        if (event.type === "pointerdown") {
            const hit = this._hitTest(pos);
            if (!hit) return false;
            this._dragging = { hit, startX: pos[0], startY: pos[1], moved: false };
            return true;
        }
        if (event.type === "pointermove") {
            if (!this._dragging) return false;
            const dx = pos[0] - this._dragging.startX;
            if (Math.abs(dx) > 2) this._dragging.moved = true;
            // Drag-to-scrub on strength val
            if (this._dragging.hit === "strVal" || this._dragging.hit === "str2Val") {
                const which = this._dragging.hit === "str2Val" ? "strengthTwo" : "strength";
                const base =
                    this._dragging.startVal ??
                    (this._dragging.startVal = this.value[which] ?? this.value.strength);
                const newVal = clampRound(base + dx * 0.01, 0.01);
                if (which === "strengthTwo") this.value.strengthTwo = newVal;
                else this.value.strength = newVal;
                node.setDirtyCanvas(true, true);
            }
            return true;
        }
        if (event.type === "pointerup") {
            if (!this._dragging) return false;
            const { hit, moved } = this._dragging;
            this._dragging = null;
            if (moved) return true;

            if (hit === "toggle") {
                this.value.on = !this.value.on;
                node.setDirtyCanvas(true, true);
            } else if (hit === "lora") {
                this._showLoraChooser(event, node);
            } else if (hit === "strDec" || hit === "strInc") {
                const delta = hit === "strInc" ? 0.05 : -0.05;
                this.value.strength = clampRound((this.value.strength ?? 1) + delta, 0.01);
                node.setDirtyCanvas(true, true);
            } else if (hit === "str2Dec" || hit === "str2Inc") {
                const delta = hit === "str2Inc" ? 0.05 : -0.05;
                const base =
                    this.value.strengthTwo != null ? this.value.strengthTwo : this.value.strength;
                this.value.strengthTwo = clampRound(base + delta, 0.01);
                node.setDirtyCanvas(true, true);
            } else if (hit === "strVal") {
                this._promptValue("strength", node);
            } else if (hit === "str2Val") {
                this._promptValue("strengthTwo", node);
            }
            return true;
        }
        return false;
    }

    _promptValue(which, node) {
        const cur =
            which === "strengthTwo"
                ? (this.value.strengthTwo != null ? this.value.strengthTwo : this.value.strength)
                : this.value.strength;
        const s = window.prompt(`${which}:`, String(cur ?? 1));
        if (s == null) return;
        const f = parseFloat(s);
        if (Number.isFinite(f)) {
            if (which === "strengthTwo") this.value.strengthTwo = f;
            else this.value.strength = f;
            node.setDirtyCanvas(true, true);
        }
    }

    async _showLoraChooser(event, node) {
        const all = await loadLoraList();
        let pool = all.slice();
        // Apply optional Match filter (regex stored in properties).
        const match = (node.properties?.["Match"] || "").trim();
        if (match) {
            try {
                const rx = new RegExp(match);
                pool = pool.filter((n) => rx.test(n));
            } catch (_) {}
        }
        if (!pool.length) {
            window.alert("DARASK Lora Loader: no LoRAs found in loras/.");
            return;
        }

        // Build context menu items.
        const items = pool.map((name) => ({
            content: name,
            callback: () => {
                this.value.lora = name;
                if (!this.value.on) this.value.on = true;
                node.setDirtyCanvas(true, true);
            },
        }));
        new LiteGraph.ContextMenu(items, {
            event: event,
            scrollSpeed: 0.1,
            title: "Choose LoRA",
        });
    }
}

// ---------------------------------------------------------------------------
// "+ Add Lora" button widget.
// ---------------------------------------------------------------------------

class DaraskAddLoraButton {
    constructor() {
        this.name = "darask_add_lora";
        this.type = "custom";
        this.value = null;
        this._hit = [0, 0, 0, 0];
    }

    serializeValue() {
        return null;
    }

    computeSize(_width) {
        return [0, 26];
    }

    draw(ctx, node, width, posY, height) {
        const margin = 8;
        const x = margin;
        const w = width - margin * 2;
        const h = height - 4;
        ctx.save();
        ctx.fillStyle = "rgba(70,130,90,0.35)";
        ctx.strokeStyle = "rgba(140,220,170,0.5)";
        ctx.lineWidth = 1;
        ctx.fillRect(x, posY + 2, w, h);
        ctx.strokeRect(x, posY + 2, w, h);
        ctx.fillStyle = "#dfe";
        ctx.font = "bold 12px sans-serif";
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillText("➕ Add Lora", x + w / 2, posY + 2 + h / 2);
        ctx.restore();
        this._hit = [x, posY + 2, w, h];
    }

    mouse(event, pos, node) {
        if (event.type !== "pointerup") return false;
        const [x, y] = pos;
        const [hx, hy, hw, hh] = this._hit;
        if (x >= hx && x <= hx + hw && y >= hy && y <= hy + hh) {
            node.daraskAddLoraRow();
            return true;
        }
        return false;
    }
}

// ---------------------------------------------------------------------------
// Node registration.
// ---------------------------------------------------------------------------

app.registerExtension({
    name: "darask.lora_loader",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE_NAME) return;

        // Pre-fetch the LoRA list so the chooser opens instantly.
        loadLoraList();

        nodeType.prototype.serialize_widgets = true;

        nodeType.prototype.daraskAddLoraRow = function (initial) {
            const idx = (this._daraskRowCounter = (this._daraskRowCounter || 0) + 1);
            const widget = new DaraskLoraRowWidget(`lora_${idx}`);
            if (initial) widget.value = { ...widget.value, ...initial };
            this.addCustomWidget(widget);
            // Keep the "+ Add Lora" button at the bottom.
            this._daraskReorderWidgets();
            this.setDirtyCanvas(true, true);
            return widget;
        };

        nodeType.prototype.daraskRemoveRow = function (widget) {
            const i = this.widgets.indexOf(widget);
            if (i >= 0) {
                this.widgets.splice(i, 1);
                this.setDirtyCanvas(true, true);
            }
        };

        nodeType.prototype._daraskReorderWidgets = function () {
            // Sort: row widgets first (preserving their order), then the add button last.
            const rows = [];
            const addBtn = [];
            const other = [];
            for (const w of this.widgets || []) {
                if (w instanceof DaraskLoraRowWidget) rows.push(w);
                else if (w instanceof DaraskAddLoraButton) addBtn.push(w);
                else other.push(w);
            }
            this.widgets = [...other, ...rows, ...addBtn];
        };

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const r = onNodeCreated?.apply(this);
            if (!this.properties[PROP_SHOW_STRENGTHS]) {
                this.properties[PROP_SHOW_STRENGTHS] = PROP_SHOW_STRENGTHS_SINGLE;
            }
            if (this.properties["Match"] == null) {
                this.properties["Match"] = "";
            }
            // Add the "+ Add Lora" button on first creation.
            this.addCustomWidget(new DaraskAddLoraButton());
            this._daraskReorderWidgets();
            this.setSize(this.computeSize());
            return r;
        };

        const onConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function (info) {
            // Rebuild row widgets from saved widgets_values.
            // Clear existing row widgets first to avoid duplicates.
            this.widgets = (this.widgets || []).filter(
                (w) => !(w instanceof DaraskLoraRowWidget),
            );
            for (const v of info?.widgets_values || []) {
                if (v && typeof v === "object" && "lora" in v && "strength" in v) {
                    this.daraskAddLoraRow(v);
                }
            }
            // Restore button & reorder.
            if (!(this.widgets || []).some((w) => w instanceof DaraskAddLoraButton)) {
                this.addCustomWidget(new DaraskAddLoraButton());
            }
            this._daraskReorderWidgets();
            const r = onConfigure?.apply(this, arguments);
            this.setDirtyCanvas(true, true);
            return r;
        };

        // Right-click on a row → context menu (toggle / move / remove).
        const getSlotMenuOptions = nodeType.prototype.getSlotMenuOptions;
        nodeType.prototype.getSlotMenuOptions = function (slot) {
            return getSlotMenuOptions?.apply(this, arguments);
        };
        const getSlotInPosition = nodeType.prototype.getSlotInPosition;
        nodeType.prototype.getSlotInPosition = function (cx, cy) {
            const slot = getSlotInPosition?.apply(this, arguments);
            if (slot) return slot;
            // Find which widget the user clicked on (if any).
            let target = null;
            const localY = cy - this.pos[1];
            for (const w of this.widgets || []) {
                if (w instanceof DaraskLoraRowWidget && w.last_y != null) {
                    if (localY >= w.last_y && localY <= w.last_y + ROW_HEIGHT) {
                        target = w;
                        break;
                    }
                }
            }
            if (target) {
                return { widget: target, output: { type: "DARASK LORA ROW" } };
            }
            return null;
        };

        const _getSlotMenu = nodeType.prototype.getSlotMenuOptions;
        nodeType.prototype.getSlotMenuOptions = function (slot) {
            if (slot?.widget instanceof DaraskLoraRowWidget) {
                const w = slot.widget;
                const idx = this.widgets.indexOf(w);
                const rowsOnly = (this.widgets || []).filter(
                    (x) => x instanceof DaraskLoraRowWidget,
                );
                const rowIdx = rowsOnly.indexOf(w);
                const items = [
                    {
                        content: `${w.value.on ? "⚫ Disable" : "🟢 Enable"}`,
                        callback: () => {
                            w.value.on = !w.value.on;
                            this.setDirtyCanvas(true, true);
                        },
                    },
                    {
                        content: "📁 Change LoRA…",
                        callback: () => w._showLoraChooser({}, this),
                    },
                    null,
                    {
                        content: "⬆️ Move Up",
                        disabled: rowIdx <= 0,
                        callback: () => {
                            const prev = rowsOnly[rowIdx - 1];
                            const i = this.widgets.indexOf(w);
                            const j = this.widgets.indexOf(prev);
                            this.widgets[i] = prev;
                            this.widgets[j] = w;
                            this.setDirtyCanvas(true, true);
                        },
                    },
                    {
                        content: "⬇️ Move Down",
                        disabled: rowIdx >= rowsOnly.length - 1,
                        callback: () => {
                            const next = rowsOnly[rowIdx + 1];
                            const i = this.widgets.indexOf(w);
                            const j = this.widgets.indexOf(next);
                            this.widgets[i] = next;
                            this.widgets[j] = w;
                            this.setDirtyCanvas(true, true);
                        },
                    },
                    null,
                    {
                        content: "🗑️ Remove",
                        callback: () => this.daraskRemoveRow(w),
                    },
                ];
                new LiteGraph.ContextMenu(items, {
                    title: "DARASK LoRA",
                    event: window.event,
                });
                return undefined;
            }
            return _getSlotMenu?.apply(this, arguments);
        };
    },
});
