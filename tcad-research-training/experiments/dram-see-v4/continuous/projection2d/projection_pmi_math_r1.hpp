#ifndef DRAM_SEE_V4_PROJECTION_PMI_MATH_R1_HPP
#define DRAM_SEE_V4_PROJECTION_PMI_MATH_R1_HPP
// Explicit 2D projection of the unchanged physical-xyz source rows.
// Original R12 header is copied byte-identically into the compile package.
#include "source_kernel_r12.hpp"

namespace projection_r14 {
const double width_um=.02;
const double reference_rate=1e35;
struct Context { double lo,hi; };
struct Evaluation { double generation,yield,time,dt; int type; };

Context load_context(const char* name) {
  std::ifstream input(name);input.imbue(std::locale::classic());
  std::string magic,extra;double width=0;Context value{0,0};
  nuclear_source::need(bool(input>>magic>>width>>value.lo>>value.hi) && !(input>>extra),"R14: invalid 2D source context");
  nuclear_source::need(magic=="DRAM_SEE_V4_2D_SOURCE_CONTEXT_R1" && width==width_um &&
    std::isfinite(value.lo) && std::isfinite(value.hi) && value.lo>=0 && value.hi>value.lo,"R14: context width/window changed");
  return value;
}

double peak_bound(const std::vector<nuclear_source::Step>& steps,const Context& context) {
  nuclear_source::need(std::isfinite(context.lo)&&std::isfinite(context.hi)&&context.lo>=0&&context.hi>context.lo,"R14: invalid context");
  long double charge=0;
  for(const auto& step:steps) {
    nuclear_source::need(step.a[6]>=context.lo && step.a[7]<=context.hi,
      "R14: raw deposition is outside frozen complete timing; preserve late source and extend matching timing contract");
    charge+=step.a[8];
  }
  // Strip probability <=1. This is a representation-basis bound, never clipping.
  long double bound=charge*1e-15L/nuclear_source::echarge*1e12L/
    (nuclear_source::pi*nuclear_source::width*nuclear_source::width*width_um*
     std::sqrt(2*nuclear_source::pi)*nuclear_source::sigma);
  nuclear_source::need(std::isfinite(bound)&&bound<=reference_rate,"R14: optical representation basis overflow; do not clip");
  return static_cast<double>(bound);
}

struct Integrand {
  const nuclear_source::Step& step;double x,z,lo,hi;
  double operator()(double u) const {
    double cx=step.a[0]+u*(step.a[3]-step.a[0]);
    double cy=step.a[1]+u*(step.a[4]-step.a[1]);
    double cz=step.a[2]+u*(step.a[5]-step.a[2]);
    double ct=step.a[6]+u*(step.a[7]-step.a[6]);
    double w=step.a[9],scale=std::sqrt(2.)*step.a[10];
    double strip=.5*nuclear_source::erf_difference((-.01-cy)/w,(.01-cy)/w);
    double temporal=.5*nuclear_source::erf_difference((lo-ct)/scale,(hi-ct)/scale);
    double dx=(x-cx)/w,dz=(z-cz)/w;
    return std::exp(-dx*dx-dz*dz)*strip*temporal;
  }
};

double quadrature(const Integrand& fn,double lo,double hi,const std::vector<std::pair<double,double>>& nodes) {
  double sum=0,correction=0;
  for(const auto& node:nodes) {
    double term=fn(lo+(hi-lo)*node.first)*node.second*(hi-lo)-correction;
    double next=sum+term;correction=(next-sum)-term;sum=next;
  }
  return sum;
}

double adaptive(const Integrand& fn,double lo,double hi,unsigned depth=0) {
  double a=quadrature(fn,lo,hi,nuclear_source::nodes8()),b=quadrature(fn,lo,hi,nuclear_source::nodes16());
  if(std::fabs(a-b)<=1e-12*(hi-lo)+1e-10*std::fabs(b))return b;
  nuclear_source::need(depth<18,"R14: projected BE quadrature did not converge");
  double mid=(lo+hi)/2;return adaptive(fn,lo,mid,depth+1)+adaptive(fn,mid,hi,depth+1);
}

double average_step(const nuclear_source::Step& step,double x,double z,double lo,double hi,double actual_dt) {
  std::vector<double> points{0.,1.};const double multiples[]={-12,-8,-4,-2,0,2,4,8,12};
  // Every physical coordinate including omitted-y and actual time subdivides u.
  const double faces[3][2]={{x,x},{-.01,.01},{z,z}};
  for(unsigned axis=0;axis<3;++axis) {
    double delta=step.a[axis+3]-step.a[axis];
    if(delta!=0)for(double face:faces[axis])for(double m:multiples)
      nuclear_source::add(points,(face+m*step.a[9]-step.a[axis])/delta);
  }
  double duration=step.a[7]-step.a[6];
  if(duration>0)for(double edge:{lo,hi})for(double m:multiples)
    nuclear_source::add(points,(edge+m*std::sqrt(2.)*step.a[10]-step.a[6])/duration);
  std::sort(points.begin(),points.end());points.erase(std::unique(points.begin(),points.end()),points.end());
  Integrand fn{step,x,z,lo,hi};double integral=0;
  for(std::size_t i=1;i<points.size();++i)integral+=adaptive(fn,points[i-1],points[i]);
  return step.a[8]*1e-15/nuclear_source::echarge*1e12*integral/
    (nuclear_source::pi*step.a[9]*step.a[9]*width_um*actual_dt);
}

double average(const std::vector<nuclear_source::Step>& steps,double x,double z,double actual_lo,double actual_hi,const Context& context) {
  nuclear_source::need(std::isfinite(x)&&std::isfinite(z)&&std::isfinite(actual_lo)&&std::isfinite(actual_hi)&&actual_hi>actual_lo,
    "R14: nonfinite/nonpositive actual native BE interval or coordinates");
  double lo=std::max(actual_lo,context.lo),hi=std::min(actual_hi,context.hi);
  if(hi<=lo)return 0.;
  double sum=0,correction=0;
  for(const auto& step:steps) {
    double rate=average_step(step,x,z,lo,hi,actual_hi-actual_lo);
    nuclear_source::need(std::isfinite(rate)&&rate>=0,"R14: negative/nonfinite projected rate");
    double term=rate-correction,next=sum+term;correction=(next-sum)-term;sum=next;
  }
  nuclear_source::need(std::isfinite(sum),"R14: projected source overflow");return sum;
}

Evaluation evaluate(const std::vector<nuclear_source::Step>& steps,const Context& context,
    const std::array<double,3>& native,double time,double dt,int type,int be,int undefined,bool silicon) {
  nuclear_source::need(std::isfinite(time)&&std::isfinite(dt)&&time>=0&&dt>=0,"R14: invalid actual raw clock");
  for(double v:native)nuclear_source::need(std::isfinite(v),"R14: nonfinite native coordinate");
  nuclear_source::need(std::fabs(native[2])<=1e-14,"R14: native third coordinate is not a 2D mesh zero");
  nuclear_source::need(type==be||type==undefined,"R14: unsupported actual step type");
  Evaluation out{0,0,time,dt,type};
  if(type==be) {
    nuclear_source::need(dt>0&&time-dt>=-1e-18,"R14: invalid actual BE interval");
    if(silicon)out.generation=average(steps,native[0],native[1],time-dt,time,context);
  }
  nuclear_source::need(std::isfinite(out.generation)&&out.generation>=0&&out.generation<=reference_rate,"R14: invalid source or representation overflow");
  out.yield=out.generation/reference_rate;return out;
}
}
#endif
