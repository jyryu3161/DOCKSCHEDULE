import { useEffect, useRef, useState } from "react";
import * as NGL from "ngl";
import { Maximize2, RotateCcw } from "lucide-react";
import { Residue } from "./api";
import { PoseInteraction, interactionKinds, residueLabel } from "./interactions";

const noInteractions: PoseInteraction[] = [];

const selection = (r: Residue) =>
  `${r.number}${r.insertion ? "^" + r.insertion : ""}:${r.chain}`;

export default function Viewer({
  url,
  ligand,
  selected = [],
  center,
  size,
  onPick,
  interactions = noInteractions,
  activeInteraction,
  atomLabels = false,
}: {
  url: string;
  ligand?: string;
  selected?: Residue[];
  center?: number[];
  size?: number[];
  onPick?: (r: { chain: string; number: number; insertion: string }) => void;
  interactions?: PoseInteraction[];
  activeInteraction?: PoseInteraction;
  atomLabels?: boolean;
}) {
  const element = useRef<HTMLDivElement>(null),
    stage = useRef<NGL.Stage | null>(null),
    protein = useRef<any>(null),
    cartoon = useRef<any>(null),
    pose = useRef<any>(null),
    highlight = useRef<any>(null),
    box = useRef<any>(null);
  const [structureError, setStructureError] = useState("");
  const [ligandError, setLigandError] = useState("");
  const error = structureError || ligandError;
  const pick = useRef(onPick);
  pick.current = onPick;
  const [loaded, setLoaded] = useState("");
  const [poseLoaded, setPoseLoaded] = useState("");
  useEffect(() => {
    if (!element.current) return;
    const container = element.current;
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
        cartoon.current = c.addRepresentation("cartoon", {
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
      // NGL disposes WebGL resources but leaves its canvas in the container.
      // React StrictMode and receptor changes can otherwise stack stale canvases.
      container.replaceChildren();
      stage.current = null;
      protein.current = null;
      cartoon.current = null;
      pose.current = null;
      highlight.current = null;
      box.current = null;
    };
  }, [url]);
  useEffect(() => {
    cartoon.current?.setParameters({ opacity: ligand ? 0.18 : 1 });
    stage.current?.setParameters({ clipDist: ligand ? 2 : 10 });
  }, [ligand, loaded]);
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
    setPoseLoaded("");
    pose.current = null;
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
        pose.current = c;
        c.addRepresentation("ball+stick", {
          sele: "not hydrogen",
          colorScheme: "element",
          scale: 1.3,
        });
        c.autoView(400);
        setPoseLoaded(ligand);
      } catch (e) {
        if (!disposed) setLigandError(String(e));
      }
    })();
    return () => {
      disposed = true;
      request.abort();
      pose.current = null;
      if (component) s.removeComponent(component);
    };
  }, [url, ligand, loaded]);
  useEffect(() => {
    const s = stage.current;
    if (!s || !protein.current || !pose.current || loaded !== url || poseLoaded !== ligand) return;
    const representations: any[] = [];
    const components: any[] = [];
    const rgb = (hex: string): [number, number, number] => [1, 3, 5].map((i) => parseInt(hex.slice(i, i+2), 16)/255) as [number, number, number];
    if (interactions.length) {
      const indices = [...new Set(interactions.flatMap((i) => i.residue.atom_indices))];
      representations.push(protein.current.addRepresentation("ball+stick", {
        sele: `@${indices.join(",")} and not hydrogen`, colorScheme: "element", scale: 0.6,
      }));
      const shape = new NGL.Shape("pose interactions", { dashedCylinder: true });
      interactions.forEach((i) => {
        const meta = interactionKinds[i.kind];
        shape.addCylinder(i.ligand_position, i.protein_position, rgb(meta.color),
          i.id === activeInteraction?.id ? 0.12 : 0.055,
          `${meta.label} · ${residueLabel(i.residue)} · ${i.distance.toFixed(2)} Å`);
      });
      const c = s.addComponentFromObject(shape);
      if (c) {
        c.addRepresentation("buffer", {});
        components.push(c);
      }
    }
    if (activeInteraction) {
      const i = activeInteraction;
      representations.push(protein.current.addRepresentation("ball+stick", {
        sele: `@${i.residue.atom_indices.join(",")} and not hydrogen`, color: "#f6bb59", scale: 0.9,
      }));
      const indices = i.ligand_atoms.filter((a) => a.index !== null).map((a) => a.index);
      if (indices.length) representations.push(pose.current.addRepresentation("ball+stick", {
        sele: `@${indices.join(",")}`, color: "#f6bb59", scale: 1.5,
      }));
      const detail = new NGL.Shape("selected interaction");
      const middle = i.ligand_position.map((v, axis) => (v + i.protein_position[axis])/2);
      detail.addText(middle, [1, 1, 1], 1.1, `${i.distance.toFixed(2)} Å`);
      detail.addText(i.protein_position, [1, 0.8, 0.4], 1, `${residueLabel(i.residue)} ${i.protein_atoms.map((a) => a.label).join(",")}`);
      i.ligand_atoms.filter((a) => !atomLabels || a.element === "H" || a.index === null)
        .forEach((a) => detail.addText(a.position, [1, 0.8, 0.4], 1, a.label));
      const c = s.addComponentFromObject(detail);
      if (c) {
        c.addRepresentation("buffer", {});
        components.push(c);
      }
    }
    if (atomLabels) {
      const labelText: string[] = [];
      pose.current.structure.eachAtom((atom: any) => {
        const element = atom.element[0] + atom.element.slice(1).toLowerCase();
        labelText[atom.index] = `${element}${atom.index + 1}`;
      });
      representations.push(pose.current.addRepresentation("label", {
        sele: "not hydrogen", labelType: "text", labelText, color: "white",
        showBorder: true, borderColor: "#101c2d", zOffset: 1.5, scale: 0.7,
      }));
    }
    s.viewer.requestRender();
    return () => {
      representations.forEach((r) => r.dispose());
      components.forEach((c) => s.removeComponent(c));
    };
  }, [url, ligand, loaded, poseLoaded, interactions, activeInteraction, atomLabels]);
  useEffect(() => {
    const s = stage.current;
    if (!s || !activeInteraction || !pose.current || poseLoaded !== ligand) return;
    const bounds = new NGL.Box3();
    pose.current.structure.eachAtom((a: any) => bounds.expandByPoint(new NGL.Vector3(a.x, a.y, a.z)));
    activeInteraction.protein_atoms.forEach((a) => bounds.expandByPoint(new NGL.Vector3(...a.position)));
    bounds.expandByScalar(2);
    s.animationControls.zoomMove(bounds.getCenter(new NGL.Vector3()), s.getZoomForBox(bounds), 300);
  }, [activeInteraction, poseLoaded, ligand]);
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
      {activeInteraction && <div className="viewer-interaction" role="status">
        {interactionKinds[activeInteraction.kind].label} · {residueLabel(activeInteraction.residue)} · {activeInteraction.distance.toFixed(2)} Å
      </div>}
      {error && <div className="viewer-error">{error}</div>}
    </div>
  );
}
