# Third party components and sample data

QuickVina 2.1 is downloaded from the [official QuickVina repository](https://github.com/QVina/qvina) at commit `f4bb3b1073a0d50bb2f1fdd14d38594f937602ee`. Its Apache 2.0 license is included in `third_party/quickvina/LICENSE`. The installer verifies the binary SHA256. QuickVina should be cited as Alhossary et al., *Fast, Accurate, and Reliable Molecular Docking with QuickVina 2*, Bioinformatics (2015), DOI: 10.1093/bioinformatics/btv082.

The protein fixture `tests/fixtures/1L83.pdb` is the public [RCSB PDB entry 1L83](https://www.rcsb.org/structure/1L83), downloaded from `https://files.rcsb.org/download/1L83.pdb`. It is used for preparation, docking integration, and interface validation. These checks do not establish prospective screening accuracy.

The throughput script reads RDKit's bundled `Data/NCI/first_5K.smi` example dataset and records the selected structures in its output. It does not use student data.

Python and JavaScript dependency versions are locked in `uv.lock` and `frontend/package-lock.json`. Their license files are retained in the installed packages. The molecular viewer is NGL. Protein preparation uses PDBFixer/OpenMM and Open Babel; ligand preparation uses RDKit and Meeko.

Pose interaction analysis uses [ProLIF](https://github.com/chemosim-lab/ProLIF) (Apache 2.0) and MDAnalysis (LGPL 2.1 or later). ProLIF's interaction metadata is rendered with the existing NGL viewer. See Bouysset and Fiorucci, *ProLIF: a library to encode molecular interactions as fingerprints*, Journal of Cheminformatics (2021), [DOI: 10.1186/s13321-021-00548-6](https://doi.org/10.1186/s13321-021-00548-6).

`tests/fixtures/interaction-pose.sdf` was generated locally with the existing preparation/QuickVina pipeline from `C[C@H](O)c1ccccc1` and the 1L83 fixture (chain A, pH 7.4, center 26.929/6.158/4.216 Å, box 20 Å, seed 42, one conformer, exhaustiveness 1). It is a browser test asset; the browser tests mock the analysis API. Separate Python tests run real ProLIF and real preparation/docking.
