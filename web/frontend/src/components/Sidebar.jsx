import React from "react";

const ICONS = { chat: "💬", memory: "🧠", skills: "⚡", config: "⚙️" };
const LABELS = { chat: "Chat", memory: "Memory", skills: "Skills", config: "Settings" };

export default function Sidebar({ active, onNavigate }) {
  return (
    <nav className="w-12 flex flex-col items-center py-3 gap-1 bg-layer1 border-r border-border">
      <div className="w-8 h-8 rounded-lg bg-accent flex items-center justify-center mb-4 text-white text-sm font-bold">
        ✖
      </div>
      {Object.entries(ICONS).map(([key, icon]) => (
        <button
          key={key}
          onClick={() => onNavigate(key)}
          className={`w-9 h-9 rounded-xl flex items-center justify-center text-sm transition-all duration-150 ${
            active === key
              ? "bg-accent/15 text-white scale-105"
              : "text-text-secondary hover:bg-layer2 hover:text-text-primary"
          }`}
          title={LABELS[key]}
        >
          {icon}
        </button>
      ))}
    </nav>
  );
}
