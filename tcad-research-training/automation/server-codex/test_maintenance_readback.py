import gzip
import hashlib
import io
import unittest
from maintenance_readback import verify_stream


class ReadbackTests(unittest.TestCase):
    def test_both_streams_must_be_complete(self):
        original=b'scientific evidence\n'*10000; raw=gzip.compress(original)
        sha=lambda b:hashlib.sha256(b).hexdigest()
        verify_stream(io.BytesIO(raw),len(raw),sha(raw),len(original),sha(original))
        for data,cz,ch,oz,oh in [(raw[:-1],len(raw),sha(raw),len(original),sha(original)),
                                  (raw,len(raw),'0'*64,len(original),sha(original)),
                                  (raw,len(raw),sha(raw),len(original)-1,sha(original)),
                                  (raw,len(raw),sha(raw),len(original),'0'*64),
                                  (raw+b'\0',len(raw),sha(raw),len(original),sha(original))]:
            with self.subTest(cz=cz,oz=oz), self.assertRaises((EOFError,ValueError,OSError)):
                verify_stream(io.BytesIO(data),cz,ch,oz,oh)
