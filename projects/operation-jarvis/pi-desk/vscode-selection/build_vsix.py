#!/usr/bin/env python3
"""Build the optional local VS Code bridge, offline and without npm dependencies."""
import argparse
import json
from pathlib import Path
from xml.sax.saxutils import escape
import zipfile

ROOT = Path(__file__).resolve().parent


def build(output):
    package = json.loads((ROOT / 'package.json').read_text())
    identity = {key: escape(package[key], {'"': '&quot;'}) for key in
                ('name', 'publisher', 'version', 'displayName', 'description')}
    manifest = f'''<?xml version="1.0" encoding="utf-8"?>
<PackageManifest Version="2.0.0" xmlns="http://schemas.microsoft.com/developer/vsx-schema/2011">
  <Metadata>
    <Identity Language="en-US" Id="{identity['name']}" Version="{identity['version']}" Publisher="{identity['publisher']}" />
    <DisplayName>{identity['displayName']}</DisplayName>
    <Description xml:space="preserve">{identity['description']}</Description>
    <Categories>Other</Categories>
    <Properties>
      <Property Id="Microsoft.VisualStudio.Code.Engine" Value="{escape(package['engines']['vscode'])}" />
      <Property Id="Microsoft.VisualStudio.Code.ExtensionKind" Value="ui" />
    </Properties>
  </Metadata>
  <Installation><InstallationTarget Id="Microsoft.VisualStudio.Code" /></Installation>
  <Dependencies />
  <Assets>
    <Asset Type="Microsoft.VisualStudio.Code.Manifest" Path="extension/package.json" Addressable="true" />
  </Assets>
</PackageManifest>
'''
    types = '''<?xml version="1.0" encoding="utf-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="json" ContentType="application/json" />
  <Default Extension="js" ContentType="application/javascript" />
  <Default Extension="md" ContentType="text/markdown" />
  <Default Extension="vsixmanifest" ContentType="text/xml" />
</Types>
'''
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('extension.vsixmanifest', manifest)
        archive.writestr('[Content_Types].xml', types)
        for name in ('package.json', 'extension.js', 'README.md'):
            archive.write(ROOT / name, 'extension/' + name)
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    print(build(parser.parse_args().output))
