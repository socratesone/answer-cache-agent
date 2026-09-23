from pathlib import Path
from PyInstaller.utils.hooks import collect_all

root = Path(SPECPATH).parent
packages = ['answer_cache_agent','questionnaire_host','fastembed','onnxruntime','sqlite_vec',
            'langgraph','langgraph.checkpoint.sqlite','langchain_openai','langchain_anthropic','tiktoken']
datas, binaries, hiddenimports = [], [], []
for package in packages:
    d,b,h = collect_all(package)
    datas += d; binaries += b; hiddenimports += h
model = root / 'artifacts' / 'embedding-model'
if not model.exists():
    raise RuntimeError('Run packaging/download_model.py first')
datas += [(str(model), 'embedding-model'), (str(root / 'artifacts' / 'allowed-origins.json'), 'questionnaire_host')]
a = Analysis([str(root/'packaging'/'entry.py')],pathex=[str(root/'companion')],binaries=binaries,datas=datas,hiddenimports=hiddenimports)
pyz = PYZ(a.pure)
exe = EXE(pyz,a.scripts,[],exclude_binaries=True,name='questionnaire-host',console=True)
coll = COLLECT(exe,a.binaries,a.datas,strip=False,upx=False,name='questionnaire-host')
