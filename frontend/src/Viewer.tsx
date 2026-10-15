import { useEffect, useRef, useState } from "react";
import * as NGL from "ngl";
import { Maximize2, RotateCcw } from "lucide-react";
import { Residue } from "./api";

const selection = (r: Residue) =>
  `${r.number}${r.insertion ? "^" + r.insertion : ""}:${r.chain}`;

export default function Viewer({
  url,
  ligand,
  selected = [],
  center,
  size,
  onPick,
}: {
  url: string;
  ligand?: string;
  selected?: Residue[];
  center?: number[];
  size?: number[];
  onPick?: (r: { chain: string; number: number; insertion: string }) => void;
}) {
  const element = useRef<HTMLDivElement>(null),
    stage = useRef<NGL.Stage | null>(null),
    protein = useRef<any>(null),
    highlight = useRef<any>(null),
    box = useRef<any>(null);
  const [structureError, setStructureError] = useState("");
  const [ligandError, setLigandError] = useState("");
  const error = structureError || ligandError;
  const pick = useRef(onPick);
  pick.current = onPick;
  const [loaded, setLoaded] = useState("");
  useEffect(() => {
    if (!element.current) return;
    let disposed = false;
    const request = new AbortController();
    setStructureError("");
    setLoaded("");
    const s = new NGL.Stage(element.current, {
      backgroundColor: "#101c2d",
      quality: "medium",
    });
    stage.current = s;
    const resize = new ResizeObserver(() => s.handleResize());
    resize.observe(element.current);
    s.signals.clicked.add((p: any) => {
      if (p?.atom)
        pick.current?.({
          chain: p.atom.chainname,
          number: p.atom.resno,
          insertion: p.atom.inscode || "",
        });
    });
    (async () => {
      try {
        const response = await fetch(url, { signal: request.signal });
        if (!response.ok) throw new Error("구조 파일을 불러오지 못했습니다.");
        const blob = await response.blob();
        if (disposed) return;
        const c: any = await s.loadFile(blob, { ext: "pdb" });
        if (disposed) {
          s.removeComponent(c);
          return;
        }
        protein.current = c;
        c.addRepresentation("cartoon", {
          colorScheme: "chainname",
          colorScale: ["#52c8b8", "#8aa4d9", "#e5af68"],
        });
        c.addRepresentation("ball+stick", {
          sele: "hetero and not water",
          colorScheme: "element",
          scale: 0.7,
        });
        c.autoView();
        setLoaded(url);
      } catch (e) {
        if (!disposed) setStructureError(String(e));
      }
    })();
    return () => {
      disposed = true;
      request.abort();
      resize.disconnect();
      s.dispose();
      stage.current = null;
      protein.current = null;
      highlight.current = null;
      box.current = null;
    };
  }, [url]);
  useEffect(() => {
    if (!protein.current) return;
    highlight.current?.dispose();
    highlight.current = null;
    if (selected.length)
      highlight.current = protein.current.addRepresentation("ball+stick", {
        sele: selected.map(selection).join(" or "),
        color: "#f6bb59",
        scale: 0.6,
      });
  }, [selected, loaded]);
  useEffect(() => {
    const s = stage.current;
    if (!s) return;
    if (box.current) {
      s.removeComponent(box.current);
      box.current = null;
    }
    if (!center || !size || ![...center, ...size].every(Number.isFinite))
      return;
    const shape = new NGL.Shape("grid");
    const corners: number[][] = [];
    for (let i = 0; i < 8; i++)
      corners.push(
        center.map((v, a) => v + (((i >> a) & 1 ? 1 : -1) * size[a]) / 2),
      );
    for (let i = 0; i < 8; i++)
      for (let a = 0; a < 3; a++) {
        const j = i ^ (1 << a);
        if (i < j)
          shape.addCylinder(
            corners[i],
            corners[j],
            [0.95, 0.72, 0.32],
            0.07,
            "grid edge",
          );
      }
    shape.addSphere(center, [0.95, 0.72, 0.32], 0.3, "grid center");
    box.current = s.addComponentFromObject(shape);
    box.current.addRepresentation("buffer");
  }, [center, size, loaded]);
  useEffect(() => {
    const s = stage.current;
    setLigandError("");
    if (!s || !ligand || loaded !== url) return;
    let component: any,
      disposed = false;
    const request = new AbortController();
    (async () => {
      try {
        const r = await fetch(ligand, { signal: request.signal });
        if (!r.ok) throw new Error("Pose 파일을 불러오지 못했습니다.");
        const blob = await r.blob();
        if (disposed) return;
        const c: any = await s.loadFile(blob, { ext: "sdf" });
        if (disposed) {
          s.removeComponent(c);
          return;
        }
        component = c;
        c.addRepresentation("ball+stick", {
          colorScheme: "element",
          scale: 1.3,
        });
        c.autoView(400);
      } catch (e) {
        if (!disposed) setLigandError(String(e));
      }
    })();
    return () => {
      disposed = true;
      request.abort();
      if (component) s.removeComponent(component);
    };
  }, [url, ligand, loaded]);
  return (
    <div className="viewer">
      <div className="viewer-canvas" ref={element} />
      <div className="viewer-top">
        <span>
          <i /> LIVE STRUCTURE
        </span>
        <div>
          <button
            title="전체 구조 보기"
            onClick={() => stage.current?.autoView(300)}
          >
            <RotateCcw size={15} />
          </button>
          <button
            title="전체 화면"
            onClick={() => element.current?.parentElement?.requestFullscreen()}
          >
            <Maximize2 size={15} />
          </button>
        </div>
      </div>
      <div className="viewer-bottom">
        드래그하여 회전 · 스크롤하여 확대 {onPick && "· 잔기를 클릭하여 선택"}
      </div>
      {error && <div className="viewer-error">{error}</div>}
    </div>
  );
}
