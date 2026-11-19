// Zero-event material diagnostic. Run each mode in a fresh process.
// This file has no run manager, physics list, primary generator or BeamOn.
#include "G4NistManager.hh"
#include "G4Material.hh"
#include "G4Element.hh"
#include "G4Isotope.hh"
#include "G4IonisParamMat.hh"
#include "G4SystemOfUnits.hh"
#include "G4Version.hh"
#include "geometry.hh"
#include <cmath>
#include <iomanip>
#include <iostream>
#include <stdexcept>
#include <string>

namespace probe {
// BEGIN CONTRACT_MATERIAL_R2: exact shared density, no default NIST oxide.
G4Material* contract_silicon_dioxide(G4NistManager* n, double density_g_cm3) {
  const G4String name="G4_SILICON_DIOXIDE";
  if (density_g_cm3!=2.2)
    throw std::runtime_error("Material r2 requires the frozen SiO2 density 2.2 g/cm3");
  static G4Material* owned=nullptr;
  auto registered=G4Material::GetMaterial(name,false);
  if (registered && registered!=owned)
    throw std::runtime_error("Contract SiO2 name already registered by another material; no duplicate construction");
  if (!registered && owned)
    throw std::runtime_error("Previously owned contract SiO2 disappeared from the material table");
  auto silicon=n->FindOrBuildElement("Si",true);
  auto oxygen=n->FindOrBuildElement("O",true);
  if (!silicon || !oxygen || silicon->GetNumberOfIsotopes()==0 || oxygen->GetNumberOfIsotopes()==0)
    throw std::runtime_error("Natural NIST Si/O isotope definitions are unavailable");
  if (!owned) {
    owned=new G4Material(name,density_g_cm3*g/cm3,2,kStateSolid);
    owned->AddElement(silicon,1);
    owned->AddElement(oxygen,2);
  }
  std::size_t matches=0;
  for (auto material:*G4Material::GetMaterialTable())
    if (material && material->GetName()==name) ++matches;
  auto elements=owned->GetElementVector();
  auto atoms=owned->GetAtomsVector();
  if (matches!=1 || owned->GetNumberOfElements()!=2 || !atoms ||
      (*elements)[0]!=silicon || (*elements)[1]!=oxygen || atoms[0]!=1 || atoms[1]!=2)
    throw std::runtime_error("Contract SiO2 must be unique and contain natural Si:O atoms exactly 1:2");
  return owned;
}
// END CONTRACT_MATERIAL_R2

}

void dump(const char* mode, const char* origin, const G4Material* material) {
  if (!material) throw std::runtime_error("Missing diagnostic material");
  std::size_t copies=0;
  for (auto value:*G4Material::GetMaterialTable())
    if (value && value->GetName()==material->GetName()) ++copies;
  auto elements=material->GetElementVector();
  auto densities=material->GetVecNbOfAtomsPerVolume();
  auto fractions=material->GetFractionVector();
  double silicon_density=0.;
  for (std::size_t i=0;i<material->GetNumberOfElements();++i)
    if ((*elements)[i]->GetZ()==14.) silicon_density=densities[i];
  if (!(silicon_density>0.)) throw std::runtime_error("Diagnostic material has no silicon");
  std::cout << "MATERIAL mode=" << mode << " origin=" << origin
    << " name=" << material->GetName() << " density_g_cm3=" << material->GetDensity()/(g/cm3)
    << " same_name_registrations=" << copies << " number_elements=" << material->GetNumberOfElements()
    << " mean_excitation_energy_eV=" << material->GetIonisation()->GetMeanExcitationEnergy()/eV
    << " temperature_K=" << material->GetTemperature()/kelvin
    << " pressure_Pa=" << material->GetPressure()/pascal
    << " state=" << static_cast<int>(material->GetState()) << '\n';
  if (copies!=1) throw std::runtime_error("Duplicate diagnostic material registration");
  for (std::size_t i=0;i<material->GetNumberOfElements();++i) {
    auto element=(*elements)[i];
    std::cout << "ELEMENT material=" << material->GetName() << " name=" << element->GetName()
      << " Z=" << element->GetZ() << " atoms_relative_to_Si=" << densities[i]/silicon_density
      << " mass_fraction=" << fractions[i] << " isotope_count=" << element->GetNumberOfIsotopes() << '\n';
    auto abundances=element->GetRelativeAbundanceVector();
    for (std::size_t j=0;j<element->GetNumberOfIsotopes();++j)
      std::cout << "ISOTOPE element=" << element->GetName() << " Z=" << element->GetIsotope(j)->GetZ()
        << " A=" << element->GetIsotope(j)->GetN() << " natural_relative_abundance=" << abundances[j] << '\n';
  }
}

int main(int argc,char** argv) {
  try {
    if (argc!=2) throw std::runtime_error("Usage: material_probe nist|contract|collision");
    const std::string mode=argv[1];
    if (mode!="nist" && mode!="contract" && mode!="collision") throw std::runtime_error("Unknown diagnostic mode");
    const frozen::Solid* oxide=nullptr;
    for (const auto& solid:frozen::solids) if (std::string(solid.material)=="G4_SILICON_DIOXIDE") {
      if (oxide) throw std::runtime_error("Ambiguous oxide in shared geometry");
      oxide=&solid;
    }
    if (!oxide || oxide->density!=2.2) throw std::runtime_error("Missing or changed contract SiO2");
    std::cout << std::setprecision(17) << "MATERIAL_PROBE_R2 geant4_version=" << G4Version
      << " geometry_sha256=" << frozen::geometry_sha256 << " primaries=0 transport_initialization=false\n";
    auto n=G4NistManager::Instance();
    n->FindOrBuildMaterial("G4_Galactic");
    dump(mode.c_str(),"unchanged_NIST",n->FindOrBuildMaterial("G4_Si"));
    if (mode=="nist" || mode=="collision") {
      auto standard=n->FindOrBuildMaterial("G4_SILICON_DIOXIDE");
      dump(mode.c_str(),"default_NIST_definition",standard);
      if (mode=="collision") {
        bool rejected=false;
        try { probe::contract_silicon_dioxide(n,oxide->density); }
        catch (const std::exception& e) {
          rejected=std::string(e.what()).find("already registered")!=std::string::npos;
          std::cout << "EXPECTED_COLLISION_REJECTION " << e.what() << '\n';
        }
        if (!rejected) throw std::runtime_error("Foreign same-name registration was not rejected");
        dump(mode.c_str(),"retained_default_after_rejection",standard);
      }
    } else {
      auto contract=probe::contract_silicon_dioxide(n,oxide->density);
      if (probe::contract_silicon_dioxide(n,oxide->density)!=contract)
        throw std::runtime_error("Repeated own material lookup changed identity");
      dump("contract","explicit_shared_contract_density",contract);
    }
    std::cout << "MATERIAL_PROBE_R2_COMPLETED mode=" << mode << " primaries=0\n";
    return 0;
  } catch (const std::exception& e) {
    std::cerr << "MATERIAL_PROBE_R2_FAILED " << e.what() << '\n';return 2;
  }
}
