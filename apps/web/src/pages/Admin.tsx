import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, Me } from "../api/client";
import AdminStats from "../components/AdminStats";
import AdminUsersTable from "../components/AdminUsersTable";

export default function Admin() {
  const { data: me } = useQuery<Me>({
    queryKey: ["me"],
    queryFn: async () => (await api.get("/api/me")).data,
  });

  return (
    <div className="container">
      <div className="spaced" style={{ marginBottom: 24 }}>
        <div>
          <h1 style={{ margin: 0 }}>관리자 페이지</h1>
          <p className="muted" style={{ margin: "4px 0 0" }}>{me?.name} · {me?.email}</p>
        </div>
        <div className="row">
          <Link to="/dashboard">
            <button className="secondary">대시보드로</button>
          </Link>
        </div>
      </div>

      <AdminStats />
      <AdminUsersTable meId={me?.id} />
    </div>
  );
}
