import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import resolve_import as ri


class ResolveImportTests(unittest.TestCase):
    def run_report(self,report):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'report.json'; path.write_text(json.dumps(report))
            return ri.import_timeline_external(path)

    def test_failed_sync_never_connects(self):
        with patch.object(ri,'connect') as connection:
            self.assertFalse(self.run_report({'ok':False})['ok'])
            connection.assert_not_called()

    def test_unavailable_external_api_is_honest_fallback(self):
        with patch.object(ri,'connect',return_value=None):
            result=self.run_report({'ok':True})
            self.assertFalse(result['ok']); self.assertIn('unavailable',result['reason'])

    def test_unrelated_project_untouched(self):
        app=Mock(); manager=app.GetProjectManager.return_value
        manager.GetCurrentProject.return_value.GetName.return_value='Personal project'
        with patch.object(ri,'connect',return_value=app):
            self.assertFalse(self.run_report({'ok':True})['ok'])
        manager.CreateProject.assert_not_called(); manager.LoadProject.assert_not_called()
        manager.SaveProject.assert_not_called()
        manager.GetCurrentProject.return_value.GetMediaPool.assert_not_called()

    def test_lua_quoting_closing_bracket(self):
        result=ri.lua_quote('/some/]=]/path')
        self.assertTrue(result.startswith('[==[')); self.assertTrue(result.endswith(']==]'))


if __name__=='__main__': unittest.main()
