#ifndef NC_CANDIDATE_MATH_R12_HPP
#define NC_CANDIDATE_MATH_R12_HPP
#include "source_kernel_r12.hpp"

namespace candidate_r12 {
const double reference_rate = 1e35; // cm^-3 s^-1, representation only
struct Evaluation {
  double generation, yield, time, dt;
  int type;
};

double peak_bound(const std::vector<nuclear_source::Step>& steps) {
  long double charge = 0;
  for (const auto& step : steps) charge += step.a[8];
  const long double spatial = std::pow(nuclear_source::pi, 1.5) *
                              std::pow(nuclear_source::width, 3);
  const long double temporal = std::sqrt(2*nuclear_source::pi) * nuclear_source::sigma;
  const long double value = charge*1e-15L/nuclear_source::echarge*1e12L/spatial/temporal;
  nuclear_source::need(std::isfinite(value) && value <= reference_rate,
                       "R12: source peak exceeds frozen representation basis; do not clip");
  return static_cast<double>(value);
}

Evaluation evaluate(const std::vector<nuclear_source::Step>& steps,
                    const std::array<double,3>& xyz, double time, double dt,
                    int type, int be_type, int undefined_type, bool silicon) {
  nuclear_source::need(std::isfinite(time) && std::isfinite(dt) && time>=0 && dt>=0,
                       "R12: invalid actual clock/step");
  for (double x : xyz) nuclear_source::need(std::isfinite(x), "R12: invalid actual coordinate");
  nuclear_source::need(type==be_type || type==undefined_type, "R12: unsupported actual step type");
  Evaluation out{0,0,time,dt,type};
  if (type==be_type) {
    nuclear_source::need(dt>0 && time-dt>=-1e-18, "R12: invalid actual BE interval");
    if (silicon) out.generation=nuclear_source::average(steps,xyz,time-dt,time);
  }
  nuclear_source::need(std::isfinite(out.generation) && out.generation>=0 &&
                       out.generation<=reference_rate, "R12: invalid native source or basis overflow");
  out.yield=out.generation/reference_rate;
  return out;
}
}
#endif
