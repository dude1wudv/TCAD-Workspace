// Original source implementation. ABI declarations are supplied by the licensed
// installed PMIModels.h; no vendor implementation is copied into this file.
#include <algorithm>
#include <array>
#include <cmath>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <locale>
#include <sstream>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

#ifndef NUCLEAR_SOURCE_STANDALONE
#include "PMIModels.h"
#include <atomic>
#include <mutex>
#endif

namespace nuclear_source {
const double pi = 3.141592653589793238462643383279502884;
const double echarge = 1.602176634e-19;
const double width = .03;
const double sigma = 2e-12;

struct Step { std::array<double, 11> a; };

void need(bool ok, const char* message) {
  if (!ok) throw std::runtime_error(message);
}

std::vector<Step> load(const char* filename) {
  std::ifstream stream(filename);
  stream.imbue(std::locale::classic());
  need(stream.good(), "NUCLEAR_SOURCE: missing sources.dat");
  std::string header, magic, extra;
  need(bool(std::getline(stream, header)), "NUCLEAR_SOURCE: missing header");
  std::istringstream first(header); first.imbue(std::locale::classic());
  unsigned long long count = 0;
  need(bool(first >> magic >> count) && magic == "NUCLEAR_CLOSURE_SOURCE_V1" && !(first >> extra),
       "NUCLEAR_SOURCE: invalid format/header");
  std::vector<Step> steps;
  need(count <= steps.max_size(), "NUCLEAR_SOURCE: source count exceeds capacity");
  steps.reserve(static_cast<std::size_t>(count));
  for (unsigned long long i = 0; i < count; ++i) {
    std::string line;
    need(bool(std::getline(stream, line)), "NUCLEAR_SOURCE: truncated source table");
    std::istringstream row(line); row.imbue(std::locale::classic());
    Step step;
    for (std::size_t j = 0; j < step.a.size(); ++j) {
      need(bool(row >> step.a[j]) && std::isfinite(step.a[j]), "NUCLEAR_SOURCE: invalid/nonfinite source value");
    }
    need(!(row >> extra), "NUCLEAR_SOURCE: extra source column");
    need(step.a[6] >= 0 && step.a[7] >= step.a[6] && step.a[8] > 0,
         "NUCLEAR_SOURCE: invalid time/charge");
    need(step.a[9] == width && step.a[10] == sigma, "NUCLEAR_SOURCE: unregistered width/time assumption");
    if (!steps.empty()) need(!(step.a < steps.back().a), "NUCLEAR_SOURCE: source rows are not canonical");
    steps.push_back(step);
  }
  need(!(stream >> extra), "NUCLEAR_SOURCE: extra source records");
  return steps;
}

double erf_difference(double lo, double hi) {
  if (lo >= 0) return std::erfc(lo) - std::erfc(hi);
  if (hi <= 0) return std::erfc(-hi) - std::erfc(-lo);
  return std::erf(hi) - std::erf(lo);
}

std::vector<std::pair<double,double> > gauss(unsigned n) {
  std::vector<std::pair<double,double> > result;
  for (unsigned i = 1; i <= n; ++i) {
    double z = std::cos(pi * (i - .25) / (n + .5));
    double derivative = 0;
    for (unsigned iter = 0; iter < 40; ++iter) {
      double p0 = 1, p1 = z;
      for (unsigned k = 2; k <= n; ++k) {
        double p2 = ((2*k-1)*z*p1-(k-1)*p0)/k; p0=p1; p1=p2;
      }
      derivative = n * (z*p1-p0)/(z*z-1);
      double next = z-p1/derivative;
      if (std::fabs(next-z) <= 2e-16) { z=next; break; }
      z=next;
    }
    result.push_back(std::make_pair((z+1)/2,1/((1-z*z)*derivative*derivative)));
  }
  std::sort(result.begin(),result.end()); return result;
}

const std::vector<std::pair<double,double> >& nodes8() {
  static const std::vector<std::pair<double,double> > value=gauss(8); return value;
}
const std::vector<std::pair<double,double> >& nodes16() {
  static const std::vector<std::pair<double,double> > value=gauss(16); return value;
}

struct AverageIntegrand {
  const Step& step; std::array<double,3> xyz; double lo,hi;
  double operator()(double u) const {
    double distance2=0;
    for (unsigned i=0;i<3;++i) {
      double v=(xyz[i]-step.a[i]-u*(step.a[i+3]-step.a[i]))/step.a[9]; distance2+=v*v;
    }
    double center=step.a[6]+u*(step.a[7]-step.a[6]);
    double scale=std::sqrt(2.)*step.a[10];
    return std::exp(-distance2)*.5*erf_difference((lo-center)/scale,(hi-center)/scale);
  }
};

double quadrature(const AverageIntegrand& f,double lo,double hi,
                  const std::vector<std::pair<double,double> >& nodes) {
  double sum=0, correction=0;
  for (std::size_t i=0;i<nodes.size();++i) {
    double term=f(lo+(hi-lo)*nodes[i].first)*nodes[i].second*(hi-lo)-correction;
    double next=sum+term; correction=(next-sum)-term; sum=next;
  }
  return sum;
}

double adaptive(const AverageIntegrand& f,double lo,double hi,unsigned depth=0) {
  double small=quadrature(f,lo,hi,nodes8()), large=quadrature(f,lo,hi,nodes16());
  if (std::fabs(small-large)<=1e-12*(hi-lo)+1e-10*std::fabs(large)) return large;
  need(depth<18,"NUCLEAR_SOURCE: BE source quadrature did not converge");
  double mid=(lo+hi)/2;
  return adaptive(f,lo,mid,depth+1)+adaptive(f,mid,hi,depth+1);
}

void add(std::vector<double>& points,double u) {
  if (std::isfinite(u) && u>0 && u<1) points.push_back(u);
}

double average_step(const Step& step,const std::array<double,3>& xyz,double lo,double hi) {
  std::vector<double> points; points.push_back(0); points.push_back(1);
  const double multiples[]={-8,-4,-2,0,2,4,8};
  double length2=0, projection=0;
  for(unsigned i=0;i<3;++i) {
    double d=step.a[i+3]-step.a[i]; length2+=d*d; projection+=(xyz[i]-step.a[i])*d;
  }
  if(length2>0) {
    double center=projection/length2;
    for(unsigned i=0;i<7;++i) add(points,center+multiples[i]*step.a[9]/std::sqrt(length2));
  }
  double duration=step.a[7]-step.a[6];
  if(duration>0) {
    for(unsigned i=0;i<7;++i) {
      add(points,(lo+multiples[i]*std::sqrt(2.)*step.a[10]-step.a[6])/duration);
      add(points,(hi+multiples[i]*std::sqrt(2.)*step.a[10]-step.a[6])/duration);
    }
  }
  std::sort(points.begin(),points.end()); points.erase(std::unique(points.begin(),points.end()),points.end());
  AverageIntegrand f={step,xyz,lo,hi}; double integral=0;
  for(std::size_t i=1;i<points.size();++i) integral+=adaptive(f,points[i-1],points[i]);
  return step.a[8]*1e-15/echarge*1e12*integral/(std::pow(pi,1.5)*std::pow(step.a[9],3)*(hi-lo));
}

double average(const std::vector<Step>& steps,const std::array<double,3>& xyz,double lo,double hi) {
  need(std::isfinite(lo)&&std::isfinite(hi)&&hi>lo,"NUCLEAR_SOURCE: nonpositive/nonfinite actual BE interval");
  for(unsigned i=0;i<3;++i) need(std::isfinite(xyz[i]),"NUCLEAR_SOURCE: nonfinite native coordinate");
  double sum=0,correction=0;
  for(std::size_t i=0;i<steps.size();++i) {
    double rate=average_step(steps[i],xyz,lo,hi);
    need(std::isfinite(rate)&&rate>=0,"NUCLEAR_SOURCE: nonfinite/negative generation");
    double term=rate-correction,next=sum+term;correction=(next-sum)-term;sum=next;
  }
  need(std::isfinite(sum),"NUCLEAR_SOURCE: generation sum overflow"); return sum;
}
} // namespace nuclear_source

#ifndef NUCLEAR_SOURCE_STANDALONE

// Candidate diagnostics only. No compile or execution release is implied.
// These counters and logs observe the original callbacks; they never supply
// simulation times, source values, or user-field values to the solver.
namespace nuclear_trace_r10 {
const unsigned long long first_calls = 8;
const unsigned long long max_records = 512;
std::atomic<unsigned long long> next_instance(1);
std::mutex output_mutex;

struct Token {
  unsigned long long call;
  bool emitted;
};

struct State {
  const unsigned long long instance;
  std::mutex mutex;
  unsigned long long calls, completed, emitted, omitted;
  std::array<unsigned long long,5> types;
  bool seen, truncated;
  int last_type;
  double last_time, last_dt;

  State():instance(next_instance.fetch_add(1)),calls(0),completed(0),
          emitted(0),omitted(0),types{{0,0,0,0,0}},seen(false),
          truncated(false),last_type(0),last_time(0),last_dt(0) {}

  static void output(const std::string& line) {
    std::lock_guard<std::mutex> lock(output_mutex);
    std::cout << line << '\n';
    std::cout.flush();
  }

  void initialized(std::size_t source_steps) {
    std::ostringstream line;
    line << "NC_TRACE_R10_INIT instance=" << instance
         << " source_steps=" << source_steps
         << " first_calls=" << first_calls << " max_records=" << max_records;
    output(line.str());
  }

  Token begin(int type, double raw_time, double raw_dt,
              const std::array<double,3>& xyz,
              const std::array<int,4>& defined_before) {
    std::lock_guard<std::mutex> lock(mutex);
    ++calls;
    ++types[type >= 0 && type <= 3 ? static_cast<unsigned>(type) : 4];
    const bool changed = !seen || type != last_type || raw_time != last_time
                                  || raw_dt != last_dt;
    seen = true;
    last_type = type;
    last_time = raw_time;
    last_dt = raw_dt;
    const bool wanted = calls <= first_calls || changed;
    const bool emit = wanted && emitted < max_records;
    if (emit) {
      ++emitted;
      std::ostringstream line;
      line.imbue(std::locale::classic());
      line << std::setprecision(17)
           << "NC_TRACE_R10_ENTER instance=" << instance << " call=" << calls
           << " type=" << type << " raw_time_s=" << raw_time
           << " raw_dt_s=" << raw_dt
           << " xyz_um=" << xyz[0] << ',' << xyz[1] << ',' << xyz[2]
           << " defined_before=" << defined_before[0] << ','
           << defined_before[1] << ',' << defined_before[2] << ','
           << defined_before[3];
      output(line.str());
    } else if (wanted) {
      ++omitted;
      if (!truncated) {
        truncated = true;
        std::ostringstream line;
        line << "NC_TRACE_R10_TRUNCATED instance=" << instance
             << " at_call=" << calls << " max_records=" << max_records;
        output(line.str());
      }
    }
    Token token = {calls,emit};
    return token;
  }

  void end(const Token& token, const std::array<int,4>& defined_after,
           double generation, double time, double dt, int type, double r) {
    std::lock_guard<std::mutex> lock(mutex);
    ++completed;
    if (!token.emitted) return;
    std::ostringstream line;
    line.imbue(std::locale::classic());
    line << std::setprecision(17)
         << "NC_TRACE_R10_LEAVE instance=" << instance << " call=" << token.call
         << " defined_after=" << defined_after[0] << ',' << defined_after[1]
         << ',' << defined_after[2] << ',' << defined_after[3]
         << " requested_fields=" << generation << ',' << time << ',' << dt
         << ',' << type << " returned_r=" << r;
    output(line.str());
  }

  void finished() {
    std::lock_guard<std::mutex> lock(mutex);
    std::ostringstream line;
    line << "NC_TRACE_R10_SUMMARY instance=" << instance
         << " calls=" << calls << " completed=" << completed
         << " unfinished=" << (calls-completed)
         << " type_counts_Undef_TR_BDF_BE_other=" << types[0] << ',' << types[1]
         << ',' << types[2] << ',' << types[3] << ',' << types[4]
         << " emitted_records=" << emitted << " omitted_change_records=" << omitted
         << " truncated=" << (truncated ? 1 : 0);
    output(line.str());
  }
};
} // namespace nuclear_trace_r10

class NuclearSource : public PMI_Recombination {
  const std::vector<nuclear_source::Step> steps;
  nuclear_trace_r10::State trace;

  nuclear_trace_r10::Token trace_begin(PMI_StepType type) {
    const double raw_time = ReadTime();
    const double raw_dt = ReadTransientStepSize();
    std::array<double,3> xyz;
    ReadCoordinate(xyz[0],xyz[1],xyz[2]);
    std::array<int,4> defined_before;
    for (unsigned i=0;i<4;++i) {
      defined_before[i] = IsUserFieldDefined(static_cast<PMI_UserFieldIndex>(i));
    }
    return trace.begin(static_cast<int>(type),raw_time,raw_dt,xyz,defined_before);
  }

  void trace_end(const nuclear_trace_r10::Token& token, double generation,
                 double time, double dt, PMI_StepType type, double r) {
    std::array<int,4> defined_after;
    for (unsigned i=0;i<4;++i) {
      defined_after[i] = IsUserFieldDefined(static_cast<PMI_UserFieldIndex>(i));
    }
    trace.end(token,defined_after,generation,time,dt,static_cast<int>(type),r);
  }
public:
  explicit NuclearSource(const PMI_Environment& env):PMI_Recombination(env),steps(nuclear_source::load("sources.dat")) {
    std::cout<<"NUCLEAR_SOURCE_LOADED format=V1 steps="<<steps.size()
             <<" time=ReadTime_seconds coords=um discrete=BE_interval_average sign=negative_recombination\n";
    trace.initialized(steps.size());
  }
  virtual ~NuclearSource() { trace.finished(); }
  void Compute_r(double lattice_temperature,double n,double p,double nie,double field,double& r) {
    (void)lattice_temperature;(void)n;(void)p;(void)nie;(void)field;
    const PMI_StepType type=ReadTransientStepType();
    const nuclear_trace_r10::Token trace_token = trace_begin(type);
    double time=0,dt=0,generation=0;
    if(type==PMI_UndefStepType) {
      // Explicit electrostatic/DC initialization convention: radiation is off.
      // No fictitious time step or temperature-as-time substitution is used.
    } else {
      nuclear_source::need(type==PMI_BE,"NUCLEAR_SOURCE: only native BE transient steps are supported");
      time=ReadTime();dt=ReadTransientStepSize();
      nuclear_source::need(std::isfinite(time)&&std::isfinite(dt)&&time>=0&&dt>=0,
                           "NUCLEAR_SOURCE: invalid native BE time/step");
      if(time==0&&dt==0) {
        // A zero-duration initial boundary is not integrated as a source step.
      } else {
        nuclear_source::need(dt>0&&time-dt>=-1e-18,"NUCLEAR_SOURCE: unavailable or invalid actual BE interval");
        std::array<double,3> xyz;ReadCoordinate(xyz[0],xyz[1],xyz[2]);
        generation=nuclear_source::average(steps,xyz,time-dt,time);
      }
    }
    r=-generation;
    WriteUserField(PMI_UserField0,generation);
    WriteUserField(PMI_UserField1,time);
    WriteUserField(PMI_UserField2,dt);
    WriteUserField(PMI_UserField3,static_cast<double>(type));
    trace_end(trace_token,generation,time,dt,type,r);
  }
  void Compute_drdt(double,double,double,double,double,double& v) {v=0;}
  void Compute_drdn(double,double,double,double,double,double& v) {v=0;}
  void Compute_drdp(double,double,double,double,double,double& v) {v=0;}
  void Compute_drdnie(double,double,double,double,double,double& v) {v=0;}
  void Compute_drdf(double,double,double,double,double,double& v) {v=0;}
};

extern "C" PMI_Recombination* new_PMI_Recombination(const PMI_Environment& env) {return new NuclearSource(env);}
extern "C" int PMI_Recombination_ElectricField() {return 0;}
#else
// Offline native arithmetic hook for the root-owned build/qualification stage.
// This is never compiled or invoked automatically by the Python source modules.
int main(int argc,char** argv) {
  try {
    nuclear_source::need(argc==7,"Usage: source-kernel sources.dat x_um y_um z_um t0_s t1_s");
    std::array<double,3> xyz={{std::stod(argv[2]),std::stod(argv[3]),std::stod(argv[4])}};
    double value=nuclear_source::average(nuclear_source::load(argv[1]),xyz,std::stod(argv[5]),std::stod(argv[6]));
    std::cout<<std::setprecision(17)<<value<<"\n";return 0;
  } catch(const std::exception& error) {std::cerr<<error.what()<<"\n";return 1;}
}
#endif
