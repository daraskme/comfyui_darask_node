// DARASK Folder Image Loader — in-node progress display.
//
// The Python side returns {"ui": {"text": ["3/20"]}, "result": (...)} from
// each run. We catch the executed event, stash the latest progress string
// on the node, and paint it in the corner so the user can see exactly
// where the cursor is without wiring the `progress` output anywhere.

import { app } from "../../scripts/app.js";

const NODE_NAME = "DARASK Folder Image Loader";

app.registerExtension({
    name: "darask.folder_loader.progress",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE_NAME) return;

        const onExecuted = nodeType.prototype.onExecuted;
        nodeType.prototype.onExecuted = function (message) {
            const r = onExecuted?.apply(this, arguments);
            const text =
                message?.text?.[0] ??
                (Array.isArray(message?.text) ? message.text[0] : null);
            if (typeof text === "string" && text) {
                this.darask_progress = text;
                this.setDirtyCanvas(true, true);
            }
            return r;
        };

        const onDrawForeground = nodeType.prototype.onDrawForeground;
        nodeType.prototype.onDrawForeground = function (ctx) {
            onDrawForeground?.apply(this, arguments);
            if (!this.darask_progress || this.flags?.collapsed) return;

            ctx.save();
            // Right-aligned, just above the node title bar.
            ctx.font = "bold 13px sans-serif";
            ctx.textAlign = "right";
            ctx.textBaseline = "alphabetic";
            const text = this.darask_progress;
            const padX = 8;
            const y = -8;
            // Background pill so it stays readable over dark themes.
            const metrics = ctx.measureText(text);
            const w = metrics.width + 12;
            const h = 18;
            ctx.fillStyle = "rgba(30, 30, 40, 0.85)";
            ctx.beginPath();
            ctx.roundRect(this.size[0] - padX - w, y - h + 4, w, h, 6);
            ctx.fill();
            ctx.fillStyle = text.includes("(done)") ? "#7be67b" : "#f5d76e";
            ctx.fillText(text, this.size[0] - padX - 6, y - 2);
            ctx.restore();
        };

        // Clear stale progress when the node is reset/disconnected.
        const onConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function (info) {
            const r = onConfigure?.apply(this, arguments);
            this.darask_progress = "";
            return r;
        };
    },
});
