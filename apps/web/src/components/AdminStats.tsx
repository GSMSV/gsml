import { useQuery } from "@tanstack/react-query";
import { AdminStats as AdminStatsType, api } from "../api/client";

const fmtCredits = (v: number) =>
  v.toLocaleString("ko-KR", { minimumFractionDigits: 2, maximumFractionDigits: 4 });

export default function AdminStats() {
  const { data, isLoading } = useQuery<AdminStatsType>({
    queryKey: ["admin-stats"],
    queryFn: async () => (await api.get("/api/admin/stats?days=7")).data,
  });

  if (isLoading) return <div className="card">불러오는 중...</div>;
  const s = data!;
  const max = Math.max(1e-9, ...s.daily_history.map((h) => h.credits));

  return (
    <>
      <div className="stat-grid">
        <div className="stat-card">
          <div className="stat-value">{s.total_users}</div>
          <div className="stat-label">전체 유저</div>
        </div>
        <div className="stat-card">
          <div className="stat-value">{s.admin_count}</div>
          <div className="stat-label">관리자</div>
        </div>
        <div className="stat-card">
          <div className="stat-value">{s.active_users_today}</div>
          <div className="stat-label">오늘 사용한 유저</div>
        </div>
        <div className="stat-card">
          <div className="stat-value">{fmtCredits(s.total_credits_today)}</div>
          <div className="stat-label">오늘 크레딧 사용</div>
        </div>
        <div className="stat-card">
          <div className="stat-value">{s.total_requests_today.toLocaleString("ko-KR")}</div>
          <div className="stat-label">오늘 요청 수</div>
        </div>
        <div className="stat-card">
          <div className="stat-value">{s.total_tokens_today.toLocaleString("ko-KR")}</div>
          <div className="stat-label">오늘 토큰 수</div>
        </div>
      </div>

      <div className="card">
        <h2>최근 7일 크레딧 사용량 (전체 유저)</h2>
        <div className="spark">
          {s.daily_history.map((h) => (
            <div
              key={h.date}
              title={`${h.date}: ${fmtCredits(h.credits)} credits · ${h.request_count}건`}
              style={{ height: `${(h.credits / max) * 100}%` }}
            />
          ))}
        </div>
      </div>

      <div className="card">
        <h2>사용량 상위 유저</h2>
        <div className="table-wrap">
          <table className="admin-table">
            <thead>
              <tr>
                <th>이름</th>
                <th>이메일</th>
                <th>사용량</th>
                <th>한도</th>
                <th>사용률</th>
              </tr>
            </thead>
            <tbody>
              {s.top_users.map((u) => (
                <tr key={u.id}>
                  <td>{u.name}</td>
                  <td className="muted">{u.email}</td>
                  <td className="mono">{fmtCredits(u.current_usage)}</td>
                  <td className="mono">{fmtCredits(u.usage_limit)}</td>
                  <td>{u.percent_used}%</td>
                </tr>
              ))}
              {s.top_users.length === 0 && (
                <tr>
                  <td colSpan={5} className="muted">데이터가 없습니다.</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}
