"""Deterministic, logging-only transform of the frozen mc2 PMI source."""
from __future__ import annotations

import hashlib
from pathlib import Path

VERSION = "r06-o2-global-r1"
ORIGINAL_SHA256 = "6c2360c8b75840561fb61a61dccc8fddde0d4e14061f65cbd1a6f748bdb77b75"

GLOBALS = r'''
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
'''

OLD_INIT = '''      LogData()->PMIPrint("R04_NODAL_INIT nodes=%llu rows=%llu allocations=%llu sum_rate_weight_dt_pairs=%.17g analytic_pairs=%.17g Nref=%.17g exact_coordinates=true native_qualified=false\\n",
          static_cast<unsigned long long>(source_.nodes()), static_cast<unsigned long long>(source_.rows()), static_cast<unsigned long long>(source_.allocations()), source_.pairs(), source_.expected_pairs(), 1e38);'''

NEW_INIT = '''      const std::uint64_t initialization = r06_o2_logging::counters.initializations.fetch_add(1, std::memory_order_relaxed) + 1;
      if (initialization <= 4) {
        LogData()->PMIPrint("R04_NODAL_INIT log_version=r06-o2-global-r1 n=%llu nodes=%llu rows=%llu allocations=%llu sum_rate_weight_dt_pairs=%.17g analytic_pairs=%.17g Nref=%.17g exact_coordinates=true native_qualified=false\\n",
            static_cast<unsigned long long>(initialization),
            static_cast<unsigned long long>(source_.nodes()), static_cast<unsigned long long>(source_.rows()), static_cast<unsigned long long>(source_.allocations()), source_.pairs(), source_.expected_pairs(), 1e38);
      } else if (initialization == 5) {
        LogData()->PMIPrint("R06_O2_INIT_LIMIT log_version=r06-o2-global-r1 later initialization details omitted globally; source loading and errors remain enabled\\n");
      }'''

OLD_CALLBACK = '''      const std::uint64_t n = callbacks_.fetch_add(1, std::memory_order_relaxed) + 1;
      if (n <= 512) {
        LogData()->PMIPrint("R04_QY_CALLBACK n=%llu region=%s time=%.17g dt=%.17g type=%d x=%.17g y=%.17g z=%.17g G=%.17g eta=%.17g\\n",
            static_cast<unsigned long long>(n), region, time, dt,
            static_cast<int>(raw_type), x,y,z,generation,output->eta_G());
      } else if (n == 513) {
        LogData()->PMIPrint("R04_QY_TRACE_LIMIT: later callbacks omitted; trace is not full-step evidence\\n");
      }'''

NEW_CALLBACK = '''      const std::uint64_t n = r06_o2_logging::counters.callbacks.fetch_add(1, std::memory_order_relaxed) + 1;
      if (n <= 512) {
        LogData()->PMIPrint("R04_QY_CALLBACK n=%llu region=%s time=%.17g dt=%.17g type=%d x=%.17g y=%.17g z=%.17g G=%.17g eta=%.17g\\n",
            static_cast<unsigned long long>(n), region, time, dt,
            static_cast<int>(raw_type), x,y,z,generation,output->eta_G());
      } else if (n == 513) {
        LogData()->PMIPrint("R04_QY_TRACE_LIMIT: later callback details omitted globally; trace is not full-step evidence; log_version=r06-o2-global-r1\\n");
      } else if ((n & (n - 1)) == 0) {
        LogData()->PMIPrint("R06_O2_CALLBACK_PROGRESS log_version=r06-o2-global-r1 n=%llu callback_count_not_accepted_steps=true\\n",
            static_cast<unsigned long long>(n));
      }'''


def once(text: str, before: str, after: str) -> str:
    if text.count(before) != 1:
        raise ValueError("Frozen logging edit anchor changed or is ambiguous")
    return text.replace(before, after, 1)


def patched(original: bytes) -> bytes:
    if hashlib.sha256(original).hexdigest() != ORIGINAL_SHA256:
        raise ValueError("Not the frozen mc2 PMI source; never patch another version")
    text = original.decode("utf-8")
    text = once(text, "#include <cstdint>", "#include <cstdio>\n#include <cstdint>")
    text = once(text, "\nclass R04NodalYield", GLOBALS + "\nclass R04NodalYield")
    text = once(text, "  std::atomic<std::uint64_t> callbacks_{0};\n", "")
    text = once(text, OLD_INIT, NEW_INIT)
    text = once(text, OLD_CALLBACK, NEW_CALLBACK)
    return text.encode("utf-8")


def verify(package: Path) -> dict:
    original = (package / "evidence/original-pmi_r04_nodal.C").read_bytes()
    current = (package / "source/pmi_r04_nodal.C").read_bytes()
    if current != patched(original):
        raise ValueError("New source differs from the exact logging-only transform")
    return {
        "status": "passed_source_transform_only",
        "original_sha256": ORIGINAL_SHA256,
        "patched_sha256": hashlib.sha256(current).hexdigest(),
        "log_version": VERSION,
        "physical_and_solver_code_unchanged": True,
        "callback_detail_limit_per_plugin_image": 512,
        "initialization_detail_limit_per_plugin_image": 4,
        "progress_policy": "powers of two >=1024; callback count, never accepted steps",
        "errors_suppressed": False,
        "native_compilation_or_execution_verified": False,
    }


if __name__ == "__main__":
    import json
    print(json.dumps(verify(Path(__file__).resolve().parent), indent=2))
