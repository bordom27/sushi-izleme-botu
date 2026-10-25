"""zincir/vakalar.txt icindeki vakalari sirayla calistirir (satir: SYMBOL YYYYMMDD YYYYMMDD [zincir]). Hata bir vakayi durdurur, digerlerini degil."""
import os, sys, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from zincir import vaka

for satir in open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "vakalar.txt")):
    a = satir.split("#")[0].split()
    if not a:
        continue
    print("\n######", " ".join(a), flush=True)
    sys.argv = ["vaka.py"] + a
    try:
        vaka.main()
    except SystemExit as e:
        print("atlandi:", e, flush=True)
    except Exception:
        traceback.print_exc()
