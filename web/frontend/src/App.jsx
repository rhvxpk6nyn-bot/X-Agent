import React, { useState, useEffect, useRef } from "react";
import Sidebar from "./components/Sidebar";
import Chat from "./views/Chat";
import MemoryPanel from "./views/MemoryPanel";
import SkillsPanel from "./views/SkillsPanel";
import ConfigPanel from "./views/ConfigPanel";
import ContextPanel from "./components/ContextPanel";
import StatusBar from "./components/StatusBar";

const VIEWS = {
  chat: Chat,
  memory: MemoryPanel,
  skills: SkillsPanel,
  config: ConfigPanel,
};

export default function App() {
  const [view, setView] = useState("chat");
  const [contextOpen, setContextOpen] = useState(true);

  const ViewComponent = VIEWS[view];

  return (
    <div className="h-full flex flex-col">
      <div className="flex-1 flex overflow-hidden">
        <Sidebar active={view} onNavigate={setView} />
        <div className="flex-1 flex min-w-0">
          <ViewComponent />
        </div>
        {contextOpen && <ContextPanel onClose={() => setContextOpen(false)} />}
      </div>
      <StatusBar />
    </div>
  );
}
