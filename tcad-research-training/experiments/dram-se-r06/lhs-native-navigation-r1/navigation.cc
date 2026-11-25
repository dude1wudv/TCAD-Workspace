#define main frozen_transport_main
#include "transport_l08.cc"
#undef main

#include "G4GeometryTolerance.hh"
#include "G4Navigator.hh"

namespace {
void require(bool condition, const char* message) {
  if (!condition) throw std::runtime_error(message);
}

bool within(double observed, double expected, double tolerance) {
  return std::isfinite(observed) && std::abs(observed - expected) <= tolerance;
}

double distance(G4Navigator& navigator, const G4ThreeVector& position,
                const G4ThreeVector& direction, double expected) {
  if (expected < 0) return -1;
  navigator.LocateGlobalPointAndSetup(position, &direction, false, false);
  double safety = 0;
  return navigator.ComputeStep(position, direction, 3000 * nm, safety) / nm;
}
}

int main() {
  try {
    std::ifstream input("points.tsv");
    std::string task, geometry_sha, request_sha;
    double dx, dy, dz;
    int source_count, segment_count, face_count;
    require(bool(input >> task >> geometry_sha >> request_sha >> dx >> dy >> dz
                       >> source_count >> segment_count >> face_count), "Invalid probe header");
    const auto& request = frozen::requests[0];
    const auto& direction = frozen::beam_direction;
    const G4ThreeVector beam(direction[0], direction[1], direction[2]);
    require(task == request.label && geometry_sha == frozen::geometry_sha256 &&
            request_sha == frozen::contract_sha256 && (beam - G4ThreeVector(dx, dy, dz)).mag() < 1e-14 &&
            std::abs(beam.mag2() - 1) < 1e-14, "Compiled pool binding differs");

    G4GeometryManager::GetInstance()->SetWorldMaximumExtent(3000 * nm);
    G4Random::setTheSeed(request.seed);
    probe::Geometry geometry;
    auto* world = geometry.Construct();
    require(world && world->GetLogicalVolume()->GetNoDaughters() == 40, "Incomplete Geant4 geometry");
    require(G4GeometryManager::GetInstance()->CloseGeometry(true, false), "Could not close geometry");
    G4Navigator navigator;
    navigator.SetWorldVolume(world);
    const double tolerance = G4GeometryTolerance::GetInstance()->GetSurfaceTolerance() / nm;
    require(within(tolerance, 3e-8, 1e-15), "Unexpected native surface tolerance");
    const double step_limit = std::max(4 * tolerance, 1e-8);

    std::cout << "# " << task << ' ' << geometry_sha << ' ' << request_sha << '\n';
    std::cout << "kind,point,expected_region,expected_material,native_region,native_material,clearance_nm,"
                 "expected_forward_nm,native_forward_nm,expected_backward_nm,native_backward_nm,status\n";
    std::cout << std::setprecision(17);
    int sources = 0, segments = 0, faces = 0, resolved_faces = 0, failures = 0;
    char kind;
    std::string point, expected_region, expected_material;
    double x, y, z, backward, forward, clearance;
    while (input >> kind >> point >> x >> y >> z >> expected_region >> expected_material
                 >> backward >> forward >> clearance) {
      require(kind == 'S' || kind == 'C' || kind == 'F', "Unknown point type");
      sources += kind == 'S';
      segments += kind == 'C';
      faces += kind == 'F';
      const G4ThreeVector position(x * nm, y * nm, z * nm);
      auto* volume = navigator.LocateGlobalPointAndSetup(position, &beam, false, false);
      const std::string region = volume ? std::string(volume->GetName()) : "outside";
      const std::string material = volume ? std::string(volume->GetLogicalVolume()->GetMaterial()->GetName()) : "outside";
      const bool resolved = clearance > 2 * tolerance;
      const bool limited = kind == 'F' && !resolved;
      const double actual_forward = distance(navigator, position, beam, forward);
      const double actual_backward = distance(navigator, position, -beam, backward);
      const bool matches = resolved && region == expected_region && material == expected_material &&
          within(actual_forward, forward, step_limit) && within(actual_backward, backward, step_limit);
      resolved_faces += kind == 'F' && resolved;
      failures += !limited && !matches;
      std::cout << kind << ',' << point << ',' << expected_region << ',' << expected_material << ','
                << region << ',' << material << ',' << clearance << ',' << forward << ','
                << actual_forward << ',' << backward << ',' << actual_backward << ','
                << (limited ? "resolution_limited" : matches ? "pass" : "fail") << '\n';
    }
    require(input.eof() && sources == source_count && segments == segment_count && faces == face_count,
            "Incomplete probe results");
    return failures || !resolved_faces ? 1 : 0;
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
