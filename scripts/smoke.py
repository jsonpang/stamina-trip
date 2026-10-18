"""Live end-to-end acceptance run; requires configured .env."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from stamina.cli import main

sys.argv = [sys.argv[0], '爸妈 68 岁，妈妈膝盖不好，带一个 6 岁孩子，杭州 11月7日-8日 两天，每天最多走 6000 步，中午要午休。']
raise SystemExit(main())
