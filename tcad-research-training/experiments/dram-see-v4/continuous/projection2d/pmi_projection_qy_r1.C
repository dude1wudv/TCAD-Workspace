// Candidate only: mathematical 2D projection with original R12 PMI ABI.
// Actual BE/APD/dual-carrier qualification remains unresolved.
#include "projection_pmi_math_r1.hpp"
#ifndef PROJECTION_STANDALONE
#include "PMIModels.h"
#include <atomic>
#include <mutex>
namespace { std::atomic<unsigned long long> instances(0);std::mutex trace_mutex; }

class ProjectedQuantumYieldR14 : public PMI_OpticalQuantumYield {
  const std::vector<nuclear_source::Step> steps;
  const projection_r14::Context context;
  const unsigned long long instance;
  unsigned long long calls=0,be_calls=0,undefined_calls=0,records=0;
  bool previous=false;double last_time=0,last_dt=0;int last_type=0;
  void trace(const projection_r14::Evaluation& value,const std::array<double,3>& native) {
    std::lock_guard<std::mutex> guard(trace_mutex);++calls;
    if(value.type==static_cast<int>(PMI_BE))++be_calls;
    if(value.type==static_cast<int>(PMI_UndefStepType))++undefined_calls;
    bool changed=!previous||value.time!=last_time||value.dt!=last_dt||value.type!=last_type;
    if(calls<=8||changed) {
      std::cout<<std::setprecision(17)<<"R14_PROJECTION_CALL instance="<<instance<<" sequence="<<calls
        <<" type="<<value.type<<" t="<<value.time<<" dt="<<value.dt<<" native_X="<<native[0]
        <<" native_Y="<<native[1]<<" native_Z="<<native[2]<<" physical_x="<<native[0]<<" physical_z="<<native[1]
        <<" G2="<<value.generation<<" eta="<<value.yield<<" Nref="<<projection_r14::reference_rate<<std::endl;
      ++records;
    }
    previous=true;last_time=value.time;last_dt=value.dt;last_type=value.type;
  }
public:
  explicit ProjectedQuantumYieldR14(const PMI_Environment& env):PMI_OpticalQuantumYield(env),
    steps(nuclear_source::load("projection-sources3d.dat")),context(projection_r14::load_context("projection-context.dat")),instance(++instances) {
    double peak=projection_r14::peak_bound(steps,context);std::lock_guard<std::mutex> guard(trace_mutex);
    std::cout<<std::setprecision(17)<<"R14_PROJECTION_LOADED instance="<<instance<<" source_steps="<<steps.size()
      <<" W_um="<<projection_r14::width_um<<" input_window_lo="<<context.lo<<" input_window_hi="<<context.hi
      <<" peak_bound="<<peak<<" native_qualified=false pmi_r12_fixed=false"<<std::endl;
  }
  ~ProjectedQuantumYieldR14() {
    std::lock_guard<std::mutex> guard(trace_mutex);
    std::cout<<"R14_PROJECTION_SUMMARY instance="<<instance<<" calls="<<calls<<" BE="<<be_calls
      <<" Undef="<<undefined_calls<<" records="<<records<<" truncated=false"<<std::endl;
  }
  void compute(const idata* id,odata* od) override {
    (void)id;std::array<double,3> native;ReadCoordinate(native[0],native[1],native[2]);
    const int type=static_cast<int>(ReadTransientStepType());const char* material=ReadRegionMaterial();
    nuclear_source::need(material!=nullptr,"R14: missing actual native material identity");
    const bool silicon=std::string(material)=="Silicon";
    nuclear_source::need(ReadRegionMaterialGroup()!=semiconductor||silicon,"R14: unexpected non-Silicon semiconductor");
    const auto value=projection_r14::evaluate(steps,context,native,ReadTime(),ReadTransientStepSize(),type,
      static_cast<int>(PMI_BE),static_cast<int>(PMI_UndefStepType),silicon);
    od->eta_G()=value.yield;od->eta_T_Eg()=0;od->eta_T0()=0; // carrier-only representation, no photon-heat claim
    WriteUserField(PMI_UserField0,value.generation);WriteUserField(PMI_UserField1,value.time);
    WriteUserField(PMI_UserField2,value.dt);WriteUserField(PMI_UserField3,value.type);
    WriteUserField(PMI_UserField4,value.yield);WriteUserField(PMI_UserField5,projection_r14::reference_rate);
    trace(value,native);
  }
};
extern "C" PMI_OpticalQuantumYield* new_PMI_OpticalQuantumYield(const PMI_Environment& env) {return new ProjectedQuantumYieldR14(env);}
#else
int main(int argc,char** argv) {
  try {
    nuclear_source::need(argc==7,"Usage: projection_probe table context physical_x physical_z lo_s hi_s");
    auto steps=nuclear_source::load(argv[1]);auto context=projection_r14::load_context(argv[2]);projection_r14::peak_bound(steps,context);
    double lo=std::stod(argv[5]),hi=std::stod(argv[6]);std::array<double,3> native{{std::stod(argv[3]),std::stod(argv[4]),0.}};
    // Explicit synthetic standalone context, never a claimed native PMI callback.
    auto value=projection_r14::evaluate(steps,context,native,hi,hi-lo,3,3,0,true);
    std::cout<<std::setprecision(17)<<value.generation<<"\n";return 0;
  } catch(const std::exception& error) {std::cerr<<error.what()<<"\n";return 1;}
}
#endif
