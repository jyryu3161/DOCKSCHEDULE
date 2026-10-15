import { useMemo, useState } from "react";
import Viewer from "./Viewer";
import { useLoad } from "./useLoad";
import { InteractionReport, interactionKinds, residueLabel } from "./interactions";

export default function PoseInteractions({ receptorUrl, ligandUrl, path }: {
  receptorUrl: string; ligandUrl: string; path: string;
}) {
  const { data, error, reload } = useLoad<InteractionReport>(path);
  const [enabled, setEnabled] = useState(() => Object.keys(interactionKinds));
  const [activeId, setActiveId] = useState<string | null>(null);
  const [show, setShow] = useState(true);
  const [labels, setLabels] = useState(false);
  const visible = useMemo(() => (data?.interactions || []).filter((i) => enabled.includes(i.kind)), [data, enabled]);
  const active = visible.find((i) => i.id === activeId);
  const displayed = useMemo(() => show ? visible : [], [show, visible]);
  const counts = useMemo(() => {
    const result: Record<string, number> = {};
    data?.interactions.forEach((i) => { result[i.kind] = (result[i.kind] || 0) + 1; });
    return result;
  }, [data]);

  function download() {
    const cell = (value: string | number) => {
      let text = String(value);
      if (/^[=+@\-\t\r]/.test(text)) text = "'" + text;
      return '"' + text.replaceAll('"', '""') + '"';
    };
    const rows = [
      ["유형", "리간드 역할", "Chain", "Residue", "잔기 번호", "삽입 코드", "단백질 원자", "리간드 원자 (SDF 1-based)", "거리 (Å)", "각도 (°)", "분석 엔진"],
      ...visible.map((i) => [interactionKinds[i.kind].label, i.role, i.residue.chain, i.residue.name,
        i.residue.number, i.residue.insertion, i.protein_atoms.map((a) => a.label).join("; "),
        i.ligand_atoms.map((a) => a.label).join("; "), i.distance,
        Object.entries(i.angles).map(([key, value]) => `${key}=${value}`).join("; "), `${data!.engine} ${data!.engine_version}`]),
    ];
    const url = URL.createObjectURL(new Blob(["\ufeff" + rows.map((row) => row.map(cell).join(",")).join("\r\n")], { type: "text/csv;charset=utf-8" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = `interactions-${path.split("/").at(-2)}.csv`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  return <>
    <Viewer url={receptorUrl} ligand={ligandUrl} interactions={displayed}
      activeInteraction={show ? active : undefined} atomLabels={labels} />
    <section className="interaction-panel" aria-label="단백질–리간드 상호작용">
      <div className="interaction-heading">
        <h3>단백질–리간드 상호작용</h3>
        {data && <button className="secondary small" onClick={download} disabled={!visible.length}>상호작용 CSV</button>}
      </div>
      {!data && !error && <p className="muted" role="status">선택한 pose의 상호작용을 분석하는 중…</p>}
      {error && <div className="notice error" role="alert">{error} <button onClick={() => void reload()}>분석 다시 시도</button></div>}
      {data && <>
        <div className="interaction-filters" aria-label="상호작용 유형 필터">
          {Object.entries(interactionKinds).map(([kind, meta]) => <label key={kind}>
            <input type="checkbox" checked={enabled.includes(kind)} onChange={(e) => {
              setEnabled((prev) => e.target.checked ? [...prev, kind] : prev.filter((k) => k !== kind));
            }} />
            <i style={{ background: meta.color }} />{meta.label} <b>{counts[kind] || 0}</b>
          </label>)}
        </div>
        <div className="interaction-controls">
          <label><input type="checkbox" checked={show} onChange={(e) => setShow(e.target.checked)} />3D 상호작용 표시</label>
          <label><input type="checkbox" checked={labels} onChange={(e) => setLabels(e.target.checked)} />리간드 원자 번호</label>
          {active && <button className="secondary small" onClick={() => setActiveId(null)}>강조 해제</button>}
        </div>
        <p className="hint">{visible.length}개 표시 · 행을 선택하면 해당 원자와 잔기를 3D에서 강조합니다.</p>
        {visible.length ? <div className="table-wrap interaction-table"><table>
          <thead><tr><th>유형 / 리간드 역할</th><th>단백질 잔기 / 원자</th><th>리간드 원자</th><th>거리 Å</th><th>각도 °</th></tr></thead>
          <tbody>{visible.map((i) => <tr key={i.id} className={"clickable " + (activeId === i.id ? "row-selected" : "")}
            onClick={() => { setActiveId(i.id); setShow(true); }}>
            <td><button className="interaction-select" aria-pressed={activeId === i.id}>
              <i style={{ background: interactionKinds[i.kind].color }} />{interactionKinds[i.kind].label}
              <small className="block">{i.role}</small>
            </button></td>
            <td>{residueLabel(i.residue)}<small className="block mono">{i.protein_atoms.map((a) => a.label).join(", ")}</small></td>
            <td className="mono">{i.ligand_atoms.map((a) => a.label).join(", ")}</td>
            <td>{i.distance.toFixed(2)}</td>
            <td>{Object.entries(i.angles).length ? Object.entries(i.angles).map(([key, value]) => <small className="block" key={key}>{key}: {value.toFixed(1)}</small>) : "—"}</td>
          </tr>)}</tbody>
        </table></div> : <p className="interaction-empty">{data.interactions.length ? "선택한 유형의 상호작용이 없습니다." : "현재 거리·각도 기준을 만족하는 상호작용이 검출되지 않았습니다."}</p>}
        <p className="hint">리간드 O3 = SDF의 3번 산소 원자. 수소결합 거리는 donor–acceptor 간 거리이며 DHA는 donor–H–acceptor 각도입니다. π 상호작용은 고리 중심을 사용합니다.</p>
        <details className="interaction-method"><summary>분석 기준과 주의사항 · {data.engine} {data.engine_version}</summary>
          <p>수소결합 ≤ 3.5 Å, DHA 130–180° · 소수성 접촉 ≤ 4.5 Å · 염다리 ≤ 4.5 Å. π 및 할로젠 결합은 ProLIF 기본 거리·각도 기준을 사용합니다.</p>
          <p>3D pose의 기하학적 상호작용 후보입니다. 결합 에너지나 실험적 결합을 의미하지 않으며, 수소 위치와 protonation 상태에 따라 달라집니다.</p>
          {data.warnings.map((warning, index) => <p key={index}>{warning}</p>)}
        </details>
      </>}
    </section>
  </>;
}
