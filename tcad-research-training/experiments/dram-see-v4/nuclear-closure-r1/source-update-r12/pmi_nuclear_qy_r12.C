// Independent carrier-generation adapter candidate. No solver dispatch here.
// The proprietary SDK is supplied by the existing licensed installation.
#include "candidate_math_r12.hpp"
#ifndef R12_STANDALONE
#include "PMIModels.h"
#include <atomic>
#include <mutex>

namespace {
std::atomic<unsigned long long> next_instance(0);
std::mutex log_mutex;
}

class NuclearQuantumYieldR12 : public PMI_OpticalQuantumYield {
  const std::vector<nuclear_source::Step> steps;
  const unsigned long long instance;
  unsigned long long calls=0, be_calls=0, undefined_calls=0, records=0;
  bool have_previous=false, truncated=false;
  double last_time=0,last_dt=0;
  int last_type=0;

  void trace(const candidate_r12::Evaluation& v, const std::array<double,3>& xyz) {
    std::lock_guard<std::mutex> guard(log_mutex);
    ++calls;
    if(v.type==static_cast<int>(PMI_BE)) ++be_calls;
    if(v.type==static_cast<int>(PMI_UndefStepType)) ++undefined_calls;
    bool changed=!have_previous || v.time!=last_time || v.dt!=last_dt || v.type!=last_type;
    if(calls<=8 || changed) {
      if(records<20000) {
        std::cout<<std::setprecision(17)<<"NC_R12_CALL instance="<<instance<<" sequence="<<calls
                 <<" type="<<v.type<<" t="<<v.time<<" dt="<<v.dt
                 <<" x="<<xyz[0]<<" y="<<xyz[1]<<" z="<<xyz[2]
                 <<" G="<<v.generation<<" eta="<<v.yield<<" Nref="<<candidate_r12::reference_rate<<std::endl;
        ++records;
      } else truncated=true;
    }
    have_previous=true;last_time=v.time;last_dt=v.dt;last_type=v.type;
  }
public:
  explicit NuclearQuantumYieldR12(const PMI_Environment& env)
    :PMI_OpticalQuantumYield(env),steps(nuclear_source::load("sources.dat")),instance(++next_instance) {
    const double bound=candidate_r12::peak_bound(steps);
    std::lock_guard<std::mutex> guard(log_mutex);
    std::cout<<std::setprecision(17)<<"NC_R12_LOADED instance="<<instance<<" steps="<<steps.size()
             <<" peak_bound="<<bound<<" Nref="<<candidate_r12::reference_rate<<" qualified=false"<<std::endl;
  }
  ~NuclearQuantumYieldR12() {
    std::lock_guard<std::mutex> guard(log_mutex);
    std::cout<<"NC_R12_SUMMARY instance="<<instance<<" calls="<<calls<<" BE="<<be_calls
             <<" Undef="<<undefined_calls<<" records="<<records<<" truncated="<<truncated<<std::endl;
  }
  void compute(const idata* id, odata* od) override {
    (void)id; // no carrier, wavelength or temperature-shaped substitute for time
    std::array<double,3> xyz;ReadCoordinate(xyz[0],xyz[1],xyz[2]);
    const int type=static_cast<int>(ReadTransientStepType());
    const char* material=ReadRegionMaterial();
    nuclear_source::need(material!=nullptr,"R12: missing native material identity");
    const bool silicon=std::string(material)=="Silicon";
    nuclear_source::need(ReadRegionMaterialGroup()!=semiconductor || silicon,
                         "R12: unexpected non-silicon semiconductor");
    const auto v=candidate_r12::evaluate(steps,xyz,ReadTime(),ReadTransientStepSize(),
      type,static_cast<int>(PMI_BE),static_cast<int>(PMI_UndefStepType),
      silicon);
    od->eta_G()=v.yield;
    // Carrier-only adapter convention; not a physical photon-heat balance.
    od->eta_T_Eg()=0;od->eta_T0()=0;
    WriteUserField(PMI_UserField0,v.generation);
    WriteUserField(PMI_UserField1,v.time);
    WriteUserField(PMI_UserField2,v.dt);
    WriteUserField(PMI_UserField3,v.type);
    WriteUserField(PMI_UserField4,v.yield);
    WriteUserField(PMI_UserField5,candidate_r12::reference_rate);
    trace(v,xyz);
  }
};
extern "C" PMI_OpticalQuantumYield* new_PMI_OpticalQuantumYield(const PMI_Environment& env) {
  return new NuclearQuantumYieldR12(env);
}
#else
int main(int argc,char** argv) {
  try {
    nuclear_source::need(argc==7,"Usage: source-probe table x y z t0 t1");
    auto steps=nuclear_source::load(argv[1]);candidate_r12::peak_bound(steps);
    std::array<double,3> xyz{{std::stod(argv[2]),std::stod(argv[3]),std::stod(argv[4])}};
    double lo=std::stod(argv[5]),hi=std::stod(argv[6]);
    auto v=candidate_r12::evaluate(steps,xyz,hi,hi-lo,3,3,0,true);
    std::cout<<std::setprecision(17)<<v.generation<<"\n";return 0;
  } catch(const std::exception& ex) {std::cerr<<ex.what()<<"\n";return 1;}
}
#endif
