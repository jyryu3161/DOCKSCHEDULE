export const interactionKinds: Record<string, { label: string; color: string }> = {
  hydrogen_bond: { label: "수소결합", color: "#3989e8" },
  hydrophobic: { label: "소수성 접촉", color: "#a38336" },
  salt_bridge: { label: "염다리", color: "#ce4f78" },
  pi_stacking: { label: "π–π stacking", color: "#9672dc" },
  cation_pi: { label: "양이온–π", color: "#d97730" },
  halogen_bond: { label: "할로젠 결합", color: "#199b8e" },
};

export interface InteractionAtom {
  index: number | null;
  number: number | null;
  label: string;
  element: string;
  position: number[];
}

export interface PoseInteraction {
  id: string;
  kind: string;
  type: string;
  role: string;
  residue: { key: string; name: string; chain: string; number: number; insertion: string; atom_indices: number[] };
  ligand_atoms: InteractionAtom[];
  protein_atoms: InteractionAtom[];
  ligand_position: number[];
  protein_position: number[];
  distance: number;
  angles: Record<string, number>;
}

export interface InteractionReport {
  engine: string;
  engine_version: string;
  interactions: PoseInteraction[];
  warnings: string[];
}

export const residueLabel = (r: PoseInteraction["residue"]) =>
  `${r.chain || "(빈 chain)"}:${r.name} ${r.number}${r.insertion}`;
