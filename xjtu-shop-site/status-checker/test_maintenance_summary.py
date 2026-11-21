import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest
import status_checker as sc


class MaintenanceSummaryTests(unittest.TestCase):
    def test_private_and_stale_do_not_escape(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t).resolve()/'summary.json'; n=dt.datetime.now(sc.UTC)
            self.assertEqual(sc.maintenance_summary(p,n)['state'],'unknown')
            doc=dict(schema='tcad-maintenance-summary-v1',observed_at=n.isoformat(),rows=['private'],
                     counts={'find_or_extract_readout':2},selected_local_archive_bytes={'find_or_extract_readout':18})
            p.write_text(json.dumps(doc)); m=sc.maintenance_summary(p,n)
            self.assertEqual(m['state'],'fresh'); self.assertNotIn('private',json.dumps(m)); self.assertIsNone(m['reclaimed_bytes'])
            self.assertEqual(sc.maintenance_summary(p,n+dt.timedelta(seconds=181))['counts'],None)
            self.assertEqual(sc.maintenance_summary(p,n-dt.timedelta(minutes=1))['state'],'unknown')
            doc['counts']['find_or_extract_readout']=False; p.write_text(json.dumps(doc)); self.assertEqual(sc.maintenance_summary(p,n)['state'],'unknown')
