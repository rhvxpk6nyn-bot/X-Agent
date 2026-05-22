import React from "react";

export default function ContextPanel({ onClose }) {
  return (
    <aside className="w-64 bg-layer1 border-l border-border p-4 overflow-y-auto hidden xl:block">
      <div className="flex items-center justify-between mb-4">
        <span className="text-xs font-medium text-text-secondary uppercase tracking-wider">Context</span>
        <button onClick={onClose} className="text-text-tertiary hover:text-text-primary text-xs">✕</button>
      </div>

      {/* Model status */}
      <div className="card mb-3">
        <div className="flex items-center gap-2 mb-2">
          <span className="w-2 h-2 rounded-full bg-success dot-active" />
          <span className="text-sm font-medium">DeepSeek V4 Pro</span>
        </div>
        <div className="text-xs text-text-tertiary">Ready</div>
      </div>

      {/* Active tools */}
      <div className="mb-4">
        <span className="text-xs text-text-tertiary uppercase tracking-wider">Tools</span>
        <div className="mt-2 space-y-1">
          {["shell", "read", "write", "edit", "web_fetch", "mano_cua"].map((t) => (
            <div key={t} className="flex items-center gap-2 text-xs text-text-secondary py-1">
              <span className="w-1.5 h-1.5 rounded-full bg-text-tertiary" />
              {t}
            </div>
          ))}
        </div>
      </div>

      {/* Memory stats */}
      <div className="mb-4">
        <span className="text-xs text-text-tertiary uppercase tracking-wider">Memory</span>
        <div className="mt-2 space-y-1 text-xs text-text-secondary">
          <div className="flex justify-between"><span>Hot</span><span>3</span></div>
          <div className="flex justify-between"><span>Warm</span><span>12</span></div>
          <div className="flex justify-between"><span>Cold</span><span>47</span></div>
        </div>
      </div>

      {/* Token usage bar */}
      <div>
        <span className="text-xs text-text-tertiary uppercase tracking-wider">Tokens</span>
        <div className="mt-2">
          <div className="h-1.5 bg-layer3 rounded-full overflow-hidden">
            <div className="h-full bg-accent rounded-full" style={{ width: "38%" }} />
          </div>
          <div className="flex justify-between mt-1 text-xs text-text-tertiary">
            <span>3.8K / 10K</span>
          </div>
        </div>
      </div>
    </aside>
  );
}
