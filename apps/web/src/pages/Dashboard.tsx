import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { api, Me } from "../api/client";
import { authStore } from "../lib/auth";
import KeyCard from "../components/KeyCard";
import UsageCard from "../components/UsageCard";

export default function Dashboard() {
  const navigate = useNavigate();
  const { data: me } = useQuery<Me>({
    queryKey: ["me"],
    queryFn: async () => (await api.get("/api/me")).data,
  });

  return (
    <div className="container">
      <div className="spaced" style={{ marginBottom: 24 }}>
        <div>
          <h1 style={{ margin: 0 }}>GSML</h1>
          {me && <p className="muted" style={{ margin: "4px 0 0" }}>{me.name} · {me.email}</p>}
        </div>
        <div className="row">
          {me?.role === "admin" && (
            <Link to="/admin">
              <button className="secondary">관리자 페이지</button>
            </Link>
          )}
          <button className="secondary" onClick={() => { authStore.clear(); navigate("/", { replace: true }); }}>로그아웃</button>
        </div>
      </div>

      <KeyCard />
      <UsageCard />

      <div className="card">
        <h2>사용 방법</h2>
        <p className="muted">OpenAI 호환 SDK에서 baseURL을 지정해 사용하세요.</p>
        <pre className="mono" style={{ padding: 12, whiteSpace: "pre-wrap" }}>
{`from openai import OpenAI
client = OpenAI(
  base_url="${import.meta.env.VITE_API_BASE_URL || "http://localhost:8000"}/v1",
  api_key="<발급받은 키>",
)
client.chat.completions.create(model="<모델 ID>", messages=[...])`}
        </pre>
      </div>
    </div>
  );
}
