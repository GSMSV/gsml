import { useQuery } from "@tanstack/react-query";
import { api, UsageHistoryItem, UsageToday } from "../api/client";

// 크레딧 단가가 100만 토큰 기준이라 하루 사용량이 소수점 아래로 내려간다.
const fmtCredits = (v: number) =>
  v.toLocaleString("ko-KR", { minimumFractionDigits: 2, maximumFractionDigits: 4 });

export default function UsageCard() {
  const today = useQuery<UsageToday>({
    queryKey: ["usage-today"],
    queryFn: async () => (await api.get("/api/usage/today")).data,
  });
  const history = useQuery<UsageHistoryItem[]>({
    queryKey: ["usage-history"],
    queryFn: async () => (await api.get("/api/usage/history?days=7")).data,
  });

  if (today.isLoading) return <div className="card">불러오는 중...</div>;
  const t = today.data!;
  const pct = Math.min(100, t.percent_used);
  const max = Math.max(1e-9, ...(history.data?.map((h) => h.credits) || [1e-9]));

  return (
    <div className="card">
      <h2>사용량</h2>
      <div className="spaced" style={{ marginBottom: 6 }}>
        <span>오늘 {t.percent_used}% 사용</span>
        <span className="mono">
          {fmtCredits(t.used)} / {fmtCredits(t.limit)} credits
        </span>
      </div>
      <div className="bar">
        <div style={{ width: `${pct}%` }} />
      </div>
      <p className="muted" style={{ marginTop: 8 }}>
        다음 리셋: {new Date(t.reset_at).toLocaleString("ko-KR")}
      </p>

      <h2 style={{ marginTop: 20, fontSize: 14 }}>최근 7일</h2>
      <div className="spark">
        {(history.data || []).map((h) => (
          <div
            key={h.date}
            title={`${h.date}: ${fmtCredits(h.credits)} credits · ${h.request_count}건`}
            style={{ height: `${(h.credits / max) * 100}%` }}
          />
        ))}
      </div>
    </div>
  );
}
