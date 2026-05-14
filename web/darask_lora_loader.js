// DARASK Lora Loader — frontend.
//
// Each LoRA row is three standard LiteGraph widgets: a toggle (on/off), a
// combo (file picker, list pulled from /object_info/LoraLoader), and a
// number (strength). "+ Add LoRA" and "− Remove Last" are litegraph
// button widgets at the bottom of the node. No custom canvas drawing or
// mouse hit-testing — that path had reliability problems on some
// ComfyUI builds (clicks freezing the canvas). Using only built-in widget
// types means LiteGraph handles draw/input itself.
//
// Saved widgets_values format is a flat list of values in widget order
// (per ComfyUI's normal serialization). The Python side groups them back
// into (on, lora, strength) tuples by widget-name prefix `lora_N_*`.
//
// rgthree Power Lora Loader workflows save as dict-shaped values
// (`{on, lora, strength, strengthTwo}`); we detect that shape on load
// and re-create the rows from it so old workflows keep working.

import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const NODE_NAME = "DARASK Lora Loader";
const NONE_VALUE = "None";

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

function refreshComboValues(node) {
    // Any combo widgets we previously created point at the OLD LORA_LIST
    // array (since we replaced it in place). Re-assign so the dropdown
    // sees the new list.
    if (!node.widgets) return;
    for (const w of node.widgets) {
        if (w._daraskKind === "name" && w.options) {
            w.options.values = LORA_LIST;
        }
    }
    node.setDirtyCanvas(true, true);
}

app.registerExtension({
    name: "darask.lora_loader",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE_NAME) return;

        nodeType.prototype.serialize_widgets = true;

        // ---- Row management ----------------------------------------------

        nodeType.prototype.daraskAddRow = function (initial) {
            const idx = (this._daraskNextIdx = (this._daraskNextIdx || 0) + 1);

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

            const onW = this.addWidget(
                "toggle",
                `lora_${idx}_on`,
                initOn,
                () => {},
                { on: "✓", off: "—" },
            );
            const nameW = this.addWidget(
                "combo",
                `lora_${idx}`,
                initName,
                () => {},
                { values: LORA_LIST },
            );
            const strW = this.addWidget(
                "number",
                `lora_${idx}_strength`,
                initStrength,
                () => {},
                { min: -4, max: 4, step: 0.05, precision: 2 },
            );

            for (const [w, kind] of [
                [onW, "on"],
                [nameW, "name"],
                [strW, "strength"],
            ]) {
                w._daraskGroupIdx = idx;
                w._daraskKind = kind;
            }

            // Make sure the combo's values reference the always-up-to-date list.
            ensureLoraList().then(() => refreshComboValues(this));

            this._daraskMoveControlsToEnd();
            this.setSize(this.computeSize());
            this.setDirtyCanvas(true, true);
            return idx;
        };

        nodeType.prototype.daraskRemoveLastRow = function () {
            const groups = (this.widgets || [])
                .filter((w) => w._daraskGroupIdx != null)
                .map((w) => w._daraskGroupIdx);
            if (!groups.length) return;
            const maxIdx = Math.max(...groups);
            this.widgets = (this.widgets || []).filter(
                (w) => w._daraskGroupIdx !== maxIdx,
            );
            this.setSize(this.computeSize());
            this.setDirtyCanvas(true, true);
        };

        // ---- Control buttons --------------------------------------------

        nodeType.prototype._daraskEnsureControls = function () {
            const hasAdd = (this.widgets || []).some((w) => w._daraskAddBtn);
            if (!hasAdd) {
                const b = this.addWidget(
                    "button",
                    "+ Add LoRA",
                    null,
                    () => {
                        this.daraskAddRow();
                    },
                );
                b._daraskAddBtn = true;
            }
            const hasRem = (this.widgets || []).some((w) => w._daraskRemBtn);
            if (!hasRem) {
                const b = this.addWidget(
                    "button",
                    "− Remove Last",
                    null,
                    () => {
                        this.daraskRemoveLastRow();
                    },
                );
                b._daraskRemBtn = true;
            }
        };

        nodeType.prototype._daraskMoveControlsToEnd = function () {
            const ctrls = (this.widgets || []).filter(
                (w) => w._daraskAddBtn || w._daraskRemBtn,
            );
            const rest = (this.widgets || []).filter(
                (w) => !w._daraskAddBtn && !w._daraskRemBtn,
            );
            this.widgets = [...rest, ...ctrls];
        };

        // ---- Lifecycle ---------------------------------------------------

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const r = onNodeCreated?.apply(this, arguments);
            ensureLoraList().then(() => refreshComboValues(this));
            this._daraskEnsureControls();
            this._daraskMoveControlsToEnd();
            this.setSize(this.computeSize());
            return r;
        };

        const onConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function (info) {
            // Strip everything so super.configure doesn't try to apply
            // saved widget values to slots that no longer exist.
            this.widgets = [];
            this._daraskNextIdx = 0;

            const r = onConfigure?.apply(this, arguments);

            const values = info?.widgets_values || [];

            // 1) rgthree Power Lora Loader format: dicts with {lora, ...}.
            const dictRows = values.filter(
                (v) =>
                    v &&
                    typeof v === "object" &&
                    !Array.isArray(v) &&
                    typeof v.lora !== "undefined",
            );

            if (dictRows.length > 0) {
                for (const v of dictRows) {
                    this.daraskAddRow({
                        on: typeof v.on === "boolean" ? v.on : true,
                        lora: typeof v.lora === "string" ? v.lora : NONE_VALUE,
                        strength:
                            typeof v.strength === "number" ? v.strength : 1.0,
                    });
                }
            } else {
                // 2) Our own split format: (bool, string, number) triplets.
                for (let i = 0; i + 2 < values.length; ) {
                    const a = values[i];
                    const b = values[i + 1];
                    const c = values[i + 2];
                    if (
                        typeof a === "boolean" &&
                        typeof b === "string" &&
                        typeof c === "number"
                    ) {
                        this.daraskAddRow({ on: a, lora: b, strength: c });
                        i += 3;
                    } else {
                        i++;
                    }
                }
            }

            this._daraskEnsureControls();
            this._daraskMoveControlsToEnd();
            ensureLoraList().then(() => refreshComboValues(this));
            this.setSize(this.computeSize());
            this.setDirtyCanvas(true, true);
            return r;
        };
    },
});
