// DARASK Prompt Cell dynamic input slot UI.
//
// Python declares many optional `prev_N` / `set_N` slots so chains can branch
// and merge. To keep the UI clean we only ever show (connected + 1) slots:
// one trailing empty slot for the next connection, hidden once it's used.
//
// Disconnecting collapses trailing empty slots back to one.

import { app } from "../../scripts/app.js";

const NODES = {
    "DARASK Prompt Cell": { prefix: "prev", max: 16, type: "DARASK_PROMPT_SET" },
    "DARASK Prompt Cell Output": { prefix: "set", max: 16, type: "DARASK_PROMPT_SET" },
};

function slotName(prefix, n) {
    return n === 1 ? prefix : `${prefix}_${n}`;
}

function slotIndex(name, prefix) {
    if (name === prefix) return 1;
    const m = name.match(new RegExp(`^${prefix}_(\\d+)$`));
    return m ? parseInt(m[1], 10) : null;
}

function findManagedSlots(node, prefix) {
    const slots = [];
    if (!node.inputs) return slots;
    for (let i = 0; i < node.inputs.length; i++) {
        const inp = node.inputs[i];
        const n = slotIndex(inp.name, prefix);
        if (n !== null) {
            slots.push({ idx: i, num: n, name: inp.name, connected: inp.link != null });
        }
    }
    slots.sort((a, b) => a.num - b.num);
    return slots;
}

// Preserve the user's (or workflow's) node size while ensuring it never
// falls below the computed minimum. ComfyUI's addInput / removeInput
// internally calls setSize(computeSize()), which would reset any manual
// resize the user did — saving the size before slot manipulation and
// restoring it afterwards keeps the user's layout intact.
function preserveSize(node, savedSize) {
    if (!node || !node.size || !Array.isArray(savedSize)) return;
    let minSize = [0, 0];
    if (typeof node.computeSize === "function") {
        try { minSize = node.computeSize(); } catch (_) {}
    }
    node.size[0] = Math.max(savedSize[0] | 0, (minSize[0] | 0) || 0);
    node.size[1] = Math.max(savedSize[1] | 0, (minSize[1] | 0) || 0);
}

function updateSlots(node, cfg) {
    // Snapshot the size BEFORE we add/remove inputs (each addInput call
    // can trigger an internal setSize(computeSize()) which would clobber
    // the user's manual width/height).
    const savedSize = node && node.size ? [node.size[0], node.size[1]] : null;

    const slots = findManagedSlots(node, cfg.prefix);

    // How many trailing empty slots are there?
    let trailingEmpty = 0;
    for (let i = slots.length - 1; i >= 0; i--) {
        if (slots[i].connected) break;
        trailingEmpty++;
    }

    // Target: exactly one trailing empty slot (unless we'd exceed the cap).
    const connectedCount = slots.length - trailingEmpty;

    // Remove extra trailing empty slots (keep one).
    if (trailingEmpty > 1) {
        // Remove from the highest index first so earlier indices stay stable.
        const toRemove = [];
        for (let i = slots.length - 1; i > connectedCount; i--) {
            toRemove.push(slots[i].idx);
        }
        // node.inputs indices shift on removal — remove descending.
        toRemove.sort((a, b) => b - a).forEach((idx) => node.removeInput(idx));
    }

    // Add a trailing empty slot if none and we haven't hit the cap.
    if (trailingEmpty === 0 && slots.length < cfg.max) {
        const used = new Set(slots.map((s) => s.num));
        let nextNum = 1;
        while (used.has(nextNum)) nextNum++;
        if (nextNum <= cfg.max) {
            node.addInput(slotName(cfg.prefix, nextNum), cfg.type);
        }
    }

    // Restore the saved size (only growing if widgets demand it).
    preserveSize(node, savedSize);

    if (node.graph && node.graph.setDirtyCanvas) {
        node.graph.setDirtyCanvas(true, true);
    }
}

app.registerExtension({
    name: "darask.prompt_cells.dynamic_inputs",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        const cfg = NODES[nodeData.name];
        if (!cfg) return;

        // After node creation, prune the initial slot list down to just the
        // first slot + one empty (Python declares 16; we hide the rest).
        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const r = onNodeCreated?.apply(this, arguments);
            // Defer one tick so ComfyUI finishes wiring widgets / inputs first.
            queueMicrotask(() => updateSlots(this, cfg));
            return r;
        };

        // After workflow load, the inputs array reflects saved state — prune
        // any extra empty trailing slots back to one.
        const onConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function (info) {
            const r = onConfigure?.apply(this, arguments);
            queueMicrotask(() => updateSlots(this, cfg));
            return r;
        };

        const onConnectionsChange = nodeType.prototype.onConnectionsChange;
        nodeType.prototype.onConnectionsChange = function (side, slot, connected, link_info, ioSlot) {
            const r = onConnectionsChange?.apply(this, arguments);
            // side === 1 is input side in LiteGraph.
            if (side === 1) {
                // Defer: at the time this fires, node.inputs[slot].link may
                // not yet reflect the new state.
                queueMicrotask(() => updateSlots(this, cfg));
            }
            return r;
        };
    },
});
