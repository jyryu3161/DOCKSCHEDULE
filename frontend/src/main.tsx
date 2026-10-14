import React, { useCallback, useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Activity,
  ArrowDownToLine,
  ArrowLeft,
  ArrowRight,
  Check,
  CheckCircle2,
  ChevronRight,
  Clock3,
  Cpu,
  Database,
  FlaskConical,
  Layers3,
  LayoutDashboard,
  LogOut,
  Plus,
  RefreshCw,
  Search,
  Settings2,
  ShieldCheck,
  Trash2,
  UploadCloud,
  Users,
  X,
} from "lucide-react";
import { api, post, Job, labels, Residue, Structure, User } from "./api";
import Viewer from "./Viewer";
import "./style.css";

function useLoad<T = any>(path: string, interval = 0) {
  const [data, setData] = useState<T | null>(null),
    [error, setError] = useState("");
  const requestId = useRef(0);
  const reload = useCallback(async () => {
    const id = ++requestId.current;
    try {
      const result = await api<T>(path);
      if (id !== requestId.current) return;
      setData(result);
      setError("");
    } catch (e) {
      if (id === requestId.current) setError((e as Error).message);
    }
  }, [path]);
  useEffect(() => {
    reload();
    const timer = interval ? setInterval(reload, interval) : undefined;
    return () => {
      ++requestId.current;
      clearInterval(timer);
    };
  }, [reload, interval]);
  return { data, error, reload };
}
const Badge = ({ status }: { status: string }) => (
  <span className={"badge " + status}>
    <i />
    {labels[status] || status}
  </span>
);
const ErrorBox = ({ text }: { text: string }) =>
  text ? (
    <div className="notice error" role="alert">
      {text}
    </div>
  ) : null;
function Field({
  label,
  children,
  hint,
}: {
  label: string;
  children: React.ReactNode;
  hint?: string;
}) {
  return (
    <label className="field">
      <span>{label}</span>
      {children}
      {hint && <small>{hint}</small>}
    </label>
  );
}
const date = (s: string) =>
  new Date(s + "Z").toLocaleString("ko-KR", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
const go = (path: string) => {
  window.location.hash = path;
};

function Login({ onLogin }: { onLogin: (u: User) => void }) {
  const [register, setRegister] = useState(false),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [message, setMessage] = useState("");
  async function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    setError("");
    const data = Object.fromEntries(new FormData(e.currentTarget));
    try {
      if (register) {
        await post("/auth/register", data);
        setRegister(false);
        setMessage(
          "가입 신청이 완료되었습니다. 로그인 후 승인 상태를 확인하세요.",
        );
      } else onLogin(await post("/auth/login", data));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="login-page">
      <div className="login-story">
        <div className="brand">
          <FlaskConical /> DOCK<span>SCHEDULE</span>
        </div>
        <div>
          <span className="eyebrow">COMPUTATIONAL DRUG DISCOVERY</span>
          <h1>
            분자에서 시작하는
            <br />
            새로운 가능성.
          </h1>
          <p>
            구조를 준비하고, 결합 부위를 탐색하고,
            <br />
            화합물 라이브러리의 가능성을 확인하세요.
          </p>
          <div className="molecule-art">
            <i />
            <i />
            <i />
            <i />
            <i />
            <i />
            <span>Virtual Screening Lab</span>
          </div>
        </div>
        <small>QUICKVINA · CLASSROOM WORKSPACE</small>
      </div>
      <div className="login-form">
        <div className="login-card">
          <span className="eyebrow">WELCOME TO THE LAB</span>
          <h2>{register ? "연구를 시작할 준비" : "실습 공간에 로그인"}</h2>
          <p className="muted">
            {register
              ? "간단한 가입 후 관리자의 승인을 기다려 주세요."
              : "승인된 계정으로 virtual screening을 시작하세요."}
          </p>
          {message && <div className="notice">{message}</div>}
          <ErrorBox text={error} />
          <form onSubmit={submit}>
            <Field label="아이디">
              <input
                name="username"
                required
                autoComplete="username"
                minLength={3}
                maxLength={80}
              />
            </Field>
            {register && (
              <>
                <Field label="이름">
                  <input name="name" required maxLength={100} />
                </Field>
                <Field label="학번">
                  <input name="student_number" required maxLength={80} />
                </Field>
              </>
            )}
            <Field label="비밀번호">
              <input
                name="password"
                type="password"
                required
                minLength={8}
                maxLength={128}
                autoComplete={register ? "new-password" : "current-password"}
              />
            </Field>
            <button className="primary full" disabled={busy}>
              {busy ? "처리 중…" : register ? "가입 신청" : "로그인"}
              <ArrowRight size={17} />
            </button>
          </form>
          <p className="login-switch">
            {register ? "이미 계정이 있나요?" : "처음 방문하셨나요?"}{" "}
            <button
              onClick={() => {
                setRegister(!register);
                setError("");
              }}
            >
              {register ? "로그인" : "회원가입"}
            </button>
          </p>
        </div>
      </div>
    </div>
  );
}

function App() {
  const [user, setUser] = useState<User | null>(null),
    [loading, setLoading] = useState(true),
    [route, setRoute] = useState(location.hash.slice(1) || "dashboard");
  const [passwordOpen, setPasswordOpen] = useState(false),
    [passwordError, setPasswordError] = useState("");
  useEffect(() => {
    api<User>("/auth/me")
      .then(setUser)
      .catch(() => {})
      .finally(() => setLoading(false));
    const listener = () => setRoute(location.hash.slice(1) || "dashboard");
    window.addEventListener("hashchange", listener);
    return () => window.removeEventListener("hashchange", listener);
  }, []);
  if (loading)
    return (
      <div className="boot">
        <FlaskConical />
        <p>실습 공간을 불러오는 중…</p>
      </div>
    );
  if (!user) return <Login onLogin={setUser} />;
  const logout = async () => {
    await post("/auth/logout");
    setUser(null);
  };
  if (user.status === "pending")
    return (
      <div className="boot">
        <ShieldCheck size={48} />
        <h2>관리자 승인을 기다리고 있습니다</h2>
        <p>{user.name}님의 가입 신청이 접수되었습니다.</p>
        <button
          className="primary"
          onClick={() => api<User>("/auth/me").then(setUser)}
        >
          승인 상태 확인
        </button>
        <button onClick={logout}>로그아웃</button>
      </div>
    );
  const isAdmin = route === "admin";
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a className="brand" href="#dashboard">
          <FlaskConical size={25} />{" "}
          <div>
            DOCK<span>SCHEDULE</span>
            <small>VIRTUAL SCREENING LAB</small>
          </div>
        </a>
        <span className="nav-label">WORKSPACE</span>
        <nav>
          <a
            className={route === "dashboard" ? "active" : ""}
            href="#dashboard"
          >
            <LayoutDashboard size={19} />
            대시보드
          </a>
          <a className={route === "new" ? "active" : ""} href="#new">
            <Plus size={19} />새 Screening
          </a>
          {user.role === "admin" && (
            <>
              <span className="nav-label">ADMINISTRATION</span>
              <a className={isAdmin ? "active" : ""} href="#admin">
                <Settings2 size={19} />
                관리자 설정
              </a>
            </>
          )}
        </nav>
        <div className="sidebar-note">
          <div>
            <Activity size={16} /> CPU DOCKING
          </div>
          <p>
            한 번의 탐색,
            <br />
            수많은 분자의 가능성.
          </p>
          <small>Powered by QuickVina 2.1</small>
        </div>
        <div className="profile">
          <div className="avatar">{user.name.slice(0, 1)}</div>
          <button onClick={() => setPasswordOpen(true)}>
            <strong>{user.name}</strong>
            <small>
              {user.role === "admin" ? "Administrator" : user.student_number}
            </small>
          </button>
          <button aria-label="로그아웃" onClick={logout}>
            <LogOut size={17} />
          </button>
        </div>
      </aside>
      <main>
        <header className="topbar">
          <div>
            Workspace <ChevronRight size={13} />{" "}
            <b>
              {isAdmin
                ? "관리자 설정"
                : route === "new"
                  ? "새 Screening"
                  : route.startsWith("job/")
                    ? "실행 결과"
                    : "대시보드"}
            </b>
          </div>
          <span className="campus">
            <span /> Campus workspace
          </span>
          <div className="mobile-account">
            <button
              aria-label="비밀번호 변경"
              onClick={() => setPasswordOpen(true)}
            >
              <Users size={16} />
            </button>
            <button aria-label="로그아웃" onClick={logout}>
              <LogOut size={16} />
            </button>
          </div>
        </header>
        <div className="page">
          {route === "new" ? (
            <NewJob />
          ) : isAdmin && user.role === "admin" ? (
            <Admin />
          ) : route.startsWith("job/") ? (
            <JobDetail id={route.slice(4)} />
          ) : (
            <Dashboard user={user} />
          )}
        </div>
      </main>
      {passwordOpen && (
        <div className="modal-backdrop">
          <form
            className="modal"
            onSubmit={async (e) => {
              e.preventDefault();
              try {
                await post(
                  "/auth/password",
                  Object.fromEntries(new FormData(e.currentTarget)),
                );
                setPasswordOpen(false);
                setUser(null);
              } catch (e) {
                setPasswordError((e as Error).message);
              }
            }}
          >
            <button
              className="close"
              type="button"
              onClick={() => setPasswordOpen(false)}
            >
              <X />
            </button>
            <h2>비밀번호 변경</h2>
            <ErrorBox text={passwordError} />
            <Field label="현재 비밀번호">
              <input type="password" name="old_password" required />
            </Field>
            <Field label="새 비밀번호">
              <input
                type="password"
                name="new_password"
                minLength={8}
                maxLength={128}
                required
              />
            </Field>
            <button className="primary">변경 후 다시 로그인</button>
          </form>
        </div>
      )}
    </div>
  );
}

const JOB_PAGE_SIZES = [10, 20, 50, 100, 200];

function Dashboard({ user }: { user: User }) {
  const [filter, setFilter] = useState("all"),
    [search, setSearch] = useState(""),
    [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(() => {
    try {
      const saved = Number(localStorage.getItem("ds.jobs.pageSize"));
      return JOB_PAGE_SIZES.includes(saved) ? saved : 50;
    } catch {
      return 50;
    }
  });
  const jobs = useLoad<{ rows: Job[]; total: number }>(
      `/jobs?include_total=true&limit=${pageSize}&offset=${(page - 1) * pageSize}&state=${filter}&search=${encodeURIComponent(search)}`,
      4000,
    ),
    resources = useLoad("/settings", 4000),
    summary = useLoad("/jobs/summary", 4000);
  useEffect(() => {
    try {
      localStorage.setItem("ds.jobs.pageSize", String(pageSize));
    } catch {}
  }, [pageSize]);
  const rows = jobs.data?.rows || [];
  const total = jobs.data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  useEffect(() => {
    if (jobs.data && page > totalPages) setPage(totalPages);
  }, [jobs.data, page, totalPages]);
  return (
    <>
      <div className="page-heading">
        <div>
          <span className="eyebrow">YOUR DISCOVERY WORKSPACE</span>
          <h1>Screening 대시보드</h1>
          <p>실험의 진행 상황부터 새로운 발견까지, 한눈에 확인하세요.</p>
        </div>
        <button className="primary" onClick={() => go("new")}>
          <Plus size={18} />새 Screening
        </button>
      </div>
      <ErrorBox text={jobs.error || resources.error} />
      {resources.data?.scheduler_error && (
        <ErrorBox text={resources.data.scheduler_error} />
      )}
      <div className="stat-grid">
        <Stat
          icon={<Layers3 />}
          label={user.role === "admin" ? "전체 작업" : "내 작업"}
          value={summary.data?.total ?? 0}
          caption="전처리 및 docking"
        />
        <Stat
          icon={<Activity />}
          label="실행 중"
          value={summary.data?.running ?? 0}
          caption="결과를 계산하고 있어요"
        />
        <Stat
          icon={<CheckCircle2 />}
          label="완료된 작업"
          value={summary.data?.done ?? 0}
          caption="결과 확인 가능"
        />
        <Stat
          icon={<Cpu />}
          label="플랫폼 CPU 사용"
          value={`${resources.data?.allocated_cpus ?? 0} / ${resources.data?.values.cpu_budget ?? "—"}`}
          caption={`${resources.data?.active_students ?? 0}명 실행 · ${resources.data?.queued ?? 0}개 대기`}
        />
      </div>
      <div className="section-heading">
        <div>
          <h2>Screening 작업</h2>
          <p>작업을 선택하면 진행 상황과 분자별 결과를 볼 수 있습니다.</p>
        </div>
        <button
          className="icon-button"
          title="새로고침"
          onClick={() => jobs.reload()}
        >
          <RefreshCw size={17} />
        </button>
      </div>
      <section className="panel">
        <div className="table-toolbar">
          <div className="tabs">
            {[
              ["all", "전체"],
              ["running", "진행 중"],
              ["done", "종료"],
            ].map(([k, v]) => (
              <button
                key={k}
                className={filter === k ? "selected" : ""}
                onClick={() => {
                  setFilter(k);
                  setPage(1);
                }}
              >
                {v}
              </button>
            ))}
          </div>
          <div className="list-controls">
            <label className="page-size">
              <span>페이지당 표시</span>
              <select
                aria-label="페이지당 표시"
                value={pageSize}
                onChange={(e) => {
                  setPageSize(Number(e.target.value));
                  setPage(1);
                }}
              >
                {JOB_PAGE_SIZES.map((count) => (
                  <option key={count} value={count}>
                    {count}개
                  </option>
                ))}
              </select>
            </label>
            <label className="search">
              <Search size={16} />
              <input
                placeholder="작업 이름 검색"
                value={search}
                onChange={(e) => {
                  setSearch(e.target.value);
                  setPage(1);
                }}
              />
            </label>
          </div>
        </div>
        {rows.length ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>작업 이름</th>
                  {user.role === "admin" && <th>학생</th>}
                  <th>상태</th>
                  <th>진행률</th>
                  <th>CPU</th>
                  <th>제출 시각</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {rows.map((j) => (
                  <tr
                    key={j.id}
                    onClick={() => go("job/" + j.id)}
                    className="clickable"
                  >
                    <td>
                      <div className="job-name">
                        <div className="table-icon">
                          {j.kind === "prepare" ? (
                            <FlaskConical size={18} />
                          ) : (
                            <Layers3 size={18} />
                          )}
                        </div>
                        <div>
                          <strong>{j.name}</strong>
                          <small>
                            {j.kind === "prepare"
                              ? "Receptor preparation"
                              : `${j.total.toLocaleString()} compounds · QuickVina`}
                          </small>
                        </div>
                      </div>
                    </td>
                    {user.role === "admin" && <td>{j.owner_name}</td>}
                    <td>
                      <Badge status={j.status} />
                    </td>
                    <td>
                      <Progress job={j} />
                    </td>
                    <td className="mono">{j.cpu_ids.length || "—"}</td>
                    <td className="muted">{date(j.created_at)}</td>
                    <td>
                      <ChevronRight size={17} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty
            title="아직 Screening 작업이 없습니다"
            text="PDB 구조와 화합물 library를 준비하고 첫 작업을 시작하세요."
            action={
              <button className="secondary" onClick={() => go("new")}>
                첫 Screening 만들기 <ArrowRight size={15} />
              </button>
            }
          />
        )}
        <div className="pagination jobs-pagination">
          <button
            className="secondary small"
            disabled={page === 1}
            onClick={() => setPage((p) => p - 1)}
          >
            이전
          </button>
          <span>
            전체 {total.toLocaleString()}개 ·{" "}
            {rows.length ? ((page - 1) * pageSize + 1).toLocaleString() : 0}–
            {rows.length
              ? ((page - 1) * pageSize + rows.length).toLocaleString()
              : 0}
            개 · {page} / {totalPages} 페이지
          </span>
          <button
            className="secondary small"
            disabled={page >= totalPages}
            onClick={() => setPage((p) => p + 1)}
          >
            다음
          </button>
        </div>
      </section>
      <div className="info-strip">
        <ShieldCheck size={21} />
        <p>
          <strong>작업은 서버에서 계속 실행됩니다.</strong> 브라우저를 닫아도
          계산이 유지되며 완료된 화합물은 바로 확인할 수 있습니다.
        </p>
      </div>
    </>
  );
}
function Stat({
  icon,
  label,
  value,
  caption,
}: {
  icon: React.ReactNode;
  label: string;
  value: React.ReactNode;
  caption: string;
}) {
  return (
    <div className="stat-card">
      <div className="stat-label">
        {label}
        <span>{icon}</span>
      </div>
      <strong>{value}</strong>
      <small>{caption}</small>
    </div>
  );
}
function Empty({
  title,
  text,
  action,
}: {
  title: string;
  text: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="empty">
      <div>
        <FlaskConical size={28} />
      </div>
      <h3>{title}</h3>
      <p>{text}</p>
      {action}
    </div>
  );
}
function Progress({ job }: { job: Job }) {
  const n = job.completed + job.failed,
    p = job.total
      ? (n / job.total) * 100
      : job.status === "completed"
        ? 100
        : 0;
  return (
    <div className="progress-cell">
      <div className="progress">
        <span style={{ width: p + "%" }} />
      </div>
      <small>
        {job.total
          ? `${n.toLocaleString()} / ${job.total.toLocaleString()}`
          : "전처리"}{" "}
        <b>{Math.round(p)}%</b>
      </small>
    </div>
  );
}

function NewJob() {
  const saved = useLoad<any[]>("/receptors", 5000),
    settings = useLoad("/settings");
  const [error, setError] = useState(""),
    [busy, setBusy] = useState(""),
    [uploaded, setUploaded] = useState<any>(null),
    [chains, setChains] = useState<string[]>([]),
    [keep, setKeep] = useState<string[]>([]),
    [ph, setPh] = useState(7.4),
    [model, setModel] = useState(1);
  const [receptorId, setReceptorId] = useState(""),
    [receptor, setReceptor] = useState<any>(null),
    [selected, setSelected] = useState<string[]>([]),
    [center, setCenter] = useState([0, 0, 0]),
    [size, setSize] = useState([20, 20, 20]),
    [gridSet, setGridSet] = useState(false);
  const [lib, setLib] = useState<any>(null),
    [mapping, setMapping] = useState({
      delimiter: ",",
      encoding: "utf-8-sig",
      header: true,
      cid_column: "",
      smiles_column: "",
    }),
    [preview, setPreview] = useState<any>(null);
  const [name, setName] = useState(""),
    [conformers, setConformers] = useState(1),
    [exhaustiveness, setExhaustiveness] = useState(8),
    [seed, setSeed] = useState(42),
    [stripSalts, setStripSalts] = useState(true);
  const residues: Residue[] = receptor?.structure?.residues || [];
  useEffect(() => {
    if (!receptorId) {
      setReceptor(null);
      return;
    }
    let disposed = false;
    let timer: ReturnType<typeof setTimeout>;
    const load = async () => {
      try {
        const r = await api("/receptors/" + receptorId);
        if (disposed) return;
        setReceptor(r);
        if (
          r.status !== "ready" &&
          r.status !== "failed" &&
          r.status !== "cancelled"
        )
          timer = setTimeout(load, 2000);
      } catch (e) {
        if (!disposed) setError((e as Error).message);
      }
    };
    setSelected([]);
    setGridSet(false);
    load();
    return () => {
      disposed = true;
      clearTimeout(timer);
    };
  }, [receptorId]);
  async function uploadFile(file: File, kind: string) {
    setBusy("upload");
    setError("");
    try {
      const form = new FormData();
      form.append("file", file);
      const r = await api("/uploads?kind=" + kind, {
        method: "POST",
        body: form,
      });
      if (kind === "pdb") {
        setUploaded(r);
        setChains(r.structure.chains);
        setKeep([]);
        setModel(r.structure.model);
        if (!name) setName(file.name.replace(/\.pdb$/i, "") + " screening");
      } else {
        setLib(r);
        setPreview(null);
        await loadPreview(r.id, mapping);
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy("");
    }
  }
  async function loadPreview(id = lib?.id, options = mapping) {
    if (!id) return;
    setError("");
    try {
      const p = await post("/uploads/" + id + "/preview", options);
      setPreview(p);
      setMapping((m) => {
        const smiles = p.columns.includes(m.smiles_column)
          ? m.smiles_column
          : p.columns.find((c: string) => /smiles/i.test(c)) ||
            p.columns[1] ||
            "";
        const cid =
          p.columns.includes(m.cid_column) && m.cid_column !== smiles
            ? m.cid_column
            : p.columns.find(
                (c: string) =>
                  c !== smiles &&
                  /^(cid|id|compoundid|catalogid|catalogueid|enamineid)$/i.test(
                    c.replace(/[\s_-]+/g, ""),
                  ),
              ) ||
              p.columns.find((c: string) => c !== smiles) ||
              "";
        return { ...m, cid_column: cid, smiles_column: smiles };
      });
    } catch (e) {
      setPreview(null);
      setError((e as Error).message);
    }
  }
  async function prepare() {
    setBusy("prepare");
    setError("");
    try {
      const r = await post("/receptors", {
        upload_id: uploaded.id,
        name: uploaded.filename,
        model,
        chains,
        keep_heterogens: keep,
        ph,
      });
      setReceptorId(r.receptor_id);
      saved.reload();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy("");
    }
  }
  function selectResidue(key: string) {
    const next = selected.includes(key)
      ? selected.filter((x) => x !== key)
      : [...selected, key];
    setSelected(next);
    const chosen = residues.filter(
      (r) => next.includes(r.key) && r.heavy_atoms,
    );
    if (chosen.length) {
      const n = chosen.reduce((a, r) => a + r.heavy_atoms, 0);
      setCenter(
        [0, 1, 2].map((a) =>
          Number(
            (
              chosen.reduce((s, r) => s + r.center[a] * r.heavy_atoms, 0) / n
            ).toFixed(3),
          ),
        ),
      );
      setGridSet(true);
    }
  }
  async function submit() {
    setBusy("submit");
    setError("");
    try {
      if (!gridSet)
        throw new Error("결합 위치를 직접 입력하거나 잔기를 선택하세요.");
      const r = await post("/jobs", {
        name,
        receptor_id: receptorId,
        library_id: lib.id,
        library: mapping,
        center,
        size,
        selected_residues: selected,
        conformers,
        exhaustiveness,
        seed,
        strip_salts: stripSalts,
      });
      go("job/" + r.id);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy("");
    }
  }
  const stage = receptor?.status === "ready" ? (preview ? 3 : 2) : 1;
  return (
    <>
      <div className="page-heading">
        <div>
          <span className="eyebrow">START A NEW EXPERIMENT</span>
          <h1>새 Screening</h1>
          <p>표적 구조와 library를 준비하고 결합 가능성을 탐색하세요.</p>
        </div>
        <button className="secondary" onClick={() => go("dashboard")}>
          <ArrowLeft size={16} />
          대시보드
        </button>
      </div>
      <div className="steps">
        {["단백질 준비", "결합 위치 선택", "Library와 실행 설정"].map(
          (x, i) => (
            <div key={x} className={stage >= i + 1 ? "current" : ""}>
              <span>{stage > i + 1 ? <Check size={15} /> : i + 1}</span>
              {x}
              {i < 2 && <ChevronRight size={16} />}
            </div>
          ),
        )}
      </div>
      <ErrorBox text={error} />
      <div className="new-grid">
        <div className="form-main">
          <section className="panel form-panel">
            <div className="panel-heading">
              <span className="step-number">01</span>
              <div>
                <h2>표적 단백질</h2>
                <p>미전처리 PDB도 업로드할 수 있습니다.</p>
              </div>
            </div>
            <Field label="저장된 단백질">
              <select
                value={receptorId}
                onChange={(e) => setReceptorId(e.target.value)}
              >
                <option value="">새 PDB 업로드 또는 기존 구조 선택</option>
                {saved.data?.map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.name} · {labels[r.status]}
                  </option>
                ))}
              </select>
            </Field>
            <label className="dropzone">
              <UploadCloud size={29} />
              <strong>
                {uploaded ? uploaded.filename : "PDB 파일을 선택하세요"}
              </strong>
              <small>최대 100 MB · 원본은 별도로 보관합니다</small>
              <input
                type="file"
                accept=".pdb,.ent"
                onChange={(e) =>
                  e.target.files?.[0] && uploadFile(e.target.files[0], "pdb")
                }
              />
            </label>
            {uploaded && (
              <>
                <div className="input-grid">
                  <Field label="구조 model">
                    <select
                      value={model}
                      onChange={async (e) => {
                        const m = +e.target.value;
                        setModel(m);
                        try {
                          const s = await api(
                            "/uploads/" + uploaded.id + "/structure?model=" + m,
                          );
                          setUploaded({ ...uploaded, structure: s });
                          setChains(s.chains);
                          setKeep([]);
                        } catch (e) {
                          setError(String(e));
                        }
                      }}
                    >
                      {uploaded.structure.models.map((m: number) => (
                        <option key={m}>{m}</option>
                      ))}
                    </select>
                  </Field>
                  <Field label="수소 추가 pH">
                    <input
                      type="number"
                      min={0}
                      max={14}
                      step={0.1}
                      value={ph}
                      onChange={(e) => setPh(+e.target.value)}
                    />
                  </Field>
                </div>
                <Field label="사용할 chain">
                  <div className="chips">
                    {uploaded.structure.chains.map((c: string) => (
                      <button
                        key={c}
                        className={chains.includes(c) ? "chosen" : ""}
                        onClick={() =>
                          setChains(
                            chains.includes(c)
                              ? chains.filter((x) => x !== c)
                              : [...chains, c],
                          )
                        }
                      >
                        Chain {c || "(blank)"}
                      </button>
                    ))}
                  </div>
                </Field>
                <details className="details">
                  <summary>물·리간드·금속·보조인자 선택</summary>
                  <p className="muted">
                    물과 기존 리간드는 기본 제거됩니다. 유지할 성분을
                    선택하세요.
                  </p>
                  <div className="heterogens">
                    {uploaded.structure.residues
                      .filter(
                        (r: Residue) =>
                          r.category !== "protein" && chains.includes(r.chain),
                      )
                      .map((r: Residue) => (
                        <label key={r.key}>
                          <input
                            type="checkbox"
                            checked={keep.includes(r.key)}
                            onChange={() =>
                              setKeep(
                                keep.includes(r.key)
                                  ? keep.filter((k) => k !== r.key)
                                  : [...keep, r.key],
                              )
                            }
                          />
                          <span>
                            {r.name} · {r.chain}:{r.number}
                            {r.insertion}
                          </span>
                          <small>{r.category}</small>
                        </label>
                      ))}
                  </div>
                </details>
                <button
                  className="secondary"
                  disabled={!!busy || !chains.length}
                  onClick={prepare}
                >
                  {busy === "prepare" ? "요청 중…" : "자동 전처리 시작"}
                  <ArrowRight size={16} />
                </button>
              </>
            )}
            {receptor && receptor.status !== "ready" && (
              <div className="notice">
                <Badge status={receptor.status} />
                <p>
                  {receptor.report?.error ||
                    "전처리 완료 후 결합 위치를 설정할 수 있습니다. 다른 작업이 실행 중이면 큐에서 기다립니다."}
                </p>
              </div>
            )}
            {receptor?.status === "ready" && (
              <div className="notice success">
                <CheckCircle2 size={18} />
                전처리가 완료되었습니다.{" "}
                {receptor.report.modeled_residues?.length || 0}개 잔기 복구
                <a href={`/api/receptors/${receptorId}/file/json`}>
                  전처리 보고서
                </a>
              </div>
            )}
          </section>
          {receptor?.status === "ready" && (
            <section className="panel form-panel">
              <div className="panel-heading">
                <span className="step-number">02</span>
                <div>
                  <h2>결합 위치와 Grid box</h2>
                  <p>
                    서열 또는 3D 구조의 잔기를 선택하거나 중심 좌표를
                    입력하세요.
                  </p>
                </div>
              </div>
              <Viewer
                url={`/api/receptors/${receptorId}/file/pdb`}
                selected={residues.filter((r) => selected.includes(r.key))}
                center={gridSet ? center : undefined}
                size={size}
                onPick={(p) => {
                  const r = residues.find(
                    (r) =>
                      r.chain === p.chain &&
                      r.number === p.number &&
                      r.insertion === p.insertion,
                  );
                  if (r && r.category === "protein") selectResidue(r.key);
                }}
              />
              <div className="sequence">
                {receptor.structure.chains.map((chain: string) => (
                  <div key={chain}>
                    <strong>CHAIN {chain || "_"}</strong>
                    <div>
                      {residues
                        .filter(
                          (r) => r.chain === chain && r.category === "protein",
                        )
                        .map((r) => (
                          <button
                            title={`${r.name} ${r.chain}:${r.number}${r.insertion}${r.modeled ? " · 복구된 잔기" : ""}`}
                            key={r.key}
                            className={[
                              selected.includes(r.key) ? "selected" : "",
                              r.modeled ? "modeled" : "",
                            ].join(" ")}
                            onClick={() => selectResidue(r.key)}
                          >
                            <small>
                              {r.number}
                              {r.insertion}
                            </small>
                            {r.letter}
                          </button>
                        ))}
                    </div>
                  </div>
                ))}
              </div>
              <div className="selection-summary">
                선택한 잔기 {selected.length}개{" "}
                <button onClick={() => setSelected([])}>선택 해제</button>
                <span>주황색 밑줄: 복구된 잔기</span>
              </div>
              <div className="input-grid">
                <Field label="중심 좌표 (Å)">
                  <div className="xyz">
                    {center.map((v, i) => (
                      <label key={i}>
                        <small>{"XYZ"[i]}</small>
                        <input
                          aria-label={`중심 ${"XYZ"[i]}`}
                          type="number"
                          step={0.001}
                          value={v}
                          onChange={(e) => {
                            setCenter(
                              center.map((x, j) =>
                                i === j ? +e.target.value : x,
                              ),
                            );
                            setGridSet(true);
                          }}
                        />
                      </label>
                    ))}
                  </div>
                </Field>
                <Field label="박스 크기 (Å)">
                  <div className="xyz">
                    {size.map((v, i) => (
                      <label key={i}>
                        <small>{"XYZ"[i]}</small>
                        <input
                          aria-label={`크기 ${"XYZ"[i]}`}
                          type="number"
                          min={1}
                          max={100}
                          value={v}
                          onChange={(e) =>
                            setSize(
                              size.map((x, j) =>
                                i === j ? +e.target.value : x,
                              ),
                            )
                          }
                        />
                      </label>
                    ))}
                  </div>
                </Field>
              </div>
              {receptor.report.warnings?.map((w: string) => (
                <p className="hint" key={w}>
                  {w}
                </p>
              ))}
            </section>
          )}
          <section className="panel form-panel">
            <div className="panel-heading">
              <span className="step-number">03</span>
              <div>
                <h2>화합물 Library</h2>
                <p>CSV 또는 TSV 파일의 CID와 SMILES 컬럼을 지정하세요.</p>
              </div>
            </div>
            <label className="dropzone compact">
              <UploadCloud size={25} />
              <strong>{lib ? lib.filename : "화합물 파일 선택"}</strong>
              <small>
                학생당 최대{" "}
                {settings.data?.values.max_compounds.toLocaleString() ||
                  "20,000"}
                개
              </small>
              <input
                type="file"
                accept=".csv,.tsv,.txt,.smi"
                onChange={(e) =>
                  e.target.files?.[0] &&
                  uploadFile(e.target.files[0], "library")
                }
              />
            </label>
            <div className="input-grid three">
              <Field label="구분자">
                <select
                  value={mapping.delimiter}
                  onChange={(e) => {
                    setMapping({ ...mapping, delimiter: e.target.value });
                    setPreview(null);
                  }}
                >
                  <option value=",">쉼표 (,)</option>
                  <option value="\t">탭 (TSV)</option>
                  <option value=";">세미콜론 (;)</option>
                  <option value="|">파이프 (|)</option>
                </select>
              </Field>
              <Field label="직접 지정">
                <input
                  maxLength={1}
                  placeholder="구분 문자"
                  onChange={(e) => {
                    if (e.target.value) {
                      setMapping({ ...mapping, delimiter: e.target.value });
                      setPreview(null);
                    }
                  }}
                />
              </Field>
              <Field label="인코딩">
                <select
                  value={mapping.encoding}
                  onChange={(e) => {
                    setMapping({ ...mapping, encoding: e.target.value });
                    setPreview(null);
                  }}
                >
                  <option value="utf-8-sig">UTF-8</option>
                  <option value="cp949">CP949 (한글 Excel)</option>
                  <option value="utf-16">UTF-16</option>
                  <option value="latin-1">Latin-1</option>
                </select>
              </Field>
            </div>
            <div className="row-between">
              <label className="check">
                <input
                  type="checkbox"
                  checked={mapping.header}
                  onChange={(e) => {
                    setMapping({ ...mapping, header: e.target.checked });
                    setPreview(null);
                  }}
                />
                첫 행이 컬럼 이름
              </label>
              <button
                className="secondary small"
                disabled={!lib || !!busy}
                onClick={() => loadPreview()}
              >
                미리보기 갱신
              </button>
            </div>
            {preview && (
              <>
                {preview.warnings?.map((warning: string) => (
                  <p className="hint" key={warning}>
                    {warning}
                  </p>
                ))}
                <div className="input-grid">
                  <Field label="CID 컬럼">
                    <select
                      aria-label="CID 컬럼"
                      value={mapping.cid_column}
                      onChange={(e) =>
                        setMapping({ ...mapping, cid_column: e.target.value })
                      }
                    >
                      {preview.columns.map((c: string) => (
                        <option key={c}>{c}</option>
                      ))}
                    </select>
                  </Field>
                  <Field label="SMILES 컬럼">
                    <select
                      aria-label="SMILES 컬럼"
                      value={mapping.smiles_column}
                      onChange={(e) =>
                        setMapping({
                          ...mapping,
                          smiles_column: e.target.value,
                        })
                      }
                    >
                      {preview.columns.map((c: string) => (
                        <option key={c}>{c}</option>
                      ))}
                    </select>
                  </Field>
                </div>
                <div className="table-wrap preview-table">
                  <table>
                    <thead>
                      <tr>
                        <th>행</th>
                        {preview.columns.map((c: string) => (
                          <th key={c}>{c}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {preview.rows.slice(0, 5).map((r: any) => (
                        <tr key={r.row_number}>
                          <td>{r.row_number}</td>
                          {r.values.map((v: string, i: number) => (
                            <td key={i} title={v}>
                              {v}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <small className="muted">
                  처음 5개 행 미리보기 · 모든 행은 제출 시 검증됩니다.
                </small>
              </>
            )}
          </section>
        </div>
        <aside className="run-settings">
          <section className="panel form-panel">
            <div className="panel-heading">
              <Settings2 size={19} />
              <h2>실행 설정</h2>
            </div>
            <Field label="작업 이름">
              <input
                value={name}
                maxLength={200}
                onChange={(e) => setName(e.target.value)}
                placeholder="예: Kinase library screening"
              />
            </Field>
            <Field
              label="Conformer 수"
              hint="RDKit 3D 생성 및 최소화 · 기본 1개"
            >
              <input
                type="number"
                min={1}
                max={settings.data?.values.max_conformers || 10}
                value={conformers}
                onChange={(e) => setConformers(+e.target.value)}
              />
            </Field>
            <Field
              label="Exhaustiveness"
              hint="탐색 강도 · 높을수록 계산 시간이 늘어납니다"
            >
              <input
                type="number"
                min={1}
                max={settings.data?.values.max_exhaustiveness || 64}
                value={exhaustiveness}
                onChange={(e) => setExhaustiveness(+e.target.value)}
              />
            </Field>
            <Field label="Random seed">
              <input
                type="number"
                min={1}
                max={2147483646}
                value={seed}
                onChange={(e) => setSeed(+e.target.value)}
              />
            </Field>
            <label className="check">
              <input
                type="checkbox"
                checked={stripSalts}
                onChange={(e) => setStripSalts(e.target.checked)}
              />
              Salt 제거 (가장 큰 유기 성분)
            </label>
            <div className="run-summary">
              <div>
                <span>Docking engine</span>
                <b>QuickVina 2.1</b>
              </div>
              <div>
                <span>화합물별 결과</span>
                <b>Best pose 1개</b>
              </div>
              <div>
                <span>CPU 배정</span>
                <b>관리자 설정</b>
              </div>
            </div>
            <button
              className="primary full"
              disabled={
                !!busy ||
                !name ||
                !preview ||
                receptor?.status !== "ready" ||
                !gridSet
              }
              onClick={submit}
            >
              {busy === "submit" ? "제출 중…" : "Screening 제출"}
              <ArrowRight size={17} />
            </button>
            <p className="hint">
              작업은 대기열에 등록됩니다. 브라우저를 닫아도 서버에서 계속
              실행됩니다.
            </p>
          </section>
          <div className="small-note">
            <FlaskConical size={20} />
            <p>
              Conformer 수와 최종 pose 수는 다릅니다. 여러 conformer의 결과 중
              가장 좋은 pose 1개를 제공합니다.
            </p>
          </div>
        </aside>
      </div>
    </>
  );
}

function JobDetail({ id }: { id: string }) {
  const job = useLoad<Job>("/jobs/" + id, 3000),
    [page, setPage] = useState(1),
    [search, setSearch] = useState(""),
    [status, setStatus] = useState(""),
    [chosen, setChosen] = useState<any>(null),
    [error, setError] = useState("");
  const results = useLoad(
      `/jobs/${id}/results?page=${page}&search=${encodeURIComponent(search)}&status=${status}`,
      4000,
    ),
    t = job.data;
  async function action(name: string) {
    try {
      await post(`/jobs/${id}/${name}`);
      job.reload();
      results.reload();
    } catch (e) {
      setError((e as Error).message);
    }
  }
  if (!t)
    return (
      <>
        <ErrorBox text={job.error} />
        <p className="muted">작업을 불러오는 중…</p>
      </>
    );
  const finished = ["completed", "partial", "failed", "cancelled"].includes(
    t.status,
  );
  return (
    <>
      <button className="back" onClick={() => go("dashboard")}>
        <ArrowLeft size={15} />
        전체 작업
      </button>
      <div className="page-heading">
        <div>
          <span className="eyebrow">
            {t.kind === "prepare"
              ? "RECEPTOR PREPARATION"
              : "SCREENING RESULTS"}
          </span>
          <h1>{t.name}</h1>
          <p>
            {t.owner_name} · {date(t.created_at)} ·{" "}
            <span className="mono">{t.id.slice(0, 8)}</span>
          </p>
        </div>
        <div className="actions">
          <Badge status={t.status} />
          {!finished ? (
            <button
              className="secondary danger"
              onClick={() => action("cancel")}
              disabled={t.cancel_requested}
            >
              {t.cancel_requested ? "취소 처리 중" : "작업 취소"}
            </button>
          ) : (
            ["failed", "partial", "cancelled"].includes(t.status) && (
              <button className="secondary" onClick={() => action("retry")}>
                <RefreshCw size={15} />
                미완료 항목 재시도
              </button>
            )
          )}
        </div>
      </div>
      <ErrorBox text={error || t.error || results.error} />
      <div className="stat-grid">
        <Stat
          icon={<Layers3 />}
          label="전체 화합물"
          value={t.total.toLocaleString()}
          caption="입력 library 기준"
        />
        <Stat
          icon={<CheckCircle2 />}
          label="결과 생성"
          value={t.completed.toLocaleString()}
          caption="최상 pose 확인 가능"
        />
        <Stat
          icon={<Activity />}
          label="실패"
          value={t.failed.toLocaleString()}
          caption="개별 원인 확인 및 재시도"
        />
        <Stat
          icon={<Cpu />}
          label="배정 CPU"
          value={t.cpu_ids.length || "—"}
          caption={
            t.cpu_ids.length
              ? "화합물을 순차 처리합니다"
              : "대기 또는 작업 종료"
          }
        />
      </div>
      {t.kind === "prepare" ? (
        <section className="panel">
          <Empty
            title={
              t.status === "completed"
                ? "단백질 준비가 완료되었습니다"
                : "단백질을 준비하고 있습니다"
            }
            text="완료 후 새 Screening 화면에서 이 구조를 선택해 결합 위치를 설정하세요."
            action={
              <button className="primary" onClick={() => go("new")}>
                Screening 만들기
                <ArrowRight size={16} />
              </button>
            }
          />
        </section>
      ) : (
        <>
          <div className="results-grid">
            <section className="panel result-list">
              <div className="panel-heading result-heading">
                <h2>화합물별 결과</h2>
                <div className="actions">
                  <a
                    className="secondary small"
                    href={`/api/jobs/${id}/scores?format=csv`}
                  >
                    <ArrowDownToLine size={14} />
                    CSV
                  </a>
                  <a
                    className="secondary small"
                    href={`/api/jobs/${id}/scores?format=tsv`}
                  >
                    TSV
                  </a>
                  <a
                    className="secondary small"
                    href={`/api/jobs/${id}/archive`}
                  >
                    전체 ZIP
                  </a>
                </div>
              </div>
              <div className="table-toolbar">
                <label className="search">
                  <Search size={15} />
                  <input
                    value={search}
                    placeholder="CID 검색"
                    onChange={(e) => {
                      setSearch(e.target.value);
                      setPage(1);
                    }}
                  />
                </label>
                <select
                  value={status}
                  onChange={(e) => {
                    setStatus(e.target.value);
                    setPage(1);
                  }}
                >
                  <option value="">모든 상태</option>
                  {["succeeded", "partial", "failed", "pending", "running"].map(
                    (s) => (
                      <option key={s} value={s}>
                        {labels[s]}
                      </option>
                    ),
                  )}
                </select>
              </div>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>CID</th>
                      <th>
                        Affinity <small>kcal/mol</small>
                      </th>
                      <th>상태</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {results.data?.rows.map((c: any) => (
                      <tr
                        key={c.id}
                        className={
                          "clickable " +
                          (chosen?.id === c.id ? "row-selected" : "")
                        }
                        onClick={() => setChosen(c)}
                      >
                        <td>
                          <strong>{c.cid || "(빈 CID)"}</strong>
                          <small className="block muted">
                            입력 {c.row_number}행
                          </small>
                        </td>
                        <td className="score">
                          {c.affinity?.toFixed(1) ?? "—"}
                        </td>
                        <td>
                          <Badge status={c.status} />
                        </td>
                        <td>
                          <ChevronRight size={14} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="pagination">
                <span>{results.data?.total.toLocaleString() || 0}개 결과</span>
                <button disabled={page === 1} onClick={() => setPage(page - 1)}>
                  이전
                </button>
                <b>{page}</b>
                <button
                  disabled={page * 50 >= (results.data?.total || 0)}
                  onClick={() => setPage(page + 1)}
                >
                  다음
                </button>
              </div>
            </section>
            <section className="panel pose-panel">
              <div className="panel-heading">
                <h2>{chosen ? chosen.cid : "Docking pose"}</h2>
                {chosen?.affinity != null && (
                  <span className="affinity">
                    {chosen.affinity.toFixed(1)} <small>kcal/mol</small>
                  </span>
                )}
              </div>
              {chosen?.affinity != null ? (
                <>
                  <Viewer
                    url={`/api/receptors/${t.receptor_id}/file/pdb`}
                    ligand={`/api/jobs/${id}/compounds/${chosen.id}/sdf`}
                  />
                  <div className="pose-info">
                    <p className="mono smiles">{chosen.normalized_smiles}</p>
                    <div className="actions">
                      <a
                        className="secondary small"
                        href={`/api/jobs/${id}/compounds/${chosen.id}/sdf`}
                      >
                        Pose SDF
                      </a>
                      <a
                        className="secondary small"
                        href={`/api/jobs/${id}/compounds/${chosen.id}/pdbqt`}
                      >
                        Pose PDBQT
                      </a>
                    </div>
                    <details>
                      <summary>계산 상세 정보</summary>
                      <pre>{JSON.stringify(chosen.details, null, 2)}</pre>
                    </details>
                  </div>
                </>
              ) : (
                <Empty
                  title={
                    chosen ? "아직 pose가 없습니다" : "화합물을 선택하세요"
                  }
                  text={
                    chosen?.error ||
                    "결과 목록에서 화합물을 선택하면 단백질과 결합 pose를 확인할 수 있습니다."
                  }
                />
              )}
              <p className="hint padded">
                Affinity는 docking으로 계산한 점수입니다. 실험으로 측정한 결합
                친화도와 구분해서 해석하세요.
              </p>
            </section>
          </div>
          {chosen?.error && <ErrorBox text={chosen.error} />}
          <section className="panel form-panel">
            <h3>실행 설정</h3>
            <div className="parameter-list">
              <span>
                Conformers <b>{t.parameters.conformers}</b>
              </span>
              <span>
                Exhaustiveness <b>{t.parameters.exhaustiveness}</b>
              </span>
              <span>
                Seed <b>{t.parameters.seed}</b>
              </span>
              <span>
                중심 <b>{t.parameters.center?.join(", ")}</b>
              </span>
              <span>
                박스 <b>{t.parameters.size?.join(" × ")} Å</b>
              </span>
            </div>
          </section>
        </>
      )}
      {finished && t.kind === "screen" && (
        <button
          className="text-danger"
          onClick={async () => {
            if (
              !confirm(
                "이 작업의 점수와 pose 파일을 삭제할까요? 다운로드한 자료를 확인한 뒤 진행하세요.",
              )
            )
              return;
            try {
              await api("/jobs/" + id, { method: "DELETE" });
              go("dashboard");
            } catch (e) {
              setError(String(e));
            }
          }}
        >
          <Trash2 size={14} />이 작업과 결과 삭제
        </button>
      )}
    </>
  );
}

function Admin() {
  const users = useLoad<User[]>("/admin/users", 6000),
    resources = useLoad("/settings", 5000),
    disk = useLoad("/admin/storage", 30000);
  const [draft, setDraft] = useState<any>(null),
    [error, setError] = useState(""),
    [message, setMessage] = useState(""),
    [busy, setBusy] = useState(false);
  useEffect(() => {
    if (resources.data && !draft) setDraft(resources.data.values);
  }, [resources.data, draft]);
  async function edit(u: User, changes: any) {
    try {
      await api("/admin/users/" + u.id, {
        method: "PATCH",
        body: JSON.stringify(changes),
      });
      users.reload();
    } catch (e) {
      setError((e as Error).message);
    }
  }
  async function save(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api("/admin/settings", {
        method: "PUT",
        body: JSON.stringify(draft),
      });
      resources.reload();
      setMessage(
        "운영 설정을 저장했습니다. 변경 사항은 신규 작업 배정부터 적용됩니다.",
      );
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  const fields = [
    ["cpu_budget", "전체 계산 CPU 한도"],
    ["max_students", "동시 실행 학생 수"],
    ["default_cpus", "기본 학생당 CPU"],
    ["max_compounds", "Library 최대 화합물 수"],
    ["max_conformers", "Conformer 최대 수"],
    ["max_exhaustiveness", "최대 Exhaustiveness"],
    ["max_pending_per_user", "학생별 대기·실행 작업 수"],
    ["compound_timeout", "화합물 제한 시간 (초)"],
    ["preparation_timeout", "전처리 제한 시간 (초)"],
    ["max_retries", "Timeout 자동 재시도 횟수"],
    ["storage_limit_gb", "전체 저장 공간 한도 (GB)"],
    ["user_storage_limit_gb", "학생별 저장 공간 한도 (GB)"],
    ["retention_days", "결과 보존 기간 (일, 0=자동 삭제 안 함)"],
  ];
  return (
    <>
      <div className="page-heading">
        <div>
          <span className="eyebrow">LAB ADMINISTRATION</span>
          <h1>실습 공간 관리</h1>
          <p>학생을 승인하고 계산 자원을 배분하세요.</p>
        </div>
        <span className="admin-tag">
          <ShieldCheck size={16} />
          Administrator
        </span>
      </div>
      <ErrorBox text={error || users.error || resources.error} />
      {message && <div className="notice success">{message}</div>}
      <div className="stat-grid">
        <Stat
          icon={<Users />}
          label="승인 대기"
          value={users.data?.filter((u) => u.status === "pending").length || 0}
          caption="새로운 학생 신청"
        />
        <Stat
          icon={<Cpu />}
          label="실제 배정 CPU"
          value={resources.data?.allocated_cpus ?? 0}
          caption={`서버에서 사용 가능한 CPU ${resources.data?.available_cpu_count || "—"}개`}
        />
        <Stat
          icon={<Database />}
          label="플랫폼 저장량"
          value={
            disk.data
              ? (disk.data.used_bytes / 1024 ** 3).toFixed(2) + " GB"
              : "—"
          }
          caption={
            disk.data
              ? `디스크 여유 ${(disk.data.free_bytes / 1024 ** 3).toFixed(1)} GB`
              : "조회 중"
          }
        />
        <Stat
          icon={<Activity />}
          label="실행 학생"
          value={resources.data?.active_students ?? 0}
          caption={`${resources.data?.queued || 0}개 작업 대기`}
        />
      </div>
      {resources.data?.scheduler_error && (
        <ErrorBox text={resources.data.scheduler_error} />
      )}
      <div className="admin-grid">
        <section className="panel">
          <div className="panel-heading">
            <h2>학생 계정</h2>
            <small className="muted">{users.data?.length || 0}명</small>
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>학생</th>
                  <th>상태</th>
                  <th>CPU</th>
                  <th>관리</th>
                </tr>
              </thead>
              <tbody>
                {users.data?.map((u) => (
                  <tr key={u.id}>
                    <td>
                      <strong>{u.name}</strong>
                      <small className="block muted">
                        {u.username} · {u.student_number || "관리자"}
                      </small>
                    </td>
                    <td>
                      <Badge status={u.status} />
                    </td>
                    <td>
                      <input
                        className="cpu-input"
                        type="number"
                        min={1}
                        max={draft?.cpu_budget}
                        placeholder="기본"
                        defaultValue={u.cpu_override ?? ""}
                        aria-label={`${u.name} CPU`}
                        onBlur={(e) => {
                          const v = e.target.value ? +e.target.value : null;
                          if (v !== u.cpu_override)
                            edit(u, { cpu_override: v });
                        }}
                      />
                    </td>
                    <td>
                      <div className="actions">
                        {u.role !== "admin" &&
                          (u.status === "pending" ? (
                            <>
                              <button
                                className="approve"
                                onClick={() => edit(u, { status: "approved" })}
                              >
                                승인
                              </button>
                              <button
                                className="subtle"
                                onClick={() => edit(u, { status: "rejected" })}
                              >
                                거절
                              </button>
                            </>
                          ) : (
                            <button
                              className="subtle"
                              onClick={() =>
                                edit(u, {
                                  status:
                                    u.status === "approved"
                                      ? "suspended"
                                      : "approved",
                                })
                              }
                            >
                              {u.status === "approved" ? "정지" : "승인"}
                            </button>
                          ))}
                        <button
                          className="subtle"
                          onClick={async () => {
                            if (
                              !confirm(`${u.name}님의 비밀번호를 초기화할까요?`)
                            )
                              return;
                            try {
                              const r = await post(
                                `/admin/users/${u.id}/reset-password`,
                              );
                              setMessage(
                                `${u.name}님의 임시 비밀번호: ${r.temporary_password} — 학생에게 직접 전달하세요.`,
                              );
                            } catch (e) {
                              setError(String(e));
                            }
                          }}
                        >
                          비밀번호
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
        <form className="panel form-panel" onSubmit={save}>
          <div className="panel-heading">
            <Settings2 size={18} />
            <h2>자원과 운영 설정</h2>
          </div>
          {draft && (
            <>
              <label className="toggle-line">
                <div>
                  <strong>신규 작업 배정 일시 중지</strong>
                  <small>실행 중인 작업은 계속 진행됩니다.</small>
                </div>
                <input
                  type="checkbox"
                  checked={draft.paused}
                  onChange={(e) =>
                    setDraft({ ...draft, paused: e.target.checked })
                  }
                />
              </label>
              <div className="settings-fields">
                {fields.map(([k, label]) => (
                  <Field key={k} label={label}>
                    <input
                      type="number"
                      required
                      min={
                        k === "retention_days" || k === "max_retries" ? 0 : 1
                      }
                      value={draft[k]}
                      onChange={(e) =>
                        setDraft({ ...draft, [k]: +e.target.value })
                      }
                    />
                  </Field>
                ))}
              </div>
              <p className="hint">
                현재 예약한 자원보다 한도를 줄이면 신규 배정이 대기합니다. 기존
                작업의 CPU는 종료 시 반환됩니다.
              </p>
              <button className="primary full" disabled={busy}>
                설정 저장
                <Check size={16} />
              </button>
            </>
          )}
        </form>
      </div>
    </>
  );
}

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
