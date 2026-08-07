import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import TreeLab from "./dev/TreeLab";
import "./styles/index.css";

/**
 * `?treelab` mounts the layout harness instead of the app. It renders fabricated
 * numbers, so it is behind an explicit opt-in rather than reachable from any
 * control — see `dev/TreeLab.tsx`.
 */
const showTreeLab =
  typeof window !== "undefined" && new URLSearchParams(window.location.search).has("treelab");

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>{showTreeLab ? <TreeLab /> : <App />}</React.StrictMode>,
);
