"""投資系統設定"""
import os
from pathlib import Path

# 路徑
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / 'data'
DB_PATH = BASE_DIR / 'db' / 'trades.db'

# 確保資料夾存在
DATA_DIR.mkdir(exist_ok=True)
DB_PATH.parent.mkdir(exist_ok=True)

# API Keys（從環境變數或 ai-hub 讀取）
def load_env():
    """載入 .env（專案本地 + ai-hub 共用）"""
    for env_path in [BASE_DIR / '.env', Path.home() / '.config' / 'ai-hub' / 'shared' / '.env']:
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, _, value = line.partition('=')
                    os.environ.setdefault(key.strip(), value.strip())

load_env()

# 預設設定
DEFAULT_CASH = 1_000_000       # 回測初始資金（台幣）
DEFAULT_COMMISSION = 0.001425  # 台股手續費率
DEFAULT_TAX = 0.003            # 交易稅率
