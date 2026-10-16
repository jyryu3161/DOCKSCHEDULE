import { useState } from "react";
import { Job, labels, post, Residue } from "./api";
import { useLoad } from "./useLoad";
import { interactionKinds, residueLabel } from "./interactions";

interface IndexStatus {
  eligible: number; analyzed: number; failed: number; remaining: number; busy: boolean;
  job: Job | null; residues: Residue[];
  failures: { compound_id: number; cid: string; error: string }[];
}

export default function LibraryInteractions({ taskId, query, onChange }: {
  taskId: string; query: string; onChange: (query: string) => void;
}) {
  const index = useLoad<IndexStatus>(`/jobs/${taskId}/interaction-index`, 4000);
  const [residues, setResidues] = useState<string[]>([]);
  const [kinds, setKinds] = useState<string[]>(["hydrogen_bond"]);
  const [match, setMatch] = useState("any");
  const [search, setSearch] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const data = index.data;
  const available = data?.residues || [];
  const filtered = available.filter((r) => residueLabel(r).toLowerCase().includes(search.toLowerCase()));
  const toggle = (values: string[], value: string) => values.includes(value) ? values.filter((x) => x !== value) : [...values, value];
  async function analyze(cancel = false) {
    setSubmitting(true);
    setError("");
    try {
      await post(cancel ? `/jobs/${data!.job!.id}/cancel` : `/jobs/${taskId}/interaction-index`);
      index.reload();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSubmitting(false);
    }
  }
  function apply() {
    const params = new URLSearchParams({ interaction: "true", match });
    residues.forEach((r) => params.append("residue", r));
    kinds.forEach((k) => params.append("kind", k));
    onChange(params.toString());
  }
  const applied = new URLSearchParams(query);
  return <section className="panel library-interactions" aria-label="잔기별 후보 찾기">
    <div className="panel-heading">
      <div><h2>잔기별 후보 찾기</h2><p className="muted">잔기와 상호작용 타입을 골라 아래 화합물 결과를 필터링합니다.</p></div>
      <button className="secondary" disabled={submitting || !data || data.busy || !data.eligible || !(data.remaining + data.failed)} onClick={() => analyze()}>
        {data?.job ? "미분석·실패 항목 분석" : "라이브러리 상호작용 분석"}
      </button>
    </div>
    {(error || index.error) && <div className="notice error" role="alert">{error || index.error}</div>}
    {data && <div className="index-progress" role="status">
      <span>Pose {data.eligible?.toLocaleString()}개 · 분석 완료 {data.analyzed?.toLocaleString()}개 · 미분석 {data.remaining?.toLocaleString()}개 · 실패 {data.failed?.toLocaleString()}개</span>
      {data.job && <span>최근 분석: {labels[data.job.status]} ({data.job.completed + data.job.failed}/{data.job.total})</span>}
      {data.busy && data.job && <button className="secondary small" disabled={submitting || data.job.cancel_requested} onClick={() => analyze(true)}>
        {data.job.cancel_requested ? "취소 처리 중" : "분석 취소"}
      </button>}
    </div>}
    {data?.job?.error && <p className="notice">{data.job.error}</p>}
    {!!data?.failed && <details className="analysis-failures"><summary>분석 실패 원인 (최대 10개)</summary>
      {data.failures.map((f) => <p key={f.compound_id}>{f.cid}: {f.error}</p>)}
    </details>}
    <div className="candidate-controls">
      <fieldset><legend>잔기 선택</legend>
        <input aria-label="후보 잔기 검색" placeholder="예: A:ASP 25 또는 25" value={search} onChange={(e) => setSearch(e.target.value)} />
        <div className="candidate-residues">
          {filtered.slice(0, 80).map((r) => <label key={r.key}>
            <input type="checkbox" checked={residues.includes(r.key)} disabled={!residues.includes(r.key) && residues.length >= 100}
              onChange={() => setResidues(toggle(residues, r.key))} />{residueLabel(r)}
          </label>)}
          {!filtered.length && <span className="muted">{data ? "일치하는 잔기가 없습니다." : "잔기를 불러오는 중…"}</span>}
        </div>
        {filtered.length > 80 && <small className="muted">검색으로 잔기를 좁혀 주세요. 처음 80개를 표시합니다.</small>}
        <div className="selected-residues" aria-label="선택한 후보 잔기">
          {residues.map((key) => <button key={key} className="secondary small" onClick={() => setResidues(toggle(residues, key))}>
            {available.find((r) => r.key === key) ? residueLabel(available.find((r) => r.key === key)!) : key} ×
          </button>)}
        </div>
      </fieldset>
      <fieldset><legend>상호작용 타입</legend>
        <div className="candidate-kinds">
          {Object.entries(interactionKinds).map(([kind, meta]) => <label key={kind}>
            <input type="checkbox" checked={kinds.includes(kind)} onChange={() => setKinds(toggle(kinds, kind))} />
            <i style={{ background: meta.color }} />{meta.label}
          </label>)}
        </div>
        <label className="field"><span>여러 잔기 조건</span><select aria-label="여러 잔기 조건" value={match} onChange={(e) => setMatch(e.target.value)}>
          <option value="any">선택한 잔기 중 하나 이상</option><option value="all">선택한 모든 잔기</option>
        </select></label>
        <p className="hint">각 잔기에서 선택한 타입 중 하나 이상이 검출되면 일치합니다.</p>
        <div className="actions">
          <button className="primary" disabled={!residues.length || !kinds.length || !data?.analyzed} onClick={apply}>후보 찾기</button>
          {query && <button className="secondary" onClick={() => onChange("")}>필터 해제</button>}
        </div>
      </fieldset>
    </div>
    {query && <p className="notice" role="status">적용 중: {applied.getAll("residue").map((key) => {
      const r = available.find((r) => r.key === key); return r ? residueLabel(r) : key;
    }).join(", ")} · {applied.get("match") === "all" ? "모든 잔기" : "하나 이상"} · {applied.getAll("kind").map((k) => interactionKinds[k]?.label).join(", ")}</p>}
    <p className="hint">요청 시점에 생성된 최상 pose를 분석합니다. 같은 사용자의 docking이 실행 중이면 분석은 큐에서 대기합니다.
      후보는 분석 완료 항목에서만 찾으며 미분석·실패 항목은 제외합니다. 분석 중 CSV는 내려받는 시점까지 저장된 결과를 포함합니다.
      물 매개 결합·금속·보조인자는 분석에 포함하지 않습니다.</p>
  </section>;
}
