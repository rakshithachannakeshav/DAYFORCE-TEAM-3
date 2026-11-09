import { BrowserRouter, Routes, Route } from "react-router-dom";

import Navbar from "./components/layout/Navbar";
import Sidebar from "./components/layout/Sidebar";
import Traceability from "./pages/Traceability";
import Dashboard from "./pages/Dashboard";
import Results from "./pages/Results";
import NotFound from "./pages/NotFound";
import { GenerationProvider } from "./context/GenerationProvider";
import "./styles/variables.css";
import "./styles/global.css";

// Root layout: shared generation state, the navigation, and one route per page.
function App() {
  return (
    <BrowserRouter>
      <GenerationProvider>
        <div className="app-container">
          <Navbar />

          <div className="app-body">
            <Sidebar />

            <main className="main-content">
              <Routes>
                <Route path="/" element={<Dashboard />} />
                <Route path="/results" element={<Results />} />
                <Route path="/traceability" element={<Traceability />} />
                <Route path="*" element={<NotFound />} />
              </Routes>
            </main>
          </div>
        </div>
      </GenerationProvider>
    </BrowserRouter>
  );
}

export default App;