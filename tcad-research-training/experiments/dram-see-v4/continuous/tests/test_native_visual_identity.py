"""New native-name mapping only. No SSH or commercial tool invocation."""
import ast
import importlib.util
import io
import os
from pathlib import Path
from unittest.mock import patch
import unittest

ROOT=Path(__file__).resolve().parents[4]
spec=importlib.util.spec_from_file_location('tcad_visual_identity',ROOT/'scripts/tcad.py')
tcad=importlib.util.module_from_spec(spec);spec.loader.exec_module(tcad)


class NativeVisualIdentityTests(unittest.TestCase):
    def predicate(self,tool):
        shell='\n'.join(tcad.native_capture_shell_lines())
        code=shell.split("<<'S2_CAPTURE_PROC_PY'\n",1)[1].split('\nS2_CAPTURE_PROC_PY',1)[0]
        tree=ast.parse(code)
        fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='exact_native')
        env=dict(tool=tool,installation='/installed/W-2024.09',Path=Path,os=os)
        exec(compile(ast.Module(body=[fn],type_ignores=[]),'<native-identity>','exec'),env)
        return env['exact_native']

    def observed(self,tool,name,exe,signature=b'\x7fELF'):
        predicate=self.predicate(tool)
        with patch('os.readlink',return_value=exe),patch('builtins.open',side_effect=lambda *a,**k:io.BytesIO(signature)):
            return predicate(12,{'name':name})

    def test_exact_installed_svisual_exec_is_recognized(self):
        exe='/installed/W-2024.09/linux64/bin/svisual_bin/svisual_exec'
        self.assertEqual(self.observed('svisual','svisual_exec',exe),exe)

    def test_wrapper_wrong_installation_and_nonelf_stay_rejected(self):
        self.assertIsNone(self.observed('svisual','svisual','/usr/bin/bash'))
        self.assertIsNone(self.observed('svisual','svisual_exec','/other/svisual_exec'))
        self.assertIsNone(self.observed('svisual','svisual_exec','/installed/W-2024.09/svisual_exec',b'#!/b'))

    def test_sdevice_identity_is_not_relaxed(self):
        self.assertEqual(self.observed('sdevice','sdevice','/installed/W-2024.09/sdevice'),'/installed/W-2024.09/sdevice')
        self.assertIsNone(self.observed('sdevice','svisual_exec','/installed/W-2024.09/svisual_exec'))


if __name__=='__main__':unittest.main()
