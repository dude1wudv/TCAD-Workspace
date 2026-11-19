#include "candidate_math_r12.hpp"

#include <algorithm>
#include <functional>
#include <iostream>
#include <limits>
#include <stdexcept>

namespace {
int checks = 0;

void require(bool condition, const char* message) {
  if (!condition) throw std::runtime_error(message);
}

void near(double actual, double expected, double relative, const char* message) {
  const double scale = std::max(std::fabs(expected), 1.0);
  if (!std::isfinite(actual) || std::fabs(actual - expected) > relative * scale)
    throw std::runtime_error(message);
}

void run(const char* name, const std::function<void()>& test) {
  try {
    test();
    ++checks;
  } catch (const std::exception& error) {
    std::cerr << "FAIL " << name << ": " << error.what() << "\n";
    throw;
  }
}

nuclear_source::Step step(double x0, double y0, double z0,
                          double x1, double y1, double z1,
                          double pulse_center, double charge) {
  nuclear_source::Step result = {{x0, y0, z0, x1, y1, z1,
                                  pulse_center, pulse_center, charge,
                                  nuclear_source::width, nuclear_source::sigma}};
  return result;
}

double temporal_fraction(double lo, double hi, double center) {
  const double scale = std::sqrt(2.0) * nuclear_source::sigma;
  return 0.5 * (std::erf((hi - center) / scale) -
                std::erf((lo - center) / scale));
}

double point_average(double charge, double xyz_distance2, double lo, double hi,
                     double center) {
  const double width = nuclear_source::width;
  return charge * 1e-15 / nuclear_source::echarge * 1e12 *
         std::exp(-xyz_distance2 / (width * width)) *
         temporal_fraction(lo, hi, center) /
         (std::pow(nuclear_source::pi, 1.5) * std::pow(width, 3) * (hi - lo));
}

void check_yield(const candidate_r12::Evaluation& value) {
  const double recovered = value.yield * candidate_r12::reference_rate;
  const double scale = std::max(std::fabs(value.generation), 1.0);
  require(std::fabs(recovered - value.generation) <=
              8 * std::numeric_limits<double>::epsilon() * scale,
          "Nref * eta_G must recover G within strict floating-point error");
}
}  // namespace

int main() {
  using candidate_r12::Evaluation;
  const int be = 3;
  const int undef = 0;
  const std::array<double, 3> origin{{0, 0, 0}};
  const double center = 8e-12;
  const double lo = 5e-12;
  const double hi = 11e-12;
  const double charge = 1e3;
  const std::vector<nuclear_source::Step> point{{step(0, 0, 0, 0, 0, 0,
                                                       center, charge)}};

  try {
    run("empty_be_preserves_clock", [&]() {
      const Evaluation value = candidate_r12::evaluate({}, origin, hi, hi - lo,
                                                        be, be, undef, true);
      require(value.generation == 0, "empty source must produce zero G");
      require(value.time == hi && value.dt == hi - lo && value.type == be,
              "empty source must preserve the actual BE clock and type");
      check_yield(value);
    });

    run("undef_preserves_zero_clock_and_type", [&]() {
      const Evaluation value = candidate_r12::evaluate(point, origin, 0, 0,
                                                        undef, be, undef, true);
      require(value.generation == 0 && value.yield == 0,
              "Undef must close the source even at raw clock zero");
      require(value.time == 0 && value.dt == 0 && value.type == undef,
              "Undef must retain raw time, dt, and type");
      check_yield(value);
    });

    run("undef_with_nonzero_clock_and_zero_source", [&]() {
      const double actual_time = 3.7e-12;
      const double actual_dt = 0.1e-12;
      const Evaluation value = candidate_r12::evaluate(point, origin, actual_time,
          actual_dt, undef, be, undef, true);
      require(value.generation == 0 && value.yield == 0,
              "Undef with a nonzero clock must still close generation and yield");
      require(value.time == actual_time && value.dt == actual_dt &&
                  value.type == undef,
              "Undef must preserve its nonzero raw time, dt, and type");
      check_yield(value);
    });

    run("point_source_delayed_be_average", [&]() {
      const Evaluation value = candidate_r12::evaluate(point, origin, hi, hi - lo,
                                                        be, be, undef, true);
      const double expected = point_average(charge, 0, lo, hi, center);
      near(value.generation, expected, 2e-9,
           "point source must match delayed analytic BE average");
      require(value.time == hi && value.dt == hi - lo && value.type == be,
              "point result must retain actual callback context");
      check_yield(value);
    });

    run("non_axis_line_delayed_be_average", [&]() {
      const std::array<double, 3> at_midpoint{{0.045, 0.060, 0.060}};
      const std::vector<nuclear_source::Step> line{{step(0, 0, 0,
          0.09, 0.12, 0.12, center, charge)}};
      const Evaluation value = candidate_r12::evaluate(line, at_midpoint, hi,
          hi - lo, be, be, undef, true);
      const double length = std::sqrt(0.09 * 0.09 + 0.12 * 0.12 + 0.12 * 0.12);
      const double spatial_integral = std::sqrt(nuclear_source::pi) *
          nuclear_source::width / length * std::erf(length /
          (2 * nuclear_source::width));
      const double expected = charge * 1e-15 / nuclear_source::echarge * 1e12 *
          spatial_integral * temporal_fraction(lo, hi, center) /
          (std::pow(nuclear_source::pi, 1.5) *
           std::pow(nuclear_source::width, 3) * (hi - lo));
      near(value.generation, expected, 2e-8,
           "diagonal line source must match analytic spatial and temporal average");
      check_yield(value);
    });

    run("rollback_and_shorter_interval_recompute", [&]() {
      const double late_lo = 12e-12;
      const double late_hi = 16e-12;
      const double late = candidate_r12::evaluate(point, origin, late_hi,
          late_hi - late_lo, be, be, undef, true).generation;
      const double short_lo = 7e-12;
      const double short_hi = 8.5e-12;
      const Evaluation rolled_back = candidate_r12::evaluate(point, origin,
          short_hi, short_hi - short_lo, be, be, undef, true);
      const double direct = point_average(charge, 0, short_lo, short_hi, center);
      require(late >= 0, "later interval call must produce a valid result");
      near(rolled_back.generation, direct, 2e-9,
           "rollback to earlier shorter interval must be recomputed without cache carryover");
      check_yield(rolled_back);
    });

    run("non_silicon_source_is_zero", [&]() {
      const Evaluation value = candidate_r12::evaluate(point, origin, hi, hi - lo,
                                                        be, be, undef, false);
      require(value.generation == 0 && value.yield == 0,
              "non-silicon material must receive no source");
      require(value.time == hi && value.dt == hi - lo && value.type == be,
              "non-silicon callback context must remain intact");
      check_yield(value);
    });

    run("negative_dt_rejected", [&]() {
      bool rejected = false;
      try { candidate_r12::evaluate(point, origin, hi, -1e-12, be, be, undef, true); }
      catch (const std::exception&) { rejected = true; }
      require(rejected, "negative dt must fail");
    });

    run("zero_dt_be_rejected_even_at_zero_time", [&]() {
      bool rejected = false;
      try { candidate_r12::evaluate(point, origin, 0, 0, be, be, undef, true); }
      catch (const std::exception&) { rejected = true; }
      require(rejected, "zero dt on a BE callback must fail, including at raw time zero");
    });

    run("nonfinite_clock_rejected", [&]() {
      const double nan = std::numeric_limits<double>::quiet_NaN();
      bool bad_time = false, bad_dt = false;
      try { candidate_r12::evaluate(point, origin, nan, 1e-12, be, be, undef, true); }
      catch (const std::exception&) { bad_time = true; }
      try { candidate_r12::evaluate(point, origin, hi, nan, be, be, undef, true); }
      catch (const std::exception&) { bad_dt = true; }
      require(bad_time && bad_dt, "NaN time and dt must fail");
    });

    run("negative_time_and_unknown_type_rejected", [&]() {
      bool bad_time = false, bad_type = false;
      try { candidate_r12::evaluate(point, origin, -1e-12, 1e-12, be, be, undef, true); }
      catch (const std::exception&) { bad_time = true; }
      try { candidate_r12::evaluate(point, origin, hi, hi - lo, 77, be, undef, true); }
      catch (const std::exception&) { bad_type = true; }
      require(bad_time && bad_type,
              "negative clock and unsupported step type must fail");
    });

    run("peak_bound_overflow_rejected_without_clamping", [&]() {
      const std::vector<nuclear_source::Step> excessive{{step(0, 0, 0, 0, 0, 0,
                                                                center, 1e30)}};
      bool rejected = false;
      try { (void)candidate_r12::peak_bound(excessive); }
      catch (const std::exception&) { rejected = true; }
      require(rejected, "peak above Nref must be rejected rather than clipped");
    });

    std::cout << "{\"status\":\"pass\",\"tests\":" << checks << "}\n";
    return 0;
  } catch (const std::exception&) {
    return 1;
  }
}
