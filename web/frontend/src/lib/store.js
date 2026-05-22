import { create } from "zustand";

export const useChatStore = create((set) => ({
  messages: [],
  model: "deepseek",
  toolsUsed: 0,
  isLoading: false,

  addMessage: (msg) =>
    set((state) => ({ messages: [...state.messages, msg] })),

  setLoading: (v) => set({ isLoading: v }),

  incrementTools: () =>
    set((state) => ({ toolsUsed: state.toolsUsed + 1 })),

  setModel: (m) => set({ model: m }),

  clear: () => set({ messages: [], toolsUsed: 0 }),
}));
