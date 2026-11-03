import { create } from "zustand";
import { errorLines } from "@/lib/api/client";

export interface ToastItem {
  id: number;
  tone: "info" | "error" | "success";
  message: string;
  hint?: string;
}

interface ToastState {
  items: ToastItem[];
  push: (t: Omit<ToastItem, "id">) => void;
  dismiss: (id: number) => void;
}

let seq = 0;

export const useToasts = create<ToastState>((set, get) => ({
  items: [],
  push: (t) => {
    const id = ++seq;
    set((s) => ({ items: [...s.items, { ...t, id }] }));
    setTimeout(() => get().dismiss(id), t.tone === "error" ? 7000 : 3500);
  },
  dismiss: (id) => set((s) => ({ items: s.items.filter((i) => i.id !== id) })),
}));

export const toast = {
  success: (message: string) => useToasts.getState().push({ tone: "success", message }),
  info: (message: string) => useToasts.getState().push({ tone: "info", message }),
  error: (err: unknown) => {
    const { message, hint } = errorLines(err);
    useToasts.getState().push({ tone: "error", message, hint });
  },
};
