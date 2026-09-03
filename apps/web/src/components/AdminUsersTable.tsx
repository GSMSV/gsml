import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { AdminUserItem, AdminUserUpdate, Role, api } from "../api/client";

const fmtCredits = (v: number) =>
  v.toLocaleString("ko-KR", { minimumFractionDigits: 2, maximumFractionDigits: 4 });

function formatDate(iso: string) {
  return new Date(iso).toLocaleString("ko-KR");
}

export default function AdminUsersTable({ meId }: { meId: string | undefined }) {
  const qc = useQueryClient();
  const [q, setQ] = useState("");
  const [editing, setEditing] = useState<AdminUserItem | null>(null);

  const { data: users, isLoading } = useQuery<AdminUserItem[]>({
    queryKey: ["admin-users", q],
    queryFn: async () =>
      (await api.get("/api/admin/users", { params: q ? { q } : {} })).data,
  });

  const update = useMutation({
    mutationFn: async ({ id, payload }: { id: string; payload: AdminUserUpdate }) =>
      (await api.patch<AdminUserItem>(`/api/admin/users/${id}`, payload)).data,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-users"] });
      qc.invalidateQueries({ queryKey: ["admin-stats"] });
      setEditing(null);
    },
  });

  return (
    <div className="card">
      <div className="spaced" style={{ marginBottom: 14 }}>
        <h2 style={{ margin: 0 }}>유저 관리</h2>
        <input
          type="search"
          placeholder="이름 또는 이메일 검색"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          style={{ width: 220 }}
        />
      </div>

      {isLoading ? (
        <div className="muted">불러오는 중...</div>
      ) : (
        <div className="table-wrap">
          <table className="admin-table">
            <thead>
              <tr>
                <th>이름</th>
                <th>이메일</th>
                <th>역할</th>
                <th>사용량 / 한도</th>
                <th>동시 요청</th>
                <th>API Key</th>
                <th>가입일</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {(users || []).map((u) => (
                <tr key={u.id}>
                  <td>{u.name}</td>
                  <td className="muted">{u.email}</td>
                  <td>
                    <span className={`badge ${u.role === "admin" ? "badge-admin" : "badge-general"}`}>
                      {u.role === "admin" ? "관리자" : "일반"}
                    </span>
                  </td>
                  <td className="mono">
                    {fmtCredits(u.current_usage)} / {fmtCredits(u.usage_limit)} ({u.percent_used}%)
                  </td>
                  <td className="mono">{u.max_concurrent}</td>
                  <td className="mono">
                    {u.api_key_prefix ? `${u.api_key_prefix}••••••••` : <span className="muted">없음</span>}
                  </td>
                  <td className="muted">{formatDate(u.created_at)}</td>
                  <td>
                    <button className="secondary" onClick={() => setEditing(u)}>
                      수정
                    </button>
                  </td>
                </tr>
              ))}
              {(users || []).length === 0 && (
                <tr>
                  <td colSpan={8} className="muted">유저가 없습니다.</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {editing && (
        <EditModal
          user={editing}
          isSelf={editing.id === meId}
          pending={update.isPending}
          onCancel={() => setEditing(null)}
          onSave={(payload) => update.mutate({ id: editing.id, payload })}
        />
      )}
    </div>
  );
}

function EditModal({
  user,
  isSelf,
  pending,
  onCancel,
  onSave,
}: {
  user: AdminUserItem;
  isSelf: boolean;
  pending: boolean;
  onCancel: () => void;
  onSave: (payload: AdminUserUpdate) => void;
}) {
  const [usageLimit, setUsageLimit] = useState(String(user.usage_limit));
  const [currentUsage, setCurrentUsage] = useState(String(user.current_usage));
  const [maxConcurrent, setMaxConcurrent] = useState(String(user.max_concurrent));
  const [role, setRole] = useState<Role>(user.role);

  const invalid =
    usageLimit === "" ||
    currentUsage === "" ||
    maxConcurrent === "" ||
    Number(usageLimit) < 0 ||
    Number(currentUsage) < 0 ||
    Number(maxConcurrent) < 1;

  return (
    <div className="modal-bg" onClick={onCancel}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h2>{user.name} 수정</h2>
        <p className="muted" style={{ marginTop: -8, marginBottom: 16 }}>{user.email}</p>

        <label className="field">
          최대 사용량 (크레딧)
          <input
            type="number"
            step="any"
            min={0}
            value={usageLimit}
            onChange={(e) => setUsageLimit(e.target.value)}
          />
        </label>

        <label className="field">
          현재 사용량 (크레딧)
          <input
            type="number"
            step="any"
            min={0}
            value={currentUsage}
            onChange={(e) => setCurrentUsage(e.target.value)}
          />
        </label>

        <label className="field">
          동시 요청 허용 수
          <input
            type="number"
            step={1}
            min={1}
            value={maxConcurrent}
            onChange={(e) => setMaxConcurrent(e.target.value)}
          />
        </label>

        <label className="field">
          역할
          <select
            value={role}
            disabled={isSelf}
            onChange={(e) => setRole(e.target.value as Role)}
            style={{ padding: "8px 12px", borderRadius: 6, border: "1px solid #d8dce0" }}
          >
            <option value="general">일반</option>
            <option value="admin">관리자</option>
          </select>
        </label>
        {isSelf && <p className="muted" style={{ marginTop: -8 }}>본인 역할은 변경할 수 없습니다.</p>}

        <div className="row" style={{ marginTop: 16, justifyContent: "flex-end" }}>
          <button className="secondary" onClick={onCancel}>
            취소
          </button>
          <button
            disabled={invalid || pending}
            onClick={() =>
              onSave({
                usage_limit: Number(usageLimit),
                current_usage: Number(currentUsage),
                max_concurrent: Number(maxConcurrent),
                ...(isSelf ? {} : { role }),
              })
            }
          >
            저장
          </button>
        </div>
      </div>
    </div>
  );
}
