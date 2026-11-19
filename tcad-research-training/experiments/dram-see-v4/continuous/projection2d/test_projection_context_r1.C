// Standalone arithmetic contexts only. This is never a native BE observation.
#include "projection_pmi_math_r1.hpp"
#include <functional>
#include <limits>

namespace {
int checks=0;
void check(bool ok,const char* message){if(!ok)throw std::runtime_error(message);++checks;}
void rejects(const std::function<void()>& fn){bool failed=false;try{fn();}catch(const std::exception&){failed=true;}check(failed,"Expected explicit rejection");}
}
int main() {
  try {
    const double t=15e-9,lo=t-2e-12,hi=t+2e-12;
    projection_r14::Context context{0,50e-9};std::array<double,3> native{{-.052,.4,0}};
    nuclear_source::Step s{{-.052,0,.4,-.052,0,.4,t,t,1,.03,2e-12}};
    std::vector<nuclear_source::Step> steps{s};projection_r14::peak_bound(steps,context);
    auto point=projection_r14::evaluate(steps,context,native,hi,hi-lo,3,3,0,true);
    double fy=std::erf(.01/.03),ft=std::erf((hi-lo)/2/(std::sqrt(2.)*2e-12));
    double expected=1e-15/nuclear_source::echarge*1e12*fy*ft/(nuclear_source::pi*.03*.03*.02*(hi-lo));
    check(std::fabs(point.generation/expected-1)<=2e-9,"Point normalization/width differs");
    check(std::fabs(point.yield*projection_r14::reference_rate/point.generation-1)<1e-14,"Basis does not recover G2");
    auto undef=projection_r14::evaluate(steps,context,native,t,0,0,3,0,true);
    check(undef.generation==0&&undef.time==t&&undef.dt==0&&undef.type==0,"Undef raw clock was replaced");
    auto nonSi=projection_r14::evaluate(steps,context,native,hi,hi-lo,3,3,0,false);check(nonSi.generation==0,"Non-Si source");
    (void)projection_r14::evaluate(steps,context,native,t+10e-12,2e-12,3,3,0,true);
    auto retry=projection_r14::evaluate(steps,context,native,hi,hi-lo,3,3,0,true);
    check(retry.generation==point.generation&&retry.time==hi&&retry.dt==hi-lo,"Retry did not recompute exact actual context");
    auto empty=projection_r14::evaluate({},context,native,hi,hi-lo,3,3,0,true);check(empty.generation==0,"Empty source not zero");
    rejects([&](){auto bad=native;bad[2]=.01;projection_r14::evaluate(steps,context,bad,hi,hi-lo,3,3,0,true);});
    rejects([&](){projection_r14::evaluate(steps,context,native,hi,0,3,3,0,true);});
    rejects([&](){projection_r14::evaluate(steps,context,native,hi,-1e-12,3,3,0,true);});
    rejects([&](){projection_r14::evaluate(steps,context,native,hi,1e-12,77,3,0,true);});
    rejects([&](){projection_r14::evaluate(steps,context,native,std::numeric_limits<double>::quiet_NaN(),1e-12,3,3,0,true);});
    rejects([&](){auto late=steps;late[0].a[7]=context.hi+1e-9;projection_r14::peak_bound(late,context);});
    rejects([&](){auto large=steps;large[0].a[8]=1e30;projection_r14::peak_bound(large,context);});
    std::cout<<"{\"arithmetic_checks\":"<<checks<<",\"compiled_context_only\":true,\"native_BE_qualified\":false,\"pmi_r12_fixed\":false}\n";
    return 0;
  }catch(const std::exception& error){std::cerr<<error.what()<<"\n";return 1;}
}
