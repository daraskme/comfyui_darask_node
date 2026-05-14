// DARASK LTX23 Video Settings — live size readout.
//
// Watches the width / height / length / fps widgets and draws the final
// clip dimensions, aspect ratio, frame count and duration as a coloured
// pill at the top of the node — updates instantly as widgets change so
// you can sanity-check the output before queueing anything.

import { app } from "../../scripts/app.js";

// Nodes that should get the live width × height × length / fps preview.
const TARGET_NODES = new Set([
    "DARASK LTX23 Video Settings",
    "DARASK LTX 2.3 Generator",
]);
const NODE_NAME = "DARASK LTX23 Video Settings"; // kept for back-compat references below

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

function pullValues(node) {
    const out = { width: 0, height: 0, length: 0, fps: 0 };
    for (const w of node.widgets || []) {
        if (w && w.name in out) out[w.name] = w.value;
    }
    return out;
}

function recomputeAndDraw(node) {
    const { width, height, length, fps } = pullValues(node);
    node._daraskLtx23Info = formatInfo(width, height, length, fps);
    node.setDirtyCanvas(true, true);
}

function hookWidgets(node) {
    for (const w of node.widgets || []) {
        if (w._daraskLtxHooked) continue;
        const orig = w.callback;
        w.callback = function (...args) {
            const r = orig ? orig.apply(this, args) : undefined;
            recomputeAndDraw(node);
            return r;
        };
        w._daraskLtxHooked = true;
    }
}

app.registerExtension({
    name: "darask.ltx23.video_settings",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (!TARGET_NODES.has(nodeData.name)) return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const r = onNodeCreated?.apply(this, arguments);
            hookWidgets(this);
            recomputeAndDraw(this);
            return r;
        };

        const onConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function (info) {
            const r = onConfigure?.apply(this, arguments);
            hookWidgets(this);
            recomputeAndDraw(this);
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
