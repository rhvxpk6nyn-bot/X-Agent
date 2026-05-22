import React from "react";
import { useChatStore } from "../lib/store";

export default function StatusBar() {
  const model = useChatStore((s) => s.model);
  const toolsUsed = useChatStore((s) => s.toolsUsed);

  return (
    <footer className="h-7 bg-layer1 border-t border-border flex items-center px-4 text-xs text-text-tertiary gap-4">
      <span className="flex items-center gap-1.5">
        <span className="w-1.5 h-1.5 rounded-full bg-success dot-active" />
        {model}
      </span>
      <span>{toolsUsed} tools this session</span>
      <span className="flex-1" />
      <span>⌘⇧Space</span>
    </footer>
  );
}
