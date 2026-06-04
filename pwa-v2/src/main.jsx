import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App.jsx";
import "./styles/tokens.css";
import "./styles/app.css";

// `basename` matches Vite's `base` setting so React Router URLs stay
// in sync with the FastAPI mount point at /pwa-v2/.
ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <BrowserRouter basename="/pwa-v2">
      <App />
    </BrowserRouter>
  </React.StrictMode>
);
