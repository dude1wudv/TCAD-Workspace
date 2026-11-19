// Geant4 Boolean solids in the same physical x,y,z_depth frame as SDE.
// GateVoid remains vacuum: the electrical ideal-metal boundary has no
// specified transport metal. This limitation is recorded in the contract.
class Geometry : public G4VUserDetectorConstruction {
  static G4VSolid* box(const char* name,const std::array<double,3>& lo,
                       const std::array<double,3>& hi) {
    auto raw=new G4Box(name,(hi[0]-lo[0])*um/2,(hi[1]-lo[1])*um/2,(hi[2]-lo[2])*um/2);
    return new G4DisplacedSolid(std::string(name)+"_at",raw,nullptr,
      G4ThreeVector((hi[0]+lo[0])*um/2,(hi[1]+lo[1])*um/2,(hi[2]+lo[2])*um/2));
  }
  static G4VSolid* round_bottom(const char* name,double radius,double half_y,
                                double top,double centre_z) {
    auto rectangle=box((std::string(name)+"_rectangle").c_str(),
      {{-radius,-half_y,top}},{{radius,half_y,centre_z}});
    auto cylinder=new G4Tubs(std::string(name)+"_circle",0,radius*um,half_y*um,0,360*deg);
    auto rotation=new G4RotationMatrix; rotation->rotateX(90*deg);
    auto moved=new G4DisplacedSolid(std::string(name)+"_circle_at",cylinder,rotation,
                                    G4ThreeVector(0,0,centre_z*um));
    // The upper cylinder half is entirely inside the rectangle.
    return new G4UnionSolid(name,rectangle,moved);
  }
public:
  G4VPhysicalVolume* Construct() override {
    auto n=G4NistManager::Instance();
    auto vacuum=n->FindOrBuildMaterial("G4_Galactic");
    auto silicon=n->FindOrBuildMaterial("G4_Si");
    auto oxide=contract_silicon_dioxide(n,2.2);
    auto world=new G4LogicalVolume(new G4Box("World",frozen::world_half_um[0]*um,
      frozen::world_half_um[1]*um,frozen::world_half_um[2]*um),vacuum,"World");
    auto root=new G4PVPlacement(nullptr,{},world,"World",nullptr,false,0);
    auto domain=box("Domain",frozen::domain_lo,frozen::domain_hi);
    auto trench=round_bottom("TrenchOuter",frozen::outer_radius,frozen::outer_half_y,0,frozen::centre_z);
    auto gate=round_bottom("GateVoid",frozen::metal_radius,frozen::metal_half_y,frozen::gate_top,frozen::centre_z);
    auto minus=box("STIMinus",{{frozen::domain_lo[0],-frozen::outer_half_y,0}},
                   {{frozen::domain_hi[0],-frozen::active_half_y,frozen::sti_depth}});
    auto plus=box("STIPlus",{{frozen::domain_lo[0],frozen::active_half_y,0}},
                  {{frozen::domain_hi[0],frozen::outer_half_y,frozen::sti_depth}});
    auto no_trench=new G4SubtractionSolid("SiMinusTrench",domain,trench);
    auto no_minus=new G4SubtractionSolid("SiMinusTrenchSTIMinus",no_trench,minus);
    std::vector<G4VSolid*> solids{
      new G4SubtractionSolid("R.Silicon",no_minus,plus),
      new G4SubtractionSolid("R.Trench",trench,gate),
      new G4SubtractionSolid("R.STI.minus",minus,trench),
      new G4SubtractionSolid("R.STI.plus",plus,trench)};
    Csv actual("geometry-built.csv","volume,material,min_x_um,min_y_um,min_z_um,max_x_um,max_y_um,max_z_um,density_g_cm3,charged_max_step_um,overlap_check_passed");
    actual.row({"World","G4_Galactic",number(-frozen::world_half_um[0]),number(-frozen::world_half_um[1]),number(-frozen::world_half_um[2]),
      number(frozen::world_half_um[0]),number(frozen::world_half_um[1]),number(frozen::world_half_um[2]),number(vacuum->GetDensity()/(g/cm3)),"","1"});
    for(std::size_t i=0;i<solids.size();++i) {
      auto material=i==0?silicon:oxide;
      if(std::abs(material->GetDensity()/(g/cm3)-frozen::solids[i].density)>1e-9)
        throw std::runtime_error("BCAT native material density mismatch");
      auto logical=new G4LogicalVolume(solids[i],material,frozen::solids[i].id);
      logical->SetUserLimits(new G4UserLimits(frozen::max_step_um*um));
      auto physical=new G4PVPlacement(nullptr,{},logical,frozen::solids[i].id,world,false,int(i));
      const bool overlap=physical->CheckOverlaps(1000,0.,true);
      G4ThreeVector lo,hi; solids[i]->BoundingLimits(lo,hi);
      actual.row({frozen::solids[i].id,material->GetName(),number(lo.x()/um),number(lo.y()/um),number(lo.z()/um),
        number(hi.x()/um),number(hi.y()/um),number(hi.z()/um),number(material->GetDensity()/(g/cm3)),number(frozen::max_step_um),integer(!overlap)});
      actual.flush();
      if(overlap) throw std::runtime_error("BCAT native overlap check failed");
    }
    std::ifstream probes("geometry-probes.tsv");
    if(!probes) throw std::runtime_error("Missing independent material probes");
    Csv measured("geometry-probes-native.csv","x_um,y_um,z_um,expected_material,native_material,native_interiors,passed");
    double x,y,z;std::string expected;
    while(probes>>x>>y>>z>>expected) {
      std::string found="G4_Galactic";int interiors=0;
      for(std::size_t i=0;i<solids.size();++i) {
        const auto inside=solids[i]->Inside(G4ThreeVector(x*um,y*um,z*um));
        if(inside==kSurface) throw std::runtime_error("Material probe unexpectedly on native boundary");
        if(inside==kInside) {++interiors;found=frozen::solids[i].material;}
      }
      const bool passed=interiors<=1 && found==expected;
      measured.row({number(x),number(y),number(z),expected,found,integer(interiors),integer(passed)});
      measured.flush();
      if(!passed) throw std::runtime_error("BCAT independent material probe mismatch");
    }
    if(!probes.eof()) throw std::runtime_error("Malformed material probe input");
    return root;
  }
};
