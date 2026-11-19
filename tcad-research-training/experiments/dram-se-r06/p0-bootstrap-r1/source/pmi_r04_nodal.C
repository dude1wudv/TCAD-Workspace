// Original r04 candidate. Compile/load evidence is separate from source qualification.
#include "PMIModels.h"
#include "voxel_source.hpp"
#include "nodal_source.hpp"
#include <atomic>
#include <cstdio>
#include <cstdint>
#include <cstring>
#include <exception>

// O2 logging state is shared by all instances in this loaded plugin image.
// It neither caches source data nor changes solver time/step/physical state.
namespace r06_o2_logging {
struct Counters {
  std::atomic<std::uint64_t> initializations{0};
  std::atomic<std::uint64_t> callbacks{0};
  ~Counters() {
    // Plugin unload is not a solver-completion or accepted-time-step hook.
    // Use stderr: PMI environments may already have been destroyed here.
    std::fprintf(stderr,
        "R06_O2_PLUGIN_UNLOAD_SUMMARY log_version=r06-o2-global-r1 initializations=%llu callbacks=%llu solver_success=unknown accepted_steps=unknown\n",
        static_cast<unsigned long long>(initializations.load(std::memory_order_relaxed)),
        static_cast<unsigned long long>(callbacks.load(std::memory_order_relaxed)));
  }
};
static Counters counters;
}  // namespace r06_o2_logging

class R04NodalYield : public PMI_OpticalQuantumYield {
  r04nodal::Source source_;
public:
  explicit R04NodalYield(const PMI_Environment& env)
    : PMI_OpticalQuantumYield(env) {
    try {
      r04voxel::require(ReadDimension() == 3, "native nodal model requires 3D");
      source_ = r04nodal::Source::load_file("nodal-source.dat");
      const std::uint64_t initialization = r06_o2_logging::counters.initializations.fetch_add(1, std::memory_order_relaxed) + 1;
      if (initialization <= 4) {
        LogData()->PMIPrint("R04_NODAL_INIT log_version=r06-o2-global-r1 n=%llu nodes=%llu rows=%llu allocations=%llu sum_rate_weight_dt_pairs=%.17g analytic_pairs=%.17g Nref=%.17g exact_coordinates=true native_qualified=false\n",
            static_cast<unsigned long long>(initialization),
            static_cast<unsigned long long>(source_.nodes()), static_cast<unsigned long long>(source_.rows()), static_cast<unsigned long long>(source_.allocations()), source_.pairs(), source_.expected_pairs(), 1e38);
      } else if (initialization == 5) {
        LogData()->PMIPrint("R06_O2_INIT_LIMIT log_version=r06-o2-global-r1 later initialization details omitted globally; source loading and errors remain enabled\n");
      }
    } catch (const std::exception& error) {
      LogData()->PMIError("R04_QY_INPUT: %s", error.what());
    }
  }

  void compute(const idata*, odata* output) override {
    try {
      // Read these on every real callback, including Undef. Never substitute a clock.
      const double time = ReadTime();
      const double dt = ReadTransientStepSize();
      const PMI_StepType raw_type = ReadTransientStepType();
      const auto classification = raw_type == PMI_UndefStepType ? r04voxel::StepClass::Undef :
          raw_type == PMI_BE ? r04voxel::StepClass::BE : r04voxel::StepClass::Unknown;
      const auto context = r04voxel::make_context(time, dt, raw_type, classification);
      double x, y, z;
      ReadCoordinate(x, y, z);
      const char* region = ReadRegionName();
      const char* material = ReadRegionMaterial();
      r04voxel::require(region && material, "missing native region/material");
      double generation = 0;
      if (ReadRegionMaterialGroup() == semiconductor) {
        r04voxel::require(std::strcmp(material, "Silicon") == 0, "unsupported semiconductor");
        generation = source_.average(region, {{x,y,z}}, context);
      }
      r04voxel::require(std::isfinite(generation) && generation >= 0 &&
          generation < 1e38, "invalid rate or reference basis exceeded");
      // Numerical carrier-generation channel only. No heat equation is supported.
      output->eta_G() = generation / 1e38;
      output->eta_T_Eg() = 0;
      output->eta_T0() = 0;
      WriteUserField(PMI_UserField0, generation);
      WriteUserField(PMI_UserField1, time);
      WriteUserField(PMI_UserField2, dt);
      WriteUserField(PMI_UserField3, static_cast<double>(raw_type));
      WriteUserField(PMI_UserField4, output->eta_G());
      WriteUserField(PMI_UserField5, 1e38);
      const std::uint64_t n = r06_o2_logging::counters.callbacks.fetch_add(1, std::memory_order_relaxed) + 1;
      if (n <= 512) {
        LogData()->PMIPrint("R04_QY_CALLBACK n=%llu region=%s time=%.17g dt=%.17g type=%d x=%.17g y=%.17g z=%.17g G=%.17g eta=%.17g\n",
            static_cast<unsigned long long>(n), region, time, dt,
            static_cast<int>(raw_type), x,y,z,generation,output->eta_G());
      } else if (n == 513) {
        LogData()->PMIPrint("R04_QY_TRACE_LIMIT: later callback details omitted globally; trace is not full-step evidence; log_version=r06-o2-global-r1\n");
      } else if ((n & (n - 1)) == 0) {
        LogData()->PMIPrint("R06_O2_CALLBACK_PROGRESS log_version=r06-o2-global-r1 n=%llu callback_count_not_accepted_steps=true\n",
            static_cast<unsigned long long>(n));
      }
    } catch (const std::exception& error) {
      LogData()->PMIError("R04_QY_COMPUTE: %s", error.what());
    }
  }
};

extern "C" PMI_OpticalQuantumYield*
new_PMI_OpticalQuantumYield(const PMI_Environment& env) {
  return new R04NodalYield(env);
}
