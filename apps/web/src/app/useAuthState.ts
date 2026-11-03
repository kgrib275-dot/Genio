import { useSyncExternalStore } from "react";
import { isLoggedIn } from "@/lib/api/client";

function subscribe(cb: () => void): () => void {
  window.addEventListener("genio:auth", cb);
  window.addEventListener("storage", cb);
  return () => {
    window.removeEventListener("genio:auth", cb);
    window.removeEventListener("storage", cb);
  };
}

export function useLoggedIn(): boolean {
  return useSyncExternalStore(subscribe, isLoggedIn, () => false);
}
