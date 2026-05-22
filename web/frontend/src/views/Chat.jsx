import React, { useState, useRef, useEffect } from "react";
import { useChatStore } from "../lib/store";

export default function Chat() {
  const { messages, isLoading, addMessage, setLoading, incrementTools, model, setModel } = useChatStore();
  const [input, setInput] = useState("");
  const endRef = useRef(null);

  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth" }); }, [messages]);

  const send = async () => {
    const text = input.trim();
    if (!text) return;

    addMessage({ role: "user", content: text, time: new Date().toLocaleTimeString() });
    setInput("");
    setLoading(true);

    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text, model }),
      });
      const data = await res.json();
      addMessage({ role: "assistant", content: data.response, time: new Date().toLocaleTimeString() });
      if (data.stats?.tools_used) incrementTools();
    } catch (e) {
      addMessage({ role: "assistant", content: "Error: could not reach agent.", time: new Date().toLocaleTimeString() });
    }
    setLoading(false);
  };

  const handleKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  };

  return (
    <div className="flex-1 flex flex-col min-w-0">
      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
        {messages.length === 0 && (
          <div className="flex items-center justify-center h-full">
            <div className="text-center">
              <div className="text-3xl mb-3">◆</div>
              <h2 className="text-lg font-medium text-text-primary mb-1">Agent</h2>
              <p className="text-sm text-text-tertiary">Ask anything. Use @model to switch, / to command.</p>
            </div>
          </div>
        )}
        {messages.map((msg, i) => (
          <div key={i} className={`msg-enter ${msg.role === "user" ? "flex justify-end" : ""}`}>
            <div className={`max-w-[80%] ${
              msg.role === "user"
                ? "bg-accent/15 border border-accent/20 rounded-2xl px-4 py-2.5"
                : ""
            }`}>
              {msg.role === "assistant" && (
                <div className="flex items-center gap-2 mb-1">
                  <span className="text-xs font-medium text-accent">◆ Agent</span>
                  <span className="text-xs text-text-tertiary">{msg.time}</span>
                </div>
              )}
              <p className="text-sm leading-relaxed whitespace-pre-wrap">{msg.content}</p>
              {msg.role === "user" && (
                <span className="text-xs text-text-tertiary mt-1 block text-right">{msg.time}</span>
              )}
            </div>
          </div>
        ))}
        {isLoading && (
          <div className="msg-enter">
            <div className="flex items-center gap-2 text-text-tertiary text-sm">
              <span className="w-1.5 h-1.5 rounded-full bg-accent dot-active" />
              Thinking...
            </div>
          </div>
        )}
        <div ref={endRef} />
      </div>

      {/* Input */}
      <div className="px-6 pb-4">
        <div className="card p-2 flex items-end gap-2">
          {/* Model selector */}
          <select
            value={model}
            onChange={(e) => setModel(e.target.value)}
            className="btn-ghost text-xs py-1.5"
          >
            <option value="deepseek">DeepSeek V4 Pro</option>
            <option value="qwen-vl">Qwen-VL-Max</option>
            <option value="ollama">Ollama (local)</option>
          </select>

          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Type your message... (@model /command)"
            rows={1}
            className="flex-1 bg-transparent text-sm text-text-primary placeholder-text-tertiary outline-none resize-none py-1.5"
          />

          <button
            onClick={send}
            disabled={isLoading || !input.trim()}
            className="btn-primary text-xs"
          >
            ↑
          </button>
        </div>
        <p className="text-xs text-text-tertiary mt-2 text-center">
          {model} · {messages.length} messages
        </p>
      </div>
    </div>
  );
}
