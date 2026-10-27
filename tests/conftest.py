import os
import sys

# 允许 tests 直接 import 项目根模块（archive_catalog 等）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
