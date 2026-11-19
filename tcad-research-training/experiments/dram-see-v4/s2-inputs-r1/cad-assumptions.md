# S2 CAD implementation decisions

Status: offline implementation; no native SDE, mesh, solver, transport, or training call.
This ledger is written before the implementation it governs. Original r13 values remain in
`course-plan-r13/model-contract.proposed.json`; these entries complete the implementation
and must be read with the main `implement-stage/ASSUMPTIONS.md` ledger.

| ID | Missing implementation detail | Decision before code | Evidence / status |
|---|---|---|---|
| CAD001 | Exact rounded bottom construction | Use rectangle plus circle in 2D, cuboid plus circular cylinder in 3D, then Boolean union. Both solids use the r13 center at 142 nm; outer radius 12 nm and metal radius 8 nm. No polygonal approximation and no rectangle substituted for the rounded bottom. | SDE W-2024.09 pp. 613, 621, 625-626; engineering implementation |
| CAD002 | Trench material above buried gate | Outer trench extends from surface z=0 through the rounded bottom at 154 nm and is SiO2 before the temporary metal replaces its interior from z=80 to 150 nm. Thus z=0 to 80 nm is an oxide cap. | r13 buried-gate interpretation plus explicit engineering completion |
| CAD003 | Finite-width gate end caps | Outer trench is y=+-60 nm; metal is y=+-56 nm. The 4 nm oxide end caps prevent gate metal contacting exterior Si at the STI boundary. Main Agent accepted this and updated A002 before dependent implementation. | Main Agent message; main A002 |
| CAD004 | CAD material identifiers | Use installed standard SDE material strings Silicon, SiO2, and Metal. Metal exists only temporarily; its complete boundary is marked gate and the body is removed. No metal transport material is inferred. | SDE examples pp. 232-233; DATEX identifiers require later native audit |
| CAD005 | Boolean ordering and shared faces | Use ABA (new replaces old); create Si, STI, rounded outer trench, rounded metal. Unite the rectangle and round pieces before inserting the next nested material. Contact imprinting occurs after the semiconductor/dielectric topology is complete. | SDE pp. 142-143, 232-235, 613 |
| CAD006 | Source/drain contact segmentation | 2D: insert vertices at each contact endpoint and locate the unique center edge. 3D: imprint the published-contract rectangle at z=0 and require one returned face and one matching center face. All probes must be unique; gate body must be uniquely located before removal and gate boundary probes cover every expected geometric surface after removal. | SDE pp. 232, 235, 328, 393-394, 604, 679-680 |
| CAD007 | Exact mixed Gaussian implementation | One General analytic function in absolute device coordinates, z for 3D and y for the 2D depth coordinate. Arsenic donors and uniform Boron acceptors are restricted to Silicon, with zero decay outside material. The required formula failure value is -1 cm^-3 as an explicitly invalid sentinel; future native concentration audit must reject negative/nonfinite/mismatched samples. | SDE pp. 552-554, 557; Smesh pp. 24-25, 37-39 |
| CAD008 | Mesh windows and resource meaning | Far bulk maximum 40 nm; all near-junction silicon (z<=160 nm) and a +-4w bounding box around the normal alpha track use maximum 5 nm. Gate-oxide bounding box plus 1 nm halo uses maximum 1 nm. All Si/SiO2 interfaces additionally use a separate definition with MaxLenInt=1 nm, factor=1.5, DoubleSide and minimum 0.5 nm. Other minimum sizes equal half each local maximum; mesh_scale multiplies both. Controls are requests, not measured native edges or a resource prediction. | r13 numerics plus explicit local-window completion; SDE pp. 252-253, 570-574 |
| CAD009 | Native mesh resource guard | After the existing build-mesh call, invoke /usr/bin/python3 mesh_resource_guard.py; nonzero status raises sde:error. Main Agent supplies the same-directory adapter. No new runner or mesh execution is added here. | Existing source-interface-3d-r1 path and Main Agent instruction |
| CAD010 | 2D and 3D meaning | 2D is exactly the y=0 x-z center section with no STI bodies; (x,z_depth) maps to SDE(x,y). 3D keeps physical x,y,z_depth. 2D AreaFactor=0.02 belongs to the device deck; it is not a geometric replication or an asserted 3D equivalence. | main A004 |

All choices are same-family/provisional. The installed manual establishes supported command
forms, not successful execution of this particular geometry. Native topology, material IDs,
analytic formula evaluation, doping, contact inventory, oxide thickness, native mesh quality,
node count, and resources remain unverified. No native execution is authorized by this file.
