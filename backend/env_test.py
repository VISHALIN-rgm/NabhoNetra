"""Checks the .env reader. Run: python env_test.py"""
import os, re, tempfile, shutil
from config import parse_env

p = parse_env('''\ufeff# comment
FIRMS_KEY=abc123
ADMIN_TOKEN="quoted token"
export DELIVERY=log
MIN_FRP=0            drop fires weaker than this
STATIC_DAYS=3  # inline note
TOKEN_SECRET=abc#def
EMPTY=
bad line=1
   SPACED  =  value  
SINGLE='it is # fine'
''')
assert p["FIRMS_KEY"] == "abc123" and p["ADMIN_TOKEN"] == "quoted token" and p["DELIVERY"] == "log"
assert p["STATIC_DAYS"] == "3" and p["TOKEN_SECRET"] == "abc#def", "# inside a value is kept; ' #' starts a comment"
assert p["EMPTY"] == "" and "bad line" not in p and p["SPACED"] == "value" and p["SINGLE"] == "it is # fine"

# Every line of .env.example, uncommented, must load and give valid settings (no stray text in numbers or secrets).
here = os.path.dirname(os.path.abspath(__file__)); tmp = tempfile.mkdtemp()
try:
    for f in ("config.py",): shutil.copy(os.path.join(here, f), tmp)
    lines = []
    for ln in open(os.path.join(here, ".env.example"), encoding="utf-8"):
        m = re.match(r"#\s*([A-Z][A-Z0-9_]+=\S*)\s*$", ln.strip())
        lines.append(m.group(1) if m else ln.rstrip())
    open(os.path.join(tmp, ".env"), "w", encoding="utf-8").write("\n".join(lines))
    import subprocess, sys
    r = subprocess.run([sys.executable, "-c", "import config, os; assert config.MAX_CLUSTERS and float(os.environ['MIN_FRP']) >= 0 and float(os.environ['SMOKE_REACH_KM']) > 0; "
                        "assert '(' not in os.environ.get('TOKEN_SECRET','') and ' ' not in os.environ.get('ALERT_WINDOW_UTC','')"], cwd=tmp, capture_output=True, text=True,
                       env={k: v for k, v in os.environ.items() if k not in ("ADMIN_TOKEN", "FIRMS_KEY")})
    assert r.returncode == 0, r.stderr[-400:]
finally:
    shutil.rmtree(tmp, ignore_errors=True)
print("All env checks passed")
