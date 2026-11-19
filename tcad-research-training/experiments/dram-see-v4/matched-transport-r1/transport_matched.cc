// Geant4 10.7.3 geometry-matched three-dimensional transport pilot. No TCAD mapping or user track killing.
#include "G4RunManager.hh"
#include "G4VUserDetectorConstruction.hh"
#include "G4VModularPhysicsList.hh"
#include "G4VPhysicsConstructor.hh"
#include "G4EmStandardPhysics_option4.hh"
#include "QGSP_BIC.hh"
#include "G4StepLimiterPhysics.hh"
#include "G4VUserPrimaryGeneratorAction.hh"
#include "G4UserEventAction.hh"
#include "G4UserTrackingAction.hh"
#include "G4UserSteppingAction.hh"
#include "G4UserStackingAction.hh"
#include "G4ParticleGun.hh"
#include "G4ParticleTable.hh"
#include "G4ParticleDefinition.hh"
#include "G4ProcessManager.hh"
#include "G4ProcessVector.hh"
#include "G4VProcess.hh"
#include "G4HadronicProcess.hh"
#include "G4HadronicInteraction.hh"
#include "G4NeutronKiller.hh"
#include "G4NistManager.hh"
#include "G4Material.hh"
#include "G4Element.hh"
#include "G4ProductionCuts.hh"
#include "G4ProductionCutsTable.hh"
#include "G4MaterialCutsCouple.hh"
#include "G4Box.hh"
#include "G4LogicalVolume.hh"
#include "G4PVPlacement.hh"
#include "G4SystemOfUnits.hh"
#include "G4UserLimits.hh"
#include "G4Event.hh"
#include "G4PrimaryVertex.hh"
#include "G4Track.hh"
#include "G4DynamicParticle.hh"
#include "G4Step.hh"
#include "G4StepPoint.hh"
#include "G4Version.hh"
#include "Randomize.hh"
#include <algorithm>
#include <cerrno>
#include <chrono>
#include <ctime>
#include "geometry.hh"
#include <cmath>
#include <cstdlib>
#include <fstream>
#include <iomanip>
#include <limits>
#include <map>
#include <memory>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>
#include <fcntl.h>
#include <unistd.h>

namespace probe {
using Row = std::vector<std::string>;

std::string number(double x) {
  if (!std::isfinite(x)) throw std::runtime_error("Nonfinite output value");
  std::ostringstream s; s << std::setprecision(17) << x; return s.str();
}
std::string integer(long long x) { return std::to_string(x); }
std::string boolean(bool b) { return b ? "true" : "false"; }
std::string quote(const std::string& value) {
  std::string result = "\"";
  for (unsigned char c : value) {
    if (c == '"' || c == '\\') { result += '\\'; result += char(c); }
    else if (c == '\n') result += "\\n";
    else if (c == '\r') result += "\\r";
    else if (c == '\t') result += "\\t";
    else if (c < 32) {
      const char* hex = "0123456789abcdef";
      result += "\\u00"; result += hex[c >> 4]; result += hex[c & 15];
    } else result += char(c);
  }
  return result + '"';
}
std::string object(const std::vector<std::pair<std::string,std::string>>& fields) {
  std::string result = "{";
  for (std::size_t i = 0; i < fields.size(); ++i) {
    if (i) result += ',';
    result += '\n' + quote(fields[i].first) + ':' + fields[i].second;
  }
  return result + "\n}";
}
std::string vector_json(const G4ThreeVector& v, double unit) {
  return "[" + number(v.x()/unit) + "," + number(v.y()/unit) + "," + number(v.z()/unit) + "]";
}
void write_json(const char* file, const std::string& text) {
  std::ofstream out; out.exceptions(std::ios::badbit | std::ios::failbit);
  out.open(file); out << text << '\n'; out.close();
}
struct Csv {
  std::ofstream out;
  std::size_t columns;
  Csv(const char* filename, const std::string& header)
      : columns(1 + std::count(header.begin(), header.end(), ',')) {
    out.exceptions(std::ios::badbit | std::ios::failbit);
    out.open(filename); out << header << '\n'; out.flush();
  }
  void row(const Row& fields) {
    if (fields.size() != columns) throw std::runtime_error("CSV column contract mismatch");
    for (std::size_t i = 0; i < fields.size(); ++i) {
      if (i) out << ',';
      out << '"';
      for (char c : fields[i]) { if (c == '"') out << '"'; out << c; }
      out << '"';
    }
    out << '\n';
  }
  void flush() { out.flush(); }
};

struct Config {
  std::string label, mode, arm;
  double energy=100., angle=0.;
  int seed=0, events=0;
  const frozen::Request* request=nullptr;
  G4ThreeVector surface() const { const auto& v=request->surface; return {v[0]*um,v[1]*um,v[2]*um}; }
  G4ThreeVector position() const { const auto& v=request->position; return {v[0]*um,v[1]*um,v[2]*um}; }
  G4ThreeVector direction() const { return {0.,1.,0.}; }
};
Config parse(int argc, char** argv) {
  if (argc!=2) throw std::runtime_error("Usage: transport_matched FROZEN_REQUEST_LABEL");
  for (const auto& r:frozen::requests) if (r.label==std::string(argv[1])) {
    Config c; c.label=r.label; c.mode=r.mode; c.arm=r.arm; c.seed=r.seed; c.events=r.events; c.request=&r;
    return c;
  }
  throw std::runtime_error("Request not in the six-call frozen contract");
}
std::map<std::string,std::string> declared_volumes() {
  std::map<std::string,std::string> result{{"World","G4_Galactic"}};
  for (const auto& s:frozen::solids) result.emplace(s.id,s.material);
  return result;
}
std::set<std::string> declared_materials() {
  std::set<std::string> result;
  for (const auto& v:declared_volumes()) result.insert(v.second);
  return result;
}
void reserve() {
  const char* outputs[] = {"metadata.json","status.json","status-history.jsonl","events.csv",
    "tracks.csv","steps.csv","birth-links.csv","constructors.csv","processes.csv","hadronic-models.csv",
    "materials.csv","elements.csv","cuts.csv","particles.csv","geometry-built.csv","material-energy.csv","timings.csv"};
  for (const char* file : outputs) {
    std::ifstream prior(file);
    if (prior.good()) throw std::runtime_error("Existing output; use a new run directory");
  }
  int fd=::open("matched-reservation.lock",O_CREAT|O_EXCL|O_WRONLY,0600);
  if (fd < 0) throw std::runtime_error("Run directory reservation failed; never resume by rerunning");
  ::close(fd); // Reservation deliberately survives success and failure.
}

class Geometry : public G4VUserDetectorConstruction {
public:
  G4VPhysicalVolume* Construct() override {
    auto n=G4NistManager::Instance();
    auto world=new G4LogicalVolume(new G4Box("World",frozen::world_half_um[0]*um,
      frozen::world_half_um[1]*um,frozen::world_half_um[2]*um),n->FindOrBuildMaterial("G4_Galactic"),"World");
    auto root=new G4PVPlacement(nullptr,{},world,"World",nullptr,false,0);
    Csv actual("geometry-built.csv","volume,material,min_x_um,min_y_um,min_z_um,max_x_um,max_y_um,max_z_um,density_g_cm3,charged_max_step_um,overlap_check_passed");
    actual.row({"World","G4_Galactic",number(-frozen::world_half_um[0]),number(-frozen::world_half_um[1]),number(-frozen::world_half_um[2]),
      number(frozen::world_half_um[0]),number(frozen::world_half_um[1]),number(frozen::world_half_um[2]),number(world->GetMaterial()->GetDensity()/(g/cm3)),"","1"});
    int copy=0;
    for (const auto& s:frozen::solids) {
      G4ThreeVector centre,half;
      for (int i=0;i<3;++i) { centre[i]=.5*(s.lo[i]+s.hi[i])*um; half[i]=.5*(s.hi[i]-s.lo[i])*um; }
      auto material=n->FindOrBuildMaterial(s.material);
      if (!material || std::abs(material->GetDensity()/(g/cm3)-s.density)>1e-9)
        throw std::runtime_error("Shared contract and native NIST material density differ");
      auto logical=new G4LogicalVolume(new G4Box(s.id,half.x(),half.y(),half.z()),material,s.id);
      logical->SetUserLimits(new G4UserLimits(.02*um));
      auto physical=new G4PVPlacement(nullptr,centre,logical,s.id,world,false,copy++);
      bool overlap=physical->CheckOverlaps(1000,0.,true);
      actual.row({s.id,s.material,number(s.lo[0]),number(s.lo[1]),number(s.lo[2]),number(s.hi[0]),number(s.hi[1]),number(s.hi[2]),
        number(material->GetDensity()/(g/cm3)),"0.02",integer(!overlap)});
      actual.flush();
      if (overlap) throw std::runtime_error("Native Geant4 overlap check failed; geometry retained");
    }
    return root;
  }
};
class Electromagnetic : public G4VModularPhysicsList {
public:
  Electromagnetic() { RegisterPhysics(new G4EmStandardPhysics_option4(1)); }
  void SetCuts() override { SetCutsWithDefault(); }
};
G4VModularPhysicsList* physics(const Config& c) {
  G4VModularPhysicsList* p=nullptr;
  if (c.arm == "H") {
    p=new QGSP_BIC(1);
    p->ReplacePhysics(new G4EmStandardPhysics_option4(1));
    // Keep the reference-list neutronTrackingCut. No custom track kill is added.
  } else p=new Electromagnetic;
  auto limiter=new G4StepLimiterPhysics;
  limiter->SetApplyToAll(false);
  p->RegisterPhysics(limiter);
  p->SetDefaultCutValue(.01*um);
  return p;
}
class Beam : public G4VUserPrimaryGeneratorAction {
  Config c; G4ParticleGun gun;
public:
  explicit Beam(const Config& config):c(config),gun(1) {}
  void GeneratePrimaries(G4Event* event) override {
    if (c.mode=="init") throw std::runtime_error("Primary generation forbidden in initialization-only mode");
    auto proton=G4ParticleTable::GetParticleTable()->FindParticle("proton");
    if (!proton) throw std::runtime_error("Missing proton definition");
    gun.SetParticleDefinition(proton); gun.SetParticleEnergy(c.energy*MeV);
    gun.SetParticlePosition(c.position()); gun.SetParticleMomentumDirection(c.direction());
    gun.SetParticleTime(0.); gun.GeneratePrimaryVertex(event);
  }
};

struct Energy {
  double edep=0., niel=0., ion=0.;
  void add(double e, double n, double i) { edep+=e; niel+=n; ion+=i; }
  void append(Row& row) const { row.push_back(number(edep)); row.push_back(number(niel)); row.push_back(number(ion)); }
};
struct TrackRecord {
  Row birth;
  Energy all, si;
  std::map<std::string,Energy> materials;
  std::map<std::string,long long> material_steps;
  long long steps=0;
  bool cut=false, ended=false, hadronic_seen=false, lineage_hadronic=false;
  bool direct_hadronic=false, em_from_lineage=false, em_after_primary=false, em_transition=false;
  std::string token="primary";
  int parent_step=0;
};
struct BirthLink {
  std::string token;
  int parent=0, step=0, ordinal=0, child=0;
  bool parent_before=false, parent_after=false;
  const G4VProcess* creator=nullptr;
};
struct EventRecord {
  int id=-1, primary_count=0;
  long long track_count=0, step_count=0, si_steps=0, world_steps=0;
  long long hadronic_steps=0, primary_hadronic_steps=0, first_hadronic_step=0;
  long long neutron_cut_steps=0, neutron_cut_tracks=0;
  bool primary_hadronic_seen=false;
  std::string first_hadronic_process="none";
  double first_hadronic_time=-1., primary_before=0., primary_after=0., nonprimary=0.;
  Energy all, si, world;
  std::map<std::string,Energy> materials;
  std::map<std::string,long long> material_steps;
};
struct Data {
  Config c;
  Csv events, tracks, steps, constructors, processes, models, materials, elements, cuts, births, particles, material_energy, timings;
  std::map<const G4Track*,BirthLink> pending_births;
  std::map<int,BirthLink> bound_births;
  EventRecord event;
  std::map<int,TrackRecord> track;
  long long completed_events=0, completed_tracks=0, recorded_steps=0;
  bool initialized=false, beam_on_called=false, zero_event_beam_on_called=false;
  bool nonzero_event_beam_on_called=false, physics_tables_built=false;
  explicit Data(const Config& config):c(config),
    events("events.csv","event_id,primary_count,track_count,step_count,si_step_count,world_step_count,edep_all_MeV,niel_all_MeV,ionizing_all_MeV,edep_si_MeV,niel_si_MeV,ionizing_si_MeV,edep_world_MeV,niel_world_MeV,ionizing_world_MeV,hadronic_step_count,primary_hadronic_step_count,primary_first_hadronic_step,primary_first_hadronic_process,primary_first_hadronic_t_ns,si_ionizing_primary_before_hadronic_MeV,si_ionizing_primary_at_or_after_hadronic_MeV,si_ionizing_nonprimary_MeV,neutron_tracking_cut_steps,neutron_tracking_cut_tracks,zero_si_ionizing,event_complete"),
    tracks("tracks.csv","event_id,track_id,parent_id,particle,pdg,charge_e,Z,A,mass_MeV,creator_process,creator_type,creator_subtype,birth_ke_MeV,birth_x_um,birth_y_um,birth_z_um,birth_dx,birth_dy,birth_dz,birth_t_ns,birth_volume,birth_material,end_ke_MeV,end_x_um,end_y_um,end_z_um,end_dx,end_dy,end_dz,end_t_ns,end_volume,end_material,track_length_um,step_count,edep_all_MeV,niel_all_MeV,ionizing_all_MeV,edep_si_MeV,niel_si_MeV,ionizing_si_MeV,end_track_status,ended_by_neutron_tracking_cut,birth_token,parent_step_id,direct_hadronic_child,creator_lineage_hadronic,em_from_hadronic_lineage,em_from_post_hadronic_primary,em_in_primary_hadronic_transition_step,termination_process,termination_process_type,termination_process_subtype,termination_reason"),
    steps("steps.csv","event_id,track_id,parent_id,step_id,particle,pdg,pre_x_um,pre_y_um,pre_z_um,pre_dx,pre_dy,pre_dz,pre_ke_MeV,pre_t_ns,pre_volume,pre_material,post_x_um,post_y_um,post_z_um,post_dx,post_dy,post_dz,post_ke_MeV,post_t_ns,post_volume,post_material,step_um,edep_MeV,niel_MeV,ionizing_MeV,post_process,post_process_type,post_process_subtype,primary_hadronic_seen_before,primary_hadronic_seen_after,neutron_tracking_cut_step,pre_step_status,post_step_status,chord_um,deposit_kind,local_ionizing_MeV_per_um,track_hadronic_before,track_hadronic_after,secondary_count"),
    constructors("constructors.csv","phase,index,name,physics_type"),
    processes("processes.csv","phase,particle,pdg,process_index,process,process_type,process_subtype,hadronic_model_count,is_neutron_killer"),
    models("hadronic-models.csv","phase,particle,pdg,process,model_index,model,min_energy_MeV,max_energy_MeV"),
    materials("materials.csv","phase,material,density_g_cm3,temperature_K,pressure_Pa,state,number_elements"),
    elements("elements.csv","phase,material,element,Z,A_g_mol,mass_fraction,atom_density_cm3"),
    cuts("cuts.csv","phase,couple_index,material,particle,range_cut_um,energy_cut_MeV,energy_cut_available"),
    births("birth-links.csv","event_id,birth_token,parent_track_id,parent_step_id,secondary_ordinal,child_track_id,creator_process,creator_type,creator_subtype,parent_hadronic_before,parent_hadronic_after"),
    particles("particles.csv","phase,particle,pdg,Z,A,particle_type,particle_subtype,has_process_manager,process_count"),
    material_energy("material-energy.csv","scope,event_id,track_id,material,step_count,edep_MeV,niel_MeV,ionizing_MeV"),
    timings("timings.csv","phase,wall_seconds,cpu_seconds,events,tracks,steps") {}
  void ledger(const std::string& scope, int track_id, const std::map<std::string,Energy>& values,
              const std::map<std::string,long long>& counts) {
    for (const auto& material:declared_materials()) {
      auto value=values.find(material); auto count=counts.find(material);
      Row row{scope,integer(event.id),integer(track_id),material,integer(count==counts.end()?0:count->second)};
      (value==values.end()?Energy():value->second).append(row); material_energy.row(row);
    }
  }
  void status(const std::string& state, const std::string& error="") {
    auto text=object({{"schema",quote("v4-matched-transport-status-r1")},{"state",quote(state)},
      {"events_requested",integer(c.events)},{"events_completed",integer(completed_events)},
      {"tracks_completed",integer(completed_tracks)},{"steps_recorded",integer(recorded_steps)},
      {"beam_on_called",boolean(beam_on_called)},{"initialized",boolean(initialized)},
      {"zero_event_beam_on_called",boolean(zero_event_beam_on_called)},
      {"nonzero_event_beam_on_called",boolean(nonzero_event_beam_on_called)},
      {"physics_tables_built",boolean(physics_tables_built)},
      {"error",error.empty()?"null":quote(error)}});
    write_json("status.json",text);
    std::ofstream history; history.exceptions(std::ios::badbit|std::ios::failbit);
    history.open("status-history.jsonl",std::ios::app);
    std::string compact=text; compact.erase(std::remove(compact.begin(),compact.end(),'\n'),compact.end());
    history << compact << '\n'; history.close();
  }
  void flush() {
    events.flush(); tracks.flush(); steps.flush(); constructors.flush(); processes.flush();
    models.flush(); materials.flush(); elements.flush(); cuts.flush(); births.flush();
    particles.flush(); material_energy.flush(); timings.flush();
  }
};
std::string volume_name(const G4VPhysicalVolume* v) { return v ? std::string(v->GetName()) : "OUTSIDE"; }
std::string material_name(const G4Material* m) { return m ? std::string(m->GetName()) : "NONE"; }
void append_vector(Row& row, const G4ThreeVector& v, double unit) {
  row.push_back(number(v.x()/unit)); row.push_back(number(v.y()/unit)); row.push_back(number(v.z()/unit));
}
void append_process(Row& row, const G4VProcess* p) {
  row.push_back(p?std::string(p->GetProcessName()):"none");
  row.push_back(integer(p?static_cast<int>(p->GetProcessType()):-1));
  row.push_back(integer(p?p->GetProcessSubType():-1));
}
void append_track_state(Row& row, const G4Track* t, const G4VPhysicalVolume* v, const G4Material* m) {
  row.push_back(number(t->GetKineticEnergy()/MeV)); append_vector(row,t->GetPosition(),um);
  append_vector(row,t->GetMomentumDirection(),1.); row.push_back(number(t->GetGlobalTime()/ns));
  row.push_back(volume_name(v)); row.push_back(material_name(m));
}
void append_step_point(Row& row, const G4StepPoint* p) {
  append_vector(row,p->GetPosition(),um); append_vector(row,p->GetMomentumDirection(),1.);
  row.push_back(number(p->GetKineticEnergy()/MeV)); row.push_back(number(p->GetGlobalTime()/ns));
  auto v=p->GetPhysicalVolume(); row.push_back(volume_name(v));
  row.push_back(v?material_name(p->GetMaterial()):"NONE");
}

class Events : public G4UserEventAction {
  Data& d;
public:
  explicit Events(Data& data):d(data) {}
  void BeginOfEventAction(const G4Event* event) override {
    d.event=EventRecord(); d.event.id=event->GetEventID(); d.track.clear();
    d.pending_births.clear(); d.bound_births.clear();
    for (int i=0;i<event->GetNumberOfPrimaryVertex();++i)
      d.event.primary_count+=event->GetPrimaryVertex(i)->GetNumberOfParticle();
    if (d.event.primary_count != 1) throw std::runtime_error("Expected exactly one primary");
  }
  void EndOfEventAction(const G4Event* event) override {
    auto& e=d.event;
    bool complete=!event->IsAborted();
    for (const auto& pair:d.track) if (!pair.second.ended) complete=false;
    if (!d.pending_births.empty() || d.bound_births.size()+1!=d.track.size()) complete=false;
    Row row={integer(e.id),integer(e.primary_count),integer(e.track_count),integer(e.step_count),integer(e.si_steps),integer(e.world_steps)};
    e.all.append(row); e.si.append(row); e.world.append(row);
    row.insert(row.end(),{integer(e.hadronic_steps),integer(e.primary_hadronic_steps),integer(e.first_hadronic_step),
      e.first_hadronic_process,number(e.first_hadronic_time),number(e.primary_before),number(e.primary_after),number(e.nonprimary),
      integer(e.neutron_cut_steps),integer(e.neutron_cut_tracks),integer(e.si.ion==0.),integer(complete)});
    d.events.row(row); d.ledger("event",0,e.materials,e.material_steps); d.flush();
    if (!complete) throw std::runtime_error("Incomplete or aborted event retained");
    ++d.completed_events;
    G4cout << "EVENT_COMPLETED event=" << e.id << " tracks=" << e.track_count << " steps=" << e.step_count << G4endl;
  }
};
class Stacking : public G4UserStackingAction {
  Data& d;
public:
  explicit Stacking(Data& data):d(data) {}
  G4ClassificationOfNewTrack ClassifyNewTrack(const G4Track* t) override {
    if (t->GetParentID()==0) return fUrgent;
    auto found=d.pending_births.find(t);
    if (found==d.pending_births.end()) {
      // A suspended track may be stacked again; its original binding survives.
      if (d.track.count(t->GetTrackID()) && d.bound_births.count(t->GetTrackID())) return fUrgent;
      throw std::runtime_error("Secondary has no exact current-step birth token");
    }
    BirthLink link=found->second;
    if (t->GetTrackID()<=0 || link.parent!=t->GetParentID() || link.creator!=t->GetCreatorProcess())
      throw std::runtime_error("Secondary object binding disagrees with assigned track/parent/creator");
    link.child=t->GetTrackID();
    if (!d.bound_births.emplace(link.child,link).second) throw std::runtime_error("Duplicate child track binding");
    Row row={integer(d.event.id),link.token,integer(link.parent),integer(link.step),integer(link.ordinal),integer(link.child)};
    append_process(row,link.creator);
    row.insert(row.end(),{integer(link.parent_before),integer(link.parent_after)});
    d.births.row(row); d.pending_births.erase(found);
    return fUrgent; // No filter, kill, postponement, weight or biasing.
  }
};
class Tracking : public G4UserTrackingAction {
  Data& d;
public:
  explicit Tracking(Data& data):d(data) {}
  void PreUserTrackingAction(const G4Track* t) override {
    auto found=d.track.find(t->GetTrackID());
    if (found!=d.track.end()) {
      if (found->second.ended) throw std::runtime_error("Tracking resumed after final track record");
      return; // Preserve birth and accumulated steps if Geant4 resumes a suspended track.
    }
    TrackRecord record;
    if (t->GetParentID()!=0) {
      const auto& link=d.bound_births.at(t->GetTrackID());
      const auto& parent=d.track.at(t->GetParentID());
      auto creator=t->GetCreatorProcess();
      record.token=link.token; record.parent_step=link.step;
      record.direct_hadronic=creator && creator->GetProcessType()==fHadronic;
      record.lineage_hadronic=record.direct_hadronic || parent.lineage_hadronic;
      bool em=creator && creator->GetProcessType()==fElectromagnetic;
      record.em_from_lineage=em && parent.lineage_hadronic;
      record.em_after_primary=em && t->GetParentID()==1 && link.parent_before;
      record.em_transition=em && t->GetParentID()==1 && !link.parent_before && link.parent_after;
    }
    auto p=t->GetDefinition();
    record.birth={integer(d.event.id),integer(t->GetTrackID()),integer(t->GetParentID()),p->GetParticleName(),
      integer(p->GetPDGEncoding()),number(t->GetDynamicParticle()->GetCharge()/eplus),integer(p->GetAtomicNumber()),
      integer(p->GetAtomicMass()),number(t->GetDynamicParticle()->GetMass()/MeV)};
    append_process(record.birth,t->GetCreatorProcess());
    auto v=t->GetVolume();
    append_track_state(record.birth,t,v,v?v->GetLogicalVolume()->GetMaterial():nullptr);
    d.track.emplace(t->GetTrackID(),record); ++d.event.track_count;
  }
  void PostUserTrackingAction(const G4Track* t) override {
    auto& record=d.track.at(t->GetTrackID());
    if (t->GetTrackStatus()==fSuspend) return;
    if (t->GetTrackStatus()==fPostponeToNextEvent) throw std::runtime_error("Postponed track crosses event contract");
    if (record.ended) throw std::runtime_error("Duplicate final track record");
    Row row=record.birth;
    const G4StepPoint* post=t->GetStep()?t->GetStep()->GetPostStepPoint():nullptr;
    const G4VPhysicalVolume* v=post?post->GetPhysicalVolume():t->GetVolume();
    const G4Material* m=v?(post?post->GetMaterial():v->GetLogicalVolume()->GetMaterial()):nullptr;
    append_track_state(row,t,v,m);
    row.push_back(number(t->GetTrackLength()/um)); row.push_back(integer(record.steps));
    record.all.append(row); record.si.append(row);
    row.push_back(integer(static_cast<int>(t->GetTrackStatus()))); row.push_back(integer(record.cut));
    row.insert(row.end(),{record.token,integer(record.parent_step),integer(record.direct_hadronic),
      integer(record.lineage_hadronic),integer(record.em_from_lineage),integer(record.em_after_primary),integer(record.em_transition)});
    const G4VProcess* process=post?post->GetProcessDefinedStep():nullptr;
    append_process(row,process);
    std::string reason="unknown";
    if (record.cut) reason="reference_neutron_tracking_cut";
    else if (post && post->GetStepStatus()==fWorldBoundary && !v) reason="escaped_world";
    else if (t->GetTrackStatus()==fStopAndKill && t->GetKineticEnergy()==0. && v)
      reason="natural_stop_or_absorption";
    else if (t->GetTrackStatus()==fStopAndKill && process && process->GetProcessType()==fHadronic)
      reason="hadronic_termination";
    row.push_back(reason);
    d.tracks.row(row); d.ledger("track",t->GetTrackID(),record.materials,record.material_steps); record.ended=true; ++d.completed_tracks;
    if (record.cut) ++d.event.neutron_cut_tracks;
  }
};
class Steps : public G4UserSteppingAction {
  Data& d;
public:
  explicit Steps(Data& data):d(data) {}
  void UserSteppingAction(const G4Step* s) override {
    auto t=s->GetTrack(); auto pre=s->GetPreStepPoint(); auto post=s->GetPostStepPoint();
    const G4VProcess* process=post->GetProcessDefinedStep();
    bool hadronic=process && process->GetProcessType()==fHadronic;
    bool neutron_cut=t->GetDefinition()->GetPDGEncoding()==2112 && dynamic_cast<const G4NeutronKiller*>(process)!=nullptr;
    auto& e=d.event; auto& record=d.track.at(t->GetTrackID());
    bool before=e.primary_hadronic_seen;
    bool track_before=record.hadronic_seen;
    record.hadronic_seen=record.hadronic_seen || hadronic;
    const auto* secondaries=s->GetSecondaryInCurrentStep();
    for (std::size_t i=0;i<secondaries->size();++i) {
      const G4Track* child=(*secondaries)[i];
      BirthLink link;
      link.parent=t->GetTrackID(); link.step=t->GetCurrentStepNumber(); link.ordinal=static_cast<int>(i)+1;
      link.token="e"+integer(e.id)+":t"+integer(link.parent)+":s"+integer(link.step)+":n"+integer(link.ordinal);
      link.parent_before=track_before; link.parent_after=record.hadronic_seen; link.creator=child->GetCreatorProcess();
      if (!d.pending_births.emplace(child,link).second) throw std::runtime_error("Secondary object seen twice at creation");
    }
    if (hadronic) {
      ++e.hadronic_steps;
      if (t->GetParentID()==0) {
        ++e.primary_hadronic_steps;
        if (!e.primary_hadronic_seen) {
          e.first_hadronic_step=t->GetCurrentStepNumber(); e.first_hadronic_process=process->GetProcessName();
          e.first_hadronic_time=post->GetGlobalTime()/ns;
        }
        e.primary_hadronic_seen=true;
      }
    }
    double edep=s->GetTotalEnergyDeposit()/MeV, niel=s->GetNonIonizingEnergyDeposit()/MeV;
    double ion=std::max(0.,edep-niel);
    std::string volume=volume_name(pre->GetPhysicalVolume());
    std::string material=material_name(pre->GetMaterial());
    const auto declared=declared_volumes();
    auto definition=declared.find(volume);
    if (definition==declared.end() || definition->second!=material)
      throw std::runtime_error("Step belongs to undeclared volume/material pair");
    e.all.add(edep,niel,ion); record.all.add(edep,niel,ion);
    e.materials[material].add(edep,niel,ion); record.materials[material].add(edep,niel,ion);
    ++e.material_steps[material]; ++record.material_steps[material];
    if (material=="G4_Si") {
      ++e.si_steps; e.si.add(edep,niel,ion); record.si.add(edep,niel,ion);
      if (t->GetParentID()!=0) e.nonprimary+=ion;
      else if (e.primary_hadronic_seen) e.primary_after+=ion;
      else e.primary_before+=ion;
    }
    if (volume=="World") { ++e.world_steps; e.world.add(edep,niel,ion); }
    ++e.step_count; ++record.steps; ++d.recorded_steps;
    if (neutron_cut) { ++e.neutron_cut_steps; record.cut=true; }
    Row row={integer(e.id),integer(t->GetTrackID()),integer(t->GetParentID()),integer(t->GetCurrentStepNumber()),
             t->GetDefinition()->GetParticleName(),integer(t->GetDefinition()->GetPDGEncoding())};
    append_step_point(row,pre); append_step_point(row,post);
    row.insert(row.end(),{number(s->GetStepLength()/um),number(edep),number(niel),number(ion)});
    append_process(row,process);
    row.insert(row.end(),{integer(before),integer(e.primary_hadronic_seen),integer(neutron_cut)});
    double path=s->GetStepLength()/um, chord=(post->GetPosition()-pre->GetPosition()).mag()/um;
    std::string kind=ion==0.?"zero_ionizing":path==0.?"point_zero_length":chord==0.?"point_zero_chord":"finite_path";
    row.insert(row.end(),{integer(static_cast<int>(pre->GetStepStatus())),integer(static_cast<int>(post->GetStepStatus())),
      number(chord),kind,path>0.?number(ion/path):"",integer(track_before),integer(record.hadronic_seen),integer(secondaries->size())});
    d.steps.row(row); // No filtering by edep, particle, creator or material.
  }
};

void metadata(const Config& c) {
  write_json("metadata.json",object({
    {"schema",quote("v4-matched-transport-r1")},{"mode",quote(c.mode)},{"arm",quote(c.arm)},
    {"energy_MeV",number(c.energy)},{"angle_deg",number(c.angle)},{"seed",integer(c.seed)},
    {"events_requested",integer(c.events)},
    {"request_label",quote(c.label)},{"geometry_id",quote(frozen::geometry_id)},
    {"geometry_sha256",quote(frozen::geometry_sha256)}, {"contract_sha256",quote(frozen::contract_sha256)},
    {"geometry",frozen::geometry_json},
    {"geant4_version",quote(G4Version)},{"geant4_version_number",integer(G4VERSION_NUMBER)},
    {"run_manager",quote("G4RunManager")},{"multithreaded_run_manager","false"},{"requested_threads","1"},
    {"compiler",quote(__VERSION__)},{"rng_engine",quote(CLHEP::HepRandom::getTheEngine()->name())},
    {"production_cut_um","0.01"},{"max_step_um","0.02"},{"max_step_region",quote("all_device_solids")},
    {"step_limiter_charged_only","true"},{"primary_particle",quote("proton")},
    {"beam_position_um",vector_json(c.position(),um)},{"beam_direction",vector_json(c.direction(),1.)},
    {"surface_position_um",c.request->hits?vector_json(c.surface(),um):"null"},
    {"world_half_um","["+number(frozen::world_half_um[0])+","+number(frozen::world_half_um[1])+","+number(frozen::world_half_um[2])+"]"},
    {"standard_neutron_time_limit_ns",c.arm=="H"?"10000":"null"},
    {"user_track_killing","false"},
    {"initialization_method",quote("Initialize_then_BeamOn_0")},
    {"inventory_phases",c.mode=="init"?"[\"post_zero_event_init\"]":"[\"post_zero_event_init\",\"post_events\"]"},
    {"units","{\"length\":\"um\",\"time\":\"ns\",\"energy\":\"MeV\",\"charge\":\"eplus\",\"direction\":\"unit_vector\"}"},
    {"scope",quote("Geometry-matched representative DRAM transport format and cost pilot; no transport convergence, SEE probability or TCAD response claim; E retains Opt4 NIEL; H retains standard 10us neutron tracking limit")},
    {"cut_semantics",quote("Production cut is a secondary-production range threshold, not a stop-track cutoff or max step; BeamOn(0) builds tables without particle events")},
    {"ancestry_semantics",quote("Reconstruct creator ancestry from parent_id and creator_type/subtype; primary_hadronic_seen flags track primary type-fHadronic interactions in actual event order, not creator ancestry")},
    {"point_deposition_policy",quote("Keep exact zero path/chord deposition; no artificial path; local deposition per path is not unrestricted or mass LET")},{"birth_binding",quote("current-step secondary object identity, bound to assigned child track ID in ClassifyNewTrack; no coordinate matching")},{"output_precision_digits","17"}}));
}
void require_built_cuts() {
  auto table=G4ProductionCutsTable::GetProductionCutsTable();
  std::set<std::string> seen;
  if (table->GetTableSize()==0) throw std::runtime_error("No material-cut couples after zero-event table initialization");
  for (std::size_t i=0;i<table->GetTableSize();++i) {
    auto couple=table->GetMaterialCutsCouple(static_cast<int>(i));
    std::string material=couple->GetMaterial()->GetName();
    if (!declared_materials().count(material)) continue;
    for (int j=0;j<4;++j) {
      auto values=table->GetEnergyCutsVector(j);
      if (!values || i>=values->size() || !std::isfinite((*values)[i]) || (*values)[i]<=0.)
        throw std::runtime_error("Missing/nonpositive energy-cut table after zero-event initialization");
      if (std::abs(couple->GetProductionCuts()->GetProductionCut(j)/um-.01)>1e-12)
        throw std::runtime_error("Actual range cut differs from explicit 0.01 um policy");
    }
    seen.insert(material);
  }
  if (seen!=declared_materials()) throw std::runtime_error("Every declared material needs built energy-cut tables");
}
void inventory(Data& d, G4VModularPhysicsList* list, const std::string& phase) {
  for (int i=0;;++i) {
    auto constructor=list->GetPhysics(i); if (!constructor) break;
    d.constructors.row({phase,integer(i),constructor->GetPhysicsName(),integer(constructor->GetPhysicsType())});
  }
  auto iterator=G4ParticleTable::GetParticleTable()->GetIterator(); iterator->reset(false); // Include dynamically constructed general ions.
  while ((*iterator)()) {
    auto particle=iterator->value(); auto manager=particle->GetProcessManager();
    d.particles.row({phase,particle->GetParticleName(),integer(particle->GetPDGEncoding()),
      integer(particle->GetAtomicNumber()),integer(particle->GetAtomicMass()),particle->GetParticleType(),particle->GetParticleSubType(),
      integer(manager!=nullptr),integer(manager?manager->GetProcessListLength():0)});
    if (!manager) continue;
    auto process_list=manager->GetProcessList();
    for (int i=0;i<manager->GetProcessListLength();++i) {
      auto process=(*process_list)[i]; auto hadronic=dynamic_cast<G4HadronicProcess*>(process);
      std::size_t count=hadronic?hadronic->GetHadronicInteractionList().size():0;
      d.processes.row({phase,particle->GetParticleName(),integer(particle->GetPDGEncoding()),integer(i),
        process->GetProcessName(),integer(static_cast<int>(process->GetProcessType())),integer(process->GetProcessSubType()),integer(count),integer(particle->GetPDGEncoding()==2112 && dynamic_cast<const G4NeutronKiller*>(process)!=nullptr)});
      if (hadronic) {
        auto& models=hadronic->GetHadronicInteractionList();
        for (std::size_t j=0;j<models.size();++j)
          d.models.row({phase,particle->GetParticleName(),integer(particle->GetPDGEncoding()),process->GetProcessName(),
            integer(j),models[j]->GetModelName(),number(models[j]->GetMinEnergy()/MeV),number(models[j]->GetMaxEnergy()/MeV)});
      }
    }
  }
  auto material_table=G4Material::GetMaterialTable();
  for (auto material:*material_table) {
    d.materials.row({phase,material->GetName(),number(material->GetDensity()/(g/cm3)),number(material->GetTemperature()/kelvin),
      number(material->GetPressure()/pascal),integer(static_cast<int>(material->GetState())),integer(material->GetNumberOfElements())});
    auto elements=material->GetElementVector(); auto fractions=material->GetFractionVector();
    auto densities=material->GetVecNbOfAtomsPerVolume();
    for (std::size_t i=0;i<material->GetNumberOfElements();++i)
      d.elements.row({phase,material->GetName(),(*elements)[i]->GetName(),number((*elements)[i]->GetZ()),
        number((*elements)[i]->GetA()/(g/mole)),number(fractions[i]),number(densities[i]*cm3)});
  }
  auto table=G4ProductionCutsTable::GetProductionCutsTable();
  const char* particles[]={"gamma","e-","e+","proton"};
  for (std::size_t i=0;i<table->GetTableSize();++i) {
    auto couple=table->GetMaterialCutsCouple(static_cast<int>(i));
    for (int j=0;j<4;++j) {
      auto values=table->GetEnergyCutsVector(j); bool available=values && i<values->size();
      d.cuts.row({phase,integer(i),couple->GetMaterial()->GetName(),particles[j],
        number(couple->GetProductionCuts()->GetProductionCut(j)/um),available?number((*values)[i]/MeV):"",integer(available)});
    }
  }
  d.flush();
}
} // namespace probe

int main(int argc,char** argv) {
  using Clock=std::chrono::steady_clock;
  auto phase_start=Clock::now(); auto cpu_start=std::clock();
  bool reserved=false;
  std::unique_ptr<probe::Data> data;
  std::unique_ptr<G4RunManager> manager;
  try {
    probe::Config c=probe::parse(argc,argv);
    probe::reserve(); reserved=true;
    CLHEP::HepRandom::setTheSeed(c.seed);
    data.reset(new probe::Data(c)); probe::metadata(c);
    data->status("INITIALIZING");
    G4cout << "INITIALIZATION_STARTED mode=" << c.mode << " arm=" << c.arm << G4endl;
    manager.reset(new G4RunManager);
    auto physics=probe::physics(c);
    manager->SetUserInitialization(new probe::Geometry);
    manager->SetUserInitialization(physics);
    manager->SetUserAction(new probe::Beam(c));
    manager->SetUserAction(new probe::Events(*data));
    manager->SetUserAction(new probe::Tracking(*data));
    manager->SetUserAction(new probe::Steps(*data));
    manager->SetUserAction(new probe::Stacking(*data));
    manager->Initialize(); data->initialized=true;
    data->beam_on_called=true; data->zero_event_beam_on_called=true;
    data->status("BUILDING_PHYSICS_TABLES_ZERO_EVENTS");
    // Geant4 10.7.3 treats BeamOn(0) as fakeRun: RunInitialization builds the
    // tables, the event loop has zero iterations, then RunTermination executes.
    manager->BeamOn(0);
    probe::require_built_cuts();
    if (data->completed_events!=0 || data->completed_tracks!=0 || data->recorded_steps!=0)
      throw std::runtime_error("Zero-event initialization unexpectedly processed particles");
    data->physics_tables_built=true;
    data->timings.row({"initialization",probe::number(std::chrono::duration<double>(Clock::now()-phase_start).count()),
      probe::number(double(std::clock()-cpu_start)/CLOCKS_PER_SEC),"0","0","0"});
    phase_start=Clock::now(); cpu_start=std::clock();
    probe::inventory(*data,physics,"post_zero_event_init");
    data->timings.row({"inventory_initialization",probe::number(std::chrono::duration<double>(Clock::now()-phase_start).count()),
      probe::number(double(std::clock()-cpu_start)/CLOCKS_PER_SEC),"0","0","0"});
    data->status("INITIALIZED");
    G4cout << "INITIALIZATION_COMPLETED mode=" << c.mode << " arm=" << c.arm
           << " events=0 physics_tables_built=true" << G4endl;
    if (c.mode!="init") {
      data->nonzero_event_beam_on_called=true; data->status("RUNNING");
      phase_start=Clock::now(); cpu_start=std::clock();
      manager->BeamOn(c.events);
      if (data->completed_events!=c.events) throw std::runtime_error("BeamOn returned with missing completed events");
      data->timings.row({"event_loop",probe::number(std::chrono::duration<double>(Clock::now()-phase_start).count()),
        probe::number(double(std::clock()-cpu_start)/CLOCKS_PER_SEC),probe::integer(data->completed_events),
        probe::integer(data->completed_tracks),probe::integer(data->recorded_steps)});
      phase_start=Clock::now(); cpu_start=std::clock();
      probe::inventory(*data,physics,"post_events");
      data->timings.row({"inventory_events",probe::number(std::chrono::duration<double>(Clock::now()-phase_start).count()),
        probe::number(double(std::clock()-cpu_start)/CLOCKS_PER_SEC),probe::integer(data->completed_events),
        probe::integer(data->completed_tracks),probe::integer(data->recorded_steps)});
    }
    manager.reset(); data->flush(); data->status("COMPLETED");
    G4cout << "TRANSPORT_MATCHED_COMPLETED mode=" << c.mode << " arm=" << c.arm
           << " events=" << data->completed_events << " tracks=" << data->completed_tracks
           << " steps=" << data->recorded_steps << G4endl;
    return 0;
  } catch (const std::exception& error) {
    G4cerr << "TRANSPORT_MATCHED_FAILED " << error.what() << G4endl;
    try {
      if (data) { data->flush(); data->status("FAILED",error.what()); }
      else if (reserved) probe::write_json("status.json",probe::object({
        {"schema",probe::quote("v4-matched-transport-status-r1")},{"state",probe::quote("FAILED")},
        {"error",probe::quote(error.what())}}));
    } catch (...) { G4cerr << "FAILED_TO_WRITE_FAILURE_STATUS" << G4endl; }
    return 2;
  }
}
