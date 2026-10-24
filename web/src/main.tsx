import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "@fontsource/abhaya-libre/400.css";
import "@fontsource/abhaya-libre/700.css";
import "@fontsource/abhaya-libre/800.css";
import "@fontsource/gemunu-libre/400.css";
import "@fontsource/gemunu-libre/600.css";
import "./styles.css";
import App from "./App";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);

// Offline app shell only works on https or localhost; on plain LAN http the browser just skips it.
if ("serviceWorker" in navigator && window.isSecureContext) {
  navigator.serviceWorker.register("/sw.js").catch(() => {});
}
