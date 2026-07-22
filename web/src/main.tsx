/**
 * Purpose: Web app bootstrap (basename /demo for marketing walkthrough).
 * Author: Doug Hesseltine
 * Created: 2026-07-12
 * Modified: 2026-07-22
 * Version: 1.2.0
 */

import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import { AuthProvider } from "./auth";
import { demoBasename } from "./demo/mode";
import "./styles.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter basename={demoBasename()}>
      <AuthProvider>
        <App />
      </AuthProvider>
    </BrowserRouter>
  </React.StrictMode>
);
