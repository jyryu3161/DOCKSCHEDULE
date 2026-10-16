export async function api<T = any>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const headers: Record<string, string> = {
    "X-DS-Request": "1",
    ...((options.headers as Record<string, string>) || {}),
  };
  if (options.body && !(options.body instanceof FormData))
    headers["Content-Type"] = "application/json";
  const response = await fetch("/api" + path, {
    ...options,
    headers,
    credentials: "same-origin",
  });
  if (!response.ok) {
    const data = await response
      .json()
      .catch(() => ({ detail: "서버 응답을 읽을 수 없습니다." }));
    throw new Error(
      typeof data.detail === "string"
        ? data.detail
        : JSON.stringify(data.detail),
    );
  }
  return response.json();
}
export const post = (path: string, body?: unknown) =>
  api(path, {
    method: "POST",
    body: body === undefined ? undefined : JSON.stringify(body),
  });
export interface User {
  id: number;
  username: string;
  name: string;
  student_number: string;
  role: string;
  status: string;
  cpu_override: number | null;
}
export interface Residue {
  key: string;
  chain: string;
  number: number;
  insertion: string;
  name: string;
  letter: string;
  category: string;
  heavy_atoms: number;
  center: number[];
  modeled?: boolean;
}
export interface Structure {
  models: number[];
  model: number;
  residues: Residue[];
  chains: string[];
  seqres: Record<string, string[]>;
  atom_count: number;
}
export interface Job {
  id: string;
  owner_id: number;
  owner_name: string;
  receptor_id: string;
  source_task_id?: string | null;
  kind: string;
  name: string;
  status: string;
  cpu_ids: number[];
  total: number;
  completed: number;
  failed: number;
  error: string | null;
  cancel_requested: boolean;
  created_at: string;
  parameters: any;
}
export const labels: Record<string, string> = {
  pending: "대기",
  queued: "대기 중",
  reserved: "자원 배정",
  running: "실행 중",
  preparing: "전처리 중",
  completed: "완료",
  succeeded: "성공",
  partial: "부분 성공",
  failed: "실패",
  cancelled: "취소",
  ready: "사용 가능",
  approved: "승인",
  rejected: "거절",
  suspended: "정지",
};
