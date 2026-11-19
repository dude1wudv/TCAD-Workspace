"""Focused new parser guards; fixtures are explicitly synthetic, never native."""
from pathlib import Path
import tempfile
import unittest
import dfise_observer as observer

ROOT = Path(__file__).resolve().parents[4]
OUTPUT = ROOT / 'local_runtime/dram-see-v4/continuous/device'

GRID = '''DF-ISE text
# UNIT_FIXTURE_NOT_NATIVE
Info {
 version = 1.1
 type = grid
 dimension = 3
 nb_vertices = 4
 nb_edges = 6
 nb_faces = 4
 nb_elements = 5
 nb_regions = 5
 regions = [ "R.Silicon" "bottom" "front" "sloped" "left" ]
 materials = [ Silicon Contact Contact Contact Contact ]
}
Data {
 CoordSystem {
  translate = [ 0 0 0 ]
  transform = [ 1 0 0 0 1 0 0 0 1 ]
 }
 Vertices (4) {
  0 0 0
  1 0 0
  0 1 0
  0 0 1
 }
 Edges (6) {
  0 1
  1 2
  2 0
  0 3
  1 3
  2 3
 }
 Faces (4) {
  3 0 1 2
  3 0 4 -4
  3 1 5 -5
  3 2 3 -6
 }
 Locations (4) {
  eeee
 }
 Elements (5) {
  5 0 1 2 3
  2 0 1 2
  2 0 4 -4
  2 1 5 -5
  2 2 3 -6
 }
 Region ("R.Silicon") {
  material = Silicon
  Elements (1) {
   0
  }
 }
 Region ("bottom") {
  material = Contact
  Elements (1) {
   1
  }
 }
 Region ("front") {
  material = Contact
  Elements (1) {
   2
  }
 }
 Region ("sloped") {
  material = Contact
  Elements (1) {
   3
  }
 }
 Region ("left") {
  material = Contact
  Elements (1) {
   4
  }
 }
}
'''

DATA = '''DF-ISE text
# UNIT_FIXTURE_NOT_NATIVE
Info {
 version = 1.0
 type = dataset
 dimension = 2
 nb_vertices = 3
 nb_edges = 3
 nb_faces = 0
 nb_elements = 1
 nb_regions = 1
}
Data {
 Dataset ("ArsenicActiveConcentration") {
  function = ArsenicActiveConcentration
  type = scalar
  dimension = 1
  location = vertex
  validity = [ "R.Trench" ]
  Values (3) {
   0 5e19 0
  }
 }
}
'''


class NewDfiseGuards(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = Path(tempfile.mkdtemp(prefix='UNIT_FIXTURE_NOT_NATIVE-dfise-', dir=str(OUTPUT)))
        (cls.directory/'SYNTHETIC_NOT_NATIVE').write_text('Parser tests only; never submit to native tools.\n')

    def parsed(self, name, content, parser):
        path = self.directory/name
        path.write_text(content, encoding='ascii')
        return parser(path)

    def test_d3_triangular_contact_nodes_from_oriented_edges(self):
        result = self.parsed('d3.grd', GRID, observer.read_grid)
        self.assertEqual(result['contacts']['bottom']['bounds'], [[0.,1.],[0.,1.],[0.,0.]])
        self.assertEqual(result['contacts']['front']['bounds'], [[0.,1.],[0.,0.],[0.,1.]])
        self.assertEqual(result['contacts']['left']['bounds'], [[0.,0.],[0.,1.],[0.,1.]])
        self.assertEqual(result['contacts']['sloped']['bounds'], [[0.,1.],[0.,1.],[0.,1.]])
        self.assertAlmostEqual(result['contacts']['sloped']['mesh_measure'], 3**.5/2)

    def test_bad_contact_edge_or_nonidentity_mapping_is_rejected(self):
        for name, text in [('bad-edge.grd', GRID.replace('  2 0 1 2\n','  2 0 1 1\n')),
                           ('scaled.grd', GRID.replace('1 0 0 0 1 0 0 0 1','2 0 0 0 1 0 0 0 1'))]:
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.parsed(name, text, observer.read_grid)

    def test_adverse_non_silicon_value_is_retained(self):
        result = self.parsed('adverse.dat', DATA, observer.read_datasets)
        self.assertEqual(result['datasets'][('R.Trench','ArsenicActiveConcentration')]['max'], 5e19)

    def test_missing_truncated_or_nonfinite_data_is_rejected(self):
        for name, text in [('empty.dat', DATA.replace('0 5e19 0','')),
                           ('truncated.dat', DATA.replace('0 5e19 0','0 5e19')),
                           ('nonfinite.dat', DATA.replace('0 5e19 0','0 nan 0'))]:
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.parsed(name, text, observer.read_datasets)


if __name__ == '__main__':
    unittest.main()
