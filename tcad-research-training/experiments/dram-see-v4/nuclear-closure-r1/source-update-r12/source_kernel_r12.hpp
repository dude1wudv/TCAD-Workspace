#ifndef NC_SOURCE_KERNEL_R12_HPP
#define NC_SOURCE_KERNEL_R12_HPP
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
#endif
