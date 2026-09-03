import { useQuery } from "@tanstack/react-query";
import { Navigate, Route, Routes } from "react-router-dom";
import { api, Me } from "./api/client";
import { authStore } from "./lib/auth";
import Login from "./pages/Login";
import Callback from "./pages/Callback";
import Dashboard from "./pages/Dashboard";
import Admin from "./pages/Admin";

function Protected({ children }: { children: JSX.Element }) {
  return authStore.isAuthed() ? children : <Navigate to="/" replace />;
}

function AdminOnly({ children }: { children: JSX.Element }) {
  const { data: me, isLoading } = useQuery<Me>({
    queryKey: ["me"],
    queryFn: async () => (await api.get("/api/me")).data,
  });
  if (isLoading) return <div className="container">불러오는 중...</div>;
  if (!me || me.role !== "admin") return <Navigate to="/dashboard" replace />;
  return children;
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={authStore.isAuthed() ? <Navigate to="/dashboard" replace /> : <Login />} />
      <Route path="/auth/callback" element={<Callback />} />
      <Route
        path="/dashboard"
        element={
          <Protected>
            <Dashboard />
          </Protected>
        }
      />
      <Route
        path="/admin"
        element={
          <Protected>
            <AdminOnly>
              <Admin />
            </AdminOnly>
          </Protected>
        }
      />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
